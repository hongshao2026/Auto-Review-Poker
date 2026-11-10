#define main research_solver_main
#include "../../native/hrc_research_solver.cpp"
#undef main
#include "../../native/hrc_fast_bound.hpp"
#include <limits>

struct LegacyRandom:Random {
    using Random::Random;
    uint32_t bound(uint32_t n){++bounded_calls;if(scripted)return std::min(uint32_t(gate),n-1);
        uint64_t v,limit=(uint64_t(0)-uint64_t(n))%n;do{v=next();}while(v<limit);return uint32_t(v%n);}
};
void require(bool ok){if(!ok)throw std::runtime_error("Exact bound/RNG comparison failed");}
void same(const Random& a,const Random& b){require(std::equal(a.s,a.s+4,b.s));
    require(a.bounded_calls==b.bounded_calls&&a.double_calls==b.double_calls&&a.int_calls==b.int_calls);}
int main(){try{
    uint64_t checks=0;Random source(73);
    for(uint32_t n=1;n<=64;++n){
        uint64_t limit=(uint64_t(0)-uint64_t(n))%n;
        require(hrc_fast_bound::table[n].rejection==limit);
        for(uint64_t v:{uint64_t(0),uint64_t(1),uint64_t(n-1),uint64_t(n),uint64_t(n+1),limit,limit+1,UINT64_MAX,UINT64_MAX-1}){
            require(hrc_fast_bound::remainder(v,n)==v%n);++checks;}
        for(int i=0;i<20000;++i){uint64_t v=source.next();require(hrc_fast_bound::remainder(v,n)==v%n);++checks;}
    }
    for(int i=0;i<200000;++i){uint64_t a=source.next(),b=source.next();
        require(hrc_fast_bound::high_product(a,b)==uint64_t((static_cast<__uint128_t>(a)*b)>>64));++checks;}
    const uint32_t bounds[]={1,2,3,4,5,6,7,8,9,16,17,31,32,51,52,53,63,64,65,97,65535,UINT32_MAX};
    for(uint64_t seed:std::array<uint64_t,4>{0,1,43,UINT64_MAX}){
        Random current(seed);LegacyRandom old(seed);
        for(int i=0;i<200000;++i){auto n=bounds[i%(sizeof(bounds)/sizeof(bounds[0]))];
            require(current.bound(n)==old.bound(n));same(current,old);++checks;
            if(i%7==0){require(current.unit()==old.unit());same(current,old);}
            if(i%11==0){require(current.integer()==old.integer());same(current,old);}
        }
    }
    // Invert xoshiro256**'s output permutation to force every small rejection
    // boundary as the first raw draw, then check full subsequent state.
    for(uint32_t n:bounds){uint64_t limit=(uint64_t(0)-uint64_t(n))%n;
        for(uint64_t first:{uint64_t(0),uint64_t(1),limit,limit+1,limit?limit-1:0,UINT64_MAX}){
            uint64_t inverse9=0x8e38e38e38e38e39ULL,inverse5=0xcccccccccccccccdULL;
            uint64_t t=first*inverse9,s1=Random::rot(t,57)*inverse5;
            Random current(5);LegacyRandom old(5);current.s[1]=old.s[1]=s1;
            Random copy=current;require(copy.next()==first);
            require(current.bound(n)==old.bound(n));same(current,old);++checks;
        }
    }
    for(uint32_t n:{0u,1u,2u,3u,4u,52u,64u,65u,UINT32_MAX})for(int gate:{-1,0,1,2,99}){
        Random current(7);LegacyRandom old(7);current.scripted=old.scripted=true;current.gate=old.gate=gate;
        require(current.bound(n)==old.bound(n));same(current,old);++checks;
    }
    std::cout<<"{\"exact_checks\":"<<checks<<",\"passed\":true}"<<std::endl;return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<std::endl;return 1;}}
