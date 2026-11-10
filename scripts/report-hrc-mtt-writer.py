"""Check the fixed-work lock trials and summarize the scheduler observations."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/mtt-writer-20261109'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def benchmark(name, count, order):
    folder=BASE/name
    report=read(folder/'report.json')
    assert report['status']=='completed' and report['inputs_unchanged']
    assert report['samples']==count and [r['variant'] for r in report['trials']]==order
    assert {v['threads'] for v in report['cases'].values()}=={20}
    commands=[read(folder/r['phase']/'command.json') for r in report['trials']]
    assert all(cmd[1:5]+cmd[6:]==commands[0][1:5]+commands[0][6:] for cmd in commands)
    runs=[]
    for trial in report['trials']:
        end=trial['summary']
        assert end['scope_effective_samples']==count and end['sampling_path']==[0]
        assert end['sampling_scope']=='selected_subtree' and end['stop_reason']=='sample_target'
        assert end['iteration']==report['source_samples']+count
        assert end['ci'] is None and end['terminal_tables'] and end['terminal_settlements']==0
        assert end['unlocked_strategy_reads']
        lines=[json.loads(x) for x in (folder/trial['phase']/'monitor.jsonl').read_text(encoding='utf-8').splitlines()]
        low=next(x for x in lines if x['wall_seconds']>=trial['loading_setup_and_initial_save_seconds'])
        high=lines[-1]
        cpu=high['cpu_seconds']-low['cpu_seconds']
        elapsed=high['wall_seconds']-low['wall_seconds']
        lo,hi=low['system_cpu_times'],high['system_cpu_times']
        busy=sum(hi[k]-lo[k] for k in ('kernel_seconds_including_idle','user_seconds'))-(hi['idle_seconds']-lo['idle_seconds'])
        runs.append({'case':trial['variant'],'repeat':trial['repeat'],'compute_seconds':trial['compute_seconds'],
                     'wall_seconds':trial['wall_seconds'],'solver_cpu_seconds_sampled':cpu,
                     'scalar_calls_per_sample':end['scalar_calls']/count,
                     'non_solver_mean_logical_cpus':(busy-cpu)/elapsed})
    ref=report['medians']['baseline']['compute_seconds']
    return {'source_samples':report['source_samples'],'additional_samples':count,'runs':runs,'inputs_unchanged':True,
            'input_sha256':report['input_sha256'],
            'medians':report['medians'],'throughput_ratio_from_median_times':{
                case:ref/v['compute_seconds'] for case,v in report['medians'].items()},
            'raw_report':str((folder/'report.json').relative_to(ROOT))}


def profile(folder):
    d=read(folder/'analysis.json')
    c=read(folder/'capture.json')
    assert d['validation']['no_lost_events'] and d['validation']['cswitch_continuity_mismatches']==0
    assert d['validation']['cpu_stack_coverage']>.99 and len(d['worker_tids'])==20
    window=d['window']
    capacity=window['wall_seconds']*20
    yielded=sum(x['seconds'] for x in d['off_cpu_state_reason'] if x['state'] in (1,3,7) and x['reason']==33)
    waits=sum(v for k,v in d['off_cpu_seconds'].items() if k in ('waiting','waiting_without_ready_event'))
    offset = d['clock_calibration']['offset_ticks']
    start, end = window['qpc_begin'] + offset, window['qpc_end'] + offset
    workers = set(d['worker_tids'])
    yield_switches = sum(
        start <= tick < end and previous in workers and previous != current
        and state in (1, 3, 7) and reason == 33
        for tick, _, current, previous, state, reason in read(folder/'parsed-events.json')['switches']
    )
    lock_frames = ('Engine::update', 'hrc_node_mutex::NodeMutex::lock')
    lock_resume = sum(x['seconds'] for x in d['off_cpu_by_resume_native_frame'] if x['symbol'] in lock_frames)
    return {'window_seconds':window['wall_seconds'],'starting_checkpoint_sha256':c['source_sha256'],
            'yield_ready_percent':100*yielded/capacity,'waiting_percent':100*waits/capacity,
            'yield_switch_count':yield_switches,'yield_switches_per_second':yield_switches/window['wall_seconds'],
            'off_cpu_percent':100*sum(d['off_cpu_seconds'].values())/capacity,
            'mean_running_logical_cpus':d['worker_mean_logical_cpus'],
            'update_or_node_lock_resume_stack_off_cpu_percent':100*lock_resume/capacity,
            'validation':d['validation'],'raw_report':str((folder/'analysis.json').relative_to(ROOT))}


def compare_pairs(*benchmarks):
    pairs = []
    for benchmark_result in benchmarks:
        for first, second in zip(benchmark_result['runs'][::2], benchmark_result['runs'][1::2]):
            baseline, candidate = (first, second) if first['case'] == 'baseline' else (second, first)
            assert baseline['case'] == 'baseline' and candidate['case'] == 'adaptive'
            background_delta = candidate['non_solver_mean_logical_cpus'] - baseline['non_solver_mean_logical_cpus']
            pairs.append({
                'raw_report': benchmark_result['raw_report'],
                'order': [first['case'], second['case']],
                'non_solver_mean_logical_cpus_delta': background_delta,
                'background_comparable': abs(background_delta) <= .5,
                'compute_time_delta_percent': 100 * (candidate['compute_seconds'] / baseline['compute_seconds'] - 1),
                'solver_cpu_delta_percent': 100 * (candidate['solver_cpu_seconds_sampled'] /
                                                   baseline['solver_cpu_seconds_sampled'] - 1),
            })
    return pairs


def main():
    runs={'lock_screen':benchmark('screen',20_000_000,['baseline','adaptive','park','srw']),
          'write_screen':benchmark('write-screen',20_000_000,['baseline','short-writer','prefetch']),
          'confirmation':benchmark('confirmation',50_000_000,['baseline','adaptive','adaptive','baseline']),
          'confirmation_repeat':benchmark('confirmation-repeat',50_000_000,['adaptive','baseline','baseline','adaptive'])}
    assert all(r['input_sha256'] == runs['confirmation']['input_sha256'] for r in runs.values())
    pairs = compare_pairs(runs['confirmation'], runs['confirmation_repeat'])
    old=profile(ROOT/'.research-cache/mtt-hotspots-pgo-20261109/native-mature')
    new=profile(BASE/'trace/adaptive-mature')
    assert old['starting_checkpoint_sha256']==new['starting_checkpoint_sha256']
    manifest=read(ROOT/'.research-cache/bubble-round2-20261109/accepted/manifest.json')
    unchanged=all(hashlib.sha256((ROOT/'native'/name).read_bytes()).hexdigest()==data['sha256']
                  for name,data in manifest['identity_spec']['source_files'].items())
    variants={name:read(BASE/path/'manifest.json') for name,path in (
        ('adaptive','adaptive'),('park','park'),('srw','srw'),('short-writer','write-path/short-writer'),
        ('prefetch','write-path/prefetch'))}
    output={'schema':'mtt-ep-writer-lock-v1','workload':'Hand bubble, EP selected subtree, 20 workers',
            'benchmarks':runs,'confirmation_pairs':pairs,'profiles':{'prior_baseline':old,'adaptive':new},
            'candidate_validation':variants,
            'native_sources_match_frozen_baseline':unchanged,
            'boundaries':['Screening trials are single observations; confirmation uses ABBA and BAAB.',
                          'Pairs with a mean non-solver load difference greater than half a logical CPU are marked separately.',
                          'Compute time subtracts measured training checkpoint writes and excludes initialization.',
                          'ETW windows use the same mature checkpoint, but different runs and ambient load.',
                          'Yield switch counts include only actual worker switch-outs in the common ETW window.',
                          'Update and node lock resume stacks attribute off-CPU time, without measuring lock hold time.',
                          'Ready-after-yield is a subset of off-CPU time; less of it may reflect additional spinning.',
                          'Mutex stress and native probes are not a measured time-to-CI result.']}
    report=ROOT/'reports/hrc-mtt-writer-20261109.json'
    report.write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(report),'ratios':{name:r['throughput_ratio_from_median_times'] for name,r in runs.items()},
                      'confirmation_pairs':pairs,'profiles':{'baseline':old,'adaptive':new},
                      'native_sources_unchanged':unchanged},ensure_ascii=False))


if __name__=='__main__':
    main()
