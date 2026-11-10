// Compile the actual current kernel into an isolated synthetic fixture. No
// production source rewrite, installed-resource load, dealing or training job.
#define main hrc_production_main_not_called
#include "../../native/hrc_research_solver.cpp"
#undef main
#include <sstream>

struct FixtureNode {int id,actor=-1,street=0,special=0;std::vector<int> children;Values value{};};
struct Fixture {std::string name;uint64_t seed;int mode,target,depth,steps;double marker;std::vector<FixtureNode> nodes;};
void run_fixture(const Fixture& c){
    Engine e(c.seed);e.v4=c.mode==4;e.tree.players=2;e.tree.nodes.resize(c.nodes.size());
    for(const auto& s:c.nodes){auto& n=e.tree.nodes[s.id];n.actor=s.actor;n.street=s.street;n.buckets=2;n.k=int(s.children.size());n.special=s.special;
        if(n.k){n.first=int(e.tree.children.size());e.tree.children.insert(e.tree.children.end(),s.children.begin(),s.children.end());n.init();}
        else {n.terminal=int(e.tree.terms.size());Terminal t;t.synthetic=true;t.value=s.value;e.tree.terms.push_back(t);}}
    for(int st=0;st<4;++st){e.bucket_ready[st]=true;e.bucket[st][0]=0;e.bucket[st][1]=1;}
    for(int step=1;step<=c.steps;++step){double scalar=0;const double* value;
        if(c.target<0)value=e.vector(0);else{scalar=e.scalar(0,c.target,c.depth,c.marker);value=&scalar;}
        std::cout<<"{\"kind\":\"nested_result\",\"case\":\""<<c.name<<"\",\"step\":"<<step<<",\"value\":";array_json(value,c.target<0?2:1);std::cout<<",\"nodes\":[";bool first=true;
        for(size_t i=0;i<e.tree.nodes.size();++i){auto& n=e.tree.nodes[i];if(!n.k)continue;if(!first)std::cout<<',';first=false;
            std::cout<<"{\"id\":"<<i<<",\"updates\":"<<n.updates<<",\"raw\":";array_json(n.raw.data(),n.raw.size());std::cout<<'}';}
        std::cout<<"],\"rng_calls\":["<<e.rng.bounded_calls<<','<<e.rng.double_calls<<','<<e.rng.int_calls<<"],\"traversal_calls\":["<<e.vector_calls<<','<<e.scalar_calls<<','<<e.terminal_calls<<"]}\n";
    }
}
int main(int argc,char** argv){try{
    if(argc!=2)throw std::runtime_error("fixture input required");std::ifstream in(argv[1]);if(!in)throw std::runtime_error("fixture input missing");
    std::cout<<std::setprecision(17);std::string line;Fixture c;
    while(std::getline(in,line)){if(line.empty()||line[0]=='#')continue;std::istringstream s(line);std::string op;s>>op;
        if(op=="CASE"){c=Fixture{};s>>c.name>>c.seed>>c.mode>>c.target>>c.depth>>c.marker>>c.steps;}
        else if(op=="NODE"){FixtureNode n;s>>n.id>>n.actor>>n.street>>n.special;int child;while(s>>child)n.children.push_back(child);if(n.id!=int(c.nodes.size()))throw std::runtime_error("ID order");c.nodes.push_back(n);}
        else if(op=="LEAF"){FixtureNode n;s>>n.id>>n.value[0]>>n.value[1];if(n.id!=int(c.nodes.size()))throw std::runtime_error("ID order");c.nodes.push_back(n);}
        else if(op=="END")run_fixture(c);else throw std::runtime_error("Unknown fixture directive");}
    return 0;
}catch(const std::exception& ex){std::cerr<<ex.what()<<'\n';return 1;}}
