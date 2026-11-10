"""Compare a preserved native baseline to the production kernel on identical inputs.

Runs serially in rotated order and requires identical checkpoint bytes. Output
directories must be new; no user run or baseline result is overwritten.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import statistics
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_native import build


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=5_000_000)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--seed',type=int,default=43)
    args=parser.parse_args()
    if not 1000<=args.samples<=60_000_000 or not 1<=args.repeats<=5:parser.error('Invalid benchmark budget')
    folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=False)
    helpers=runpy.run_path(str(ROOT/'scripts/audit-hrc-performance.py'))
    sha,run_case,scenes=(helpers[key] for key in ('sha','run_case','SCENES'))
    binaries={'baseline':args.baseline.resolve(),'optimized':args.candidate.resolve() if args.candidate else build()}
    reference=subprocess.check_output([str(binaries['baseline']),'--self-test'],text=True)
    actual=subprocess.check_output([str(binaries['optimized']),'--self-test'],text=True)
    expected=list(map(json.loads,reference.splitlines()))
    if expected!=list(map(json.loads,actual.splitlines())):raise ValueError('Native numeric probes differ')
    report={'schema':'hrc-production-optimization-benchmark-v1','samples':args.samples,'seed':args.seed,
        'repeats':args.repeats,'numeric_probes':{'records':len(expected),'identical':True},
        'executables':{name:{'path':str(p),'sha256':sha(p)} for name,p in binaries.items()},
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'native').iterdir() if p.is_file()},
        'scene_sha256':{name:sha(p) for name,p in scenes.items()},'trials':[],
        'limits':['No CPU affinity or clock control; sequential runs in rotated order.',
            'Fixed scene, seed and sample budget; numerical equality is not a convergence certificate.',
            'Native duration includes periodic/final checkpoint output; process wall duration includes startup.',
            'Resource metrics refer to the native process only.']}
    for repeat in range(args.repeats):
        order=list(binaries) if repeat%2==0 else list(reversed(binaries))
        for scene,tree in scenes.items():
            for name in order:
                trial=run_case(binaries[name],tree,folder/f'{scene}-{name}-{repeat}',args.samples,args.seed)
                trial.update(scene=scene,variant=name,repeat=repeat);report['trials'].append(trial)
                (folder/'partial.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps({'scene':scene,'variant':name,'repeat':repeat,
                    'seconds':trial['native_seconds'],'peak_mib':trial['peak_working_set_bytes']/1048576}),flush=True)
    report['results']={}
    for scene in scenes:
        rows=[t for t in report['trials'] if t['scene']==scene]
        expected=rows[0]['checkpoint_sha256']
        result={}
        for name in binaries:
            subset=[t for t in rows if t['variant']==name]
            result[name]={
                'median_native_seconds':statistics.median(t['native_seconds'] for t in subset),
                'median_wall_seconds':statistics.median(t['wall_seconds'] for t in subset),
                'median_peak_working_set_bytes':statistics.median(t['peak_working_set_bytes'] for t in subset),
                'identical_checkpoint':all(t['checkpoint_sha256']==expected for t in subset)}
        result['speedup']=result['baseline']['median_native_seconds']/result['optimized']['median_native_seconds']
        result['saved_working_set_bytes']=result['baseline']['median_peak_working_set_bytes']-result['optimized']['median_peak_working_set_bytes']
        report['results'][scene]=result
    report['all_checkpoints_identical']=all(r[n]['identical_checkpoint'] for r in report['results'].values() for n in binaries)
    (folder/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'completed':True,'report':str(folder/'report.json'),'results':report['results']}),flush=True)
    if not report['all_checkpoints_identical']:raise SystemExit('Checkpoint equivalence failed')


if __name__=='__main__':main()
