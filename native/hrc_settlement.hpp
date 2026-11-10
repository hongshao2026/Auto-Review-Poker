// Independent rank-ordered pot settlement for the audited raked-cash model.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace hrc_settlement {
enum class RakeMode : int { None=0, NoFlopNoDrop=1, GGNetwork=2, Full=3 };
struct RakeConfig { RakeMode mode=RakeMode::None; double fraction=0; int64_t cap=0; };
struct Pot { int64_t rake=0, amount=0; std::vector<int> winners; std::vector<int64_t> awards; };
struct Result { std::vector<int64_t> stacks; std::vector<uint16_t> winner_masks; int64_t rake=0; bool tied_award=false; std::vector<Pot> pots; };

inline Result settle(const std::vector<int64_t>& remaining, const std::vector<int64_t>& paid,
                     uint16_t folded, const std::vector<int>& ranks, int64_t dead_money,
                     int street, int raises, const RakeConfig& config) {
    const int n=int(remaining.size());
    if(n<2||n>10||paid.size()!=remaining.size()||ranks.size()!=remaining.size()||dead_money<0||street<0||street>3
       ||raises<0||!std::isfinite(config.fraction)||config.fraction<0||config.fraction>1||config.cap<0
       ||int(config.mode)<0||int(config.mode)>3||folded>>n)throw std::invalid_argument("Invalid settlement inputs");
    Result out;out.stacks=remaining;out.winner_masks.assign(n,0);
    std::vector<int> active;
    for(int p=0;p<n;++p){if(remaining[p]<0||paid[p]<0)throw std::invalid_argument("Negative chip state");if(!(folded&(1<<p)))active.push_back(p);}
    if(active.empty())throw std::invalid_argument("No live player");
    std::sort(active.begin(),active.end(),[&](int a,int b){if(ranks[a]!=ranks[b])return ranks[a]>ranks[b];if(paid[a]!=paid[b])return paid[a]<paid[b];return a>b;});
    const bool eligible=street>0||active.size()>1||config.mode==RakeMode::Full||(config.mode==RakeMode::GGNetwork&&raises>1);
    int64_t level=0;
    for(size_t first=0;first<active.size();++first){
        int seat=active[first];if(first&&paid[seat]<=level)continue;
        Pot pot;pot.amount=first?0:dead_money;pot.awards.assign(n,0);
        for(size_t j=first;j<active.size()&&ranks[active[j]]==ranks[seat];++j)pot.winners.push_back(active[j]);
        uint16_t mask=0;for(int p:pot.winners)mask|=uint16_t(1u<<p);
        out.tied_award|=pot.winners.size()>1;int contributors=0;
        for(int p=0;p<n;++p)if(first==0||paid[p]>level){
            pot.amount+=std::min(paid[p]-level,paid[seat]-level);++contributors;
            if(!remaining[p]&&paid[p]<=paid[seat]&&((folded&(1<<p))||ranks[p]<ranks[seat]))out.winner_masks[p]=mask;
        }
        level=paid[seat];
        if(contributors>1&&eligible&&config.mode!=RakeMode::None&&config.fraction>0&&config.cap>out.rake){
            pot.rake=std::min(int64_t(std::floor(double(pot.amount)*config.fraction+.5)),config.cap-out.rake);
            pot.amount-=pot.rake;out.rake+=pot.rake;
        }
        int64_t share=pot.amount/int64_t(pot.winners.size()),odd=pot.amount%int64_t(pot.winners.size());
        for(int p:pot.winners){out.stacks[p]+=share;pot.awards[p]+=share;}
        // lF final stacks and lG display details intentionally use different odd-chip recipients.
        out.stacks[pot.winners.front()]+=odd;pot.awards[pot.winners.back()]+=odd;
        out.pots.push_back(std::move(pot));
    }
    int64_t initial=dead_money,final=out.rake;
    for(int p=0;p<n;++p){if(paid[p]>level)out.stacks[p]+=paid[p]-level;
        if((out.winner_masks[p]==0)==(out.stacks[p]==0))throw std::runtime_error("Settlement has an invalid elimination outcome");
        initial+=remaining[p]+paid[p];final+=out.stacks[p];}
    if(initial!=final)throw std::runtime_error("Settlement does not conserve chips plus rake");
    return out;
}
}
