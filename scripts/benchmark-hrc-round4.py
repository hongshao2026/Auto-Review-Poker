"""Frozen-kernel large-tree diagnosis and candidate matrix; never builds in timing."""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/cpu-round4-20261108'


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnose-nine',action='store_true')
    parser.add_argument('--seconds',type=int,default=600)
    args=parser.parse_args()
    if not args.diagnose_nine:raise SystemExit('Select --diagnose-nine')
    out=BASE/'nine-baseline'
    out.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('round4_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    old=ROOT/'.research-cache/nine40bb-ci10-independent-20261106'
    initial=old/'initialization/checkpoint.bin'
    plan=copy.deepcopy(json.loads((ROOT/'reports/hrc-nine40bb-ci10-independent-20261106.json').read_text()))
    accepted=json.loads((ROOT/'.research-cache/throughput-round3-20261108/accepted/manifest.json').read_text())
    exe=Path(accepted['executable']);assert sha(exe)==accepted['sha256']
    plan['build']=dict(accepted['build'],executable_path=str(exe))
    for name in ['phases','interruption','observed_bottlenecks','topology_fairness_audit']:
        plan.pop(name,None)
    plan.update(output=str(out),training_threads=20,memory_budget_bytes=8<<30,
                formal_track_ci=True,formal_target_ci=10,formal_total_sample_cap=3_000_000_000,
                maximum_additional_samples=2_990_000_000,hard_seconds_per_phase=args.seconds)
    report={'status':'running','initial_checkpoint':str(initial),'initial_sha256_before':sha(initial),
            'plan':plan,'purpose':'Fixed-tree 20-worker diagnosis; wall bound, not a CI10 completion claim',
            'executable_sha256':sha(exe)}
    monitor.dump(out/'plan.json',plan);monitor.dump(out/'report.json',report)
    print(json.dumps({'status':'started','threads':20,'seconds':args.seconds,'output':str(out)}),flush=True)
    try:
        with (out/'runner.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):
            result=monitor.run_phase(plan,'formal',resume=initial)
        report.update(status='completed',formal=result)
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        report['initial_unchanged']=sha(initial)==report['initial_sha256_before']
        monitor.dump(out/'report.json',report)
        monitor.dump(ROOT/'reports/hrc-round4-nine-diagnostic-20261108.json',report)
    print(json.dumps({'status':report['status'],'report':str(out/'report.json'),
                      'summary':report.get('formal',{}).get('summary')}),flush=True)


if __name__=='__main__':main()
