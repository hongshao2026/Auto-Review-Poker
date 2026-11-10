#include "../../native/hrc_fgs.hpp"
#include <iostream>
#include <iomanip>
#include <sstream>
#include <thread>

template<class T> void json_vector(const T& values) {
    std::cout<<'[';bool first=true;for(auto x:values){if(!first)std::cout<<',';std::cout<<x;first=false;}std::cout<<']';
}

int main(int argc,char** argv) {
    if(argc!=3)return 2;
    auto tables=hrc_fgs::ChanceTables::read(argv[1]);
    std::ifstream input(argv[2]);std::string line;std::cout<<std::setprecision(17);
    auto vector=[](const std::string& text){std::istringstream input(text);std::string token;std::vector<double> out;while(std::getline(input,token,','))out.push_back(std::stod(token));return out;};
    while(std::getline(input,line)) {
        if(line.empty())continue;std::istringstream row(line);std::string token;std::vector<std::string> fields;
        while(std::getline(row,token,'\t'))fields.push_back(token);
        hrc_fgs::Config config;config.equity.mode=hrc_equity::Mode::ICM;config.equity.payouts=vector(fields[2]);
        auto blinds=vector(fields[3]);config.big_blind=blinds[0];config.small_blind=blinds[1];config.ante=blinds[2];config.depth=std::stoi(fields[4]);config.depth3way=std::stoi(fields[5]);
        config.moving_button=fields[7]=="true";if(fields.size()>8)config.ante_type=static_cast<hrc_fgs::AnteType>(std::stoi(fields[8]));if(fields.size()>9)config.straddle=static_cast<hrc_fgs::Straddle>(std::stoi(fields[9]));
        hrc_fgs::Context context;for(auto x:vector(fields[1]))context.stacks.push_back(std::int64_t(x));context.skip_sb=fields[6]=="true";
        if(fields.size()>10){config.next_level_at=std::stoi(fields[10]);if(config.next_level_at>=0){auto next=vector(fields[11]);for(int i=0;i<3;++i)config.next_level[i]=next[i];}}
        if(fields.size()>12){config.equity.bounty_mode=static_cast<hrc_equity::BountyMode>(std::stoi(fields[12]));if(config.equity.bounty_mode!=hrc_equity::BountyMode::None)context.bounties=vector(fields[13]);config.equity.immediate_fraction=std::stod(fields[14]);}
        hrc_fgs::Calculator solver(config,tables);auto start=std::chrono::steady_clock::now();auto values=solver.equities(context);
        auto elapsed=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
        std::cout<<"{\"kind\":\"fgs\",\"id\":\""<<fields[0]<<"\",\"values\":[";for(std::size_t i=0;i<values.size();++i)std::cout<<(i?",":"")<<values[i];
        std::cout<<"],\"states\":"<<solver.stats().states<<",\"sweeps\":"<<solver.stats().sweeps<<",\"nanoseconds\":"<<elapsed<<"}\n";
        auto plainConfig=config.equity;plainConfig.initial_stacks=context.stacks;plainConfig.bounties=context.bounties;plainConfig.cache_capacity=0;
        hrc_equity::Calculator plain(plainConfig);
        auto emit=[&](const std::vector<int>& participants) {
            int count=participants.size(),outcomes=count==1?1:count==2?3:13;
            for(int r=0;r<outcomes;++r) {
                int code=count==1?1:count==2?hrc_fgs::results2[r]:hrc_fgs::results3[r];std::vector<int> ranks(count);
                for(int i=count-1;i>=0;--i){ranks[i]=code%10;code/=10;}
                auto terminal=hrc_fgs::allin_outcome(context,config,participants,ranks);
                hrc_equity::Chips chips{};hrc_equity::WinnerMasks masks{};
                std::copy(terminal.stacks.begin(),terminal.stacks.end(),chips.begin());std::copy(terminal.winner_masks.begin(),terminal.winner_masks.end(),masks.begin());
                auto evaluated=plain.compute_terminal(chips,masks);
                hrc_fgs::Values heads(evaluated.remaining_bounties.begin(),evaluated.remaining_bounties.begin()+context.stacks.size());
                auto child=hrc_fgs::next_context(context,terminal,config,heads);
                std::vector<int> mapping(context.stacks.size(),-1);for(std::size_t j=0;j<child.second.size();++j)mapping[child.second[j]]=j;
                auto future=solver.terminal(context,terminal);
                std::cout<<"{\"kind\":\"outcome\",\"id\":\""<<fields[0]<<"\",\"participants\":";json_vector(participants);
                std::cout<<",\"result\":"<<r<<",\"stacks\":";json_vector(terminal.stacks);std::cout<<",\"winner_masks\":";json_vector(terminal.winner_masks);
                std::cout<<",\"tied\":"<<(terminal.tied_award?"true":"false")<<",\"next_stacks\":";json_vector(child.first.stacks);
                std::cout<<",\"mapping\":";json_vector(mapping);std::cout<<",\"next_skip_sb\":"<<(child.first.skip_sb?"true":"false")<<",\"next_bounties\":";json_vector(child.first.bounties);
                std::cout<<",\"ordinary_values\":";json_vector(hrc_fgs::Values(evaluated.total.begin(),evaluated.total.begin()+context.stacks.size()));
                std::cout<<",\"fgs_values\":";json_vector(future);std::cout<<"}\n";
            }
        };
        int n=context.stacks.size();for(int a=0;a<n;++a)emit({a});for(int a=0;a<n;++a)for(int b=a+1;b<n;++b)emit({a,b});
        for(int a=0;a<n;++a)for(int b=a+1;b<n;++b)for(int c=b+1;c<n;++c)emit({a,b,c});
    }
    hrc_fgs::Config control;control.equity.mode=hrc_equity::Mode::ICM;control.equity.payouts={100,50};control.depth=0;control.max_seconds=.05;
    hrc_fgs::Context context{{1000,1000},{},0,false};hrc_fgs::Calculator cache(control,tables);
    auto first=hrc_fgs::allin_outcome(context,control,{0},{1}),second=hrc_fgs::allin_outcome(context,control,{1},{1});
    auto value=cache.terminal(context,first);double used=cache.work_seconds();std::this_thread::sleep_for(std::chrono::milliseconds(75));
    auto repeated=cache.terminal(context,first);auto fresh=cache.terminal(context,second);
    bool idle=value==repeated&&cache.stats().terminal_cache_hits==1&&cache.work_seconds()<.05&&fresh.size()==2;
    std::cout<<"{\"kind\":\"control\",\"id\":\"idle_and_terminal_cache\",\"passed\":"<<(idle?"true":"false")<<",\"work_seconds\":"<<cache.work_seconds()<<"}\n";
    control.depth=1;control.max_states=1;control.max_seconds=60;hrc_fgs::Calculator budget(control,tables);bool failed=false;
    try{budget.equities(context);}catch(const hrc_fgs::ResourceLimit&){failed=true;}
    std::cout<<"{\"kind\":\"control\",\"id\":\"state_budget_returns_no_partial_result\",\"passed\":"<<(failed?"true":"false")<<"}\n";
    int checks=0;control.max_states=20000;control.cancel_check=[&](){return ++checks>=10;};
    hrc_fgs::Calculator cancelled(control,tables);bool stopped=false;
    try{cancelled.equities(context);}catch(const hrc_fgs::Cancelled&){stopped=true;}
    std::cout<<"{\"kind\":\"control\",\"id\":\"cancel_inside_fgs_recursion\",\"passed\":"<<(stopped&&checks==10?"true":"false")<<",\"checks\":"<<checks<<"}\n";
}
