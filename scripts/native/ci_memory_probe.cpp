// Reservation-only tests call the actual Engine helper. No abstract-card files.
#define main hrc_solver_main
#include "../../native/hrc_research_solver.cpp"
#undef main

static void require(bool condition,const char* text){if(!condition)throw std::runtime_error(text);}
static void setup(Engine& e){
    e.tree.players=2;e.tree.root=0;e.tree.chip_scale=100;e.tree.track_ci=true;
    e.tree.initial[0]=e.tree.initial[1]=1000;e.tree.estimated_memory=1024;e.tree.max_memory=16<<20;
    e.tree.nodes.resize(3);e.tree.children={1,2};e.tree.terms.resize(2);
    auto& n=e.tree.nodes[0];n.actor=0;n.street=0;n.buckets=3;n.k=2;n.first=0;n.init();
    n.raw[0]=7;n.updates=19;n.visits[0]=19;
    for(size_t i=1;i<n.raw.size();++i)n.raw[i]=double(i)/8;
    for(int i=0;i<2;++i){e.tree.nodes[i+1].terminal=i;auto& t=e.tree.terms[i];
        t.paid[0]=t.paid[1]=10;t.base[0]=t.base[1]=-10;t.pots.push_back({20,3,3});t.participants=2;}
}
struct Untouched {
    std::vector<double> raw,shared;std::vector<uint64_t> visits;uint64_t updates,samples,epoch;
    std::array<uint64_t,4> rng;uint64_t integers,units,bounds;
    explicit Untouched(const Engine& e):raw(e.tree.nodes[0].raw),shared(e.tree.nodes[0].shared_sums),
        visits(e.tree.nodes[0].visits),updates(e.tree.nodes[0].updates),samples(e.samples),epoch(e.epoch),
        integers(e.rng.int_calls),units(e.rng.double_calls),bounds(e.rng.bounded_calls){std::copy(e.rng.s,e.rng.s+4,rng.begin());}
    void check(const Engine& e)const{
        const auto& n=e.tree.nodes[0];require(n.raw==raw&&n.shared_sums==shared&&n.visits==visits&&n.updates==updates,"Reservation changed storage");
        require(e.samples==samples&&e.epoch==epoch,"Reservation changed sample state");
        require(std::equal(rng.begin(),rng.end(),e.rng.s)&&integers==e.rng.int_calls&&units==e.rng.double_calls&&bounds==e.rng.bounded_calls,"Reservation changed RNG");
    }
};
int main(int argc,char**argv){try{
    if(argc!=2)throw std::runtime_error("mode required");std::string mode=argv[1];
    Engine reference(43);setup(reference);reference.reserve_ci_memory();const uint64_t required=reference.ci_reserved;
    require(required>0,"Empty CI requirement");Engine e(43);setup(e);const uint64_t baseline=e.tree.estimated_memory;
    Untouched before(e);bool table=false,rejected=false;
    if(mode=="idempotent"){
        e.reserve_ci_memory();before.check(e);require(!e.ci,"Reservation initialized Tracker");
        require(e.ci_nodes==std::vector<int>{0},"Wrong CI scope");require(e.tree.estimated_memory==baseline+required,"Wrong first reserve");
        e.reserve_ci_memory();before.check(e);require(e.tree.estimated_memory==baseline+required,"Double reserve");
        e.start_ci(0);require(e.tree.estimated_memory==baseline+required,"Start double-reserved");
        require(bool(e.ci)&&e.tree.nodes[0].raw[0]==19,"Original start did not flush stale counter");
        require(std::equal(before.rng.begin(),before.rng.end(),e.rng.s),"Start changed RNG");
    }else if(mode=="ci_off"){
        e.tree.track_ci=false;e.tree.max_memory=baseline;e.reserve_ci_memory();e.start_ci(0);before.check(e);
        require(!e.ci&&e.ci_reserved==0&&e.ci_nodes.empty(),"CI off created metadata");
        require(e.tree.estimated_memory==baseline,"CI off consumed budget");
    }else if(mode=="one_byte_short"){
        e.tree.max_memory=baseline+required-1;
        try{e.reserve_ci_memory();}catch(const NativeResourceLimit&){rejected=true;}
        before.check(e);require(rejected&&!e.ci&&e.ci_reserved==0,"Missing precise rejection");
        require(e.tree.estimated_memory==baseline,"Failed reserve consumed budget");
    }else if(mode=="exact"||mode=="tiny_headroom"||mode=="table_fits"){
        uint64_t headroom=mode=="tiny_headroom"?16:0;
        if(mode=="table_fits"){
            auto sizes=hrc_terminal_table::Tables::build(e.tree.terms,2,e.tree.chip_scale,1<<20,{});
            require(bool(sizes),"Valid tiny table did not build");headroom=4*sizes->bytes();
        }
        e.tree.max_memory=baseline+required+headroom;e.reserve_ci_memory();before.check(e);
        uint64_t table_budget=std::min(uint64_t(64)<<20,(e.tree.max_memory-e.tree.estimated_memory)/4);
        auto prepared=hrc_terminal_table::Tables::build(e.tree.terms,2,e.tree.chip_scale,size_t(table_budget),{});
        table=bool(prepared);require(table==(mode=="table_fits"),"Optional table fallback incorrect");
        if(prepared){e.tree.reserve_budget(prepared->bytes());e.tree.terminal_tables=std::move(prepared);}
        before.check(e);uint64_t after_table=e.tree.estimated_memory;
        e.start_ci(0);require(bool(e.ci)&&e.tree.nodes[0].raw[0]==19,"CI failed after optional table decision");
        require(e.tree.estimated_memory==after_table&&e.tree.estimated_memory<=e.tree.max_memory,"CI changed reserved budget");
    }else throw std::runtime_error("Unknown mode");
    std::cout<<"{\"mode\":\""<<mode<<"\",\"required\":"<<required<<",\"reserved\":"<<e.ci_reserved<<",\"estimated\":"<<e.tree.estimated_memory<<",\"maximum\":"<<e.tree.max_memory<<",\"table\":"<<(table?"true":"false")<<",\"rejected\":"<<(rejected?"true":"false")<<",\"tracker\":"<<(e.ci?"true":"false")<<"}\n";return 0;
}catch(const std::exception& x){std::cerr<<x.what()<<'\n';return 1;}}
