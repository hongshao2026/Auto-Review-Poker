"""Sequential, interleaved comparison against the previous shipped kernel."""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_native import build


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--extra',action='append',nargs=2,default=[],metavar=('NAME','EXE'))
    parser.add_argument('--samples',type=int,default=5_000_000)
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    source=ROOT/'.research-cache/throughput-round2-20261108'
    baseline=json.loads((source/'baseline.json').read_text(encoding='utf-8'))
    cases=[('previous',baseline['executable']),('current',str(build()))]
    cases.extend((name,str(Path(path).resolve())) for name,path in args.extra)
    spec=importlib.util.spec_from_file_location('round2_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    scene=ROOT/'.research-cache/three40bb-ci10-independent-20261107'
    initial=scene/'initialization/checkpoint.bin';formal=scene/'formal/checkpoint.bin'
    base=json.loads((scene/'plan.json').read_text(encoding='utf-8'))
    base.update(output=str(output),formal_track_ci=False,formal_target_ci=-1,hard_seconds_per_phase=120)
    base.pop('maximum_additional_samples',None)
    result={'status':'running','cases':dict(cases),'executable_sha256':{name:digest(path) for name,path in cases},
            'samples_per_trial':args.samples,'repeats':3,'serial':[],'trials':[],
            'initial_sha256_before':digest(initial),'formal_sha256_before':digest(formal),
            'limitations':['Fixed-sample throughput is not CI10 completion time or a strategy quality bound.',
                           'One machine; asynchronous trajectories, CPU clocks and affinity are not fixed.',
                           'CI disabled; independent original/previous CI10 evidence remains unmodified.']}

    def run(label,exe,name,samples,threads):
        plan=copy.deepcopy(base);plan['build']['executable_path']=exe
        plan.update(formal_total_sample_cap=10_000_000+samples,training_threads=threads)
        with (output/'events.log').open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log):
            row=monitor.run_phase(plan,name,resume=initial)
        assert row['summary']['iteration']==10_000_000+samples
        assert row['summary']['stop_reason']=='sample_target'
        row.update(variant=label,samples_per_second=samples/row['summary']['elapsed_seconds'])
        return row

    try:
        for label,exe in cases:
            row=run(label,exe,'serial_'+label,100_000,1)
            row['checkpoint_sha256']=digest(Path(row['output'])/'checkpoint.bin');result['serial'].append(row)
        result['serial_equal']=len({row['checkpoint_sha256'] for row in result['serial']})==1
        if not result['serial_equal']:raise RuntimeError('Serial checkpoint parity failed')
        for repeat in range(3):
            ordered=cases[repeat:]+cases[:repeat]
            if repeat%2:ordered=list(reversed(ordered))
            for label,exe in ordered:
                row=run(label,exe,f'{label}_r{repeat}',args.samples,8);row['repeat']=repeat
                result['trials'].append(row);monitor.dump(args.report,result)
                print(json.dumps({'case':label,'repeat':repeat,'seconds':row['summary']['elapsed_seconds'],
                                  'million_per_second':row['samples_per_second']/1e6}),flush=True)
        result['medians']={}
        for label,_ in cases:
            rows=[r for r in result['trials'] if r['variant']==label]
            seconds=[r['summary']['elapsed_seconds'] for r in rows]
            result['medians'][label]={'seconds':statistics.median(seconds),'min_seconds':min(seconds),
                                     'max_seconds':max(seconds),'million_samples_per_second':args.samples/statistics.median(seconds)/1e6,
                                     'cpu_seconds':statistics.median([r['process_cpu_seconds'] for r in rows]),
                                     'average_cores':statistics.median([r['average_logical_cpus'] for r in rows])}
        for row in result['medians'].values():row['speed_vs_previous']=result['medians']['previous']['seconds']/row['seconds']
        result['status']='completed'
    finally:
        result['initial_unchanged']=digest(initial)==result['initial_sha256_before']
        result['formal_unchanged']=digest(formal)==result['formal_sha256_before']
        monitor.dump(args.report,result);monitor.dump(output/'report.json',result)
    print(json.dumps({'status':result['status'],'medians':result['medians']}),flush=True)


if __name__=='__main__':main()
