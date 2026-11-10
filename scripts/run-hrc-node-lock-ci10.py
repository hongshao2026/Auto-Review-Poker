"""Formal CI10 continuation from the same independent 10m comparison state."""
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
    source=ROOT/'.research-cache/three40bb-ci10-independent-20261107'
    output=ROOT/'.research-cache/three40bb-ci10-node-lock-20261108'
    output.mkdir(parents=True,exist_ok=False)
    report_path=ROOT/'reports/hrc-three40bb-ci10-node-lock-20261108.json'
    final_benchmark=json.loads((ROOT/'reports/hrc-throughput-round2-final-20261108.json').read_text(encoding='utf-8'))
    if final_benchmark['status']!='completed' or not final_benchmark['serial_equal']:
        raise RuntimeError('Final benchmark/serial validation must complete before CI run')
    exe=Path(final_benchmark['cases']['current'])
    if sha(exe)!=final_benchmark['executable_sha256']['current']:
        raise RuntimeError('Measured executable identity changed')
    spec=importlib.util.spec_from_file_location('node_lock_ci_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    plan=copy.deepcopy(json.loads((source/'plan.json').read_text(encoding='utf-8')))
    plan.update(output=str(output),formal_track_ci=True,formal_target_ci=10,
                formal_total_sample_cap=3_000_000_000,maximum_additional_samples=2_990_000_000,
                hard_seconds_per_phase=1800,training_threads=8)
    plan['build']['executable_path']=str(exe)
    initial=source/'initialization/checkpoint.bin';old_formal=source/'formal/checkpoint.bin'
    report={'schema':'three40bb-node-lock-ci10-v1','status':'running','plan':plan,
            'initial_checkpoint':str(initial),'initial_sha256_before':sha(initial),
            'old_formal_sha256_before':sha(old_formal),'executable_sha256':sha(exe),
            'formal_initial_samples':10_000_000,
            'comparison':'Same independently generated 10m state as the previous formal run; no HRC strategy/payoff training input.',
            'limitations':['The new lock changes asynchronous interleavings; one formal run per implementation.',
                           'CI is recent policy drift, not exploitability or a statistical confidence interval.',
                           'Measured new formal run excludes reused initialization and includes periodic/final saves.']}
    monitor.dump(report_path,report);monitor.dump(output/'plan.json',plan)
    started=time.perf_counter()
    try:
        phase=monitor.run_phase(plan,'formal',resume=initial)
        report['formal']=phase
        summary=phase['summary'];value=(summary.get('ci') or {}).get('value')
        reached=summary['stop_reason']=='ci_target' and summary['target_reached'] and value is not None and value<10
        report.update(status='ci_target_reached' if reached else 'stopped_without_ci_target',
                      target_reached=bool(reached),ci=value,
                      formal_new_samples=summary['iteration']-10_000_000,
                      formal_training_seconds=summary['elapsed_seconds'])
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        report.update(wall_seconds=time.perf_counter()-started,
                      initial_unchanged=sha(initial)==report['initial_sha256_before'],
                      old_formal_unchanged=sha(old_formal)==report['old_formal_sha256_before'])
        monitor.dump(report_path,report);monitor.dump(output/'report.json',report)
    print(json.dumps({'status':report['status'],'ci':report.get('ci'),
                      'seconds':report.get('formal_training_seconds'),'report':str(report_path)}),flush=True)


if __name__=='__main__':main()
