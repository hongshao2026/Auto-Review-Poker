// Exercise the actual production table builder against the independent legacy
// Engine::terminal fallback for every rank assignment of each live seat.
#define main native_solver_main
#include "../../native/hrc_research_solver.cpp"
#undef main
#include <cstring>
int main(int argc,char** argv){
    try{
        if(argc!=4)throw std::invalid_argument("tree resources budget required");
        Engine engine(43);engine.tree.load(argv[1],argv[2]);
        if(!engine.tree.equity||engine.tree.fgs||engine.tree.raked)throw std::invalid_argument("Monetary static tree required");
        auto rng=std::array<uint64_t,4>{engine.rng.s[0],engine.rng.s[1],engine.rng.s[2],engine.rng.s[3]};
        auto table=engine.make_terminal_table(std::stoull(argv[3]));
        if(!table){std::cout<<"{\"refused\":true}\n";return 0;}
        uint64_t queries=0,mismatches=0;
        engine.rank_ready=true;
        for(size_t id=0;id<engine.tree.terms.size();++id){
            std::vector<int> live;for(int p=0;p<engine.tree.players;++p)if(!(engine.tree.terms[id].folded&(1u<<p)))live.push_back(p);
            if(live.empty()||live.size()>4)throw std::invalid_argument("Probe bounded to four live seats");
            uint64_t count=1;for(size_t p=0;p<live.size();++p)count*=live.size();
            for(uint64_t code=0;code<count;++code){
                uint64_t word=code;std::fill(engine.rank,engine.rank+MAXP,99);
                for(int p:live){engine.rank[p]=int(word%live.size());word/=live.size();}
                ++engine.epoch;const double* old=engine.terminal(int(id));const double* fast=table->lookup(id,engine.rank);
                ++queries;if(std::memcmp(old,fast,engine.tree.players*sizeof(double))!=0)++mismatches;
            }
        }
        bool unchanged=std::equal(rng.begin(),rng.end(),engine.rng.s)&&engine.samples==0;
        std::cout<<"{\"refused\":false,\"terminals\":"<<table->entries()<<",\"outcomes\":"<<table->outcomes()
                 <<",\"bytes\":"<<table->bytes()<<",\"queries\":"<<queries<<",\"mismatches\":"<<mismatches
                 <<",\"rng_samples_unchanged\":"<<(unchanged?"true":"false")<<"}\n";
        return mismatches||!unchanged?1:0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 2;}
}
