"""Compare independent general policies with original qp/qw and pinned shipped JS."""
from __future__ import annotations
import base64
import copy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_tree_builder import _Builder,default_settings
from preflop_lab import hrc_general_policy as general

JAVA=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
NODE=Path(r'D:\Tools\REA-Research\node-v24.22.2-win-x64\node.exe')
JAR=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')


def settings(case,rng):
    n=2+case%9;deep=case%5>=2
    stacks=[rng.choice([5000,10000,30000]) if deep else rng.choice([25,50,100,500,2000]) for _ in range(n)]
    config=default_settings(n,stacks,100,preflop_policy='general',postflop_policy='general')
    h=config['handdata'];h.update(skipSb=bool(case%2),anteType=['REGULAR','BB_ANTE_ANTE_FIRST','BB_ANTE_BLIND_FIRST'][case%3],straddleType=['OFF','SINGLE','DOUBLE','BUTTON'][case%4] if n>=3 else 'OFF')
    h['blinds'][2]=[0,10,100][case%3]
    pre=config['treeconfig']['preflop']['settings'];post=config['treeconfig']['postflop']['settings']
    pre.update(PREFLOP_ALLIN_THRESHOLD=100,PREFLOP_ADD_ALLIN_SPR=[0,7,-1][case%3],ALLOWED_FLATS_PER_RAISE=[4,3,2,1,1],
               ALLOW_COLD_CALLS=bool(case%2),ALLOW_FLATS_CLOSING_ACTION=bool(case%3),ALLOW_SB_COMPLETE=bool(case%4))
    # Distinct values exercise every position branch, including optional fallback.
    for i,key in enumerate(k for k in pre if k.startswith('SIZES_')):
        if case%5:pre[key]=(f'{2+i/10:.1f}bb + 1bb' if key.startswith('SIZES_OPEN_') else f'{1.5+i/20:.2f}x + 0.5x')
    if case%4==0:pre['SIZES_3BET_OOP']=None
    if case%7==0:pre['SIZES_3BET_SB_VS_OTHER']=pre['SIZES_3BET_BB_VS_OTHER']=None
    post.update(POSTFLOP_LOW_SPR_THRESHOLD=[2.5,2.5] if case%3 else [-1,-1],POSTFLOP_ALLOW_DONK=[bool(case%2)]*2,
                POSTFLOP_ALLOW_DONK_PREV_AGGRESSION=[bool(case%3)]*2,POSTFLOP_MAX_BETS_PER_STREET=[-1,-1] if case%4 else [2,2],
                POSTFLOP_FORCE_CHECKDOWN_AFTER=[3]*9,POSTFLOP_ADD_ALLIN_SPR=[0,0] if case%2 else [5,5])
    if case%2:
        for i,key in enumerate(k for k in post if k.endswith(('_BET','_RAISE','_DONK')) and not k.startswith('POSTFLOP_ALLOW_')):
            post[key]=[[f'{30+i*3}%','2e','50g','2x','2bb','none','33% 66g 3e'][i%7]]*2
    return config


