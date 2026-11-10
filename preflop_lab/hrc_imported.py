"""Immutable saved-HRC scenario adapter with explicit imported policy history.

The source tree is replayed, never rebuilt. Original decision stores may seed
native continuation only after shape/profile/payoff checks. Original leaf EVs
are never passed into the native payoff calculator. Source visits/RNG remain
unknown; new samples and per-bucket visits are counted separately from zero.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import uuid

from .hrc_benchmarks import CACHE, MAX_SAMPLES
from .hrc_hrcz_settings import settings_to_config
from .hrc_research import HRCResearchSolver, decoder

ENGINE='hrc_imported'
RUN_FIELDS={'iterations','seed','solver_mode','threads','constant_scalar_shortcuts','track_ci','stop_after_seconds','hard_seconds','target_ci','max_memory_bytes',
            'stopping_mode','sampling_scope','sampling_path','sampling_stage'}
MODEL={
    'title':'HRC 存档 · 导入策略后继续研究',
    'continuation':'保留存档实际行动树、设置和决策存储；使用独立收益计算继续训练。',
    'limitations':[
        '原全局采样次数、逐手访问次数和 RNG 状态未知；新增样本从零单独计数。',
        '保留原 float32 节点累计时钟与策略数据，重新建立独立 RNG 和 CI 历史。',
        '单线程续算不复现原程序随机流、线程调度或快照时机。',
        '未知存储格式或缺失资源 profile 可只读查看，不能替换默认配置继续训练。',
        '导入已有策略不证明其收敛；继续采样也不保证与原版逐位一致。',
    ]}


def config_for_source(source,iterations=100000,seed=42):
    config=settings_to_config(source.settings,source.state)
    config.update(engine=ENGINE,source_sha256=source.sha256,iterations=iterations,seed=seed)
    return config


def _integer(value,name,minimum,maximum):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError(f'{name} 必须为 {minimum} 到 {maximum} 的整数。')
    return value


def _plain(value):
    """Preserve read-only decoder diagnostics without JSON NaN/Infinity."""
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_plain(v) for v in value]
    return value


def _has_policy(row):
    denominator=row.get('weighted_denominator')
    if isinstance(denominator,(int,float)) and math.isfinite(denominator) and denominator>0:return True
    return any(math.isfinite(v) and v!=0 for key in ('regret_values','average_weights')
               for v in (row.get(key) or [])) or bool(row.get('locked_probabilities'))


class HRCImportedSolver(HRCResearchSolver):
    model=MODEL

    def __init__(self,config,*,source=None):
        if not isinstance(config,dict) or config.get('engine')!=ENGINE:
            raise ValueError('导入场景必须指定 hrc_imported 内核。')
        sha=config.get('source_sha256')
        if not isinstance(sha,str) or re.fullmatch('[0-9a-f]{64}',sha) is None:
            raise ValueError('无效 HRC 来源 SHA-256。')
        if source is None:
            from .hrc_hrcz import load_source
            source=load_source(sha)
        if source.sha256!=sha:
            raise ValueError('导入配置与不可变源存档身份不匹配。')
        self.source,self.archive,self.tree=source,Path(source.path),source.tree
        self.config=config_for_source(source)
        self.output=self.index=self.resume_from=self.reference=None
        self.resource_dir=CACHE/'abstractions'
        self.training_blockers=[dict(row) for row in self.tree.validation.get('unsupported',[]) if row['scope']=='training']
        self.utility_unit='bb' if self.config['utility']=='chips' else 'currency' if self.config['utility'] in ('icm','mtt_icm') else 'archive'
        self.utility_scale=self.tree.rules.big_blind/100 if self.config['utility']=='chips' else 1.
        baseline=source.state.get('eqpre')
        n=self.tree.rules.players
        self.utility_offsets=list(baseline) if isinstance(baseline,list) and len(baseline)==n else [0.]*n
        if not isinstance(baseline,list) or len(baseline)!=n:
            self._block('state.eqpre','源存档没有可校验的完整权益基线。')
        self.equity_config=None
        if self.config['utility'] in ('icm','mtt_icm'):
            try:
                from .tournament import validated_equity
                equity=validated_equity(self.config,n)
                self.equity_config={'mode':equity['utility'],'payouts':equity['payouts'],
                    'other_stacks':[float(Decimal(str(s))*10000) for s in equity['other_stacks']],
                    'bounty':deepcopy(equity['bounty'])}
            except ValueError as exc:
                self._block('eqmodel',str(exc))
        self.compact_override=self.tree.compact_export()
        if self.equity_config:self.compact_override['equity']=deepcopy(self.equity_config)
        from .hrc_hrcz_storage import storage_configuration
        self.storage=storage_configuration(source.records,self.compact_override,
            utility_scale=self.utility_scale,utility_offsets=self.utility_offsets)
        for reason in self.storage['reasons']:self._block('nodedata',reason)
        self.compact_override.update(stores=deepcopy(self.storage['stores']),policies=deepcopy(self.storage['policies']),
            import_provenance={'format':'hrcz','source_sha256':sha,
                               'saved_update_counters':list(self.storage['saved_update_counters']),
                               'source_iterations':None,'source_per_bucket_visits':None,'source_rng_state':None,
                               'utility_scale':self.utility_scale,'utility_offsets':list(self.utility_offsets)})
        self.config.update(stores=deepcopy(self.storage['stores']),policies=deepcopy(self.storage['policies']))
        # Import projection is authoritative. Only explicit run controls may
        # differ; even source policy/metadata edits are rejected here.
        for key,value in config.items():
            if key in RUN_FIELDS:continue
            if key not in self.config or value!=self.config[key]:
                raise ValueError(f'导入存档场景不可修改 {key}；只允许新增采样与运行控制。')
        from .hrc_sampling import iteration_limit
        self.config['iterations']=_integer(iteration_limit(config),'iterations',0,MAX_SAMPLES)
        self.config['seed']=_integer(config.get('seed',42),'seed',0,2**32-1)
        from .hrc_training import validated_training
        controls=validated_training({key:config[key] for key in RUN_FIELDS if key in config and key not in ('iterations','seed','max_memory_bytes')})
        self.config.update(controls)
        if controls.get('sampling_scope')=='selected_subtree':
            from .hrc_sampling import sampling_selection
            sampling_selection(self.compact_override,controls['sampling_scope'],controls.get('sampling_path',[]))
        if 'max_memory_bytes' in config:
            self.config['max_memory_bytes']=_integer(config['max_memory_bytes'],'max_memory_bytes',1<<20,8<<30)
        if controls.get('track_ci'):self.compact_override['ci']={'enabled':True}
        if self.config.get('fgs',{}).get('enabled'):
            try:
                from .hrc_fgs_config import fgs_spec,CACHE_SHA256,CACHE_BYTES
                spec=fgs_spec(self.config['fgs'],self.equity_config,self.tree,chip_scale=10000)
                self.compact_override['fgs']={**spec,'chance_sha256':CACHE_SHA256,'chance_bytes':CACHE_BYTES}
            except ValueError as exc:self._block('fgs',str(exc))
        rake=self.config.get('rake',{})
        if rake.get('mode','none')!='none':
            self.compact_override['rake']={'mode':rake['mode'],'fraction':rake['percentage']/100,
                'cap':int(Decimal(str(rake['cap']))*10000)}
        self.baseline_validation={'status':'pending_native','source':list(self.utility_offsets),
                                  'absolute_tolerance':1e-7,'relative_tolerance':1e-8}
        # A cheap independent check makes incompatible source results read-only
        # before any compilation/resources. FGS requires its real recurrence.
        if not self.config.get('fgs',{}).get('enabled') and self.config['utility']!='unsupported':
            try:self._validate_baseline(self._python_baseline(),'python_reference',block_only=True)
            except (ValueError,ArithmeticError,OverflowError) as exc:self._block('state.eqpre',str(exc))

    def _block(self,field,reason):
        item={'scope':'training','field':field,'reason':reason}
        if item not in self.training_blockers:self.training_blockers.append(item)

    @property
    def training_supported(self):return not self.training_blockers

    def _require_training(self):
        if not self.training_supported:
            raise ValueError('该存档当前仅可查看：'+'; '.join(x['reason'] for x in self.training_blockers))

    def _python_baseline(self):
        stacks=list(self.tree.rules.initial_stacks)
        if self.config['utility']=='chips':return [.01*s for s in stacks]
        if self.equity_config is None:raise ValueError('缺少独立收益模型。')
        equity=self.equity_config
        if equity['mode']=='mtt_icm':
            from .mtt_equity import mtt_icm_equities
            prizes=mtt_icm_equities(stacks,equity['payouts'],equity['other_stacks'])
        else:
            from .hrc_fgs import _icm
            prizes=_icm(stacks,equity['payouts'])
        bounty=equity['bounty'];pool=math.fsum(bounty['amounts']+bounty['other_amounts'])
        chips=math.fsum(stacks+equity['other_stacks'])
        return [value+pool*stack/chips for value,stack in zip(prizes,stacks)]

    def _validate_baseline(self,actual,method,*,block_only=False):
        valid=isinstance(actual,(list,tuple)) and len(actual)==len(self.utility_offsets) and all(math.isfinite(x) for x in actual)
        differences=[abs(a-b) for a,b in zip(actual,self.utility_offsets)] if valid else []
        passed=valid and all(d<=1e-7+1e-8*abs(b) for d,b in zip(differences,self.utility_offsets))
        self.baseline_validation.update(status='verified' if passed else 'mismatch',method=method,
            independent=list(actual),absolute_differences=differences,passed=passed)
        if not passed:
            self._block('state.eqpre','原存档权益基线与独立收益模型不一致，不能安全转换策略收益单位。')
            if not block_only:self._require_training()
        return passed

    def _prepare_resources(self):
        if any(n['street']>0 and n['children'] for n in self.compact_override['nodes']):
            from .hrc_abstraction import prepare_resources
            prepare_resources(Path(r'D:\Program Files\HRC\plugins'),self.resource_dir,save=self.archive)
        if self.compact_override.get('fgs'):
            from .hrc_fgs_config import prepare_chances
            prepare_chances(Path(r'D:\Program Files\HRC\plugins'),self.resource_dir)

    def initialize_checkpoint(self,output_dir):
        """Import checked decision data; all original payoff leaves are ignored."""
        self._require_training()
        folder=Path(output_dir)
        if any((folder/name).exists() for name in ('checkpoint.bin','index.json','tree.json')):
            raise ValueError('导入目标已有原生状态，不能覆盖。')
        folder.mkdir(parents=True,exist_ok=True)
        self._prepare_resources()
        from .hrc_hrcz_leaves import evaluate_baseline
        baseline=evaluate_baseline(self.compact_override,self.resource_dir,folder/'baseline-check')
        self._validate_baseline(baseline,'native_production_baseline')
        from .hrc_hrcz_storage import records_to_checkpoint
        result=records_to_checkpoint(self.source.records,self.compact_override,folder,seed=self.config['seed'],
            utility_scale=self.utility_scale,utility_offsets=self.utility_offsets,mode=self.config.get('solver_mode','v4'))
        from .hrc_snapshot import dump_tree
        dump_tree(self.tree,folder/'tree-snapshot.json')
        self.output=folder
        self.index=json.loads((folder/'index.json').read_text(encoding='utf-8'))
        self.index['utility_baseline']=[v/self.utility_scale for v in baseline] if self.config['utility']=='chips' else baseline
        (folder/'index.json').write_text(json.dumps(self.index,allow_nan=False),encoding='utf-8')
        self.resume_from=folder/'checkpoint.bin'
        self.import_history=result['report']
        (folder/'baseline-validation.json').write_text(json.dumps(self.baseline_validation,allow_nan=False,indent=2),encoding='utf-8')
        return result

    def describe_node(self,path=None):
        result=super().describe_node(path)
        state=self.tree.states[result['native_id']]
        record=self.source.records.get(result['native_id'])
        if record and not result['terminal']:result['buckets']=record['bucket_or_vector_count']
        result.update(utility_unit=self.utility_unit,equity_model=self.config['utility'],
            dead_money=getattr(state,'dead_money',0)/self.tree.rules.big_blind,
            minimum_raise_to=state.minimum_raise_to/self.tree.rules.big_blind if getattr(state,'minimum_raise_to',-1)>0 else None,
            imported_source_sha256=self.source.sha256,training_supported=self.training_supported,
            source_history_unknown=True)
        return result

    def _source_strategy(self,node):
        if node['terminal']:return None
        record=self.source.decoder_records.get(node['native_id'])
        original=self.source.nodes.get(node['native_id'])
        if record is None or original is None:
            return {'actions':node['actions'],'visits':None,'hands':{},'decode_status':'missing_saved_storage',
                    'source_history_unknown':True,'utility_unit':self.utility_unit,'source':'hrcz_saved_policy'}
        data=decoder().decode_storage(record,original)
        ev_key='relative_ev_bb' if self.config['utility']=='chips' else 'relative_ev'
        hands={}
        for row in data.get('buckets',[]):
            label=row.get('hand',f"桶 {row['bucket']}")
            relative=row.get('relative_ev_to_action0')
            hands[label]={'frequencies':_plain(row['display_strategy']),'visits':None,
                'new_visits':0,'has_saved_policy':_has_policy(row),'source_history_unknown':True,
                ev_key:_plain([x/self.utility_scale for x in relative]) if relative is not None else None}
        return {'actions':node['actions'],'visits':None,'new_visits':0,'hands':hands,
            'basis':'current_regret_policy' if data['format_id']==25 else 'saved_average',
            'display_semantics':'original_saved_policy','storage_format':data['format_id'],
            'decode_status':data['decode_status'],'source':'hrcz_saved_policy',
            'saved_counter_float32':_plain(data.get('saved_counter_float32')),
            'frequency':_plain(data.get('frequency_constraints')),'source_history_unknown':True,
            'has_saved_policy':any(r['has_saved_policy'] for r in hands.values()),'utility_unit':self.utility_unit}

    def strategy_for(self,node):
        source=self._source_strategy(node)
        if self.output is None or node['terminal']:return source
        native=super().strategy_for(node)
        if native is None:return source
        source_hands=(source or {}).get('hands',{})
        for label,row in native['hands'].items():
            row.update(new_visits=row['visits'],has_saved_policy=source_hands.get(label,{}).get('has_saved_policy',False),
                       source_history_unknown=True)
        native.update(visits=sum(row['visits'] for row in native['hands'].values()),
            source='hrcz_policy_native_continuation',source_history_unknown=True,
            saved_counter_float32=(source or {}).get('saved_counter_float32'),
            storage_update_counter=self.index['nodes'][node['native_id']]['updates'],
            has_saved_policy=any(r['has_saved_policy'] for r in native['hands'].values()),
            utility_unit=self.utility_unit)
        native['new_visits']=native['visits']
        return native

    def build_result(self,*,summary=None):
        samples=0 if self.index is None else self.index.get('samples',0)
        source_state=deepcopy(self.source.state)
        stats={'status':'completed','iterations_requested':0,'iterations_completed':samples,
            'samples_since_import':samples,'source_iterations':None,'source_per_bucket_visits':None,
            'source_rng_state':None,'fresh_zero_origin':False,'imported_policy':True,
            'training_supported':self.training_supported,'training_blockers':deepcopy(self.training_blockers),
            'utility_unit':self.utility_unit,'equity_model':self.config['utility'],
            'bounty_model':self.config['bounty']['mode'],'tree_validation':self.tree.validation,
            'baseline_validation':deepcopy(self.baseline_validation)}
        if summary:stats.update(summary)
        # These are explicitly source observations, distinct from new samples.
        stats['source_state']=source_state
        root=self.result_node([])
        stats['hrcz_import']={'source_saved_counter':(root['strategy'] or {}).get('saved_counter_float32'),
            'source_iterations_known':False,'history_unknown':True,'training_supported':self.training_supported,
            'unsupported':deepcopy(self.training_blockers)}
        output={'config':deepcopy(self.config),'summary':stats,'model':deepcopy(self.model),
            'nodes':{'root':root['strategy']},'tree_provenance':deepcopy(self.tree.provenance),
            'utility_unit':self.utility_unit,'equity_config':deepcopy(self.equity_config),
            'source_sha256':self.source.sha256,'imported_policy':True,
            'export_scope':'Saved source policy plus explicitly counted independent continuation; unknown historical visits are never invented.'}
        if self.output is not None:
            output['native_artifacts']={f'{key}_path':str(self.output/f'{key}.{ext}') for key,ext in (('index','json'),('checkpoint','bin'),('manifest','json'))}
            output['native_artifacts']['resources_path']=str(self.resource_dir)
        else:output['native_artifacts']={}
        return output

    def run(self,iterations,progress_callback=None,cancel_check=None):
        self._require_training()
        _integer(iterations,'iterations',0,MAX_SAMPLES)
        progress=progress_callback or (lambda _:None)
        if self.resume_from is None:
            progress({'phase':'preparing','message':'校验源存档收益基线并转换原策略状态'})
            self.initialize_checkpoint(CACHE/'runs'/uuid.uuid4().hex)
        self._prepare_resources()
        folder=CACHE/'runs'/uuid.uuid4().hex
        folder.mkdir(parents=True,exist_ok=True)
        from .hrc_snapshot import dump_tree
        dump_tree(self.tree,folder/'tree-snapshot.json')
        from .hrc_native import run
        from .hrc_training import run_options
        options=run_options(self)
        if 'max_memory_bytes' in self.config:options['max_memory_bytes']=self.config['max_memory_bytes']
        result=run(self.compact_override,self.resource_dir,iterations,self.config['seed'],folder,
            progress_callback=lambda event:progress({**event,'phase':'training','message':''}),
            cancel_check=cancel_check,resume_from=self.resume_from,**options)
        self.output=folder
        self.index=json.loads((folder/'index.json').read_text(encoding='utf-8'))
        actual=self.index.get('utility_baseline')
        if actual is None:raise ValueError('原生续算没有输出独立权益基线。')
        actual=[x*self.utility_scale for x in actual] if self.config['utility']=='chips' else actual
        self._validate_baseline(actual,'native_production_baseline')
        self.resume_from=folder/'checkpoint.bin'
        summary={**result['summary'],'iterations_requested':iterations,
                 'iterations_completed':self.index['samples'],'samples_since_import':self.index['samples'],
                 'status':'cancelled' if result['summary'].get('cancelled') else 'completed'}
        output=self.build_result(summary=summary)
        (folder/'application-result.json').write_text(json.dumps(output,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        return output
