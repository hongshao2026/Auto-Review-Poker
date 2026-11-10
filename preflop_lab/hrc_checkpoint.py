"""Explicit checkpoint policy/store migration with structural identity checks.

No original solver runs here. Preserve conversions follow audited mB.a(mA),
mz.a():mx and fi policy editing; unsupported preservation is rejected.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import struct


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def _identity(tree):
    return int.from_bytes(hashlib.sha256(_canonical(tree)).digest()[:8],'little')


def _structural(tree):
    tree=deepcopy(tree)
    for key in ('policies','stores','ci'):
        tree.pop(key,None)
    return _canonical(tree)


def _policy(tree):
    return {entry['node_id']:entry for entry in tree.get('policies',{}).get('nodes',[])}


def _base(tree,node):
    return tree.get('stores',{}).get('street_formats',[23,25,25,25])[node['street']]


def _count(fmt,h,k):
    if not k:return 0
    return 1+h*(2*k+1) if fmt==23 else 1+(h+1)*k if fmt==25 else 1+k+h*(2*k if fmt==27 else 2*k+1)


def _offset(fmt,h,k):
    return 1+h*(2*k+1) if fmt==23 else 1+(h+1)*k if fmt==25 else 1+k+h*(2*k if fmt==27 else 2*k+1)


def _normal(r):
    p=[max(x,0.) for x in r];total=sum(p)
    return [x/total for x in p] if total>0 else [1/len(p)]*len(p)


def _float32(values):
    return list(struct.unpack(f'<{len(values)}f',struct.pack(f'<{len(values)}f',*values)))


def _fresh(fmt,h,k,policy):
    state={'format':fmt,'raw':[0.]*_count(fmt,h,k),'updates':0,'visits':[0]*h,'extra':[]}
    if fmt==31:
        state['extra']=[0.]*k
    if fmt==63:
        edges=policy['frequency'].get('edges',[0.]*k)
        state['extra']=[float.fromhex('0x1.fffffep127'),2.**-149,*edges,*edges,*([0.]*k)]
        state['targets']=[math.nan if x is None else x for x in policy['frequency'].get('targets',[None]*k)]
    return state


def migrate_checkpoint(checkpoint,new_tree,output_dir,mode,solver_mode):
    """Create a v3 resume input and an auditable per-node migration report.

    Modes preserve/reset apply only to changed store/policy nodes. Global
    reset_regret/reset_average remain separate original 1e-20 operations.
    """
    if mode not in ('preserve','reset'):
        raise ValueError('Checkpoint migration must be preserve or reset')
    path=Path(checkpoint).resolve();output=Path(output_dir).resolve()
    if path.parent==output:
        raise ValueError('Policy migration requires a new output directory to preserve the source checkpoint')
    old_tree_path=path.parent/'tree.json';old_index_path=path.parent/'index.json'
    if not old_tree_path.is_file() or not old_index_path.is_file():
        raise ValueError('Migration requires the original tree.json and index.json beside checkpoint.bin')
    old_tree=json.loads(old_tree_path.read_text());index=json.loads(old_index_path.read_text())
    if _structural(old_tree)!=_structural(new_tree):
        raise ValueError('Checkpoint migration cannot change topology, stacks, utility, FGS or abstraction settings')
    old_policies,new_policies=_policy(old_tree),_policy(new_tree)
    raw_file=path.read_bytes()
    if raw_file[:8] not in (b'HRSOLV01',b'HRSOLV02',b'HRSOLV03'):
        raise ValueError('Unsupported source checkpoint version')
    targets_stored=raw_file[:8]==b'HRSOLV03';extended=raw_file[:8]!=b'HRSOLV01'
    identity,samples,nn,players,old_v4=struct.unpack_from('<QQIII',raw_file,8)
    if identity!=_identity(old_tree) or nn!=len(new_tree['nodes']) or players!=new_tree['players'] or len(index['nodes'])!=nn:
        raise ValueError('Checkpoint identity/shape does not match its source metadata')
    if index['samples']!=samples:
        raise ValueError('Checkpoint and index sample counts disagree')
    states=[];changes=[]
    cursor=68+players*8
    for node,n in zip(new_tree['nodes'],index['nodes']):
        node_id=node['id'];k=len(node['children']);h=node['buckets'];old_policy=old_policies.get(node_id,{});new_policy=new_policies.get(node_id,{})
        if any(n[a]!=b for a,b in [('id',node_id),('actor',node['actor']),('street',node['street']),('buckets',h),('actions',k)]):
            raise ValueError('Checkpoint node metadata differs from topology')
        base_old,base_new=(_base(old_tree,node),_base(new_tree,node)) if k else (0,0)
        fmt_old=0 if not k else 63 if 'frequency' in old_policy else base_old
        fmt_new=0 if not k else 63 if 'frequency' in new_policy else base_new
        if n['format']!=fmt_old or n['raw_count']!=_count(fmt_old,h,k):
            raise ValueError('Checkpoint store layout differs from source configuration')
        vo,ro=n['visits_offset'],n['raw_offset']
        expected_vo=cursor+(12 if extended else 8)
        if type(vo) is not int or type(ro) is not int or vo!=expected_vo or ro!=vo+8*h:
            raise ValueError('Invalid checkpoint index offsets')
        if struct.unpack_from('<Q',raw_file,cursor)[0]!=n['updates']:
            raise ValueError('Checkpoint counter differs from index')
        if extended and struct.unpack_from('<I',raw_file,cursor+8)[0]!=fmt_old:
            raise ValueError('Checkpoint format tag differs from index')
        state={'format':fmt_old,'raw':list(struct.unpack_from(f'<{n["raw_count"]}d',raw_file,ro)),
               'visits':list(struct.unpack_from(f'<{h}Q',raw_file,vo)),'updates':n['updates'],'extra':[]}
        if fmt_old==63:
            if n['frequency_state_offset']!=ro+8*n['raw_count']:
                raise ValueError('Invalid frequency checkpoint index offset')
            state['extra']=list(struct.unpack_from(f'<{2+3*k}d',raw_file,n['frequency_state_offset']))
            state['targets']=(list(struct.unpack_from(f'<{k}d',raw_file,n['frequency_state_offset']+8*(2+3*k))) if targets_stored
                              else [math.nan if x is None else x for x in old_policy['frequency'].get('targets',[None]*k)])
        elif fmt_old==31:
            if n['shared_state_offset']!=ro+8*n['raw_count']:
                raise ValueError('Invalid shared checkpoint index offset')
            state['extra']=list(struct.unpack_from(f'<{k}d',raw_file,n['shared_state_offset']))
        cursor=ro+8*n['raw_count']+8*len(state['extra'])+(8*k if fmt_old==63 and targets_stored else 0)
        if not k or (fmt_old==fmt_new and base_old==base_new and old_policy==new_policy):
            states.append(state);continue
        report={'node_id':node_id,'old_format':fmt_old,'new_format':fmt_new,'old_base_format':base_old,'new_base_format':base_new,
                'mode':mode,'float_quantized':False,'counter_reset':False}
        if mode=='reset':
            old=state;state=_fresh(fmt_new,h,k,new_policy)
            if fmt_old==23 and fmt_new==63:
                # Original mz.a(mx,..) copies the float archive bucket payload,
                # then invokes reset(true,true), retaining only 1e-20 residuals.
                state['raw'][1+k:]=[x*1e-20 for x in _float32(old['raw'][1:])]
                targets=new_policy['frequency'].get('targets',[None]*k)
                edges=new_policy['frequency'].get('edges',[0.]*k)
                state['targets']=_float32(state['targets'])
                converted=_float32([edges[a] if targets[a] is None else 0. for a in range(k)])
                state['extra'][2:2+k]=converted;state['extra'][2+k:2+2*k]=converted
                report.update(reason='original_23_to_63_float_copy_and_tiny_reset',float_quantized=True,counter_reset=True)
            else:
                report.update(reason='explicit_fresh_reset_of_changed_store',counter_reset=True)
        elif fmt_old==fmt_new and fmt_new!=63:
            report['reason']='preserve_underlying_storage_while_replacing_locks'
        elif fmt_old==fmt_new==63 and base_old==base_new:
            targets=new_policy['frequency'].get('targets',[None]*k);edges=new_policy['frequency'].get('edges',[0.]*k)
            # fi first flushes when reading the current edges for its editor.
            state['raw'][0]=float(state['updates']);state['raw'][1:1+k]=state['extra'][2+2*k:]
            state['targets']=[math.nan if t is None else t for t in targets]
            updated=[edges[a] if targets[a] is None else 0. for a in range(k)]
            state['extra'][2:2+k]=updated;state['extra'][2+k:2+2*k]=updated
            report['reason']='original_fi_target_edit_preserves_learning_and_restarts_dual_edges'
        elif fmt_old==25 and fmt_new==27:
            old=state;state=_fresh(27,h,k,new_policy)
            state['updates']=math.floor(old['raw'][0]+.5);state['visits']=old['visits'];state['raw'][:1+k]=old['raw'][:1+k]
            for b in range(h):
                old_r=_offset(25,b,k);new_r=_offset(27,b,k);r=old['raw'][old_r:old_r+k]
                state['raw'][new_r:new_r+k]=r;state['raw'][new_r+k:new_r+2*k]=_normal(r)
            report['reason']='original_mB_from_mA_preserves_regrets_and_seeds_bucket_averages_from_current_policy'
        elif fmt_old==63 and base_old in (23,31) and fmt_new==base_old:
            old=state;flushed=old['raw'][:];flushed[0]=float(old['updates']);flushed[1:1+k]=old['extra'][2+2*k:]
            quantized=_float32(flushed)
            state=_fresh(fmt_new,h,k,new_policy);state['raw']=([quantized[0]]+quantized[1+k:]) if fmt_new==23 else quantized
            state['updates']=math.floor(quantized[0]+.5);state['visits']=old['visits']
            if fmt_new==31:state['extra']=quantized[1:1+k]
            report.update(reason='original_mz_unwrap_flush_and_float_serialization',float_quantized=True)
        else:
            raise ValueError(f'Cannot preserve node {node_id} format {fmt_old}->{fmt_new}; select checkpoint_migration="reset" explicitly')
        states.append(state);changes.append(report)
    from .hrc_parallel import validate_trailer
    trailer=raw_file[cursor:]
    validate_trailer(trailer,struct.unpack_from('<4Q',raw_file,36),expected_threads=index.get('training_threads',1))
    header_size=68+players*8
    data=bytearray(raw_file[:header_size]);data[:8]=b'HRSOLV03'
    struct.pack_into('<Q',data,8,_identity(new_tree));struct.pack_into('<I',data,32,int(solver_mode=='v4'))
    for state in states:
        data.extend(struct.pack('<QI',state['updates'],state['format']))
        for values,code in ((state['visits'],'Q'),(state['raw'],'d'),(state['extra'],'d')):
            data.extend(struct.pack(f'<{len(values)}{code}',*values))
        if state['format']==63:
            data.extend(struct.pack(f'<{len(state["targets"])}d',*state['targets']))
    data.extend(trailer)
    output.mkdir(parents=True,exist_ok=True);target=output/'migration-input.bin';target.write_bytes(data)
    report={'mode':mode,'source_checkpoint':str(path),'source_sha256':hashlib.sha256(raw_file).hexdigest(),
            'source_identity':identity,'new_identity':_identity(new_tree),'samples':samples,'rng_preserved':True,
            'solver_mode_changed':bool(old_v4)!=bool(solver_mode=='v4'),'changed_nodes':changes,
            'structural_scope_unchanged':True,'migration_checkpoint_sha256':hashlib.sha256(data).hexdigest()}
    (output/'migration.json').write_text(json.dumps(report,indent=2))
    return target,report
