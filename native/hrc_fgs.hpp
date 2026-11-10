#pragma once
// Independent finite future-game simulation; original software is only a test oracle.
// The caller supplies the user's derived chance-table research cache separately.
#include "hrc_equity.hpp"
#include <chrono>
#include <cstring>
#include <fstream>
#include <list>
#include <map>
#include <memory>
#include <numeric>
#include <string>

namespace hrc_fgs {
using Integers = std::vector<std::int64_t>;
using Values = std::vector<double>;
inline constexpr std::array<int,13> results3{111,113,131,122,123,132,212,221,213,231,311,312,321};
inline constexpr std::array<int,3> results2{11,12,21};

struct Context {
    Integers stacks;
    Values bounties;
    int depth = 0;
    bool skip_sb = false;
    bool operator<(const Context& b) const {
        if (stacks != b.stacks) return stacks < b.stacks;
        if (bounties != b.bounties) return bounties < b.bounties;
        return skip_sb < b.skip_sb; // Cache is already separated by depth.
    }
};
enum class AnteType { Regular, BBAnteFirst, BBBlindFirst };
enum class Straddle { Off, Single, Double, Button };
struct Config {
    hrc_equity::EquityConfig equity;
    std::int64_t big_blind = 100, small_blind = 50, ante = 0;
    AnteType ante_type = AnteType::Regular;
    Straddle straddle = Straddle::Off;
    bool moving_button = false;
    int depth = 1, depth3way = 1, next_level_at = -1;
    std::array<std::int64_t,3> next_level{};
    std::size_t cache_capacity = 5000, max_states = 20000, max_sweeps = 2000000;
    std::size_t terminal_cache_capacity = 65536;
    double max_seconds = 60;
    std::function<bool()> cancel_check;
};
struct Outcome {
    Integers stacks;
    std::vector<std::uint16_t> winner_masks;
    int participants = 1;
    bool tied_award = false;
};
struct Stats { std::size_t states=0, sweeps=0, cache_hits=0, terminal_calls=0, terminal_cache_hits=0; };
struct ResourceLimit : std::runtime_error { using std::runtime_error::runtime_error; };
struct Cancelled : std::runtime_error { using std::runtime_error::runtime_error; };

class ChanceTables {
    Values marginal_, two_, three_;
    static std::array<int,3> permutation(int a,int b,int c) {
        std::array<int,3> indices{0,1,2}, values{a,b,c};
        std::sort(indices.begin(),indices.end(),[&](int i,int j) { return values[i] != values[j] ? values[i] > values[j] : i < j; });
        return indices;
    }
    static std::size_t pair_index(int a,int b) { if(a<b)std::swap(a,b); return (std::size_t(a)*(a+1)/2+b)*4; }
    static std::size_t triple_index(int a,int b,int c) {
        if(a<b)std::swap(a,b);if(b<c)std::swap(b,c);if(a<b)std::swap(a,b);
        return (std::size_t(a)*(a+1)*(a+2)/6+b*(b+1)/2+c)*14;
    }
public:
    ChanceTables(Values marginal,Values two,Values three) : marginal_(std::move(marginal)),two_(std::move(two)),three_(std::move(three)) {
        if(marginal_.size()!=169 || two_.size()!=57460 || three_.size()!=11463270)
            throw std::invalid_argument("FGS chance table dimensions are invalid");
        for(const auto* v:{&marginal_,&two_,&three_}) for(double x:*v)
            if(!std::isfinite(x)) throw std::invalid_argument("Nonfinite FGS cumulative chance weight");
    }
    static std::shared_ptr<const ChanceTables> read(const std::string& path) {
        std::ifstream stream(path,std::ios::binary);
        char magic[8];stream.read(magic,8);
        if(!stream || std::string(magic,8)!="FGSCHN01") throw std::invalid_argument("Invalid FGS chance cache header");
        auto vector=[&](std::size_t count) {
            Values out(count);
            // Explicit little-endian IEEE754 reader, not host-order serialization.
            std::vector<unsigned char> raw(count*8);stream.read(reinterpret_cast<char*>(raw.data()),raw.size());
            if(!stream) throw std::invalid_argument("Truncated FGS chance cache");
            for(std::size_t i=0;i<count;++i) {
                std::uint64_t bits=0;for(int b=0;b<8;++b)bits|=std::uint64_t(raw[i*8+b])<<(8*b);
                std::memcpy(&out[i],&bits,8);
            }
            return out;
        };
        auto marginal=vector(169),two=vector(57460),three=vector(11463270);
        if(stream.peek()!=std::char_traits<char>::eof()) throw std::invalid_argument("Trailing FGS chance cache data");
        return std::make_shared<const ChanceTables>(std::move(marginal),std::move(two),std::move(three));
    }
    double mass(int a) const { return marginal_.at(a); }
    double mass(int a,int b) const { return two_[pair_index(a,b)+3]; }
    double mass(int a,int b,int c) const { return three_[triple_index(a,b,c)+13]; }
    double expected(int a,int b,const double* utility) const {
        auto index=pair_index(a,b);double value=0;
        for(int r=0;r<3;++r)value+=two_[index+(a<b && r ? 3-r : r)]*utility[r];
        return value/two_[index+3];
    }
    double expected(int a,int b,int c,const double* utility) const {
        auto p=permutation(a,b,c);auto index=triple_index(a,b,c);double value=0;
        for(int r=0;r<13;++r) {
            int code=results3[r];std::array<int,3> ranks{code/100,code/10%10,code%10};
            int permuted=ranks[p[0]]*100+ranks[p[1]]*10+ranks[p[2]];
            auto mapped=std::find(results3.begin(),results3.end(),permuted)-results3.begin();
            value+=three_[index+mapped]*utility[r];
        }
        return value/three_[index+13];
    }
};

struct ForcedState { Integers remaining,posted,dead; std::int64_t pool=0; };
inline ForcedState forced_state(const Context& context,const Config& config) {
    int n=int(context.stacks.size());if(n<2||n>10)throw std::invalid_argument("FGS forced bets require 2..10 players");ForcedState state{context.stacks,Integers(n),Integers(n),0};
    auto big=config.big_blind,small=config.small_blind,ante=config.ante;
    if(config.next_level_at>=0 && context.depth>=config.next_level_at) {big=config.next_level[0];small=config.next_level[1];ante=config.next_level[2];}
    auto pay=[&](int i,std::int64_t amount,Integers& destination) {auto value=std::min(state.remaining[i],amount);state.remaining[i]-=value;destination[i]+=value;};
    if(config.ante_type==AnteType::Regular)for(int i=0;i<n;++i)pay(i,ante,state.dead);
    if(config.ante_type==AnteType::BBAnteFirst) {state.pool=std::min(state.remaining[n-1],ante);state.remaining[n-1]-=state.pool;}
    if(!context.skip_sb)pay(n-2,small,state.posted);
    pay(n-1,big,state.posted);
    if(config.ante_type==AnteType::BBBlindFirst) {state.pool=std::min(state.remaining[n-1],ante);state.remaining[n-1]-=state.pool;}
    if(config.straddle==Straddle::Single || config.straddle==Straddle::Double) {
        pay(0,std::max<std::int64_t>(2*big-state.posted[0],0),state.posted);
        if(config.straddle==Straddle::Double)pay(1,std::max<std::int64_t>(4*big-state.posted[1],0),state.posted);
    } else if(config.straddle==Straddle::Button) {
        int button=n==2?0:n-(context.skip_sb?2:3);
        pay(button,std::max<std::int64_t>(2*big-state.posted[button],0),state.posted);
    }
    return state;
}

inline Outcome allin_outcome(const Context& context,const Config& config,const std::vector<int>& participants,const std::vector<int>& ranks) {
    auto state=forced_state(context,config);int n=int(context.stacks.size());
    if(participants.empty() || participants.size()>3 || participants.size()!=ranks.size()) throw std::invalid_argument("FGS expects 1..3 showdown participants");
    Integers contributions(n);std::vector<int> strength(n,100),ordered=participants;
    for(int i=0;i<n;++i)contributions[i]=state.posted[i]+state.dead[i];
    for(std::size_t j=0;j<participants.size();++j) {
        int i=participants[j];if(i<0 || i>=n || strength[i]!=100)throw std::invalid_argument("Invalid FGS participant");
        strength[i]=ranks[j];contributions[i]+=state.remaining[i];state.remaining[i]=0;
    }
    std::sort(ordered.begin(),ordered.end(),[&](int i,int j) {
        if(strength[i]!=strength[j])return strength[i]<strength[j];
        if(contributions[i]!=contributions[j])return contributions[i]<contributions[j];
        return i>j;
    });
    Outcome out{state.remaining,std::vector<std::uint16_t>(n),int(participants.size()),false};
    std::int64_t covered=0;
    for(std::size_t position=0;position<ordered.size();++position) {
        int first=ordered[position];auto cap=contributions[first];if(position && cap<=covered)continue;
        std::vector<int>winners;std::uint16_t mask=0;
        for(std::size_t j=position;j<ordered.size() && strength[ordered[j]]==strength[first];++j) {winners.push_back(ordered[j]);mask|=std::uint16_t(1u<<ordered[j]);}
        out.tied_award|=winners.size()>1;std::int64_t pot=position==0?state.pool:0;
        for(int i=0;i<n;++i) {
            if(position && contributions[i]<=covered)continue;
            pot+=std::min(contributions[i]-covered,cap-covered);
            if(state.remaining[i]==0 && contributions[i]<=cap && strength[i]>strength[first])out.winner_masks[i]=mask;
        }
        for(int i:winners)out.stacks[i]+=pot/std::int64_t(winners.size());
        out.stacks[first]+=pot%std::int64_t(winners.size());covered=cap;
    }
    for(int i=0;i<n;++i) {out.stacks[i]+=std::max<std::int64_t>(contributions[i]-covered,0);if(out.stacks[i])out.winner_masks[i]=0;}
    if(std::accumulate(out.stacks.begin(),out.stacks.end(),std::int64_t(0))!=std::accumulate(context.stacks.begin(),context.stacks.end(),std::int64_t(0)))throw std::runtime_error("FGS chip conservation failure");
    return out;
}

inline std::pair<Context,std::vector<int>> next_context(const Context& context,const Outcome& outcome,const Config& config,const Values& heads) {
    std::vector<int> alive;int n=int(outcome.stacks.size());for(int i=0;i<n;++i)if(outcome.stacks[i])alive.push_back(i);
    bool skip=n<2?context.skip_sb:false;
    if(n>1) {
        int rotations=1;
        if(config.moving_button && n>2) {rotations+=int(outcome.stacks[n-1]==0)+int(outcome.stacks[n-2]==0);if(alive.size()==2)++rotations;}
        else skip=outcome.stacks.back()==0 && alive.size()>2;
        std::rotate(alive.begin(),alive.begin()+rotations%alive.size(),alive.end());
    }
    Context child;child.depth=context.depth+1;child.skip_sb=skip;
    for(int i:alive) {child.stacks.push_back(outcome.stacks[i]);if(config.equity.bounty_mode!=hrc_equity::BountyMode::None)child.bounties.push_back(heads[i]);}
    return {std::move(child),std::move(alive)};
}

struct Utilities {
    int n;
    std::array<Values,10> single;
    std::array<Values,100> pair;
    std::array<Values,1000> triple;
    explicit Utilities(int players):n(players){}
};

class ThresholdSolver {
    const ChanceTables& tables_;
    const Utilities& utilities_;
    std::array<int,10> push_{};
    std::array<int,100> call_{};
    std::array<int,1000> over_{};
    std::array<float,10> smooth_push_{};
    std::array<float,100> smooth_call_{};
    std::array<float,1000> smooth_over_{};
    std::array<bool,100> lock_call_{};
    std::array<bool,1000> lock_over_{};
    float mass_=1;
    int iteration_=0,n_;
    double value(int player,int count,int a,int b,int next,bool has_fallback=false,double fallback=0) const {
        if((!count && next>=n_-1) || next>=n_) {
            if(count<2)return utilities_.single[count?a:n_-1][player];
            return tables_.expected(push_[a],call_[a*10+b],utilities_.pair[a*10+b].data()+player*3);
        }
        double chance;
        if(!count)chance=tables_.mass(push_[next]);
        else if(count==1)chance=tables_.mass(push_[a],call_[a*10+next])/tables_.mass(push_[a]);
        else chance=tables_.mass(push_[a],call_[a*10+b],over_[a*100+b*10+next])/tables_.mass(push_[a],call_[a*10+b]);
        double folded=has_fallback?fallback:value(player,count,a,b,next+1);
        if(!(chance>0))return folded;
        double active;
        if(!count)active=value(player,1,next,0,next+1);
        else if(count==1)active=value(player,2,a,next,next+1);
        else active=tables_.expected(push_[a],call_[a*10+b],over_[a*100+b*10+next],utilities_.triple[a*100+b*10+next].data()+player*13);
        return active*chance+folded*(1-chance);
    }
    void update(int count,int a,int b,int c,float weight,float complement) {
        int& threshold=count==1?push_[a]:count==2?call_[a*10+b]:over_[a*100+b*10+c];
        float& smooth=count==1?smooth_push_[a]:count==2?smooth_call_[a*10+b]:smooth_over_[a*100+b*10+c];
        bool locked=count==2?lock_call_[a*10+b]:count==3?lock_over_[a*100+b*10+c]:false;
        int original=threshold,best=original;
        if(!locked) {
            int player=count==1?a:count==2?b:c;
            int width=std::max(169/(iteration_+1),count==1?14:count==2?8:3);
            double fallback=value(player,count-1,a,b,player+1),maximum=std::numeric_limits<float>::denorm_min();
            for(int candidate=original;candidate>=std::max((count==3?original:best)-width,0);--candidate) {
                threshold=candidate;double v=value(player,count-1,a,b,player,true,fallback);
                if(v>maximum){maximum=v;best=candidate;}
            }
            for(int candidate=original+1;candidate<std::min((count==3?original:best)+width,169);++candidate) {
                threshold=candidate;double v=value(player,count-1,a,b,player,true,fallback);
                if(v>maximum){maximum=v;best=candidate;}
            }
            threshold=original;if(count==1)best=std::max(best,1);
        }
        smooth=float(best)*weight+smooth*complement;
    }
public:
    ThresholdSolver(const ChanceTables& tables,const Utilities& utilities,const ForcedState& state)
        :tables_(tables),utilities_(utilities),n_(utilities.n) {
        push_.fill(50);call_.fill(20);over_.fill(5);push_[n_-1]=168;
        auto call=[&](int a,int b,int value){call_[a*10+b]=value;lock_call_[a*10+b]=true;};
        auto over=[&](int a,int b,int c,int value){over_[a*100+b*10+c]=value;lock_over_[a*100+b*10+c]=true;};
        int small=n_-2,big=n_-1;
        if(!state.remaining[small])for(int a=0;a<small;++a) {
            call(a,small,168);
            for(int b=a+1;b<small;++b){over(a,b,small,168);for(int c=b+1;c<small;++c)over(a,b,c,0);}
        }
        for(int a=0;a<big;++a) {
            if(state.remaining[big] && state.posted[a]+state.remaining[a]>state.posted[big])continue;
            call(a,big,168);
            for(int b=a+1;b<big;++b) {
                if(state.remaining[big] && state.posted[b]+state.remaining[b]>state.posted[big])continue;
                over(a,b,big,168);if(!state.remaining[big])for(int c=b+1;c<big;++c)over(a,b,c,0);
            }
        }
        if(!state.remaining[small] && !state.remaining[big])for(int a=0;a<small-1;++a)for(int b=a+1;b<small;++b)call(a,b,0);
        std::copy(push_.begin(),push_.end(),smooth_push_.begin());std::copy(call_.begin(),call_.end(),smooth_call_.begin());std::copy(over_.begin(),over_.end(),smooth_over_.begin());
    }
    void sweep() {
        mass_=float(double(mass_)+double(0.11f)*std::log(double(iteration_+10)));
        float weight=1.0f/mass_,complement=1.0f-weight;
        for(int a=0;a<n_-1;++a)update(1,a,0,0,weight,complement);
        for(int a=0;a<n_;++a)for(int b=a+1;b<n_;++b)update(2,a,b,0,weight,complement);
        for(int a=0;a<n_;++a)for(int b=a+1;b<n_;++b)for(int c=b+1;c<n_;++c)update(3,a,b,c,weight,complement);
        for(int a=0;a<n_;++a) {
            push_[a]=int(std::floor(double(smooth_push_[a])+0.5));
            for(int b=a+1;b<n_;++b) {
                call_[a*10+b]=int(std::floor(double(smooth_call_[a*10+b])+0.5));
                for(int c=b+1;c<n_;++c)over_[a*100+b*10+c]=int(std::floor(double(smooth_over_[a*100+b*10+c])+0.5));
            }
        }
        ++iteration_;
    }
    Values equities() const {Values output(n_);for(int i=0;i<n_;++i)output[i]=value(i,0,0,0,0);return output;}
    const auto& push_thresholds() const {return push_;}
    const auto& call_thresholds() const {return call_;}
    const auto& overcall_thresholds() const {return over_;}
};

class Calculator {
    Config config_;
    std::shared_ptr<const ChanceTables> tables_;
    struct Cache {std::map<Context,std::pair<Values,std::list<Context>::iterator>> entries;std::list<Context> recent;};
    std::vector<Cache> caches_;
    struct TerminalKey {
        Context context;Outcome outcome;
        bool operator<(const TerminalKey& b) const {
            if(context.depth!=b.context.depth)return context.depth<b.context.depth;
            if(context<b.context)return true;if(b.context<context)return false;
            if(outcome.stacks!=b.outcome.stacks)return outcome.stacks<b.outcome.stacks;
            if(outcome.winner_masks!=b.outcome.winner_masks)return outcome.winner_masks<b.outcome.winner_masks;
            if(outcome.participants!=b.outcome.participants)return outcome.participants<b.outcome.participants;
            return outcome.tied_award<b.outcome.tied_award;
        }
    };
    std::map<TerminalKey,std::pair<Values,std::list<TerminalKey>::iterator>> terminal_cache_;
    std::list<TerminalKey> terminal_recent_;
    Stats stats_{};
    std::chrono::steady_clock::time_point work_started_{};
    double work_seconds_=0;
    std::size_t active_calls_=0;
    struct WorkScope {
        Calculator& owner;
        explicit WorkScope(Calculator& c):owner(c){if(owner.active_calls_++==0)owner.work_started_=std::chrono::steady_clock::now();}
        ~WorkScope(){if(--owner.active_calls_==0)owner.work_seconds_+=std::chrono::duration<double>(std::chrono::steady_clock::now()-owner.work_started_).count();}
    };
    void checkpoint(bool sweep=false) {
        if(config_.cancel_check && config_.cancel_check())throw Cancelled("FGS calculation cancelled");
        if(sweep)++stats_.sweeps;
        double elapsed=work_seconds();
        if(stats_.states>config_.max_states || stats_.sweeps>config_.max_sweeps || elapsed>config_.max_seconds)
            throw ResourceLimit("FGS resource budget exhausted; result is incomplete");
    }
    void validate(const Context& context) const {
        if(context.stacks.empty() || context.stacks.size()>10 || context.depth<0)throw std::invalid_argument("Invalid FGS context size/depth");
        long double total=0;for(auto s:context.stacks){if(s<=0)throw std::invalid_argument("FGS stacks must be positive");total+=s;}
        if(total>std::numeric_limits<std::int64_t>::max())throw std::invalid_argument("FGS chip total overflow");
        if(config_.equity.bounty_mode!=hrc_equity::BountyMode::None) {
            if(context.bounties.size()!=context.stacks.size())throw std::invalid_argument("Missing FGS survivor bounties");
            for(double b:context.bounties)if(!std::isfinite(b)||b<0)throw std::invalid_argument("Invalid FGS bounty");
        }
    }
    std::unique_ptr<hrc_equity::Calculator> ordinary(const Context& context) const {
        auto c=config_.equity;c.initial_stacks=context.stacks;c.bounties=context.bounties;c.cache_capacity=0;
        return std::make_unique<hrc_equity::Calculator>(std::move(c));
    }
    Values terminal_impl(const Context& context,const Outcome& outcome,hrc_equity::Calculator& base) {
        ++stats_.terminal_calls;checkpoint();
        if(outcome.stacks.size()!=context.stacks.size() || outcome.winner_masks.size()!=context.stacks.size())throw std::invalid_argument("FGS outcome dimension mismatch");
        if(outcome.participants<1||std::size_t(outcome.participants)>context.stacks.size())throw std::invalid_argument("Invalid FGS terminal participant count");
        long double before=0,after=0;for(auto s:context.stacks)before+=s;for(auto s:outcome.stacks)after+=s;
        if(before!=after)throw std::invalid_argument("FGS terminal chip total differs from initial context");
        hrc_equity::Chips chips{};hrc_equity::WinnerMasks masks{};
        std::copy(outcome.stacks.begin(),outcome.stacks.end(),chips.begin());std::copy(outcome.winner_masks.begin(),outcome.winner_masks.end(),masks.begin());
        const auto calculated=base.compute_terminal(chips,masks);
        Values values(calculated.total.begin(),calculated.total.begin()+context.stacks.size());
        if(context.depth<config_.depth && !outcome.tied_award && (context.depth<config_.depth3way || outcome.participants<3)) {
            Values heads(calculated.remaining_bounties.begin(),calculated.remaining_bounties.begin()+context.stacks.size());
            auto child=next_context(context,outcome,config_,heads);auto continuation=equities(child.first);
            for(std::size_t i=0;i<values.size();++i)values[i]=calculated.immediate_prizes[i]+calculated.immediate_bounties[i];
            for(std::size_t j=0;j<continuation.size();++j)values[child.second[j]]+=continuation[j];
        }
        return values;
    }
public:
    Calculator(Config config,std::shared_ptr<const ChanceTables> tables):config_(std::move(config)),tables_(std::move(tables)) {
        if(!tables_ || config_.equity.mode!=hrc_equity::Mode::ICM)throw std::invalid_argument("FGS requires ICM (optional KO/PKO) and chance tables");
        if(config_.depth<0||config_.depth>10||config_.depth3way<0||config_.depth3way>10)throw std::invalid_argument("FGS depths require 0..10");
        if(int(config_.ante_type)<0||int(config_.ante_type)>2||int(config_.straddle)<0||int(config_.straddle)>3)throw std::invalid_argument("Invalid FGS forced-bet enum");
        if(config_.big_blind<=0||config_.small_blind<0||config_.ante<0||config_.big_blind>std::numeric_limits<std::int64_t>::max()/4)throw std::invalid_argument("Invalid FGS blinds");
        hrc_equity::validate_payouts(config_.equity.payouts);
        if(config_.equity.payouts.empty())throw std::invalid_argument("FGS requires payouts");
        if(config_.next_level_at>=0 && (config_.next_level[0]<=0||config_.next_level[1]<0||config_.next_level[2]<0||config_.next_level[0]>std::numeric_limits<std::int64_t>::max()/4))throw std::invalid_argument("Invalid FGS future blinds");
        if(config_.max_states==0||config_.max_sweeps==0||!(config_.max_seconds>0)||!std::isfinite(config_.max_seconds))throw std::invalid_argument("Invalid FGS resource budget");
        caches_.resize(config_.depth+1);
    }
    Calculator(const Calculator&)=delete;
    Calculator& operator=(const Calculator&)=delete;
    const Stats& stats() const {return stats_;}
    std::unique_ptr<Calculator> fork() const {return std::make_unique<Calculator>(config_,tables_);}
    std::uint64_t cache_memory_bound() const {
        return std::uint64_t(config_.depth+1)*config_.cache_capacity*1024+std::uint64_t(config_.terminal_cache_capacity)*2048;
    }
    double work_seconds() const {return work_seconds_+(active_calls_?std::chrono::duration<double>(std::chrono::steady_clock::now()-work_started_).count():0);}
    void reset_budget() {if(active_calls_)throw std::logic_error("Cannot reset active FGS budget");stats_={};work_seconds_=0;}
    Values terminal(const Context& context,const Outcome& outcome) {
        validate(context);TerminalKey key{context,outcome};auto found=terminal_cache_.find(key);
        if(found!=terminal_cache_.end()){++stats_.terminal_cache_hits;terminal_recent_.splice(terminal_recent_.end(),terminal_recent_,found->second.second);return found->second.first;}
        WorkScope work(*this);auto base=ordinary(context);auto value=terminal_impl(context,outcome,*base);
        if(config_.terminal_cache_capacity) {
            terminal_recent_.push_back(key);terminal_cache_.emplace(key,std::make_pair(value,std::prev(terminal_recent_.end())));
            if(terminal_cache_.size()>config_.terminal_cache_capacity){terminal_cache_.erase(terminal_recent_.front());terminal_recent_.pop_front();}
        }
        return value;
    }
    Values equities(const Context& context) {
        validate(context);
        if(context.stacks.size()==1) {
            double value=config_.equity.payouts.empty()?0:config_.equity.payouts[0];
            if(config_.equity.bounty_mode!=hrc_equity::BountyMode::None)value+=context.bounties[0];
            return {value};
        }
        if(context.depth>config_.depth){WorkScope work(*this);checkpoint();auto base=ordinary(context);return Values(base->baseline().total.begin(),base->baseline().total.begin()+context.stacks.size());}
        auto& cache=caches_[context.depth];auto found=cache.entries.find(context);
        if(found!=cache.entries.end()) {++stats_.cache_hits;cache.recent.splice(cache.recent.end(),cache.recent,found->second.second);return found->second.first;}
        WorkScope work(*this);checkpoint();
        ++stats_.states;checkpoint();
        auto base=ordinary(context);
        int n=int(context.stacks.size());Utilities utilities(n);
        auto add=[&](const std::vector<int>& participants,Values& output) {
            int count=int(participants.size()),outcomes=count==1?1:count==2?3:13;output.resize(n*outcomes);
            for(int result=0;result<outcomes;++result) {
                int code=count==1?1:count==2?results2[result]:results3[result];std::vector<int> ranks(count);
                for(int p=count-1;p>=0;--p){ranks[p]=code%10;code/=10;}
                auto terminal=allin_outcome(context,config_,participants,ranks);auto values=terminal_impl(context,terminal,*base);
                for(int p=0;p<n;++p)output[p*outcomes+result]=values[p];
            }
        };
        for(int a=0;a<n;++a)add({a},utilities.single[a]);
        for(int a=0;a<n;++a)for(int b=a+1;b<n;++b)add({a,b},utilities.pair[a*10+b]);
        for(int a=0;a<n;++a)for(int b=a+1;b<n;++b)for(int c=b+1;c<n;++c)add({a,b,c},utilities.triple[a*100+b*10+c]);
        ThresholdSolver solver(*tables_,utilities,forced_state(context,config_));
        for(int iteration=0;iteration<(context.depth<=1?200:50);++iteration){checkpoint(true);solver.sweep();}
        Values values=solver.equities();double sum=0;for(double v:values)sum+=std::abs(v);double tolerance=std::max(sum*1e-7,1e-10);
        for(double& v:values){if(v<0&&v>=-tolerance)v=0;if(!std::isfinite(v)||v<0)throw std::runtime_error("Invalid FGS equity estimate");}
        if(config_.cache_capacity) {
            cache.recent.push_back(context);cache.entries.emplace(context,std::make_pair(values,std::prev(cache.recent.end())));
            if(cache.entries.size()>config_.cache_capacity){cache.entries.erase(cache.recent.front());cache.recent.pop_front();}
        }
        return values;
    }
};
} // namespace hrc_fgs
