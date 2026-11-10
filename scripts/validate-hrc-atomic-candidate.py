"""Exercise isolated per-cell atomics before throughput measurements."""
import argparse
from pathlib import Path
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.research-cache/throughput-round3-20261108/atomic-candidate'
COMPILER=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')

PROBE=r'''#define main candidate_solver_main
#include "hrc_research_solver.cpp"
#undef main
static void check(bool condition){if(!condition)throw std::runtime_error("Atomic/serial semantic mismatch");}
int main(){try{
    uint64_t cases=0;
    for(int f:{23,25})for(int k:{2,3,4,16})for(int special:{0,1,2})for(int scripted:{-1,0,1})for(uint64_t initial:{uint64_t(0),uint64_t(60000000)}){
        Node a,b;for(Node* n:{&a,&b}){n->actor=0;n->k=k;n->buckets=7;n->special=special;n->store_format=f;n->init();n->raw[0]=double(initial);n->updates=initial;
            for(int h=0;h<7;++h)for(int i=0;i<k;++i)n->raw[n->regret(h)+i]=(h-2)*(i-3)*.25;}
        Random ra(43),rb(43),values(59);hrc_atomic_candidate::Cache cache;
        if(scripted>=0){ra.scripted=rb.scripted=true;ra.scripted_integer=rb.scripted_integer=scripted;}
        for(int i=0;i<100;++i){int h=int(values.bound(7));double p[MAXA],copy[MAXA],q[MAXA];
            a.strategy(h,p);hrc_atomic_candidate::strategy(b,h,copy);check(!std::memcmp(p,copy,k*sizeof(double)));
            check(a.exploration_probability()==cache.epsilon(hrc_atomic_candidate::load(b.raw.data())));
            for(int j=0;j<k;++j)q[j]=100*values.unit()-50;
            double marker=(i%3==0?0:i%3==1?1:100);
            a.update(ra,h,p,q,1,marker);hrc_atomic_candidate::update(b,rb,cache,h,p,q,marker);
            check(a.raw==b.raw&&a.visits==b.visits&&a.updates==b.updates);
            check(!std::memcmp(ra.s,rb.s,sizeof(ra.s))&&ra.int_calls==rb.int_calls);++cases;
        }
    }
    double cell=5;hrc_atomic_candidate::refresh(&cell,4,7);check(cell==5);
    hrc_atomic_candidate::refresh(&cell,5,7);check(cell==7);
    std::cout<<"{\"ok\":true,\"update_snapshots\":"<<cases<<",\"cas_failure_keeps_cell\":true}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,default=OUT)
    args=parser.parse_args();out=args.candidate.resolve()
    probe=PROBE
    if 'namespace hrc_bucket_candidate' in (out/'hrc_atomic_candidate.hpp').read_text(encoding='utf-8'):
        probe=probe.replace('hrc_atomic_candidate::update(b,rb,cache,h,p,q,marker);',
            'hrc_bucket_candidate::update(b,rb,cache,h,p,q,marker,[&]{return initial+__atomic_load_n(&cache.local_updates,__ATOMIC_RELAXED);});'
            'b.updates=initial+__atomic_load_n(&cache.local_updates,__ATOMIC_RELAXED);')
    (out/'atomic_semantics.cpp').write_text(probe,encoding='utf-8')
    adaptive=(ROOT/'scripts/native/adaptive_parallel_probe.cpp').read_text(encoding='utf-8')
    adaptive=adaptive.replace('../../native/hrc_research_solver.cpp','hrc_research_solver.cpp')
    (out/'adaptive_probe.cpp').write_text(adaptive,encoding='utf-8')
    result={'status':'running','production_modified':False,'executables':{},'semantic':None,'adaptive':[]}
    for name in ('atomic_semantics','adaptive_probe'):
        exe=out/(name+'.exe')
        subprocess.run([str(COMPILER),'c++','-O3','-std=c++17','-ffp-contract=off',str(out/(name+'.cpp')),'-o',str(exe)],
                       check=True,capture_output=True,text=True)
        result['executables'][name]={'path':str(exe),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}
    row=subprocess.run([str(out/'atomic_semantics.exe')],check=True,capture_output=True,text=True,timeout=20)
    result['semantic']=json.loads(row.stdout)
    for mode in ('budgets','deadline','pause','resume','exception','exception_legacy','counter_lookup','counter_settle'):
        for threads in (2,8):
            folder=out/f'probe-{mode}-{threads}'
            row=subprocess.run([str(out/'adaptive_probe.exe'),mode,str(threads),str(folder)],
                               check=True,capture_output=True,text=True,timeout=20)
            result['adaptive'].append(json.loads(row.stdout))
    result['status']='passed'
    (out/'validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'semantic':result['semantic'],'adaptive_cases':len(result['adaptive'])}),flush=True)


if __name__=='__main__':main()
