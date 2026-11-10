// Independent outcome-table tests; optional comparison to a frozen native
// production Engine is selected at compile time, never to original HRC values.
#ifdef HRC_TABLE_FROZEN_ENGINE
#define main frozen_training_main
#include HRC_TABLE_FROZEN_ENGINE
#undef main
#endif
#include "../../native/hrc_terminal_table.hpp"
#include <iomanip>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>
#include <atomic>

struct ProbePot {double amount;uint32_t eligible;};
struct ProbeTerminal {
    std::array<double,10> base{},paid{};
    std::vector<ProbePot> pots;
    uint16_t folded=0;bool synthetic=false;
};

int main(int argc,char** argv) {
    std::cout<<std::setprecision(17);
#ifdef HRC_TABLE_FROZEN_ENGINE
    if(argc==3 && std::string(argv[1])=="--tree") {
        try {
            Engine engine(42);engine.tree.load(argv[2]);
            auto& tree=engine.tree;
            if(tree.players>4 || tree.raked || tree.equity || tree.fgs)
                throw std::invalid_argument("Tree probe is bounded to at most four ChipEV seats");
            // The frozen loader stored folded only for raked states. Restore
            // the very same serialized masks supplied by the Python fixture;
            // production integration fixes that assignment for every terminal.
            std::size_t count=0;std::cin>>count;
            if(count!=tree.terms.size())throw std::invalid_argument("Fold mask count mismatch");
            for(auto& t:tree.terms){unsigned mask;std::cin>>mask;t.folded=uint16_t(mask);}
            if(!std::cin)throw std::invalid_argument("Truncated fold masks");
            auto table=hrc_terminal_table::Tables::build(tree.terms,tree.players,tree.chip_scale,64u<<20);
            if(!table)throw std::runtime_error("Tree terminal table budget declined");
            uint32_t permutations=1;for(int p=0;p<tree.players;++p)permutations*=3;
            uint64_t queries=0,mismatches=0,constant=0;
            engine.rank_ready=true;
            for(std::size_t id=0;id<tree.terms.size();++id) {
                constant+=!table->rank_mask(id);
                for(uint32_t index=0;index<permutations;++index) {
                    uint32_t code=index;
                    for(int p=0;p<tree.players;++p){engine.rank[p]=int(code%3);code/=3;}
                    ++engine.epoch;
                    const auto* previous=engine.terminal(int(id));
                    const auto* current=table->lookup(id,table->rank_mask(id)?engine.rank:nullptr);
                    mismatches+=std::memcmp(previous,current,sizeof(double)*tree.players)!=0;++queries;
                }
            }
            std::cout<<"{\"status\":\"ok\",\"terminals\":"<<table->entries()
                     <<",\"outcomes\":"<<table->outcomes()<<",\"bytes\":"<<table->bytes()
                     <<",\"queries\":"<<queries<<",\"bitwise_mismatches\":"<<mismatches
                     <<",\"card_independent_terminals\":"<<constant
                     <<",\"original_ev_read\":false,\"folded_masks_restored_for_frozen_loader\":true}\n";
            return mismatches?1:0;
        }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
    }
#endif
    int cases;std::cin>>cases;
    for(int id=0;id<cases;++id) {
        int n,folded,queries,cancel_after,mutation;double dead,scale;
        uint64_t budget;
        std::cin>>n>>folded>>dead>>scale>>budget>>cancel_after>>mutation>>queries;
        if(n<2||n>10)return 2;
        ProbeTerminal t;t.folded=uint16_t(folded);
        for(int p=0;p<n;++p)std::cin>>t.base[p];
        for(int p=0;p<n;++p)std::cin>>t.paid[p];
        std::vector<std::array<int,10>> ranks(queries);
        for(auto& row:ranks)for(int p=0;p<n;++p)std::cin>>row[p];
        uint32_t live=((1u<<n)-1)&~uint32_t(folded);
        if(dead)t.pots.push_back({dead,live});
        std::vector<double> levels;
        for(int p=0;p<n;++p)if(t.paid[p]>0)levels.push_back(t.paid[p]);
        std::sort(levels.begin(),levels.end());levels.erase(std::unique(levels.begin(),levels.end()),levels.end());
        double previous=0;
        for(double level:levels) {
            int count=0;uint32_t eligible=0;
            for(int p=0;p<n;++p)if(t.paid[p]>=level){++count;if(live&(1u<<p))eligible|=1u<<p;}
            t.pots.push_back({(level-previous)*count,eligible});previous=level;
        }
        // Fault injection tests validate rejection before publishing a table.
        if(mutation==1)t.pots={{1,1u<<1}};
        if(mutation==2)t.pots={{1,1},{1,live}};
        if(mutation==3)t.pots={{1,1}};
        if(mutation==4)t.synthetic=true;
        if(mutation==5)t.paid[0]=.5;
        std::vector<ProbeTerminal> pool{t};
        if(mutation==6){auto second=t;second.base[0]+=17;second.base[1]-=17;pool.push_back(second);}
        int calls=0;
        try {
            auto table=hrc_terminal_table::Tables::build(pool,n,scale,std::size_t(budget),[&](){return cancel_after>0&&++calls>=cancel_after;});
            if(!table){std::cout<<"{\"status\":\"declined\",\"calls\":"<<calls<<"}\n";continue;}
            std::cout<<"{\"status\":\"ok\",\"bytes\":"<<table->bytes()<<",\"outcomes\":"<<table->outcomes()<<",\"mask\":"<<table->live_mask(0)<<",\"rank_mask\":"<<table->rank_mask(0)<<",\"keys\":[";
            for(int i=0;i<queries;++i){if(i)std::cout<<',';std::cout<<table->outcome_index(0,ranks[i].data());}
            std::cout<<"],\"values\":[";
            for(int i=0;i<queries;++i){if(i)std::cout<<',';std::cout<<'[';const double* v=table->lookup(0,ranks[i].data());
                for(int p=0;p<n;++p){if(p)std::cout<<',';std::cout<<v[p];}std::cout<<']';}
            std::atomic<bool> stable{true};std::vector<std::thread> threads;
            for(int thread=0;thread<4;++thread)threads.emplace_back([&](){
                for(int repeat=0;repeat<20;++repeat)for(const auto& r:ranks){const auto* a=table->lookup(0,r.data());const auto* b=table->lookup(0,r.data());
                    for(int p=0;p<n;++p)if(a[p]!=b[p])stable=false;}
            });
            for(auto& thread:threads)thread.join();
            std::cout<<"],\"concurrent_reads_stable\":"<<(stable?"true":"false");
            if(!table->rank_mask(0)){
                const auto* constant=table->lookup(0,nullptr);
                bool no_ranks=true;
                for(const auto& r:ranks)for(int p=0;p<n;++p)no_ranks&=constant[p]==table->lookup(0,r.data())[p];
                std::cout<<",\"null_ranks_constant\":"<<(no_ranks?"true":"false");
            }
            if(mutation==6){bool separate=table->entries()==2;
                for(const auto& r:ranks){const double* a=table->lookup(0,r.data());const double* b=table->lookup(1,r.data());
                    separate&=b-a==std::ptrdiff_t(table->outcome_count(0)*n);
                    separate&=b[0]==a[0]+17/scale&&b[1]==a[1]-17/scale;
                    for(int p=2;p<n;++p)separate&=b[p]==a[p];}
                std::cout<<",\"multiple_entries_separate\":"<<(separate?"true":"false");}
#ifdef HRC_TABLE_FROZEN_ENGINE
            Engine engine(42);engine.tree.players=n;engine.tree.chip_scale=scale;engine.tree.terms.resize(1);engine.rank_ready=true;
            auto& term=engine.tree.terms[0];term.base=t.base;term.paid=t.paid;term.folded=t.folded;
            for(const auto& pot:t.pots)term.pots.push_back({pot.amount,pot.eligible,0});
            bool exact=true;
            for(const auto& r:ranks){std::copy(r.begin(),r.end(),engine.rank);++engine.epoch;
                const double* legacy=engine.terminal(0);const double* current=table->lookup(0,r.data());
                if(std::memcmp(legacy,current,sizeof(double)*n)!=0)exact=false;}
            std::cout<<",\"frozen_engine_exact\":"<<(exact?"true":"false");
#endif
            std::cout<<"}\n";
        } catch(const hrc_terminal_table::Cancelled&) {
            std::cout<<"{\"status\":\"cancelled\",\"calls\":"<<calls<<"}\n";
        } catch(const std::exception& error) {
            std::cout<<"{\"status\":\"error\",\"message\":\""<<error.what()<<"\"}\n";
        }
    }
}
