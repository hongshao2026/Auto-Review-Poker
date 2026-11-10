"""Summarize the verified MTT captures and the resumed same-compiler PGO trials."""
from pathlib import Path
import hashlib
import json
import statistics
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'.research-cache/mtt-hotspots-pgo-20261109'
OUTPUT=ROOT/'reports/hrc-mtt-hotspots-pgo-20261109.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file,'sha256').hexdigest()


def rel(path):
    return path.relative_to(ROOT).as_posix()


def summarize_capture(name):
    path=RUN/name/'analysis.json'
    d=read(path)
    v=d['validation']
    assert v['no_lost_events'] and v['cswitch_continuity_mismatches']==0
    assert v['cpu_stack_coverage']>.99 and v['max_abs_thread_residual_seconds']<.0001
    assert len(d['worker_tids'])==20
    capacity=d['window']['wall_seconds']*20
    off=d['off_cpu_seconds']
    waits=sum(seconds for key,seconds in off.items() if key in ('waiting','waiting_without_ready_event'))
    ready=sum(seconds for key,seconds in off.items() if key in ('ready_to_run','ready_after_wait'))
    yielded=sum(x['seconds'] for x in d['off_cpu_state_reason'] if x['state'] in (1,3,7) and x['reason']==33)
    javapath=path.with_name('java-hotspots.json')
    j=read(javapath) if javapath.exists() else None
    if d['kind']=='hrc':
        assert j and j['workers_observed']==20
    return {'etw_evidence':rel(path),'java_evidence':rel(javapath) if j else None,
            'window':d['window'],'validation':v,'etw_worker_samples':d['sample_count'],
            'mean_running_logical_cpus':d['worker_mean_logical_cpus'],
            'worker_capacity_percent':{'running':100*d['worker_running_cpu_seconds']/capacity,
                'waiting':100*waits/capacity,'ready':100*ready/capacity,
                'ready_after_yield_reason_33_subset':100*yielded/capacity},
            'top_native_exclusive_samples':d['exclusive_native'][:12],
            'off_cpu_resume_native_frames':d['off_cpu_by_resume_native_frame'][:8],
            'top_java_execution_samples':j['exclusive_java'][:12] if j else None,
            'java_execution_sample_count':j['worker_execution_samples'] if j else None}


def summarize_bench(stage, *, confirmation=False):
    path=RUN/f'benchmark-{"confirmation" if confirmation else "resumed"}-{stage}'/'report.json'
    d=read(path)
    assert d['status']=='completed' and d['inputs_unchanged']
    assert d['samples']==50_000_000
    order=['canonical','pgo'] if confirmation else ['canonical','pgo','pgo','canonical']
    assert [r['variant'] for r in d['trials']]==order
    assert {c['threads'] for c in d['cases'].values()}=={20}
    commands=[read(path.parent/r['phase']/'command.json') for r in d['trials']]
    assert all(cmd[1:5]+cmd[6:]==commands[0][1:5]+commands[0][6:] for cmd in commands)
    result={}
    def observation(r):
        monitor=path.parent/r['phase']/'monitor.jsonl'
        lines=[json.loads(line) for line in monitor.read_text(encoding='utf-8').splitlines()]
        begin=next(row for row in lines if row['wall_seconds']>=r['loading_setup_and_initial_save_seconds'])
        end=lines[-1]
        wall=end['wall_seconds']-begin['wall_seconds']
        cpu=end['cpu_seconds']-begin['cpu_seconds']
        t0,t1=begin['system_cpu_times'],end['system_cpu_times']
        busy=sum(t1[k]-t0[k] for k in ('kernel_seconds_including_idle','user_seconds'))-(t1['idle_seconds']-t0['idle_seconds'])
        return {'phase':r['phase'],'compute_seconds':r['compute_seconds'],
                'training_seconds':r['summary']['elapsed_seconds'],'wall_seconds':r['wall_seconds'],
                'sampled_training_window':{'wall_seconds':wall,'solver_cpu_seconds':cpu,
                    'solver_mean_logical_cpus':cpu/wall,'non_solver_mean_logical_cpus':(busy-cpu)/wall}}
    for variant in ('canonical','pgo'):
        trials=[r for r in d['trials'] if r['variant']==variant]
        assert all(r['summary']['scope_effective_samples']==d['samples'] and
                   r['summary']['sampling_path']==[0] and r['summary']['ci'] is None and
                   r['summary']['terminal_settlements']==0 for r in trials)
        result[variant]={'binary_sha256':d['cases'][variant]['sha256'],
                         'compute_seconds':statistics.median(r['compute_seconds'] for r in trials),
                         'training_seconds':statistics.median(r['summary']['elapsed_seconds'] for r in trials),
                         'wall_seconds':statistics.median(r['wall_seconds'] for r in trials),
                         'observations':[observation(r) for r in trials]}
    pairs=[]
    for base,pgo in zip(result['canonical']['observations'],result['pgo']['observations']):
        b,p=base['sampled_training_window'],pgo['sampled_training_window']
        delta=p['non_solver_mean_logical_cpus']-b['non_solver_mean_logical_cpus']
        pairs.append({'baseline':base['phase'],'pgo':pgo['phase'],
                      'non_solver_logical_cpu_difference':delta,'within_one_logical_cpu':abs(delta)<=1,
                      'observed_compute_time_ratio_pgo_over_baseline':pgo['compute_seconds']/base['compute_seconds'],
                      'observed_solver_cpu_time_ratio_pgo_over_baseline':p['solver_cpu_seconds']/b['solver_cpu_seconds']})
    return {'evidence':rel(path),'starting_samples':d['source_samples'],'additional_samples_per_trial':d['samples'],
            'inputs_unchanged':d['inputs_unchanged'],'inputs_sha256':d['input_sha256'],
            'variants':result,'pairwise_background_comparison':pairs,
            'observed_timing_ratio_baseline_over_pgo':{k:result['canonical'][k]/result['pgo'][k]
                                        for k in ('compute_seconds','training_seconds','wall_seconds')}}


