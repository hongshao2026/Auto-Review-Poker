// Exercise the production Engine terminal path with retained original rank fixtures.
#define main hrc_research_cli_main
#include "../../native/hrc_research_solver.cpp"
#undef main

int main(){
    std::cout<<std::setprecision(17);int cases=0;std::cin>>cases;
    for(int i=0;i<cases;++i){Engine e(42);int players,mode,street,raises,folded;double fraction;int64_t cap,dead;std::cin>>players>>mode>>fraction>>cap>>street>>raises>>folded>>dead;
        e.tree.players=players;e.tree.chip_scale=100;e.tree.raked=true;e.tree.rake={hrc_settlement::RakeMode(mode),fraction,cap};e.tree.terms.resize(1);e.rank_ready=true;
        auto& t=e.tree.terms[0];t.folded=uint16_t(folded);t.dead_money=dead;t.street=street;t.raise_count=raises;
        for(int p=0;p<players;++p)std::cin>>t.remaining[p];for(int p=0;p<players;++p)std::cin>>t.paid[p];for(int p=0;p<players;++p)std::cin>>e.rank[p];
        for(int p=0;p<players;++p)e.tree.initial[p]=t.remaining[p]+t.paid[p];e.tree.initial[0]+=dead;
        try{auto value=e.terminal(0);std::cout<<"{\"case\":"<<i<<",\"values\":";array_json(value,players);std::cout<<"}\n";}
        catch(const std::exception&){std::cout<<"{\"case\":"<<i<<",\"error\":true}\n";}
    }
}
