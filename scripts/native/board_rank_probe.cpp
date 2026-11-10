// Compare every legal hole pair on independently generated five-card boards.
#include "hrc_cards.hpp"
#include <iostream>
#include <chrono>
#include <array>
#include <cstdlib>

static uint64_t random_word(uint64_t& x){
    uint64_t z=(x+=0x9e3779b97f4a7c15ULL);z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL;
    z=(z^(z>>27))*0x94d049bb133111ebULL;return z^(z>>31);
}
int main(int argc,char** argv){
    int boards=argc>1?std::atoi(argv[1]):2000;uint64_t seed=43,checks=0,mismatches=0;
    std::array<uint64_t,9> categories{};
    auto start=std::chrono::steady_clock::now();
    for(int b=0;b<boards;++b){
        uint64_t board=0;
        for(int i=0;i<5;++i){uint64_t bit;do{bit=1ULL<<(random_word(seed)%52);}while(board&bit);board|=bit;}
        hrc_cards::BoardRankState state(board);
        for(int high=1;high<52;++high)for(int low=0;low<high;++low){
            uint64_t holes=(1ULL<<high)|(1ULL<<low);if(holes&board)continue;
            int reference=hrc_cards::rank7(board|holes),actual=hrc_cards::rank7_with_board(state,holes);
            ++checks;++categories[reference>>20];if(reference!=actual)++mismatches;
        }
    }
    // Calibrate the empty duration observation; sampled hot-path clocks include
    // this observer cost and must not be added as exact exclusive CPU shares.
    uint64_t empty_ns=0;
    for(int i=0;i<100000;++i){auto a=std::chrono::steady_clock::now();auto b=std::chrono::steady_clock::now();
        empty_ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count();}
    std::cout<<"{\"boards\":"<<boards<<",\"checks\":"<<checks<<",\"mismatches\":"<<mismatches
             <<",\"elapsed_seconds\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()
             <<",\"empty_clock_mean_ns\":"<<double(empty_ns)/100000<<",\"categories\":[";
    for(size_t i=0;i<categories.size();++i){if(i)std::cout<<',';std::cout<<categories[i];}
    std::cout<<"]}"<<std::endl;
    return mismatches?1:0;
}
