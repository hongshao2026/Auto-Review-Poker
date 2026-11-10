// Tournament pairwise all-in analysis, independently composed from verified equity.
#include "hrc_equity.hpp"
#include "hrc_mtt.hpp"
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

std::vector<double> values(const std::string& line) {
    std::vector<double> out; std::istringstream stream(line); double v;
    while(stream>>v)out.push_back(v); return out;
}
void number(double value) { if(std::isfinite(value))std::cout<<value;else std::cout<<"null"; }
void array(const std::vector<double>& a) {std::cout<<'[';for(size_t i=0;i<a.size();++i){if(i)std::cout<<',';number(a[i]);}std::cout<<']';}
int main() {
    try {
        std::string line; std::getline(std::cin,line); std::istringstream head(line);
        int mode,bounty; double fraction; head>>mode>>bounty>>fraction;
        hrc_equity::EquityConfig cfg;
        cfg.mode=hrc_equity::Mode(mode);cfg.bounty_mode=hrc_equity::BountyMode(bounty);cfg.immediate_fraction=fraction;
        std::getline(std::cin,line);for(double v:values(line)){if(v!=std::floor(v)||v>1e15)throw std::invalid_argument("Invalid stack");cfg.initial_stacks.push_back(int64_t(v));}
        std::getline(std::cin,line);cfg.payouts=values(line);
        std::getline(std::cin,line);cfg.bounties=values(line);
        std::getline(std::cin,line);cfg.other_stacks=values(line);
        std::getline(std::cin,line);cfg.other_bounties=values(line);
        if(cfg.bounty_mode==hrc_equity::BountyMode::None){cfg.bounties.clear();cfg.other_bounties.clear();}
        cfg.cache_capacity=0;
        hrc_equity::Calculator calc(cfg,[](const auto& stacks,const auto& prizes,const auto& others){return hrc_mtt::equities(stacks,prizes,others);});
        const size_t n=cfg.initial_stacks.size();auto base=calc.baseline().total;
        std::vector<double> baseline(base.begin(),base.begin()+n);
        std::cout<<std::setprecision(17)<<"{\"baseline_equities\":";array(baseline);std::cout<<",\"pairs\":[";
        bool first=true;
        for(size_t i=0;i<n;++i)for(size_t j=0;j<n;++j)if(i!=j){
            auto effective=std::min(cfg.initial_stacks[i],cfg.initial_stacks[j]);
            hrc_equity::Chips win{},lose{};hrc_equity::WinnerMasks win_mask{},lose_mask{};
            std::copy(cfg.initial_stacks.begin(),cfg.initial_stacks.end(),win.begin());lose=win;
            win[i]+=effective;win[j]-=effective;lose[i]-=effective;lose[j]+=effective;
            if(!win[j])win_mask[j]=uint16_t(1u<<i);if(!lose[i])lose_mask[i]=uint16_t(1u<<j);
            double won=calc.compute_terminal(win,win_mask).total[i], lost=calc.compute_terminal(lose,lose_mask).total[i];
            double loss=base[i]-lost,gain=won-base[i],factor=loss/gain;
            double premium=100*(factor/(factor+1)-.5);
            if(!first)std::cout<<',';first=false;
            std::cout<<"{\"row\":"<<i<<",\"column\":"<<j<<",\"effective_chips\":"<<effective<<",\"win_equity\":";number(won);
            std::cout<<",\"lose_equity\":";number(lost);std::cout<<",\"bubble_factor\":";number(factor);
            std::cout<<",\"risk_premium_pp\":";number(premium);
            std::cout<<",\"state\":\""<<(std::isnan(factor)?"undefined":std::isinf(factor)?"infinite":"finite")<<"\"}";
        }
        std::cout<<"]}\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what();return 1;}
}
