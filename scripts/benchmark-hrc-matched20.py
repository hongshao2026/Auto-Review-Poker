"""Current-session native20 CI10 run and matched original20 evidence report.

Prepare/read are harmless. --native executes only the fixed accepted native
kernel; original execution stays in the explicitly logged desktop workflow.
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT/'analysis/hrc-desktop/three40bb-matched20-20261108'
NATIVE=ROOT/'.research-cache/three40bb-matched20-20261108'
REPORT=ROOT/'reports/hrc-three40bb-matched20-20261108.json'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def original_summary():
    folder=ORIGINAL/'formal';result=folder/'observation-result.json'
    if not result.exists():
        startup=ORIGINAL/'startup-observation.json'
        return {'status':'not_completed','timed_sampling_started':(folder/'win32-observations.jsonl').exists(),
                'startup_observation':read(startup) if startup.exists() else None}
    observation=read(result)
    events=[json.loads(line) for line in (folder/'win32-observations.jsonl').read_text(encoding='utf-8').splitlines()]
    ok=next(x for x in events if x.get('event')=='ok_posted')
    records=[r for r in observation['ci_records'] if r['index']>=0 and r['original_epoch_millis']>=ok['epoch_millis']]
    for row in records:row['elapsed_since_ok_seconds']=(row['original_epoch_millis']-ok['epoch_millis'])/1000
    reached=next((r for r in records if r['ci'] is not None and r['ci']<10),None)
    agent_records=[json.loads(line) for line in (folder/'agent-events.jsonl').read_text(encoding='utf-8').splitlines()]
    installed=[row for row in agent_records if row.get('event')=='installed']
    workers=installed[-1]['original_worker_count'] if installed else None
    verified=reached and workers==20 and not observation['cancel_sent'] and observation['reason']=='observed_idle_with_ci_below_target'
    return {'status':'ci_target_reached' if verified else 'stopped_without_verified_target',
            'runtime_workers':workers,'first_ci10_seconds':reached['elapsed_since_ok_seconds'] if reached else None,
            'ci':records[-1]['ci'] if records else None,'formal_samples':records[-1]['original_samples'] if records else None,
            'process_cpu_seconds':observation['process_cpu_seconds_delta'],
            'wall_seconds':observation['observer_elapsed_seconds'],
            'average_logical_cpus':observation['process_cpu_seconds_delta']/observation['observer_elapsed_seconds'],
            'peak_working_set_bytes':max(x['process_memory']['WorkingSetSize'] for x in events if 'process_memory' in x),
            'ci_trajectory':records,'observation':str(result),'cancel_sent':observation['cancel_sent']}


def native_run():
    if original_summary()['status']!='ci_target_reached':
        raise RuntimeError('Finish original20 before claiming or timing the paired native20 run')
    NATIVE.mkdir(parents=True,exist_ok=False)
    source=ROOT/'.research-cache/three40bb-ci10-independent-20261107'
    accepted=read(ROOT/'.research-cache/throughput-round3-20261108/accepted/manifest.json')
    exe=Path(accepted['executable']);assert sha(exe)==accepted['sha256']
    plan=copy.deepcopy(read(source/'plan.json'))
    plan.update(output=str(NATIVE),formal_track_ci=True,formal_target_ci=10,
                formal_total_sample_cap=3_000_000_000,maximum_additional_samples=2_990_000_000,
                hard_seconds_per_phase=1800,training_threads=20)
    plan['build']=dict(accepted['build'],executable_path=str(exe))
    initial=source/'initialization/checkpoint.bin'
    preserve=[initial,source/'formal/checkpoint.bin',
              ROOT/'.research-cache/three40bb-ci10-round3-20261108/current8/formal/checkpoint.bin',
              ROOT/'.research-cache/three40bb-ci10-round3-20261108/current20/formal/checkpoint.bin',
              Path(read(ORIGINAL/'plan.json')['source_initial_archive'])]
    report={'status':'running','workers':20,'plan':plan,'executable_sha256':sha(exe),
            'preserved_before':{str(p):sha(p) for p in preserve},'initial_samples':10_000_000}
    dump(NATIVE/'plan.json',plan);dump(NATIVE/'report.json',report)
    spec=importlib.util.spec_from_file_location('matched20_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    print(json.dumps({'status':'started','output':str(NATIVE),'threads':20}),flush=True)
    started=time.perf_counter()
    try:
        with (NATIVE/'runner-events.log').open('w',encoding='utf-8') as stream,contextlib.redirect_stdout(stream):
            phase=module.run_phase(plan,'formal',resume=initial)
        summary=phase['summary'];ci=(summary.get('ci') or {}).get('value')
        reached=summary['stop_reason']=='ci_target' and summary['target_reached'] and ci is not None and ci<10
        report.update(status='ci_target_reached' if reached else 'stopped_without_verified_target',
                      formal=phase,ci=ci,new_samples=summary['iteration']-10_000_000,
                      training_seconds=summary['elapsed_seconds'])
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        report['wall_seconds']=time.perf_counter()-started
        report['preserved_unchanged']={str(p):sha(p)==report['preserved_before'][str(p)] for p in preserve}
        dump(NATIVE/'report.json',report)
    print(json.dumps({k:report[k] for k in ('status','ci','new_samples','training_seconds')}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',action='store_true')
    args=parser.parse_args()
    if args.native:native_run()
    result={'schema':'hrc-three40bb-matched20-v1','scope':'3 players / 40BB / Full Tree / CI < 10 / 20 workers',
            'original':original_summary(),'native':read(NATIVE/'report.json') if (NATIVE/'report.json').exists() else {'status':'not_started'},
            'plan':str(ORIGINAL/'plan.json'),
            'limits':['Same tree and exact abstraction profiles, separate independently generated initial strategies/RNGs.',
                      'Formal runs execute sequentially; no overlapping training or compilation.',
                      'Original process includes GUI/JVM; native excludes Python/browser from its process measurements.',
                      'CPU affinity, clocks and other user applications are not modified or held constant.',
                      'CI is recent policy drift, not exploitability or a statistical confidence interval.']}
    dump(REPORT,result)
    print(json.dumps({'report':str(REPORT),'original_status':result['original']['status'],'native_status':result['native']['status']}),flush=True)


if __name__=='__main__':main()
