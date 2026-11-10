"""Measure the accepted kernel to CI10 from the immutable own 10m state."""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',default='current8')
    args=parser.parse_args()
    benchmark=json.loads((ROOT/'reports/hrc-throughput-round3-final-20261108.json').read_text(encoding='utf-8'))
    assert benchmark['status']=='completed' and benchmark['serial_equal']
    exe=Path(benchmark['cases'][args.case])
    assert sha(exe)==benchmark['executable_sha256'][args.case]
    source=ROOT/'.research-cache/three40bb-ci10-independent-20261107'
    output=ROOT/f'.research-cache/three40bb-ci10-round3-20261108/{args.case}'
    output.mkdir(parents=True,exist_ok=False)
    report_path=ROOT/f'reports/hrc-three40bb-ci10-round3-{args.case}-20261108.json'
    spec=importlib.util.spec_from_file_location('round3_ci_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    plan=copy.deepcopy(json.loads((source/'plan.json').read_text(encoding='utf-8')))
    plan.update(output=str(output),formal_track_ci=True,formal_target_ci=10,
                formal_total_sample_cap=3_000_000_000,maximum_additional_samples=2_990_000_000,
                hard_seconds_per_phase=1800,training_threads=benchmark['case_threads'][args.case])
    plan['build']['executable_path']=str(exe)
    initial=source/'initialization/checkpoint.bin'
    preserved=[initial,source/'formal/checkpoint.bin',
               ROOT/'.research-cache/three40bb-ci10-node-lock-20261108/formal/checkpoint.bin']
    report={'schema':'three40bb-round3-ci10-v1','status':'running','case':args.case,'plan':plan,
            'initial_checkpoint':str(initial),'executable_sha256':sha(exe),'formal_initial_samples':10_000_000,
            'preserved_sha256_before':{str(p):sha(p) for p in preserved},
            'limitations':['One formal run per thread count; asynchronous mixed snapshots change trajectories.',
                           'CI measures recent policy drift, not exploitability or a statistical confidence interval.',
                           'Initialization is reused from our independently generated state. No HRC policies/payoffs train the kernel.',
                           'Original HRC timing is historical, with its separate float32 saved initialization.',
                           'Clocks, affinity and other user applications are not controlled.']}
    monitor.dump(report_path,report);monitor.dump(output/'plan.json',plan)
    started=time.perf_counter()
    print(json.dumps({'status':'started','case':args.case,'threads':plan['training_threads'],'output':str(output)}),flush=True)
    try:
        with (output/'runner-events.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log):
            phase=monitor.run_phase(plan,'formal',resume=initial)
        summary=phase['summary'];value=(summary.get('ci') or {}).get('value')
        reached=summary['stop_reason']=='ci_target' and summary['target_reached'] and value is not None and value<10
        report.update(formal=phase,status='ci_target_reached' if reached else 'stopped_without_ci_target',
                      target_reached=bool(reached),ci=value,formal_new_samples=summary['iteration']-10_000_000,
                      formal_training_seconds=summary['elapsed_seconds'])
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        report.update(wall_seconds=time.perf_counter()-started,
                      preserved_unchanged={str(p):sha(p)==report['preserved_sha256_before'][str(p)] for p in preserved})
        monitor.dump(report_path,report);monitor.dump(output/'report.json',report)
    print(json.dumps({'status':report['status'],'case':args.case,'ci':report.get('ci'),
                      'seconds':report.get('formal_training_seconds'),'report':str(report_path)}),flush=True)


if __name__=='__main__':main()
