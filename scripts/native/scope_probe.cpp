// Actual production scope/step/dealer/traversal on synthetic constant payoffs.
#define main hrc_unused_main
#include "../../native/hrc_research_solver.cpp"
#undef main
int main(int argc,char**argv){try{
    if(argc!=2)throw std::runtime_error("scope descriptor required");
    std::cout<<std::setprecision(17);
    for(int variant=0;variant<2;++variant)for(int version:{3,4})for(uint64_t seed:{42,43}){
        Engine e(seed);e.v4=version==4;e.tree.players=2;e.tree.nodes.resize(7);e.tree.initial={20,20};e.tree.chip_scale=1;
        int actors[]={0,-1,1,-1,variant?1:0,-1,-1};
        for(int id=0;id<7;++id){auto&n=e.tree.nodes[id];n.actor=actors[id];n.street=0;
            if(n.actor>=0){n.k=2;n.buckets=169;n.first=int(e.tree.children.size());int a=id==0?1:id==2?3:5;e.tree.children.push_back(a);e.tree.children.push_back(a+1);n.init();}
            else{n.terminal=int(e.tree.terms.size());Terminal t;t.synthetic=true;t.value={double(id*3-8),double(8-id*3)};e.tree.terms.push_back(t);}}
        auto&prefix=e.tree.nodes[0];for(int h=0;h<169;++h){double q=h==168?0:double(1+h%3)/4;size_t at=prefix.average(h);prefix.raw[at]=1-q;prefix.raw[at+1]=q;}
        e.scope=std::make_shared<SamplingScope>(e.tree,argv[1]);e.root_mean_valid=false;
        for(int step=1;step<=16;++step){e.step();std::cout<<"{\"variant\":"<<variant<<",\"version\":"<<version<<",\"seed\":"<<seed<<",\"step\":"<<step<<",\"mode\":"<<e.scope->mode<<",\"samples\":"<<e.samples<<",\"deals\":"<<e.sampling_deals<<",\"attempts\":"<<e.sampling_attempts<<",\"combos\":["<<e.combo[0]<<','<<e.combo[1]<<"],\"board\":[";for(int st=0;st<4;++st){if(st)std::cout<<',';std::cout<<e.board[st];}std::cout<<"],\"rng_calls\":["<<e.rng.bounded_calls<<','<<e.rng.double_calls<<','<<e.rng.int_calls<<"],\"nodes\":[";
            bool first=true;for(int id:{0,2,4}){if(!first)std::cout<<',';first=false;auto&n=e.tree.nodes[id];std::cout<<"{\"id\":"<<id<<",\"updates\":"<<n.updates<<",\"raw\":";array_json(n.raw.data(),n.raw.size());std::cout<<'}';}std::cout<<"]}\n";}
    }return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
