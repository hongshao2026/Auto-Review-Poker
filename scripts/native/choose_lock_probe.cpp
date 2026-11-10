// Isolated candidate only: production source is not included or modified.
#define main hrc_solver_main
#include "../../.research-cache/throughput-round2-20261108/choose-lock-candidate/hrc_research_solver.cpp"
#undef main

static void check(bool v,const char* msg){if(!v)throw std::runtime_error(msg);}
static uint64_t tape=1469598103934665603ULL,checks=0;
static void record(uint64_t v){tape^=v;tape*=1099511628211ULL;}
static void compare(const Engine& a,const Engine& b,int x,int y){
    check(x==y,"action differs");
    check(std::equal(a.rng.s,a.rng.s+4,b.rng.s),"RNG state differs");
    check(a.rng.bounded_calls==b.rng.bounded_calls&&a.rng.double_calls==b.rng.double_calls&&a.rng.int_calls==b.rng.int_calls,"RNG call tape differs");
    record(x);for(auto s:a.rng.s)record(s);record(a.rng.bounded_calls);record(a.rng.double_calls);record(a.rng.int_calls);++checks;
}
static void setup(Node& n,int k){n.actor=0;n.k=k;n.buckets=1;n.init();}
int main(int argc,char** argv){try{
    if(argc!=2)throw std::runtime_error("mode required");std::string mode=argv[1];
    if(mode=="tapes"){
        const std::vector<std::vector<double>> policies={{0,1},{1,0},{.1,.2,.3,.4},{.2,.5,.3},{0,0,0},{.01,.01,.01},{0,0,1,0},{.5,.5}};
        for(uint64_t seed: {0ULL,1ULL,42ULL,43ULL,UINT64_MAX})for(auto& p:policies)for(double eps:{0.,.01,.5,1.}){
            Engine old(seed),candidate(seed);Node n;setup(n,int(p.size()));n.exploration_key=n.counter();n.exploration_cached=eps;
            for(int j=0;j<2000;++j)compare(old,candidate,old.sample(n,p.data()),candidate.sample_policy(n.k,p.data(),eps));
        }
        // Scripted endpoint/call-count branches, including fallback after all mass is exhausted.
        for(auto& p:policies)for(double eps:{0.,.75,1.})for(int gate:{0,1,100,-1}){
            Engine old(1),candidate(1);old.rng.scripted=candidate.rng.scripted=true;old.rng.gate=candidate.rng.gate=gate;
            Node n;setup(n,int(p.size()));n.exploration_key=n.counter();n.exploration_cached=eps;
            int x=old.sample(n,p.data()),y=candidate.sample_policy(n.k,p.data(),eps);compare(old,candidate,x,y);
            check(old.rng.double_calls==(eps>0.75?1:std::any_of(p.begin(),p.end(),[](double x){return x>=1;})?1:2),"Unexpected unit consumption");
            check(old.rng.bounded_calls==(eps>0.75?1:0),"Unexpected bounded consumption");
        }
    }else if(mode=="choose"){
        for(int format:{23,25,27,31})for(int special:{0,1,2})for(int k:{2,3,4})for(bool parallel:{false,true}){
            Engine old(43),candidate(43);Node a,b;a.store_format=b.store_format=format;a.special=b.special=special;setup(a,k);setup(b,k);
            std::mutex lock;if(parallel)candidate.node_mutexes=&lock;
            for(int j=0;j<1000;++j){
                a.raw[0]=b.raw[0]=double(j/17);for(int i=0;i<k;++i)a.raw[a.regret(0)+i]=b.raw[b.regret(0)+i]=double((j+i)%7)-3.;
                double p[16]{},q[16]{};a.strategy(0,p);int x=old.sample(a,p),y=candidate.choose(0,b,0,q);
                compare(old,candidate,x,y);check(std::equal(p,p+k,q),"strategy differs");
                check(a.raw==b.raw&&a.exploration_key==b.exploration_key&&a.exploration_cached==b.exploration_cached,"node/cache differs");
            }
        }
    }else throw std::runtime_error("unknown mode");
    std::cout<<"{\"mode\":\""<<mode<<"\",\"snapshots\":"<<checks<<",\"rng_tape_hash\":\""<<std::hex<<tape<<"\",\"passed\":true}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
