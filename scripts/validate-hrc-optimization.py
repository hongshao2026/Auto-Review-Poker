"""Differential checks against a preserved pre-optimization native executable.

Covers fresh learning, both traversal modes, cross-version checkpoint restore,
resets, constrained policies, monetary models, static/dynamic streets and FGS.
Requires the development test fixtures and existing local resource caches.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from preflop_lab.hrc_native import build, prepare
from test_hrc_kernel import hu_tree
from test_hrc_tournament_native import model
from test_hrc_native_rake import rake_tree
from test_hrc_native_dynamic import fixed_tree
from test_hrc_native_features import fgs_tree


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def launch(exe,binary,resources,goal,output,mode,*,resume=None,reset=(False,False)):
    output.mkdir(parents=True,exist_ok=False)
    command=[str(exe),str(binary),str(resources),str(goal),'43',str(output),mode]
    if resume or any(reset):command += [str(resume) if resume else '-',str(int(reset[0])),str(int(reset[1]))]
    result=subprocess.run(command,capture_output=True,text=True,timeout=180)
    (output/'stdout.jsonl').write_text(result.stdout,encoding='utf-8')
    (output/'stderr.log').write_text(result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(f'{output.name}: {result.stderr[-2500:]}')
    rows=list(map(json.loads,result.stdout.splitlines()))
    final=rows[-1]
    if final.get('kind')!='finished' or final.get('iteration')!=goal or final.get('cancelled'):
        raise ValueError('Incomplete differential run: '+str(output))
    return {'command':command,'checkpoint':str(output/'checkpoint.bin'),
        'checkpoint_sha256':sha(output/'checkpoint.bin'),'summary':final}


def scenarios(folder):
    resources=ROOT/'.research-cache/abstractions'
    yield 'chip',hu_tree(),resources,True,6000
    for policy in ('locks','frequency'):
        tree=hu_tree()
        entry={'node_id':0}
        entry[policy]=[[.3]*169,None] if policy=='locks' else {'targets':[.4,None],'edges':[0.,.2]}
        tree['policies']={'version':1,'nodes':[entry]}
        yield policy,tree,resources,True,6000
    for mtt in (False,True):
        for bounty in ('none','ko','pko'):
            tree=hu_tree();tree['equity']=model(bounty,mtt)
            yield ('mtt' if mtt else 'icm')+'_'+bounty,tree,resources,bounty=='pko',6000
    for rake in ('nfnd','gg','full'):
        yield 'rake_'+rake,rake_tree(rake),resources,rake=='gg',6000
    for street,fmt in ((1,25),(2,27),(3,31)):
        tree=hu_tree()
        for node in tree['nodes']:
            node['street']=street
            if node['children']:node['buckets']=[169,1024,256,256][street]
        tree['stores']={'version':1,'street_formats':[23,fmt,fmt,fmt]}
        yield f'static_street{street}_store{fmt}',tree,resources,fmt==31,6000
    for street,fmt,policy in ((1,25,None),(2,27,'locks'),(3,31,'frequency')):
        directory=folder/f'dynamic_resources{street}'
        tree,_,_,_=fixed_tree(directory,street=street,players=3)
        tree['stores']={'version':1,'street_formats':[23,fmt,fmt,fmt]}
        if policy:
            entry={'node_id':0}
            entry[policy]=[[.3,.4],None] if policy=='locks' else {'targets':[.6,None],'edges':[0.,0.]}
            tree['policies']={'version':1,'nodes':[entry]}
        yield f'dynamic_street{street}_store{fmt}',tree,directory,street==3,6000
    for depth in (0,1):
        tree,resource=fgs_tree(folder,depth=depth,max_seconds=60)
        yield f'fgs{depth}',tree,resource,True,200


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--legacy-checkpoints-only',action='store_true',help='Continue the two retained real 60M runs by 1000 samples instead of running the fixture matrix')
    args=parser.parse_args()
    folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=False)
    binaries={'baseline':args.baseline.resolve(),'optimized':build()}
    report={'schema':'hrc-optimization-differential-v1','executables':{
        name:{'path':str(p),'sha256':sha(p)} for name,p in binaries.items()},'checks':[]}
    def compare(name,left,right):
        passed=left['checkpoint_sha256']==right['checkpoint_sha256']
        report['checks'].append({'case':name,'passed':passed,'left':left,'right':right})
        (folder/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        if not passed:raise ValueError('Checkpoint mismatch: '+name)
    if args.legacy_checkpoints_only:
        for scene,run_id in (('chip','bd7346fe454144f98a80bfd81d1c31c5'),('pko','17d7a7c0226b491282320cace6306346')):
            source=ROOT/'.research-cache/runs'/run_id
            checkpoint=source/'checkpoint.bin';binary=source/'tree.bin'
            before=sha(checkpoint)
            with checkpoint.open('rb') as stream:
                stream.seek(16);samples=struct.unpack('<Q',stream.read(8))[0]
            if samples!=60_000_000:raise ValueError('Expected the preserved 60M checkpoint')
            runs={n:launch(exe,binary,ROOT/'.research-cache/abstractions',samples+1000,
                folder/f'{scene}-{n}','v4',resume=checkpoint) for n,exe in binaries.items()}
            compare(f'{scene}/legacy-60m-plus1000',runs['baseline'],runs['optimized'])
            if sha(checkpoint)!=before:raise ValueError('Legacy source checkpoint changed')
            report['checks'][-1]['source']={'checkpoint':str(checkpoint),'sha256':before,
                'tree_sha256':sha(binary),'original_samples':samples,'unchanged':True}
        report.update(passed=True,checks_count=len(report['checks']))
        (folder/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        print(json.dumps({'passed':True,'legacy_checks':len(report['checks']),'report':str(folder/'report.json')}),flush=True)
        return
    for scene,tree,resources,lifecycle,goal in scenarios(folder):
        scene_dir=folder/scene
        binary=prepare(copy.deepcopy(tree),scene_dir/'input')['tree_binary']
        for mode in ('v3','v4'):
            path=scene_dir/mode
            common=(binary,resources,goal)
            direct={n:launch(exe,*common,path/f'{n}-direct',mode) for n,exe in binaries.items()}
            compare(f'{scene}/{mode}/fresh',direct['baseline'],direct['optimized'])
            if lifecycle:
                partial={n:launch(exe,binary,resources,goal//2,path/f'{n}-partial',mode) for n,exe in binaries.items()}
                compare(f'{scene}/{mode}/partial',partial['baseline'],partial['optimized'])
                for name,other in (('optimized','baseline'),('baseline','optimized')):
                    resumed=launch(binaries[name],*common,path/f'{name}-cross-resume',mode,
                        resume=partial[other]['checkpoint'])
                    compare(f'{scene}/{mode}/{name}-cross-resume',direct[name],resumed)
                for reset in ((True,False),(False,True),(True,True)):
                    label=f'reset-{int(reset[0])}-{int(reset[1])}'
                    reset_runs={n:launch(exe,*common,path/f'{n}-{label}',mode,
                        resume=partial['baseline']['checkpoint'],reset=reset) for n,exe in binaries.items()}
                    compare(f'{scene}/{mode}/{label}',reset_runs['baseline'],reset_runs['optimized'])
            print(json.dumps({'scene':scene,'mode':mode,'checks_passed':len(report['checks'])}),flush=True)
    report['passed']=all(c['passed'] for c in report['checks'])
    report['checks_count']=len(report['checks'])
    (folder/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'report':str(folder/'report.json')}),flush=True)


if __name__=='__main__':main()