def main():
    start=time.perf_counter();rng=random.Random(5105);rows=[];expected={};configs={};input_counts={}
    for case in range(270):
        cfg=settings(case,rng);builder=_Builder(cfg,250000,None,None,'none');context=builder.initial()
        pre=builder.pre;post=builder.post
        pre_tokens=sorted({x for k,x in pre.items() if k.startswith('SIZES_') and isinstance(x,str)})
        post_tokens=sorted({x for k,row in post.items() if k.endswith(('_BET','_RAISE','_DONK')) for x in row if isinstance(x,str)})
        token=lambda xs:';'.join(base64.b64encode(x.encode()).decode() for x in xs)
        for step in range(35):
            s=context.state;actor=builder.actor(context);minimum,maximum=builder.limits(context,actor)
            item={'actor':-1 if actor is None else actor,'street':s.street,'minimum':minimum,'maximum':maximum,
                  'canRaise':minimum>0,'currentBet':s.current_bet,'remaining':list(s.remaining),'streetContributions':list(s.street_paid),
                  'previousContributions':list(s.dead_paid),'participantsMask':s.participants,'foldedMask':s.folded,'deadMoney':s.dead_money,
                  'bets':s.bets,'flats':s.flats,'live':s.live_count,'getNumberOfPlayers':builder.n,
                  'getPlayerIndexSmallBlind':-1 if builder.skip_sb else builder.n-2,'getPlayerIndexBigBlind':builder.n-1,'getPlayerIndexButton':builder.button,
                  'ip':[[general.in_position(builder,i,j) for j in range(builder.n)] for i in range(builder.n)]}
            independent={'next':builder.next_street(context)}
            if actor is not None:
                item.update(closing=general.closing_action(builder,context,actor),donk=builder.is_donk(context,actor))
                if minimum>0:
                    try:item['spr']=general.spr(builder,context,actor);independent['sizes']=builder.sizings(context,actor)
                    except Exception as exc:raise RuntimeError(f'case={case} step={step} ctx={context}') from exc
                    if s.street==0:independent['flat']=general.can_flat(builder,context,actor)
            h=cfg['handdata']
            for moving in (False,True):
                name=f'{case}_{step}_{int(moving)}';expected[name]=(copy.deepcopy(item),copy.deepcopy(independent));configs[name]={'preflop':pre,'postflop':post}
                rows.append('\t'.join([name,','.join(map(str,h['stacks'])),','.join(map(str,h['blinds'])),str(['REGULAR','BB_ANTE_ANTE_FIRST','BB_ANTE_BLIND_FIRST'].index(h['anteType'])),str(['OFF','SINGLE','DOUBLE','BUTTON'].index(h['straddleType'])),str(h['skipSb']).lower(),str(s.street),','.join(f'{a.street}:{a.kind}:{a.amount}' for a in context.history) or '-',str(moving).lower(),token(pre_tokens),token(post_tokens)]))
            normalized=builder.normalize(context)
            if normalized!=context:context=normalized;continue
            children=builder.children(context)
            if not children:break
            # Mix raises and calls to reach cold calls, deep reraises and all streets.
            candidates=children[1:] if len(children)>1 and rng.random()<.9 else children
            if case%3==0 and len(candidates)>1:context=candidates[0]
            else:context=rng.choice(candidates)
        input_counts[str(case)]=step+1
    out=ROOT/'analysis/hrc-deep/general-builder';out.mkdir(exist_ok=True);classes=out/'classes';classes.mkdir(exist_ok=True)
    inputs=out/'inputs.tsv';inputs.write_text('\n'.join(rows)+'\n');source=ROOT/'scripts/java/OriginalGeneralContextProbe.java'
    subprocess.run([str(JAVA.with_name('javac.exe')),'-d',str(classes),str(ROOT/'scripts/java/OriginalTreeProbe.java'),str(source)],check=True,capture_output=True)
    command=[str(JAVA),'-cp',str(classes),'OriginalGeneralContextProbe',str(JAR),str(inputs)]
    process=subprocess.run(command,capture_output=True,text=True);(out/'original.jsonl').write_text(process.stdout);(out/'stderr.txt').write_text(process.stderr)
    if process.returncode:raise RuntimeError(process.stderr[-4000:])
    records=list(map(json.loads,process.stdout.splitlines()));cases=[r for r in records if r['kind']=='case'];failures=[];pairs={};js=[]
    for row in cases:
        wanted,_=expected[row['id']];a=row['actual']
        for key,value in wanted.items():
            if a.get(key)!=value:failures.append({'id':row['id'],'field':key,'expected':value,'original':a.get(key)})
        group=row['id'].rsplit('_',1)[0]
        if group in pairs and pairs[group]!=a:failures.append({'id':row['id'],'field':'moving_button_current_hand_invariance'})
        pairs[group]=a;js.append({**row,'settings':configs[row['id']]})
    script_input=out/'script-input.json';script_input.write_text(json.dumps(js))
    js_command=[str(NODE),str(ROOT/'scripts/js/hrc-general-policy-oracle.cjs'),str(script_input)]
    process=subprocess.run(js_command,capture_output=True,text=True)
    if process.returncode:raise RuntimeError(process.stderr[-4000:])
    (out/'script-output.json').write_text(process.stdout);script_results=json.loads(process.stdout);covered=set()
    for row in script_results:
        covered.update(row['settings_read']);_,wanted=expected[row['id']]
        for key,value in wanted.items():
            if row.get(key)!=value:failures.append({'id':row['id'],'field':'script_'+key,'expected':value,'original':row.get(key)})
    all_keys=set(general.PRE_DEFAULTS)|set(general.POST_DEFAULTS)
    report={'passed':not failures,'context_count':len(cases),'configuration_count':270,'moving_button_pairs':len(pairs),
            'script_settings':len(all_keys),'covered_settings':sorted(covered),'uncovered_settings':sorted(all_keys-covered),'failures':failures,
            'scope':'Original pure qp/qw/lB/lC contexts plus exact hash-pinned shipped JS functions under synthetic API context; no HRC GUI, solver, arbitrary scripts or saved policies.',
            'command':command,'script_command':js_command,'class_hashes':[r for r in records if r['kind']=='class'],
            'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,Path(__file__),ROOT/'scripts/js/hrc-general-policy-oracle.cjs',ROOT/'preflop_lab/hrc_general_policy.py',ROOT/'preflop_lab/hrc_tree_builder.py']},
            'script_hashes':json.loads((ROOT/'analysis/hrc-deep/general-scripts/manifest.json').read_text()),'seconds':time.perf_counter()-start}
    (ROOT/'reports/hrc-original-general-builder-validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ['passed','context_count','moving_button_pairs','script_settings','uncovered_settings','seconds']},indent=2))
    if failures:print(json.dumps(failures[:12],indent=2));raise SystemExit(1)


if __name__=='__main__':main()
