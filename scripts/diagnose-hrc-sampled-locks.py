"""Isolated, sampled mutex observation. Never patches the production kernel."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'.research-cache/three40bb-ci10-independent-20261107'
OUT = ROOT/'.research-cache/three40bb-lock-sampling-20261107'

INSTRUMENT = r'''
#include <atomic>
struct LockObservation {
    std::atomic<uint64_t> samples{0},busy{0},wait_ns{0},busy_wait_ns{0};
};
static LockObservation lock_observations[2][4096];
struct SampledNodeLock {
    std::mutex& mutex;
    SampledNodeLock(std::mutex& m,int node,int operation):mutex(m) {
        static thread_local uint64_t calls[2]={0,0};
        if((++calls[operation]&4095)!=0 || node>=4096){mutex.lock();return;}
        auto start=std::chrono::steady_clock::now();
        bool busy=!mutex.try_lock();if(busy)mutex.lock();
        auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
        auto& stat=lock_observations[operation][node];
        stat.samples.fetch_add(1,std::memory_order_relaxed);
        stat.wait_ns.fetch_add(ns,std::memory_order_relaxed);
        if(busy){stat.busy.fetch_add(1,std::memory_order_relaxed);stat.busy_wait_ns.fetch_add(ns,std::memory_order_relaxed);}
    }
    ~SampledNodeLock(){mutex.unlock();}
};
struct WriteLockObservations {
    ~WriteLockObservations(){
        for(int op=0;op<2;++op)for(int node=0;node<4096;++node){auto& s=lock_observations[op][node];if(s.samples.load())
            std::cerr<<"{\"kind\":\"sampled_lock\",\"operation\":"<<op<<",\"node\":"<<node<<",\"samples\":"<<s.samples.load()<<",\"busy\":"<<s.busy.load()<<",\"wait_ns\":"<<s.wait_ns.load()<<",\"busy_wait_ns\":"<<s.busy_wait_ns.load()<<"}\n";}
    }
};
static WriteLockObservations write_lock_observations;
'''


def main():
    OUT.mkdir(exist_ok=False)
    spec=importlib.util.spec_from_file_location('monitor',ROOT/'scripts/benchmark-hrc-ci-target.py')
    monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
    plan=json.loads((RUN/'plan.json').read_text(encoding='utf-8'))
    source=ROOT/'native/hrc_research_solver.cpp'; original=source.read_text(encoding='utf-8')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    modified=original.replace('constexpr int MAXP=10, MAXA=16;',INSTRUMENT+'\nconstexpr int MAXP=10, MAXA=16;')
    choose='std::lock_guard<std::mutex> guard(node_mutexes[id]);n.strategy'
    update='std::lock_guard<std::mutex> guard(node_mutexes[id]);n.update'
    assert modified.count(choose)==modified.count(update)==1
    modified=modified.replace(choose,'SampledNodeLock guard(node_mutexes[id],id,0);n.strategy')
    modified=modified.replace(update,'SampledNodeLock guard(node_mutexes[id],id,1);n.update')
    cpp=OUT/'sampled-locks.cpp';cpp.write_text(modified,encoding='utf-8')
    executable=OUT/'sampled-locks.exe'
    cmd=[plan['build']['compiler'],'c++','-O3','-std=c++17','-ffp-contract=off','-I',str(ROOT/'native'),str(cpp),'-o',str(executable)]
    compiled=subprocess.run(cmd,capture_output=True,text=True)
    monitor.dump(OUT/'compile.json',{'command':cmd,'returncode':compiled.returncode,'stdout':compiled.stdout,'stderr':compiled.stderr})
    if compiled.returncode:raise RuntimeError(compiled.stderr)
    result={'schema':'sampled-node-lock-diagnostic-v1','production_source_sha256':digest,
        'source_checkpoint':str(RUN/'initialization/checkpoint.bin'),'source_checkpoint_sha256':monitor.sha(RUN/'initialization/checkpoint.bin'),
        'sampling':'every 4096th choose and every 4096th update on each worker; deterministic, not IID',
        'observer_effect':'try_lock and clocks change lock acquisition; all acquisitions get a TLS counter branch. Do not extrapolate sampled time to an actual wait fraction.',
        'formal_checkpoint_sha256_before':monitor.sha(RUN/'formal/checkpoint.bin'),'phases':{}}
    start=time.perf_counter()
    for name,exe in [('baseline',plan['build']['executable_path']),('instrumented',str(executable))]:
        p=copy.deepcopy(plan);p.update(output=str(OUT),formal_track_ci=False,formal_target_ci=-1,
            formal_total_sample_cap=15_000_000,training_threads=8,hard_seconds_per_phase=60)
        p.pop('maximum_additional_samples',None);p['build']['executable_path']=exe
        result['phases'][name]=monitor.run_phase(p,name,resume=RUN/'initialization/checkpoint.bin')
    observations=[json.loads(line) for line in (OUT/'instrumented/stderr.log').read_text().splitlines() if line.startswith('{')]
    result['observations']=observations;result['elapsed_seconds']=time.perf_counter()-start
    result['operations']=[]
    for op in [0,1]:
        rows=[r for r in observations if r['operation']==op]
        totals={k:sum(r[k] for r in rows) for k in ('samples','busy','wait_ns','busy_wait_ns')}
        totals.update(operation='choose' if op==0 else 'update',busy_fraction=totals['busy']/totals['samples'],
            mean_observed_wait_ns=totals['wait_ns']/totals['samples'],
            mean_busy_wait_ns=totals['busy_wait_ns']/totals['busy'] if totals['busy'] else None,
            top_nodes_by_observed_busy_wait_ns=sorted(rows,key=lambda x:x['busy_wait_ns'],reverse=True)[:12])
        result['operations'].append(totals)
    result['native_elapsed_ratio_instrumented_over_baseline']=result['phases']['instrumented']['summary']['elapsed_seconds']/result['phases']['baseline']['summary']['elapsed_seconds']
    result['production_source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==digest
    result['formal_checkpoint_unchanged']=result['formal_checkpoint_sha256_before']==monitor.sha(RUN/'formal/checkpoint.bin')
    monitor.dump(OUT/'report.json',result)
    monitor.dump(ROOT/'reports/hrc-three40bb-sampled-locks-20261107.json',result)
    print(json.dumps({'report':str(OUT/'report.json'),'seconds':result['elapsed_seconds'],'operations':result['operations']}))


if __name__=='__main__':main()
