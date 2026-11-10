// Exercise the actual Engine and scheduler; only leaf payoffs are synthetic.
#define main hrc_solver_main
#include "../../native/hrc_research_solver.cpp"
#undef main
#include <numeric>

static void require(bool condition,const char* message){if(!condition)throw std::runtime_error(message);}
static void setup(Engine& e){
    e.tree.players=2;e.tree.root=0;e.tree.chip_scale=100;e.tree.initial[0]=e.tree.initial[1]=1000;
    e.tree.nodes.resize(3);e.tree.children={1,2};e.tree.terms.resize(2);
    auto& n=e.tree.nodes[0];n.actor=0;n.street=0;n.buckets=169;n.k=2;n.first=0;n.init();
    for(int i=0;i<2;++i){e.tree.nodes[i+1].terminal=i;auto& t=e.tree.terms[i];t.synthetic=true;t.value[0]=i?2:-1;t.value[1]=-t.value[0];}
}
static void counters(const Engine& e,uint64_t samples){
    const auto& root=e.tree.nodes[0];
    require(e.samples==samples,"Global sample count");
    require(root.updates==samples,"Lost or extra node updates");
    require(std::accumulate(root.visits.begin(),root.visits.end(),uint64_t(0))==samples,"Lost visits");
    require(e.scope_samples==samples,"Scope aggregation");
    require(e.sampling_deals==samples,"Deal aggregation");
    require(e.vector_calls==2*samples,"Vector call aggregation");
    for(const auto& row:e.parallel_rng)require(std::any_of(row.begin(),row.end(),[](uint64_t x){return x!=0;}),"Missing worker RNG");
    require(e.parallel_rng.empty()||std::equal(e.parallel_rng[0].begin(),e.parallel_rng[0].end(),e.rng.s),"Primary RNG mismatch");
}
static auto later(int ms=10000){return std::chrono::steady_clock::now()+std::chrono::milliseconds(ms);}
int main(int argc,char**argv){try{
    if(argc<4)throw std::runtime_error("mode threads output");
    std::string mode=argv[1];int threads=std::stoi(argv[2]);fs::path out=argv[3];Engine e(43);setup(e);
    uint64_t rounds=0,blocks=0,samples=0;bool paused=false,failed=false;
    if(mode=="counter_lookup"||mode=="counter_settle"){
        for(auto& t:e.tree.terms){t.synthetic=false;t.paid[0]=t.paid[1]=10;t.base[0]=t.base[1]=-10;t.pots.push_back({20,3,3});t.participants=2;}
        ParallelTrainer p(e,threads,43);
        // Build after worker construction to cover production's shared-resource
        // publication order; workers must not use a copied null table pointer.
        if(mode=="counter_lookup")e.tree.terminal_tables=hrc_terminal_table::Tables::build(e.tree.terms,2,e.tree.chip_scale,1<<20,{});
        for(uint64_t count:{uint64_t(1003),uint64_t(2003)}){
            require(p.run_adaptive(count,later())==count,"Counter test sample budget");
            require(e.terminal_table_lookups==(mode=="counter_lookup"?2*e.samples:0),"Lookup counters were lost or double-collected");
            require(e.terminal_settlements==(mode=="counter_settle"?2*e.samples:0),"Settlement counters were lost or double-collected");
        }
        p.run(1003);counters(e,4009);
        require(e.terminal_table_lookups==(mode=="counter_lookup"?8018:0),"Legacy lookup aggregation");
        require(e.terminal_settlements==(mode=="counter_settle"?8018:0),"Legacy settlement aggregation");
        rounds=p.control_rounds();blocks=p.claimed_blocks();samples=e.samples;
    }else if(mode=="budgets"){
        ParallelTrainer p(e,threads,43);uint64_t total=0,expected_blocks=0;
        for(uint64_t count:{uint64_t(1),uint64_t(249),uint64_t(250),uint64_t(251),uint64_t(2003),uint64_t(10003)}){
            auto done=p.run_adaptive(count,later());require(done==count,"Budget incomplete");total+=count;
            expected_blocks+=count/250+uint64_t(count%250!=0);counters(e,total);
        }
        require(p.claimed_blocks()==expected_blocks,"Ticket counter");
        p.run(73);total+=73;counters(e,total);
        require(p.run_adaptive(79,later())==79,"Legacy/adaptive switch");total+=79;counters(e,total);
        rounds=p.control_rounds();blocks=p.claimed_blocks();samples=e.samples;
        require(rounds==8&&p.adaptive_rounds()==7,"Control boundary count");e.save(out);
    }else if(mode=="deadline"||mode=="pause"){
        ParallelTrainer p(e,threads,43);std::thread controller;
        if(mode=="pause")controller=std::thread([&](){std::this_thread::sleep_for(std::chrono::milliseconds(10));p.request_pause();});
        uint64_t done=p.run_adaptive(1000000000,later(mode=="pause"?5000:20));
        if(controller.joinable())controller.join();
        require(done>0&&done<1000000000,"Deadline/pause did not return partial progress");counters(e,done);paused=true;
        auto rng=e.parallel_rng;auto before=e.samples;
        require(p.run_adaptive(0,later())==0,"Zero budget did work");
        require(p.run_adaptive(999,std::chrono::steady_clock::now()-std::chrono::milliseconds(1))==0,"Expired deadline did work");
        require(e.parallel_rng==rng&&e.samples==before,"No-work call mutated RNG/count");
        require(p.run_adaptive(1003,later())==1003,"Resume after pause");counters(e,before+1003);
        rounds=p.control_rounds();blocks=p.claimed_blocks();samples=e.samples;e.save(out);
    }else if(mode=="resume"){
        {ParallelTrainer p(e,threads,43);require(p.run_adaptive(5003,later())==5003,"First segment");counters(e,5003);e.save(out/"source");}
        Engine restored(999);setup(restored);restored.resume(out/"source/checkpoint.bin");
        {ParallelTrainer p(restored,threads,999);require(p.run_adaptive(0,later())==0,"No-work resume");restored.save(out/"unchanged");
            // Invocation-local scope/call counters restart on checkpoint load.
            require(p.run_adaptive(1007,later())==1007,"Second segment");
            require(restored.samples==6010&&restored.tree.nodes[0].updates==6010,"Resumed persistent counters");
            require(restored.scope_samples==1007&&restored.sampling_deals==1007,"Resumed invocation counters");
            rounds=p.control_rounds();blocks=p.claimed_blocks();samples=restored.samples;restored.save(out/"continued");}
    }else if(mode=="exception"||mode=="exception_legacy"){
        hrc_chance::Config cfg;cfg.ranges.resize(2);e.tree.chance=std::make_unique<hrc_chance::Sampler>(cfg);
        std::atomic<uint64_t> callbacks{0};std::atomic<int> active{0};
        e.tree.chance_cancel=[&](){active.fetch_add(1);auto n=callbacks.fetch_add(1);std::this_thread::yield();active.fetch_sub(1);if(n>=1000)throw std::runtime_error("injected worker failure");return false;};
        {ParallelTrainer p(e,threads,43);
            try{if(mode=="exception_legacy")p.run(1000000000);else p.run_adaptive(1000000000,later());}catch(const std::runtime_error& x){failed=std::string(x.what())=="injected worker failure";}
            require(failed&&active.load()==0,"Exception propagated before quiescence");
            uint64_t before=callbacks.load();std::this_thread::sleep_for(std::chrono::milliseconds(2));require(callbacks.load()==before,"Worker still running after exception");
            counters(e,e.samples);bool rejected=false;try{p.run_adaptive(1,later());}catch(const std::runtime_error& x){rejected=std::string(x.what()).find("rollback")!=std::string::npos;}
            require(rejected,"Failed trainer reused without rollback");rounds=p.control_rounds();blocks=p.claimed_blocks();samples=e.samples;
            rejected=false;try{p.run(1);}catch(const std::runtime_error& x){rejected=std::string(x.what()).find("rollback")!=std::string::npos;}
            require(rejected,"Legacy API reused failed trainer");
        }
        require(e.node_mutexes==nullptr,"Destructor did not detach locks");
    }else throw std::runtime_error("Unknown mode");
    std::cout<<"{\"mode\":\""<<mode<<"\",\"threads\":"<<threads<<",\"samples\":"<<samples<<",\"rounds\":"<<rounds<<",\"claimed_blocks\":"<<blocks<<",\"paused\":"<<(paused?"true":"false")<<",\"failed_quiescent\":"<<(failed?"true":"false")<<",\"terminal_table_lookups\":"<<e.terminal_table_lookups<<",\"terminal_settlements\":"<<e.terminal_settlements<<"}\n";
    return 0;
}catch(const std::exception& x){std::cerr<<x.what()<<'\n';return 1;}}
