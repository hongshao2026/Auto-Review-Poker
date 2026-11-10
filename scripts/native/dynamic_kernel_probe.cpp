// Exercise the production Tree/Engine fixed-board path, not a copied algorithm.
#define main hrc_solver_main
#include "../../native/hrc_research_solver.cpp"
#undef main
int main(int argc,char**argv){try{
    if(argc==3&&std::string(argv[1])=="--digest"){std::cout<<hrc_digest::file_sha256(argv[2]);return 0;}
    if(argc<5)throw std::runtime_error("tree resources seed deals [cancel]");
    Engine e(std::stoull(argv[3]));e.tree.load(argv[1],argv[2]);
    if(argc>5){int checks=0;e.tree.chance_cancel=[&](){return ++checks>=2;};try{e.deal();}catch(const hrc_fgs::Cancelled&){std::cout<<"{\"cancelled\":true,\"samples\":"<<e.samples<<",\"epoch\":"<<e.epoch<<"}";return 0;}throw std::runtime_error("Expected sampling cancellation");}
    for(int i=0;i<std::stoi(argv[4]);++i){e.deal();std::cout<<std::setprecision(17)<<"{\"combos\":[";for(int p=0;p<e.tree.players;++p){if(p)std::cout<<',';std::cout<<e.combo[p];}std::cout<<"],\"holes\":[";for(int p=0;p<e.tree.players;++p){if(p)std::cout<<',';std::cout<<e.holes[p];}std::cout<<"],\"board\":[";for(int st=0;st<4;++st){if(st)std::cout<<',';std::cout<<e.board[st];}std::cout<<"],\"hands\":[";bool first=true;for(const auto& n:e.tree.nodes)if(n.k){if(!first)std::cout<<',';first=false;std::cout<<e.hand(n);}std::cout<<"],\"terminals\":[";for(size_t t=0;t<e.tree.terms.size();++t){if(t)std::cout<<',';auto q=e.terminal(int(t));std::cout<<'[';for(int p=0;p<e.tree.players;++p){if(p)std::cout<<',';std::cout<<q[p];}std::cout<<']';}std::cout<<"]}"<<std::endl;}
    return 0;
}catch(const std::exception&ex){std::cerr<<ex.what();return 1;}}