def main():
    canonical=read(ROOT/'.research-cache/bubble-round2-20261109/accepted/manifest.json')
    profile=RUN/'mtt-early-mature.profdata'
    candidate=read(RUN/'zig-pgo/build.json')
    assert candidate['returncode']==0 and not candidate['stderr'].strip()
    assert sha(profile)==candidate['profile_sha256']
    flags=[f for f in candidate['command'][:-1] if not f.startswith('-fprofile-use=') and f!='-Werror=profile-instr-out-of-date']
    assert flags==canonical['command'][:-1]
    parity=read(RUN/'zig-pgo-serial-validation.json')
    assert parity['full_checkpoint_byte_equal']
    capture_names=('hrc-early-r2','native-early','hrc-mature','native-mature')
    captures={name:summarize_capture(name) for name in capture_names}
    benches={stage:summarize_bench(stage) for stage in ('early','mature')}
    benches['mature_confirmation']=summarize_bench('mature',confirmation=True)
    reg=RUN/'pgo-regression.xml'
    regression=None
    if reg.exists():
        suites=ET.parse(reg).getroot().findall('.//testsuite')
        regression={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
        regression['evidence']=rel(reg)
    output={'schema':'mtt-ep-hotspots-pgo-v1','workload':'Hand bubble, eight-seat 58-player MTT ICM, EP after UTG folds, 20 workers',
            'profiling':captures,'fixed_work':benches,
            'pgo':{'compiler_baseline_unchanged':True,'profile_training_extra_samples':{'early':5_000_000,'mature':5_000_000},
                   'profile_sha256':sha(profile),'profile_merge_evidence':rel(RUN/'merge.json'),
                   'binary_sha256':sha(RUN/'zig-pgo/solver.exe'),'candidate_build_evidence':rel(RUN/'zig-pgo/build.json'),
                   'baseline_build_identity':canonical['build_identity'],'serial_checkpoint_evidence':rel(RUN/'zig-pgo-serial-validation.json'),
                   'serial_checkpoint_sha256':parity['zig_pgo_checkpoint_sha256'],'regression':regression},
            'boundaries':['Original and native strategies initialized independently; the trace windows are not matched random paths.',
                          'HRC Java method names are JFR execution samples; native names are exclusive ETW sampled addresses.',
                          'ETW wait accounting is normalized by 20 worker times the recorded interior. Ready-after-yield is a subset of ready.',
                          'Resume stack attribution does not prove recoverable lock delay. No PMU memory-bandwidth counters.',
                          'PGO fixed-work tests are separate from profile collection and exclude CI polling. Do not extrapolate as measured time-to-CI.',
                          'The sampled training window includes checkpoint pauses; non-solver CPU is total system busy time minus solver CPU. Background interference is retained, not silently discarded.',
                          'The confirmation pair uses a one-logical-CPU background difference as a screening rule. It does not control frequencies, core placement or transient interference.',
                          'The prior interrupted benchmark is excluded. This report does not publish or select a new production binary.']}
    OUTPUT.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(OUTPUT),'fixed_work':benches,'regression':regression},ensure_ascii=False))


if __name__=='__main__':
    main()
