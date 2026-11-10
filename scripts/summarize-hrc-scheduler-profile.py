"""Aggregate authorized scheduler diagnostics without launching CPU work."""
from pathlib import Path
import hashlib,json,math,statistics

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/architecture-review-20261108/scheduler-measurement-r2'

def merge(items):
    return {'count':sum(x['count'] for x in items),'sum_ns':sum(x['sum_ns'] for x in items),
            'max_ns':max(x['max_ns'] for x in items),
            'histogram':[sum(x['histogram'][i] for x in items) for i in range(64)]}

def summarize(hist, bounds):
    out={k:v for k,v in hist.items() if k!='histogram'}
    out['mean_ns']=hist['sum_ns']/hist['count'] if hist['count'] else None
    out['quantiles_ns']={}
    for q in (.5,.9,.95,.99):
        target=math.ceil(q*hist['count']);n=0
        if not target:out['quantiles_ns'][str(q)]=None;continue
        for b,c in enumerate(hist['histogram']):
            n+=c
            if n>=target:
                out['quantiles_ns'][str(q)]={'lower_exclusive':bounds[b-1] if b else None,'upper_inclusive':bounds[b]}
                break
    return out

def main():
    paths=[BASE/f'profile-on-r{i}.json' for i in range(3)]
    profiles=[json.loads(p.read_text()) for p in paths]
    benchmark=json.loads((ROOT/'reports/hrc-scheduler-profile-overhead-r2-20261108.json').read_text())
    bounds=profiles[0]['histogram_upper_bounds_ns'];workers=profiles[0]['workers']
    assert all(p['histogram_upper_bounds_ns']==bounds and p['workers']==workers for p in profiles)
    global_keys=['dispatch_to_quiescent','worker_exit_spread','controller_collect','controller_gap','deadline_tail']
    worker_keys=['launch_delay','work_wall','retired_wait','sampled_block_claim','sampled_block_work','finish_after_deadline']
    global_hist={k:merge([p[k] for p in profiles]) for k in global_keys}
    worker_hist={k:merge([w[k] for p in profiles for w in p['per_worker']]) for k in worker_keys}
    dispatch=global_hist['dispatch_to_quiescent']['sum_ns'];control=global_hist['controller_collect']['sum_ns']+global_hist['controller_gap']['sum_ns']
    worker_dispatch_ns=workers*dispatch
    per_worker=[]
    for i in range(workers):
        raw=[p['per_worker'][i] for p in profiles]
        w={'worker':i,**{k:sum(x[k] for x in raw) for k in ['completed_samples','claimed_samples','blocks','cas_retries','sampled_blocks']}}
        for k in ('launch_delay','work_wall','retired_wait'):
            w[k+'_ns']=sum(x[k]['sum_ns'] for x in raw)
        w['sample_share']=w['completed_samples']/60000000
        per_worker.append(w)
    counts=[w['completed_samples'] for w in per_worker]
    slices=sum(p['slices'] for p in profiles)
    medians=benchmark['medians']
    summary={
        'schema':'scheduler-profile-interpretation-v1','input_benchmark':'reports/hrc-scheduler-profile-overhead-r2-20261108.json',
        'profile_input_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'workers':workers,'slices':slices,'samples':sum(counts),
        'same_executable_on_over_off_median_elapsed_ratio':medians['profile_on']['seconds']/medians['profile_off']['seconds'],
        'off_over_production_median_elapsed_ratio':medians['profile_off']['seconds']/medians['production']['seconds'],
        'on_over_production_median_elapsed_ratio':medians['profile_on']['seconds']/medians['production']['seconds'],
        'measurement_scope':'20m x3, mature997655250 checkpoint, CI off, 20 threads; wall includes OS preemption',
        'global_distributions':{k:summarize(v,bounds) for k,v in global_hist.items()},
        'pooled_worker_distributions':{k:summarize(v,bounds) for k,v in worker_hist.items()},
        'worker_dispatch_opportunity_seconds':worker_dispatch_ns/1e9,
        'worker_wall_fractions_within_dispatch':{k:worker_hist[k]['sum_ns']/worker_dispatch_ns for k in ['launch_delay','work_wall','retired_wait']},
        'controller_fraction_dispatch_plus_control':control/(dispatch+control),
        'deadline_tail_over_dispatch':global_hist['deadline_tail']['sum_ns']/dispatch,
        'exit_spread_over_dispatch':global_hist['worker_exit_spread']['sum_ns']/dispatch,
        'sampled_claim_to_work_wall_ratio':worker_hist['sampled_block_claim']['sum_ns']/worker_hist['sampled_block_work']['sum_ns'],
        'cas_retries':sum(w['cas_retries'] for w in per_worker),
        'claimed_blocks':sum(w['blocks'] for w in per_worker),
        'worker_sample_counts':{'mean':statistics.mean(counts),'minimum':min(counts),'maximum':max(counts),'max_over_min':max(counts)/min(counts),'population_cv':statistics.pstdev(counts)/statistics.mean(counts)},
        'per_worker':per_worker,
        'per_trial':[],
        'limits':['Metrics are wall time, not CPU accounting or hardware stall counters.',
                  'Retired wait includes controller wake-up delay; late workers may still do useful work.',
                  'Deterministic 1/64 block sample is not IID; histogram quantiles are intervals, not point estimates.',
                  'Worker index is not a physical CPU identity; no core residency was recorded.',
                  'Three observations are insufficient to establish no observer effect; on/off ranges overlap.',
                  'Current ~9.5 average logical CPUs differs from historical formal20 ~16.27, so timing cannot be attributed solely to algorithm or hardware topology.']}
    for i,p in enumerate(profiles):
        w=p['per_worker'];d=p['dispatch_to_quiescent']['sum_ns']*workers
        samples=[x['completed_samples'] for x in w]
        summary['per_trial'].append({'repeat':i,'slices':p['slices'],'samples':sum(samples),
            'fraction_launch':sum(x['launch_delay']['sum_ns'] for x in w)/d,
            'fraction_work_wall':sum(x['work_wall']['sum_ns'] for x in w)/d,
            'fraction_retired_wait':sum(x['retired_wait']['sum_ns'] for x in w)/d,
            'completed_min':min(samples),'completed_max':max(samples),'completed_cv':statistics.pstdev(samples)/statistics.mean(samples)})
    assert sum(counts)==60000000
    assert sum(w['claimed_samples'] for w in per_worker)==60000000
    assert abs(sum(summary['worker_wall_fractions_within_dispatch'].values())-1)<1e-9
    target=ROOT/'reports/hrc-scheduler-profile-interpretation-20261108.json'
    target.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('per_worker','profile_input_sha256')},indent=2))

if __name__=='__main__':main()
