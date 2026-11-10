"""Isolated default-store atomics experiment; production files stay unchanged."""
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.research-cache/throughput-round3-20261108/baseline'
OUT=BASE.parent/'atomic-candidate'

HEADER=r'''#pragma once
#include <atomic>
#include <cmath>
#include <cstdint>
#if !defined(__clang__) && !defined(__GNUC__)
#error This isolated atomic candidate requires compiler generic atomic builtins
#endif
namespace hrc_atomic_candidate {
static_assert(__atomic_always_lock_free(sizeof(double), nullptr), "Lock-free double cells required");
inline double load(const double* cell) noexcept {
    double result; __atomic_load(cell,&result,__ATOMIC_RELAXED); return result;
}
inline double add(double* cell,double delta) noexcept {
    double expected=load(cell);
    for(;;){double desired=expected+delta;
        if(__atomic_compare_exchange(cell,&expected,&desired,true,__ATOMIC_RELAXED,__ATOMIC_RELAXED))return expected;}
}
inline void refresh(double* cell,double expected,double desired) noexcept {
    (void)__atomic_compare_exchange(cell,&expected,&desired,true,__ATOMIC_RELAXED,__ATOMIC_RELAXED);
}
inline uint64_t increment(uint64_t* cell) noexcept {return __atomic_fetch_add(cell,uint64_t(1),__ATOMIC_RELAXED)+1;}
inline uint64_t count(const uint64_t* cell) noexcept {return __atomic_load_n(cell,__ATOMIC_RELAXED);}
struct Cache {
    double epsilon_key=-1,epsilon_value=0,divisor_key=-1;
    int divisor_value=1;
    double epsilon(double count){if(count!=epsilon_key){epsilon_key=count;epsilon_value=1/std::sqrt(count+10000);}return epsilon_value;}
    int divisor(double count){if(count!=divisor_key){divisor_key=count;divisor_value=int(std::floor(std::sqrt(count)));}return divisor_value;}
};
template<class N> bool eligible(const N& node){
    return node.k && !node.frequency && (!node.locks||!node.locks->active()) &&
        (node.base_format()==23||node.base_format()==25);
}
template<class N> void strategy(const N& node,int hand,double* probabilities){
    double regrets[MAXA];size_t offset=node.regret(hand);
    for(int a=0;a<node.k;++a)regrets[a]=load(node.raw.data()+offset+a);
    normalize(regrets,node.k,node.special>0,probabilities);
}
template<class N,class R> void update(N& node,R& rng,Cache& cache,int hand,const double* p,const double* q,double marker){
    double value=0;for(int a=0;a<node.k;++a)if(p[a]>0)value+=p[a]*q[a];
    increment(&node.updates);increment(&node.visits[hand]);
    double previous=load(node.raw.data()),t=previous+1;
    int f=node.base_format();
    if(f==23){
        if(rng.integer()%cache.divisor(t)==0){double expected=load(node.raw.data());t=double(count(&node.updates));refresh(node.raw.data(),expected,t);}
    }else t=add(node.raw.data(),1)+1;
    size_t r=node.regret(hand);
    if(f==23){size_t av=node.average(hand);
        for(int a=0;a<node.k;++a){add(node.raw.data()+r+a,t*(q[a]-value));add(node.raw.data()+av+a,t*p[a]);}
        add(node.raw.data()+r+node.k,t);
    }else{for(int a=0;a<node.k;++a)add(node.raw.data()+r+a,t*(q[a]-value));
        if(marker>0)for(int a=0;a<node.k;++a)add(node.raw.data()+1+a,t*marker*p[a]);}
}
} // namespace hrc_atomic_candidate
'''


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    for path in BASE.glob('hrc_*.hpp'):shutil.copy2(path,OUT/path.name)
    cpp=(BASE/'hrc_research_solver.cpp').read_text(encoding='utf-8')
    marker='struct Node {'
    cpp=cpp.replace(marker,'#include "hrc_atomic_candidate.hpp"\n\n'+marker,1)
    cpp=cpp.replace('    hrc_node_mutex::NodeMutex* node_mutexes=nullptr;',
                    '    bool atomic_shared=false;\n    std::vector<hrc_atomic_candidate::Cache> atomic_cache;\n    hrc_node_mutex::NodeMutex* node_mutexes=nullptr;',1)
    cpp=cpp.replace('    int choose(int id,Node& n,int h,double* p){',
                    '    int choose(int id,Node& n,int h,double* p){\n        if(atomic_shared&&hrc_atomic_candidate::eligible(n)){hrc_atomic_candidate::strategy(n,h,p);return sample(n,p,atomic_cache[id].epsilon(hrc_atomic_candidate::load(n.raw.data())));}',1)
    cpp=cpp.replace('    void update(int id,Node& n,int h,const double* p,const double* q,double marker){',
                    '    void update(int id,Node& n,int h,const double* p,const double* q,double marker){\n        if(atomic_shared&&hrc_atomic_candidate::eligible(n)){hrc_atomic_candidate::update(n,rng,atomic_cache[id],h,p,q,marker);return;}',1)
    cpp=cpp.replace('    int sample(const Node& n,const double* p){\n        if(rng.unit()<n.exploration_probability())',
                    '    int sample(const Node& n,const double* p,double epsilon=-1){\n        if(rng.unit()<(epsilon>=0?epsilon:n.exploration_probability()))',1)
    (OUT/'hrc_research_solver.cpp').write_text(cpp,encoding='utf-8')
    (OUT/'hrc_atomic_candidate.hpp').write_text(HEADER,encoding='utf-8')
    parallel=(OUT/'hrc_parallel.hpp').read_text(encoding='utf-8')
    parallel=parallel.replace('main_.node_mutexes=nullptr;', 'main_.node_mutexes=nullptr;main_.atomic_shared=false;main_.atomic_cache.clear();',1)
    parallel=parallel.replace('node_locks_=std::make_unique<hrc_node_mutex::NodeMutex[]>(main.tree.nodes.size());',
                              'node_locks_=std::make_unique<hrc_node_mutex::NodeMutex[]>(main.tree.nodes.size());\n        main.tree.reserve_budget(uint64_t(count)*main.tree.nodes.size()*sizeof(hrc_atomic_candidate::Cache));\n        main.atomic_cache.resize(main.tree.nodes.size());',1)
    parallel=parallel.replace('engine->shared_nodes=&main.tree.nodes;engine->node_mutexes=node_locks_.get();',
                              'engine->shared_nodes=&main.tree.nodes;engine->node_mutexes=node_locks_.get();\n            engine->atomic_cache.resize(main.tree.nodes.size());engine->atomic_shared=true;',1)
    parallel=parallel.replace('main.training_threads=count;', 'main.atomic_shared=true;main.training_threads=count;',1)
    (OUT/'hrc_parallel.hpp').write_text(parallel,encoding='utf-8')
    exe=OUT/'hrc_research_solver-atomic.exe'
    compiler=Path('D:/Tools/REA-Research/zig-native/zig-x86_64-windows-0.15.2/zig.exe')
    command=[str(compiler),'c++','-O3','-std=c++17','-ffp-contract=off',str(OUT/'hrc_research_solver.cpp'),'-o',str(exe)]
    subprocess.run(command,check=True,capture_output=True,text=True)
    print(exe,flush=True)


if __name__=='__main__':main()
