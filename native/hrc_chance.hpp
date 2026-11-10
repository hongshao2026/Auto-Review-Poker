#pragma once
// Independent mode-1 joint range rejection; all dealt seats include dead cards.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <functional>
#include <stdexcept>
#include <vector>

namespace hrc_chance {
struct ResourceLimit : std::runtime_error { using std::runtime_error::runtime_error; };
struct Cancelled : std::runtime_error { using std::runtime_error::runtime_error; };
struct Config {
    std::vector<std::vector<double>> ranges; // empty row = uniform; otherwise 1326
    std::vector<uint64_t> board_history{0};
    uint64_t max_attempts=1000000, max_random_calls=10000000;
};
struct Deal {
    std::vector<int> combos;
    std::array<uint64_t,4> board{};
    uint64_t used=0, attempts=0, random_calls=0;
};
class Sampler {
    Config cfg_;
    std::array<uint64_t,1326> masks_{};
    std::vector<std::vector<double>> cumulative_;
    static int bits(uint64_t n) { int count=0;for(;n;n&=n-1)++count;return count; }
public:
    explicit Sampler(Config cfg):cfg_(std::move(cfg)) {
        if(cfg_.ranges.empty()||cfg_.ranges.size()>10||!cfg_.max_attempts||!cfg_.max_random_calls)
            throw std::invalid_argument("Invalid chance seats or resource budget");
        const auto &board=cfg_.board_history;
        if(board.empty()||board.size()>4||board[0]!=0)
            throw std::invalid_argument("Invalid chance board history");
        for(size_t i=1;i<board.size();++i)
            if(board[i]>>52||bits(board[i])!=int(i)+2||(board[i]&board[i-1])!=board[i-1])
                throw std::invalid_argument("Invalid cumulative chance board");
        for(int high=1;high<52;++high)for(int low=0;low<high;++low)
            masks_[high*(high-1)/2+low]=(1ULL<<high)|(1ULL<<low);
        cumulative_.resize(cfg_.ranges.size());
        for(size_t player=0;player<cfg_.ranges.size();++player) {
            auto &weights=cfg_.ranges[player];auto &cdf=cumulative_[player];
            if(weights.empty())continue;
            if(weights.size()!=1326)throw std::invalid_argument("Expected 1326 combo weights");
            double total=0;cdf.resize(1326);
            for(int i=0;i<1326;++i) {
                if(!std::isfinite(weights[i])||weights[i]<0)throw std::invalid_argument("Invalid range weight");
                if(masks_[i]&board.back())weights[i]=0;
                total+=weights[i];cdf[i]=total;
            }
            if(!std::isfinite(total)||total<=0)throw std::invalid_argument("Range has no positive finite mass after board blockers");
            for(auto &p:cdf)p=std::min(p/total,1.0);
            cdf.back()=1.0;
        }
    }
    size_t players() const { return cumulative_.size(); }
    const std::vector<uint64_t>& prefix() const { return cfg_.board_history; }
    template<class NextInt,class NextDouble>
    Deal sample(NextInt next_int,NextDouble next_double,
                const std::function<bool()>& cancel={},int skip_player=-1) const {
        Deal out;sample_into(out,next_int,next_double,cancel,skip_player);return out;
    }
    // Reuse only the caller's output allocation. Draw order, rejection,
    // resource counters and cancellation checks are identical to sample().
    // Workers own separate Deal objects; no mutable state lives in Sampler.
    template<class NextInt,class NextDouble>
    void sample_into(Deal& out,NextInt next_int,NextDouble next_double,
                const std::function<bool()>& cancel={},int skip_player=-1) const {
        if(skip_player < -1||skip_player>=int(players()))throw std::invalid_argument("Invalid skipped player");
        out.used=out.attempts=out.random_calls=0;out.board.fill(0);out.combos.assign(players(),-1);
        auto check=[&](){if(cancel&&cancel())throw Cancelled("Chance sampling cancelled");
            if(out.random_calls>=cfg_.max_random_calls)throw ResourceLimit("Chance random-call budget exhausted");};
        auto integer=[&](int bound){check();auto n=next_int(bound);++out.random_calls;
            if(n<0||n>=bound)throw std::invalid_argument("Invalid integer random callback");return int(n);};
        auto real=[&](){check();double u=next_double();++out.random_calls;
            if(!(u>=0&&u<1))throw std::invalid_argument("Invalid real random callback");return u;};
        bool accepted=false;
        for(uint64_t attempt=1;attempt<=cfg_.max_attempts;++attempt) {
            check();out.attempts=attempt;out.used=cfg_.board_history.back();accepted=true;
            for(size_t player=0;player<players();++player) {
                const auto &cdf=cumulative_[player];if(cdf.empty()||int(player)==skip_player)continue;
                int combo=int(std::lower_bound(cdf.begin(),cdf.end(),real())-cdf.begin());
                if(masks_[combo]&out.used){accepted=false;break;}
                out.combos[player]=combo;out.used|=masks_[combo];
            }
            if(accepted)break;
        }
        if(!accepted)throw ResourceLimit("Joint range rejection-attempt budget exhausted");
        for(size_t player=0;player<players();++player)
            if(cumulative_[player].empty()||int(player)==skip_player)
                for(;;){int combo=integer(1326);if(!(masks_[combo]&out.used)){
                    out.combos[player]=combo;out.used|=masks_[combo];break;}}
        std::copy(cfg_.board_history.begin(),cfg_.board_history.end(),out.board.begin());
        for(size_t street=cfg_.board_history.size();street<4;++street) {
            out.board[street]=out.board[street-1];
            for(int n=0;n<(street==1?3:1);++n)
                for(;;){uint64_t card=1ULL<<integer(52);if(!(card&out.used)){
                    out.used|=card;out.board[street]|=card;break;}}
        }
    }
};
} // namespace hrc_chance
