"""Interleaved independent native candidates, with immutable comparison inputs."""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',action='append',nargs=2,required=True,metavar=('NAME','EXE'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=5_000_000)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--threads',type=int,default=8)
    parser.add_argument('--scenario',choices=['three','nine'],default='three')
    parser.add_argument('--memory-gib',type=int,default=8)
    parser.add_argument('--serial-samples',type=int,default=100_000)
    parser.add_argument('--serial-reference',type=Path,help='Reuse prior full-state serial parity for the same frozen executables; not parity on this scenario')
    parser.add_argument('--discard-trial-checkpoints',action='store_true',
                        help='Hash and remove only checkpoints created under this new exclusive output directory')
    parser.add_argument('--case-threads',action='append',nargs=2,default=[],metavar=('NAME','THREADS'))
    parser.add_argument('--case-high-qos',action='append',default=[])
    parser.add_argument('--resume',type=Path,help='Optional own checkpoint for a mature-workload comparison')
    parser.add_argument('--profile-case',action='append',default=[],help='Enable experimental scheduler telemetry via native argv22 for this case')
    args=parser.parse_args();cases=[(name,str(Path(exe).resolve())) for name,exe in args.case]
    if len({name for name,_ in cases})!=len(cases):raise ValueError('Duplicate case name')
    case_threads={name:int(count) for name,count in args.case_threads}
    high_qos=set(args.case_high_qos)
    if high_qos-{name for name,_ in cases}:raise ValueError('Unknown HighQoS case')
    profile_cases=set(args.profile_case)
    if profile_cases-{name for name,_ in cases}:raise ValueError('Unknown profiling case')
    if set(case_threads)-{name for name,_ in cases}:raise ValueError('Unknown thread override case')
    if any(not 1<=count<=32 for count in [args.threads,*case_threads.values()]):raise ValueError('Threads require 1..32')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('round3_monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    original_command=monitor.phase_command
    def profile_command(plan,name,**kwargs):
        command=original_command(plan,name,**kwargs)
        if plan.get('scheduler_profile'):
            assert len(command)==20  # argv19 is the explicit additional budget.
            command.extend(['1','1','1'])  # terminal tables, adaptive scheduler, telemetry
        return command
    monitor.phase_command=profile_command
    source=ROOT/('.research-cache/three40bb-ci10-independent-20261107' if args.scenario=='three'
                 else '.research-cache/nine40bb-ci10-independent-20261106')
    initial=args.resume.resolve() if args.resume else source/'initialization/checkpoint.bin'
    formal=source/'formal/checkpoint.bin'
    with initial.open('rb') as stream:header=stream.read(24)
    if header[:8]!=b'HRSOLV03':raise ValueError('Version-three native checkpoint required')
    initial_samples=struct.unpack_from('<Q',header,16)[0]
    plan_path=source/'plan.json' if args.scenario=='three' else ROOT/'reports/hrc-nine40bb-ci10-independent-20261106.json'
    base=json.loads(plan_path.read_text(encoding='utf-8'))
    base.update(output=str(out),formal_track_ci=False,formal_target_ci=-1,hard_seconds_per_phase=180,
                memory_budget_bytes=args.memory_gib<<30)
    base.pop('maximum_additional_samples',None)
    result={'status':'running','cases':dict(cases),'executable_sha256':{name:sha(exe) for name,exe in cases},
            'scenario':args.scenario,'memory_budget_bytes':args.memory_gib<<30,
            'samples_per_trial':args.samples,'repeats':args.repeats,'threads':args.threads,
            'case_threads':{name:case_threads.get(name,args.threads) for name,_ in cases},
            'initial_checkpoint':str(initial),'initial_samples':initial_samples,
            'scheduler_profile_cases':sorted(profile_cases),
            'high_qos_cases':sorted(high_qos),
            'serial':[],'trials':[],'initial_sha256_before':sha(initial),'formal_sha256_before':sha(formal),
            'limits':['One machine; CPU clocks and affinity not fixed.',
                      'Fixed samples with CI disabled are not a strategy-quality or CI10 result.',
                      'Asynchronous update interleavings differ; serial parity is necessary, not sufficient.']}

    def run(name,exe,phase,samples,threads):
        plan=copy.deepcopy(base)
        plan['source_plan_reference_build']=plan['build']
        plan['build']={'executable_path':exe,'executable_sha256':sha(exe),
                       'build_identity':'Frozen candidate; see case manifest, not the source plan build'}
        plan.update(formal_total_sample_cap=initial_samples+samples,training_threads=threads)
        plan['high_qos']=name in high_qos
        if initial_samples+samples>1_000_000_000 or name in profile_cases:
            plan['maximum_additional_samples']=samples
        if name in profile_cases:
            plan['scheduler_profile']=True
        with (out/'events.log').open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log):
            row=monitor.run_phase(plan,phase,resume=initial)
        assert row['summary']['iteration']==initial_samples+samples and row['summary']['stop_reason']=='sample_target'
        if name in high_qos:
            assert row['process_environment']['explicit_power_request']['succeeded']
            assert row['process_environment']['power_throttling']['control_mask']&1
            assert not row['process_environment']['power_throttling']['state_mask']&1
        compute_seconds=row['summary']['elapsed_seconds']-row['summary'].get('training_checkpoint_seconds',0)
        row.update(variant=name,samples_per_second=samples/row['summary']['elapsed_seconds'],
                   compute_seconds_excluding_checkpoint=compute_seconds,
                   compute_samples_per_second=samples/compute_seconds)
        return row

    def finish_trial(row):
        checkpoint=(Path(row['output'])/'checkpoint.bin').resolve()
        row['checkpoint_sha256']=sha(checkpoint)
        if args.discard_trial_checkpoints:
            if not checkpoint.is_relative_to(out) or checkpoint.name!='checkpoint.bin':
                raise ValueError('Refusing to remove checkpoint outside this trial output')
            checkpoint.unlink()
            row['generated_checkpoint_removed_after_hash']=True
            index=checkpoint.with_name('index.json')
            row['index_sha256']=sha(index)
            index.unlink()
            row['generated_index_removed_after_hash']=True

    try:
        if args.serial_reference:
            prior=json.loads(args.serial_reference.read_text(encoding='utf-8'))
            if not prior.get('serial_equal'):raise ValueError('Reference serial validation failed')
            for name,exe in cases:
                if sha(exe) not in prior['executable_sha256'].values():raise ValueError('Reference executable identity changed')
            result.update(serial_equal=True,serial_reference=str(args.serial_reference.resolve()),
                          serial_reference_sha256=sha(args.serial_reference),serial_parity_scenario=prior.get('scenario','three'))
            result['limits'].append('Serial parity reused from the recorded reference scenario; not a new serial run on this tree.')
        else:
            for name,exe in cases:
                row=run(name,exe,'serial_'+name,args.serial_samples,1)
                finish_trial(row);result['serial'].append(row)
            result['serial_equal']=len({r['checkpoint_sha256'] for r in result['serial']})==1
        if not result['serial_equal']:raise RuntimeError('Serial checkpoint mismatch')
        for repeat in range(args.repeats):
            ordered=cases[repeat%len(cases):]+cases[:repeat%len(cases)]
            for name,exe in ordered:
                row=run(name,exe,f'{name}_r{repeat}',args.samples,case_threads.get(name,args.threads))
                finish_trial(row)
                row['repeat']=repeat;result['trials'].append(row);monitor.dump(args.report,result)
                print(json.dumps({'case':name,'repeat':repeat,'seconds':row['summary']['elapsed_seconds'],
                                  'million_per_second':row['samples_per_second']/1e6}),flush=True)
        result['medians']={}
        for name,_ in cases:
            rows=[r for r in result['trials'] if r['variant']==name]
            seconds=[r['summary']['elapsed_seconds'] for r in rows]
            result['medians'][name]={'seconds':statistics.median(seconds),'min_seconds':min(seconds),
                                     'max_seconds':max(seconds),'million_samples_per_second':args.samples/statistics.median(seconds)/1e6,
                                     'compute_seconds_excluding_checkpoint':statistics.median([r['compute_seconds_excluding_checkpoint'] for r in rows]),
                                     'checkpoint_seconds':statistics.median([r['summary'].get('training_checkpoint_seconds',0) for r in rows]),
                                     'cpu_seconds':statistics.median([r['process_cpu_seconds'] for r in rows]),
                                     'average_cores':statistics.median([r['average_logical_cpus'] for r in rows]),
                                     'peak_working_set_bytes':statistics.median([r['peak_working_set_bytes'] for r in rows])}
        reference=result['medians'][cases[0][0]]['seconds']
        for row in result['medians'].values():row['speed_vs_reference']=reference/row['seconds']
        result['status']='completed'
    except Exception as error:
        result.update(status='failed',error=str(error))
        raise
    finally:
        result['initial_unchanged']=sha(initial)==result['initial_sha256_before']
        result['formal_unchanged']=sha(formal)==result['formal_sha256_before']
        monitor.dump(args.report,result);monitor.dump(out/'report.json',result)
    print(json.dumps({'status':result['status'],'medians':result['medians']}),flush=True)


if __name__=='__main__':main()
