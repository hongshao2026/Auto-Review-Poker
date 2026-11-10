#include "../../native/hrc_divisibility.hpp"

#include <algorithm>
#include <array>
#include <iostream>
#include <set>
#include <string>
#include <vector>

using hrc_divisibility::CachedDivisor;
static std::uint64_t checked=0,tape=1469598103934665603ULL;
static void require(bool ok,const char* what){if(!ok)throw std::runtime_error(what);}
static void verify(const CachedDivisor& cache,std::int32_t value){
    bool expected=value%cache.divisor()==0;
    bool actual=cache.divides(value);
    if(expected!=actual)throw std::runtime_error("divisibility mismatch d="+std::to_string(cache.divisor())+" v="+std::to_string(value));
    ++checked;tape^=std::uint32_t(value);tape*=1099511628211ULL;tape^=std::uint32_t(cache.divisor());tape*=1099511628211ULL;tape^=actual;
}
static std::uint64_t state=20261108;
static std::uint64_t random64(){
    std::uint64_t z=(state+=0x9e3779b97f4a7c15ULL);
    z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL;z=(z^(z>>27))*0x94d049bb133111ebULL;return z^(z>>31);
}
// Map bit patterns portably to signed int32 without implementation-defined casts.
static std::int32_t signed_bits(std::uint32_t u){return u<=0x7fffffffU?std::int32_t(u):-1-std::int32_t(0xffffffffU-u);}

int main(int argc,char**argv){try{
    require(argc==2,"mode required");std::string mode=argv[1];
    constexpr auto lo=std::numeric_limits<std::int32_t>::min();
    constexpr auto hi=std::numeric_limits<std::int32_t>::max();
    if(mode=="boundaries"){
        std::set<std::int32_t> divisors={1,2,3,5,7,9,11,13,31,63,65,127,255,257,46340,65535,65537,999983,999999,1000000,hi,hi-1};
        for(int s=0;s<=30;++s){std::int32_t d=std::int32_t(1U<<s);divisors.insert(d);if(d>1)divisors.insert(d-1);if(d<hi)divisors.insert(d+1);}
        for(int d=1;d<=1000000;d+=97)divisors.insert(d);
        CachedDivisor cache;
        for(auto d:divisors){cache.set(d);std::set<std::int32_t> values={lo,lo+1,lo+2,-1,0,1,hi-2,hi-1,hi};
            for(std::int64_t q:{-2147483648LL/d,-2147483647LL/d,-3LL,-2LL,-1LL,0LL,1LL,2LL,3LL,2147483647LL/d})
                for(std::int64_t delta:{-1LL,0LL,1LL}){auto v=q*d+delta;if(v>=lo&&v<=hi)values.insert(std::int32_t(v));}
            for(auto v:values)verify(cache,v);
            require(!cache.set(d),"Same divisor rebuilt cache");
            verify(cache,lo);verify(cache,0);
        }
        std::cout<<"{\"mode\":\"boundaries\",\"divisors\":"<<divisors.size()<<",\"checks\":"<<checked;
    }else if(mode=="random"){
        CachedDivisor cache;
        for(int i=0;i<2000000;++i){
            std::int32_t d=(i%4==0)?std::int32_t((random64()&0x7fffffffULL)|1ULL):std::int32_t(1+random64()%1000000ULL);
            cache.set(d);verify(cache,signed_bits(std::uint32_t(random64())));
        }
        std::cout<<"{\"mode\":\"random\",\"seed\":20261108,\"checks\":"<<checked;
    }else if(mode=="cache"){
        CachedDivisor cache;require(cache.divisor()==1&&!cache.set(1),"Invalid initial cache");
        for(auto d:{1,3,3,4,4,1024,999983,999983,1,hi}){
            auto previous=cache.divisor();require(cache.set(d)==(d!=previous),"Wrong cache change marker");
            for(auto v:{lo,lo+1,-17,-1,0,1,17,hi})verify(cache,v);
        }
        for(auto d:{0,-1,lo}){
            auto previous=cache.divisor();bool rejected=false;
            try{cache.set(d);}catch(const std::invalid_argument&){rejected=true;}
            require(rejected&&cache.divisor()==previous,"Invalid divisor changed cache");verify(cache,lo);verify(cache,hi);
        }
        std::cout<<"{\"mode\":\"cache\",\"checks\":"<<checked;
    }else throw std::runtime_error("unknown mode");
    std::cout<<",\"tape_hash\":\""<<std::hex<<tape<<"\",\"passed\":true}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
