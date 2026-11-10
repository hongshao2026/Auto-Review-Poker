"""Isolated bucket-striped store with worker-sharded update counters."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/throughput-round3-20261108/atomic-candidate'

BUCKET=r'''
namespace hrc_bucket_candidate {
template<class N,class R,class Total> void update(N& n,R& rng,hrc_atomic_candidate::Cache& cache,
        int hand,const double* p,const double* q,double marker,Total&& total){
    double value=0;for(int a=0;a<n.k;++a)if(p[a]>0)value+=p[a]*q[a];
    uint64_t count=__atomic_load_n(&cache.local_updates,__ATOMIC_RELAXED);
    __atomic_store_n(&cache.local_updates,count+1,__ATOMIC_RELAXED);
    ++n.visits[hand];
    double t=hrc_atomic_candidate::load(n.raw.data())+1;
    const int f=n.base_format();
    if(f==23){if(rng.integer()%cache.divisor(t)==0){double expected=hrc_atomic_candidate::load(n.raw.data());
        t=double(total());hrc_atomic_candidate::refresh(n.raw.data(),expected,t);}}
    else t=hrc_atomic_candidate::add(n.raw.data(),1)+1;
    size_t r=n.regret(hand);
    if(f==23){size_t av=n.average(hand);
        for(int a=0;a<n.k;++a){n.raw[r+a]+=t*(q[a]-value);n.raw[av+a]+=t*p[a];}
        n.raw[r+n.k]+=t;
    }else{for(int a=0;a<n.k;++a)n.raw[r+a]+=t*(q[a]-value);
        if(marker>0)for(int a=0;a<n.k;++a)hrc_atomic_candidate::add(n.raw.data()+1+a,t*marker*p[a]);}
}
} // namespace hrc_bucket_candidate
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stripes',type=int,default=16)
    args=parser.parse_args();stripes=args.stripes
    if stripes<1 or stripes>256 or stripes&(stripes-1):raise ValueError('Power-of-two stripes in 1..256 required')
    out=BASE.parent/f'bucket{stripes}-candidate';out.mkdir(parents=True,exist_ok=False)
    for path in BASE.glob('hrc_*.hpp'):shutil.copy2(path,out/path.name)
    header=(out/'hrc_atomic_candidate.hpp').read_text(encoding='utf-8')
    header=header.replace('__ATOMIC_RELAXED,__ATOMIC_RELAXED','__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST')
    header=header.replace('struct Cache {','struct alignas(64) Cache {\n    uint64_t local_updates=0;')
    (out/'hrc_atomic_candidate.hpp').write_text(header+BUCKET,encoding='utf-8')
    cpp=(BASE/'hrc_research_solver.cpp').read_text(encoding='utf-8')
    cpp=cpp.replace('    bool atomic_shared=false;',
        '    hrc_node_mutex::NodeMutex* bucket_mutexes=nullptr;\n'
        '    const size_t* bucket_offsets=nullptr;\n'
        '    const uint64_t* atomic_initial_updates=nullptr;\n'
        '    std::array<hrc_atomic_candidate::Cache*,32> atomic_peers{};\n'
        '    size_t atomic_workers=0;\n'
        '    uint64_t atomic_update_count(size_t id)const{uint64_t sum=atomic_initial_updates[id];\n'
        '        for(size_t i=0;i<atomic_workers;++i)sum+=__atomic_load_n(&atomic_peers[i][id].local_updates,__ATOMIC_RELAXED);return sum;}\n'
        '    bool atomic_shared=false;',1)
    old='if(atomic_shared&&hrc_atomic_candidate::eligible(n)){hrc_atomic_candidate::strategy(n,h,p);return sample(n,p,atomic_cache[id].epsilon(hrc_atomic_candidate::load(n.raw.data())));}'
    new=('if(atomic_shared&&bucket_offsets[id]!=SIZE_MAX){\n'
         f'            std::lock_guard<hrc_node_mutex::NodeMutex> guard(bucket_mutexes[bucket_offsets[id]+(size_t(h)&{stripes-1})]);\n'
         '            n.strategy(h,p);return sample(n,p,atomic_cache[id].epsilon(hrc_atomic_candidate::load(n.raw.data())));}')
    assert old in cpp;cpp=cpp.replace(old,new,1)
    old='if(atomic_shared&&hrc_atomic_candidate::eligible(n)){hrc_atomic_candidate::update(n,rng,atomic_cache[id],h,p,q,marker);return;}'
    new=('if(atomic_shared&&bucket_offsets[id]!=SIZE_MAX){\n'
         f'            std::lock_guard<hrc_node_mutex::NodeMutex> guard(bucket_mutexes[bucket_offsets[id]+(size_t(h)&{stripes-1})]);\n'
         '            hrc_bucket_candidate::update(n,rng,atomic_cache[id],h,p,q,marker,[&]{return atomic_update_count(size_t(id));});return;}')
    assert old in cpp;cpp=cpp.replace(old,new,1)
    (out/'hrc_research_solver.cpp').write_text(cpp,encoding='utf-8')
    parallel=(BASE/'hrc_parallel.hpp').read_text(encoding='utf-8')
    parallel=parallel.replace('    std::vector<std::thread> threads_;',
        '    std::unique_ptr<hrc_node_mutex::NodeMutex[]> bucket_locks_;\n'
        '    std::vector<size_t> bucket_offsets_;\n'
        '    std::vector<uint64_t> initial_updates_;\n'
        '    std::vector<std::thread> threads_;',1)
    marker='        node_locks_=std::make_unique<hrc_node_mutex::NodeMutex[]>(main.tree.nodes.size());'
    parallel=parallel.replace(marker,marker+'\n'
        '        main.tree.reserve_budget(main.tree.nodes.size()*(sizeof(size_t)+sizeof(uint64_t)));\n'
        '        bucket_offsets_.assign(main.tree.nodes.size(),SIZE_MAX);initial_updates_.resize(main.tree.nodes.size());\n'
        '        size_t bucket_count=0;for(size_t id=0;id<main.tree.nodes.size();++id){auto& n=main.tree.nodes[id];\n'
        f'            initial_updates_[id]=n.updates;if(hrc_atomic_candidate::eligible(n)){{bucket_offsets_[id]=bucket_count;bucket_count+={stripes};}}}}\n'
        '        main.tree.reserve_budget(bucket_count*sizeof(hrc_node_mutex::NodeMutex));\n'
        '        bucket_locks_=std::make_unique<hrc_node_mutex::NodeMutex[]>(bucket_count);',1)
    old='main.atomic_shared=true;main.training_threads=count;main.node_mutexes=node_locks_.get();main.parallel_rng.resize(count);capture();'
    new=('main.parallel_rng.resize(count);\n'
         '        for(auto* engine:engines_){engine->bucket_mutexes=bucket_locks_.get();engine->bucket_offsets=bucket_offsets_.data();\n'
         '            engine->atomic_initial_updates=initial_updates_.data();engine->atomic_workers=size_t(count);\n'
         '            for(int i=0;i<count;++i)engine->atomic_peers[i]=engines_[i]->atomic_cache.data();}\n'
         '        capture();main.training_threads=count;main.node_mutexes=node_locks_.get();main.atomic_shared=true;')
    assert old in parallel;parallel=parallel.replace(old,new,1)
    parallel=parallel.replace('        capture();\n    }\npublic:',
        '        for(size_t id=0;id<main_.tree.nodes.size();++id)if(bucket_offsets_[id]!=SIZE_MAX)\n'
        '            main_.tree.nodes[id].updates=main_.atomic_update_count(id);\n'
        '        capture();\n    }\npublic:',1)
    parallel=parallel.replace('main_.atomic_cache.clear();',
        'main_.atomic_cache.clear();main_.bucket_mutexes=nullptr;main_.bucket_offsets=nullptr;\n'
        '        main_.atomic_initial_updates=nullptr;main_.atomic_workers=0;main_.atomic_peers.fill(nullptr);',1)
    (out/'hrc_parallel.hpp').write_text(parallel,encoding='utf-8')
    exe=out/f'hrc_research_solver-bucket{stripes}.exe'
    compiler=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    subprocess.run([str(compiler),'c++','-O3','-std=c++17','-ffp-contract=off',str(out/'hrc_research_solver.cpp'),'-o',str(exe)],
                   check=True,capture_output=True,text=True)
    print(exe,flush=True)


if __name__=='__main__':main()
