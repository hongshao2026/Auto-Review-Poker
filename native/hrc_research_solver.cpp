// Independent implementation of the audited HRC v3/v4 numerical operations.
// Input contains topology and independently replayed chip states, never policies.
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include "hrc_node_mutex.hpp"
#include "hrc_unlocked_read.hpp"
#include <stdexcept>
#include <string>
#include <vector>
#include "hrc_cards.hpp"
#include "hrc_equity.hpp"
#include "hrc_mtt.hpp"
#include "hrc_policy.hpp"
#include "hrc_ci.hpp"
#include "hrc_fgs.hpp"
#include "hrc_settlement.hpp"
#include "hrc_chance.hpp"
#include "hrc_dynamic.hpp"
#include "hrc_digest.hpp"
#include "hrc_terminal_table.hpp"

// Process-local execution-speed throttling override, not a priority or
// affinity change. Resolve dynamically so unsupported systems keep working.
// Microsoft documents {Version=1, ControlMask=1, StateMask=0} as HighQoS.
static bool configure_native_high_qos(bool requested) noexcept {
    if(!requested)return false;
#ifdef _WIN32
    HMODULE module=GetModuleHandleW(L"kernel32.dll");
    if(!module)return false;
    using SetProcessInformationFn=BOOL (WINAPI *)(HANDLE,int,void*,DWORD);
    auto set_information=reinterpret_cast<SetProcessInformationFn>(GetProcAddress(module,"SetProcessInformation"));
    if(!set_information)return false;
    struct PowerState {DWORD version,control_mask,state_mask;};
    static_assert(sizeof(PowerState)==3*sizeof(DWORD),"Process power state ABI mismatch");
    PowerState state{1,1,0};
    constexpr int process_power_throttling=4;
    return set_information(GetCurrentProcess(),process_power_throttling,&state,sizeof(state))!=FALSE;
#else
    return false;
#endif
}

namespace fs=std::filesystem;
constexpr int MAXP=10, MAXA=16;
using Values=std::array<double,MAXP>;
struct NativeResourceLimit:std::runtime_error{using std::runtime_error::runtime_error;};

// Full checkpoints can be several GiB. Space them by wall time and measured
// write cost, rather than stopping all workers every million samples. The
// 20x cost interval targets <5% periodic I/O, with 30..300s between saves.
// Final/cancel saves and safe FGS rollback boundaries are independent of this.
struct CheckpointSchedule {
    using Clock=std::chrono::steady_clock;
    Clock::time_point last;
    double interval_seconds;
    static double interval(double write_seconds){return std::clamp(20*write_seconds,30.,300.);}
    CheckpointSchedule(Clock::time_point now,double cost):last(now),interval_seconds(interval(cost)){}
    bool due(Clock::time_point now)const{return std::chrono::duration<double>(now-last).count()>=interval_seconds;}
    void saved(Clock::time_point now,double cost){last=now;interval_seconds=interval(cost);}
};

struct Random {
    uint64_t s[4]{};
    bool scripted=false; int gate=1;int32_t scripted_integer=0;
    uint64_t bounded_calls=0, double_calls=0, int_calls=0;
    static uint64_t mix(uint64_t& x) { uint64_t z=(x+=0x9e3779b97f4a7c15ULL); z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL; z=(z^(z>>27))*0x94d049bb133111ebULL; return z^(z>>31); }
    explicit Random(uint64_t seed=42) {for(auto& v:s)v=mix(seed);}
    static uint64_t rot(uint64_t x,int k){return (x<<k)|(x>>(64-k));}
    uint64_t next() {uint64_t r=rot(s[1]*5,7)*9,t=s[1]<<17; s[2]^=s[0];s[3]^=s[1];s[1]^=s[2];s[0]^=s[3];s[2]^=t;s[3]=rot(s[3],45);return r;}
    uint32_t bound(uint32_t n) {++bounded_calls; if(scripted)return std::min(uint32_t(gate),n-1); uint64_t v,limit=(uint64_t(0)-uint64_t(n))%n;do{v=next();}while(v<limit);return uint32_t(v%n);}
    int32_t integer(){++int_calls;return scripted?scripted_integer:int32_t(next()>>32);}
    double unit(){++double_calls;return scripted?.75:double(next()>>11)*0x1.0p-53;}
};

// Exact mv positive-regret and CHECK-special branches, including tie fallback.
void normalize(const double* r,int k,bool special,double* p) {
    double total=0;
    for(int a=0;a<k;++a){p[a]=(special&&a==0)?0:std::max(r[a],0.0);total+=p[a];}
    if(special&&k==2){p[0]=0;p[1]=1;return;}
    if(total>0){for(int a=0;a<k;++a)p[a]/=total;return;}
    if(!special){for(int a=0;a<k;++a)p[a]=1.0/k;return;}
    if(k==3&&r[1]==r[2]){p[1]=p[2]=.5;return;}
    int best=1;for(int a=2;a<k;++a)if(r[a]>r[best])best=a;p[best]=1;
}

// Keep immutable traversal metadata separate from the writer-only counters.
struct alignas(64) Node {
    // Immutable during a trainer: metadata and vector/control pointers. The
    // pointed-to raw cells remain synchronized by the existing operations.
    int actor=-1,street=0,buckets=0,first=0,k=0,special=0,terminal=-1;
    uint16_t constant_scalar_mask=0;
    int constant_scalar_terminal=-1;
    std::vector<double> raw;
    std::vector<double> shared_sums;
    std::vector<uint64_t> visits;
    int store_format=0;
    bool unlocked_read=false; // Published only after all worker caches exist.
    std::unique_ptr<hrc_policy::BucketLocks> locks;
    std::unique_ptr<hrc_policy::FrequencyStore> frequency;
    // Writers should not invalidate the cache lines holding read-only node
    // metadata. Keep the original field names, defaults and numeric accesses.
    alignas(64) uint64_t updates=0;
    mutable double exploration_key=-1,exploration_cached=0;
    double divisor_key=-1;int divisor_cached=1;
    int base_format()const{return store_format?store_format:street==0?23:25;}
    int format()const{return !k?0:frequency?63:base_format();}
    const std::vector<double>& storage()const{return frequency?frequency->raw:raw;}
    std::vector<double>& storage(){return frequency?frequency->raw:raw;}
    double counter()const{return storage().empty()?0:storage()[0];}
    double exploration_probability()const{
        double c=counter();if(c!=exploration_key){exploration_key=c;exploration_cached=1/std::sqrt(c+10000);}return exploration_cached;
    }
    int refresh_divisor(double t){if(t!=divisor_key){divisor_key=t;divisor_cached=int(std::floor(std::sqrt(t)));}return divisor_cached;}
    size_t regret(int h)const{int f=base_format();return f==23?1+size_t(2*k+1)*h:f==25?1+size_t(h+1)*k:1+k+size_t(f==27?2*k:2*k+1)*h;}
    size_t average(int h)const{return regret(h)+k+(base_format()==27?0:1);}
    void init(){if(k){int f=base_format();raw.assign(f==23?1+size_t(2*k+1)*buckets:f==25?1+(size_t(buckets)+1)*k:1+k+size_t(f==27?2*k:2*k+1)*buckets,0);if(f==31)shared_sums.assign(k,0);visits.assign(buckets,0);}}
    void strategy(int h,double* out)const{
        if(frequency)frequency->strategy_into(h,out,special>0);
        else if(locks&&locks->active())locks->compose_into(raw.data()+regret(h),h,true,out,special>0);
        else normalize(raw.data()+regret(h),k,special>0,out);
    }
    bool can_unlock_read()const{return hrc_unlocked_read::supported&&k&&(base_format()==23||base_format()==25)&&!frequency&&!(locks&&locks->active());}
    void strategy_atomic(int h,double* out)const{
        const size_t offset=regret(h);const double* source=raw.data()+offset;
        if(special==0&&k==2){
            out[0]=std::max(hrc_unlocked_read::load(source),0.0);
            out[1]=std::max(hrc_unlocked_read::load(source+1),0.0);
            double total=0;total+=out[0];total+=out[1];
            if(total>0){
                if(std::isfinite(total)){
                    if(out[0]==0){out[1]=1;return;}
                    if(out[1]==0){out[0]=1;return;}
                }
                out[0]/=total;out[1]/=total;
            }
            else{out[0]=.5;out[1]=.5;}
            return;
        }
        if(special==0&&k==3){
            out[0]=std::max(hrc_unlocked_read::load(source),0.0);
            out[1]=std::max(hrc_unlocked_read::load(source+1),0.0);
            out[2]=std::max(hrc_unlocked_read::load(source+2),0.0);
            double total=0;total+=out[0];total+=out[1];total+=out[2];
            if(total>0){out[0]/=total;out[1]/=total;out[2]/=total;}
            else{out[0]=1./3;out[1]=1./3;out[2]=1./3;}
            return;
        }
        // Special fallback reads signed regrets more than once. Preserve the
        // original single atomic snapshot, not new loads during tie/best tests.
        double r[MAXA];
        for(int a=0;a<k;++a)r[a]=hrc_unlocked_read::load(source+a);
        normalize(r,k,special>0,out);
    }
    // Called with the same whole-node writer mutex as the original update.
    // Only R and raw[0] have concurrent readers. A/D/visits/update adders remain
    // writer-only; all numerical operations and RNG calls retain their order.
    void update_atomic(Random& rng,int h,const double* p,const double* q,double w,double z){
        if(w<=0)return;
        double value=0;for(int a=0;a<k;++a)if(p[a]>0)value+=p[a]*q[a];
        ++updates;++visits[h];double t=hrc_unlocked_read::load(raw.data())+1;
        const int f=base_format();
        if(f!=25){int d=refresh_divisor(t);if(rng.integer()%d==0){t=double(updates);hrc_unlocked_read::store(raw.data(),t);}}
        else hrc_unlocked_read::store(raw.data(),t);
        const size_t r=regret(h);
        for(int a=0;a<k;++a){double previous=hrc_unlocked_read::load(raw.data()+r+a);hrc_unlocked_read::store(raw.data()+r+a,previous+t*w*(q[a]-value));}
        if(f!=25){size_t av=average(h);for(int a=0;a<k;++a)raw[av+a]+=t*p[a];raw[r+k]+=t*w;}
        if(f!=23&&z>0)for(int a=0;a<k;++a)raw[1+a]+=t*z*p[a];
    }
    std::vector<double> display(int h)const{
        if(frequency)return frequency->display(h);
        const double* base=raw.data()+(base_format()!=25?average(h):regret(h));
        if(locks&&locks->active())return locks->compose(base,h,false);
        return hrc_policy::positive_normalize(base,k);
    }
    // Same display normalization, writing into the caller's existing policy
    // row. Avoid one heap allocation per bucket during full-tree CI snapshots.
    void display_into(int h,double* out)const{
        if(frequency){const auto p=frequency->display(h);std::copy(p.begin(),p.end(),out);return;}
        const double* base=raw.data()+(base_format()!=25?average(h):regret(h));
        if(locks&&locks->active()){locks->compose_into(base,h,false,out);return;}
        double sum=0;for(int a=0;a<k;++a)sum+=(out[a]=std::max(0.0,base[a]));
        if(sum>0)for(int a=0;a<k;++a)out[a]/=sum;
        else std::fill(out,out+k,1.0/k);
    }
    void flush(){if(frequency)frequency->flush();else if(k&&base_format()!=25){raw[0]=double(updates);if(base_format()==31)std::copy(shared_sums.begin(),shared_sums.end(),raw.begin()+1);}}
    void reset(bool r,bool a){
        if(!k)return;
        if(frequency){frequency->reset(r,a);updates=frequency->updates;}
        else{
            int f=base_format();
            if(a){if(f!=25)for(int h=0;h<buckets;++h)for(int i=0;i<k;++i)raw[average(h)+i]*=1e-20;
                if(f!=23)for(int i=0;i<k;++i)raw[1+i]*=1e-20;
                if(f==31){updates=uint64_t(std::floor(raw[0]+.5));std::copy(raw.begin()+1,raw.begin()+1+k,shared_sums.begin());}}
            if(r){for(int h=0;h<buckets;++h)for(int i=0;i<k+int(f==23||f==31);++i)raw[regret(h)+i]*=1e-20;raw[0]=0;updates=0;if(f==31)std::copy(raw.begin()+1,raw.begin()+1+k,shared_sums.begin());}
        }
        if(r)std::fill(visits.begin(),visits.end(),0);
    }
    void update(Random& rng,int h,const double* p,const double* q,double w,double z){
        if(w<=0)return;
        if(unlocked_read){update_atomic(rng,h,p,q,w,z);return;}
        if(frequency){frequency->update(h,p,q,w,z,[&](double x){return rng.integer()%int(std::floor(std::sqrt(x)))==0;});updates=frequency->updates;++visits[h];return;}
        double value=0;for(int a=0;a<k;++a)if(p[a]>0)value+=p[a]*q[a];
        ++updates;++visits[h];
        double t=raw[0]+1;
        int f=base_format();
        if(f!=25){int d=refresh_divisor(t);if(rng.integer()%d==0){t=double(updates);raw[0]=t;}}
        else raw[0]=t;
        size_t r=regret(h);for(int a=0;a<k;++a)raw[r+a]+=t*w*(q[a]-value);
        if(f!=25){size_t av=average(h);for(int a=0;a<k;++a)raw[av+a]+=t*p[a];if(f==23||f==31)raw[r+k]+=t*w;}
        if(f!=23&&z>0){for(int a=0;a<k;++a){if(f==31)shared_sums[a]+=t*z*p[a];else raw[1+a]+=t*z*p[a];}}
    }
};
struct Pot {double amount;uint32_t eligible;uint32_t contributors=0;};
struct Terminal {Values base{},value{},paid{},remaining{};std::vector<Pot> pots;uint64_t cached_deal=UINT64_MAX;bool synthetic=false,card_independent=false;int participants=1,street=0,raise_count=0;uint16_t folded=0;int64_t dead_money=0;};

template<class T>T read(std::istream& in){T x{};in.read(reinterpret_cast<char*>(&x),sizeof(x));if(!in)throw std::runtime_error("Truncated input");return x;}
template<class T>void write(std::ostream& out,const T& x){out.write(reinterpret_cast<const char*>(&x),sizeof(x));}
template<class T>void read_array(std::istream& in,T* x,size_t n){in.read(reinterpret_cast<char*>(x),sizeof(T)*n);if(!in)throw std::runtime_error("Truncated array");}
template<class T>void write_array(std::ostream& out,const T* x,size_t n){out.write(reinterpret_cast<const char*>(x),sizeof(T)*n);}
std::string read_string(std::istream& in){auto n=read<uint32_t>(in);if(n>32768)throw std::runtime_error("Input string limit");std::string s(n,'\0');read_array(in,s.data(),n);return s;}

struct Tree {
    int players=0,root=0;uint64_t identity=0;double chip_scale=1;
    Values initial{}; std::vector<Node> nodes;std::vector<int> children;std::vector<Terminal> terms;
    std::shared_ptr<const hrc_terminal_table::Tables> terminal_tables;
    std::unique_ptr<hrc_equity::Calculator> equity;
    hrc_equity::EquityConfig equity_config;
    std::unique_ptr<hrc_fgs::Calculator> fgs;
    hrc_fgs::Context fgs_context;
    hrc_fgs::Values fgs_baseline;
    bool track_ci=false,policy_extension=false,raked=false;
    bool constant_scalar_shortcuts=false;
    uint64_t constant_scalar_nodes=0;
    hrc_settlement::RakeConfig rake;
    std::unique_ptr<hrc_chance::Sampler> chance;
    std::array<std::unique_ptr<hrc_dynamic::Table>,4> dynamic;
    std::function<bool()> chance_cancel;
    uint64_t estimated_memory=0,max_memory=uint64_t(1)<<30;
    void reserve_budget(uint64_t bytes){if(bytes>max_memory-estimated_memory)throw NativeResourceLimit("Native memory budget exceeded before allocation");estimated_memory+=bytes;}
    void prepare_constant_scalars(bool enabled){
        // Only chip utility: a folded player's monetary equity can still change
        // when other players exchange chips. Keep ICM/MTT/bounties/rake/FGS intact.
        constant_scalar_shortcuts=false;constant_scalar_nodes=0;
        for(auto& n:nodes){n.constant_scalar_mask=0;n.constant_scalar_terminal=-1;}
        if(!enabled||equity||raked||fgs)return;
        struct Frame {int id,next;};
        reserve_budget(nodes.size()*(sizeof(Frame)+sizeof(uint8_t)));
        std::vector<uint8_t> state(nodes.size(),0);std::vector<Frame> stack;stack.reserve(nodes.size());
        // Explicit postorder supports imported/reordered trees and shared child
        // nodes without assuming that node IDs follow traversal order.
        for(size_t start=0;start<nodes.size();++start){if(state[start])continue;
            stack.push_back({int(start),0});state[start]=1;
            while(!stack.empty()){auto& frame=stack.back();auto& n=nodes[frame.id];
                if(frame.next<n.k){int child=children[n.first+frame.next++];
                    if(state[child]==1)throw std::runtime_error("Cycle in constant scalar topology");
                    if(!state[child]){state[child]=1;stack.push_back({child,0});}continue;
                }
                if(!n.k){n.constant_scalar_terminal=n.terminal;
                    if(!terms[n.terminal].synthetic){n.constant_scalar_mask=uint16_t((1u<<players)-1);
                        for(const auto& pot:terms[n.terminal].pots)n.constant_scalar_mask&=uint16_t(~pot.eligible);}
                }else{n.constant_scalar_mask=uint16_t(((1u<<players)-1)&~(1u<<n.actor));
                    n.constant_scalar_terminal=nodes[children[n.first]].constant_scalar_terminal;
                    for(int a=0;a<n.k;++a){const auto& child=nodes[children[n.first+a]];n.constant_scalar_mask&=child.constant_scalar_mask;
                        uint32_t pending=n.constant_scalar_mask;
                        while(pending){int p=hrc_cards::lowbit(pending);pending&=pending-1;
                            if(terms[child.constant_scalar_terminal].base[p]!=terms[n.constant_scalar_terminal].base[p])n.constant_scalar_mask&=uint16_t(~(1u<<p));}
                    }
                    if(n.constant_scalar_mask)++constant_scalar_nodes;
                }
                state[frame.id]=2;stack.pop_back();
            }
        }
        constant_scalar_shortcuts=constant_scalar_nodes>0;
    }
    void load(const std::string& path,const fs::path& resource_dir={},std::function<bool()> cancel_check={},uint64_t memory_budget=uint64_t(1)<<30){
        max_memory=memory_budget;if(max_memory<(uint64_t(1)<<20)||max_memory>(uint64_t(8)<<30))throw std::runtime_error("Native memory budget must be between 1 MiB and 8 GiB");
        std::ifstream in(path,std::ios::binary);char magic[8];read_array(in,magic,8);
        bool features=!std::memcmp(magic,"HRTREE04",8);
        bool extended=features||!std::memcmp(magic,"HRTREE03",8),monetary=!std::memcmp(magic,"HRTREE02",8);
        if(!extended&&!monetary&&std::memcmp(magic,"HRTREE01",8))throw std::runtime_error("Invalid tree version");
        players=read<uint32_t>(in);root=read<uint32_t>(in);uint32_t nn=read<uint32_t>(in),ne=read<uint32_t>(in),nt=read<uint32_t>(in);
        identity=read<uint64_t>(in);chip_scale=read<double>(in);if(players<2||players>MAXP||nn>1000000||ne>4000000||nt>1000000||!std::isfinite(chip_scale)||!(chip_scale>0))throw std::runtime_error("Tree limit");
        read_array(in,initial.data(),players);reserve_budget(uint64_t(nn)*sizeof(Node)+uint64_t(ne)*sizeof(int)+uint64_t(nt)*(sizeof(Terminal)+16*sizeof(Pot)));nodes.resize(nn);children.resize(ne);terms.resize(nt);
        uint32_t flags=extended?read<uint32_t>(in):0;if(flags&~(features?511u:3u))throw std::runtime_error("Unknown tree extensions");if(extended)monetary=flags&1;track_ci=flags&8;policy_extension=flags&4;raked=flags&64;if(raked&&monetary)throw std::runtime_error("Rake supports chip equity only");
        uint32_t formats[4]={23,25,25,25};if(flags&32){read_array(in,formats,4);if(formats[0]!=23)throw std::runtime_error("Preflop storage must be format23");for(int i=1;i<4;++i)if(formats[i]!=25&&formats[i]!=27&&formats[i]!=31)throw std::runtime_error("Invalid postflop store");}
        for(int p=0;p<players;++p)if(!std::isfinite(initial[p])||initial[p]<=0||initial[p]>1e15||initial[p]!=std::floor(initial[p]))throw std::runtime_error("Invalid initial chip stack");
        for(auto& n:nodes){n.actor=read<int32_t>(in);n.street=read<int32_t>(in);n.buckets=read<int32_t>(in);n.first=read<int32_t>(in);n.k=read<int32_t>(in);n.special=read<int32_t>(in);n.terminal=read<int32_t>(in);
            if(n.k){if(n.actor<0||n.actor>=players||n.k<2||n.k>MAXA||n.street<0||n.street>3||n.buckets<1||(!(flags&128)&&n.buckets>16384)||n.first<0||n.first+n.k>int(ne))throw std::runtime_error("Invalid decision");n.store_format=formats[n.street];int f=n.base_format();uint64_t raw=f==23?1+uint64_t(2*n.k+1)*n.buckets:f==25?1+(uint64_t(n.buckets)+1)*n.k:1+n.k+uint64_t(f==27?2*n.k:2*n.k+1)*n.buckets;reserve_budget(8*(raw+n.buckets+(f==31?n.k:0)));n.init();}
            else if(n.terminal<0||n.terminal>=int(nt))throw std::runtime_error("Invalid terminal");}
        read_array(in,children.data(),ne);for(int c:children)if(c<0||c>=int(nn))throw std::runtime_error("Invalid child");
        for(auto& t:terms){Values remaining{},paid{};read_array(in,remaining.data(),players);read_array(in,paid.data(),players);uint32_t folded=read<uint32_t>(in);double dead=(flags&2)?read<double>(in):0;
            if(!std::isfinite(dead)||dead<0||dead>1e16||dead!=std::floor(dead)||folded>>players)throw std::runtime_error("Invalid terminal dead pot");
            t.folded=uint16_t(folded);
            if(raked){t.street=read<int32_t>(in);t.raise_count=read<int32_t>(in);if(t.street<0||t.street>3||t.raise_count<0)throw std::runtime_error("Invalid rake terminal context");t.remaining=remaining;t.dead_money=int64_t(dead);}
            t.participants=0;for(int p=0;p<players;++p)t.participants+=!(folded&(1u<<p));
            if(dead>0){uint32_t eligible=((1u<<players)-1)&~folded;if(!eligible)throw std::runtime_error("Dead pot without survivor");t.pots.push_back({dead,eligible,(1u<<players)-1});}
            t.paid=paid;std::vector<double> levels;for(int p=0;p<players;++p){if(!std::isfinite(remaining[p])||!std::isfinite(paid[p])||remaining[p]<0||paid[p]<0||remaining[p]!=std::floor(remaining[p])||paid[p]!=std::floor(paid[p])||remaining[p]+paid[p]>initial[p])throw std::runtime_error("Invalid terminal chip state");t.base[p]=remaining[p]-initial[p];if(paid[p]>0)levels.push_back(paid[p]);}
            std::sort(levels.begin(),levels.end());levels.erase(std::unique(levels.begin(),levels.end()),levels.end());double last=0;
            for(double level:levels){int count=0;uint32_t eligible=0,contributors=0;for(int p=0;p<players;++p)if(paid[p]>=level){++count;contributors|=1u<<p;if(!(folded&(1u<<p)))eligible|=1u<<p;}
                double amount=(level-last)*count;last=level;if(amount>0&&!eligible)throw std::runtime_error("Positive side pot without eligible player");if(amount>0)t.pots.push_back({amount,eligible,contributors});}
            double conserved=dead;for(int p=0;p<players;++p)conserved+=remaining[p]+paid[p]-initial[p];if(std::abs(conserved)>1e-8)throw std::runtime_error("Terminal chip conservation failed");
            // Single-eligible pots have the same award and elimination masks
            // on every deal. Rake and FGS retain their existing cache lifetime.
            t.card_independent=!raked&&std::all_of(t.pots.begin(),t.pots.end(),[](const Pot& p){return !(p.eligible&(p.eligible-1));});}
        if(root<0||root>=int(nn))throw std::runtime_error("Invalid root");
        if(monetary){
            hrc_equity::EquityConfig config;
            const auto mode=read<uint32_t>(in),bounty=read<uint32_t>(in),np=read<uint32_t>(in);
            if((mode!=1&&mode!=2)||bounty>2||np==0||np>10010)throw std::runtime_error("Invalid monetary model");
            config.mode=hrc_equity::Mode(mode);config.bounty_mode=hrc_equity::BountyMode(bounty);
            config.immediate_fraction=read<double>(in);config.payouts.resize(np);read_array(in,config.payouts.data(),np);
            const auto no=read<uint32_t>(in);if(no>10000||np>no+uint32_t(players))throw std::runtime_error("Invalid tournament field");
            config.other_stacks.resize(no);read_array(in,config.other_stacks.data(),no);
            config.bounties.resize(players);read_array(in,config.bounties.data(),players);
            config.other_bounties.resize(no);read_array(in,config.other_bounties.data(),no);
            if(!bounty){for(double x:config.bounties)if(x!=0)throw std::runtime_error("Unexpected bounty amount");for(double x:config.other_bounties)if(x!=0)throw std::runtime_error("Unexpected outside bounty amount");config.bounties.clear();config.other_bounties.clear();}
            for(int p=0;p<players;++p)config.initial_stacks.push_back(int64_t(initial[p]));
            hrc_equity::MttEvaluator evaluate;
            if(mode==2){auto mtt=std::make_shared<hrc_mtt::Calculator>(config.payouts,config.other_stacks);evaluate=[mtt](const auto& stacks,const auto&,const auto&){return mtt->equities(stacks);};}
            equity_config=config;equity=std::make_unique<hrc_equity::Calculator>(std::move(config),std::move(evaluate));
        }
        if(flags&4){auto count=read<uint32_t>(in);if(count>nodes.size())throw std::runtime_error("Policy node count limit");std::vector<bool> seen(nodes.size(),false);
            for(uint32_t i=0;i<count;++i){auto id=read<uint32_t>(in),kind=read<uint32_t>(in);if(id>=nodes.size()||seen[id]||!nodes[id].k)throw std::runtime_error("Invalid policy node");seen[id]=true;auto& n=nodes[id];
                if(kind==1){if(n.base_format()==25)throw std::runtime_error("Bucket locks require format23/27/31 storage");std::vector<std::vector<double>> rows(n.k);
                    for(int a=0;a<n.k;++a){auto locked=read<uint32_t>(in);if(locked>1||(locked&&a==0&&n.special))throw std::runtime_error("Invalid special-fold lock");if(locked){reserve_budget(8*uint64_t(n.buckets));rows[a].resize(n.buckets);read_array(in,rows[a].data(),n.buckets);}}
                    n.locks=std::make_unique<hrc_policy::BucketLocks>(n.k,n.buckets,std::move(rows));
                    if(n.locks->count()==n.k)for(int b=0;b<n.buckets;++b){double sum=0;for(auto& row:n.locks->rows)sum+=row[b];if(std::abs(sum-1)>((flags&256)?n.k*0x1p-23:1e-12))throw std::runtime_error("Fully locked distribution must sum to one");}
                }else if(kind==2){reserve_budget(8*(1+uint64_t(n.buckets)*(2*n.k+1)+6*n.k));std::vector<double> targets(n.k),edges(n.k);read_array(in,targets.data(),n.k);read_array(in,edges.data(),n.k);if(flags&256){double sum=0;for(double t:targets)if(!std::isnan(t)){if(!std::isfinite(t)||t<0||t>1)throw std::runtime_error("Invalid imported frequency target");sum+=t;}if(sum>1+n.k*0x1p-23)throw std::runtime_error("Imported frequency sum exceeds float32 tolerance");n.frequency=std::make_unique<hrc_policy::FrequencyStore>(n.buckets,n.k,std::vector<double>{},std::move(edges),n.base_format());n.frequency->targets=std::move(targets);}else n.frequency=std::make_unique<hrc_policy::FrequencyStore>(n.buckets,n.k,std::move(targets),std::move(edges),n.base_format());}
                else throw std::runtime_error("Unknown policy mode");
            }
        }
        if(flags&16){if(!equity||equity_config.mode!=hrc_equity::Mode::ICM)throw std::runtime_error("FGS requires local ICM");hrc_fgs::Config c;c.equity=equity_config;c.cancel_check=cancel_check;
            c.big_blind=read<int64_t>(in);c.small_blind=read<int64_t>(in);c.ante=read<int64_t>(in);c.ante_type=hrc_fgs::AnteType(read<uint32_t>(in));c.straddle=hrc_fgs::Straddle(read<uint32_t>(in));c.moving_button=read<uint32_t>(in)!=0;
            c.depth=read<int32_t>(in);c.depth3way=read<int32_t>(in);c.next_level_at=read<int32_t>(in);read_array(in,c.next_level.data(),3);
            c.cache_capacity=read<uint64_t>(in);c.terminal_cache_capacity=read<uint64_t>(in);c.max_states=read<uint64_t>(in);c.max_sweeps=read<uint64_t>(in);c.max_seconds=read<double>(in);
            fgs_context.skip_sb=read<uint32_t>(in)!=0;fgs_context.stacks=equity_config.initial_stacks;fgs_context.bounties=equity_config.bounties;
            auto chance=hrc_fgs::ChanceTables::read((resource_dir/"fgs-chance-v1.bin").string());fgs=std::make_unique<hrc_fgs::Calculator>(std::move(c),std::move(chance));
        }
        if(raked){auto mode=read<uint32_t>(in);rake.mode=hrc_settlement::RakeMode(mode);rake.fraction=read<double>(in);rake.cap=read<int64_t>(in);if(mode<1||mode>3||!std::isfinite(rake.fraction)||rake.fraction<0||rake.fraction>1||rake.cap<0)throw std::runtime_error("Invalid rake configuration");}
        if(flags&128){
            if(read<uint32_t>(in)!=1)throw std::runtime_error("Only fixed-board chance mode1 is supported");auto prefix_count=read<uint32_t>(in);if(prefix_count<2||prefix_count>4)throw std::runtime_error("Chance requires a fixed flop/turn/river");
            hrc_chance::Config config;config.max_attempts=read<uint64_t>(in);config.max_random_calls=read<uint64_t>(in);if(!config.max_attempts||!config.max_random_calls||config.max_attempts>1000000000||config.max_random_calls>1000000000)throw std::runtime_error("Chance resource budget domain");config.board_history.resize(prefix_count);read_array(in,config.board_history.data(),prefix_count);config.ranges.resize(players);
            reserve_budget(uint64_t(players)*1326*32+65536);
            for(auto& range:config.ranges){auto count=read<uint32_t>(in);if(count!=0&&count!=1326)throw std::runtime_error("Chance range requires1326 weights");range.resize(count);read_array(in,range.data(),count);}
            if(nodes[root].k&&(nodes[root].street<1||prefix_count!=uint32_t(nodes[root].street+1)))throw std::runtime_error("Fixed board street differs from subtree root street");
            chance=std::make_unique<hrc_chance::Sampler>(std::move(config));chance_cancel=cancel_check;
            auto count=read<uint32_t>(in);if(count>3)throw std::runtime_error("Dynamic table count limit");bool seen[4]={};
            for(uint32_t i=0;i<count;++i){auto street=read<uint32_t>(in);auto file=read_string(in),digest=read_string(in);auto bytes=read<uint64_t>(in);std::vector<uint32_t> effective(players);read_array(in,effective.data(),players);
                if(street<1||street>3||seen[street]||file.empty()||file=="."||file==".."||file.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")!=std::string::npos||digest.size()!=64||digest.find_first_not_of("0123456789abcdef")!=std::string::npos)throw std::runtime_error("Invalid dynamic resource descriptor");seen[street]=true;
                if(bytes>max_memory/2)throw NativeResourceLimit("Dynamic resource exceeds native memory budget");reserve_budget(2*bytes);
                auto resource=resource_dir/file;if(!fs::is_regular_file(resource)||fs::file_size(resource)!=bytes)throw std::runtime_error("Dynamic resource size mismatch");if(hrc_digest::file_sha256(resource.string())!=digest)throw std::runtime_error("Dynamic resource SHA-256 mismatch");
                auto table=std::make_unique<hrc_dynamic::Table>(hrc_dynamic::Table::read(resource.string(),max_memory));if(table->street()!=int(street)||table->players()!=players||table->prefix().size()>chance->prefix().size()||!std::equal(table->prefix().begin(),table->prefix().end(),chance->prefix().begin()))throw std::runtime_error("Dynamic resource street/players/fixed-prefix mismatch");
                for(int p=0;p<players;++p)if(table->effective(p)!=effective[p])throw std::runtime_error("Dynamic effective bucket metadata mismatch");dynamic[street]=std::move(table);
            }
            for(const auto& n:nodes)if(n.k){if(n.street<1||!dynamic[n.street])throw std::runtime_error("Missing dynamic table for decision street");if(uint32_t(n.buckets)!=dynamic[n.street]->effective(n.actor))throw std::runtime_error("Decision buckets differ from actor-specific dynamic table");}
        }
        if(in.peek()!=std::char_traits<char>::eof())throw std::runtime_error("Unexpected trailing tree data");
    }
};

#include "hrc_scope.hpp"

struct Engine {
    Tree tree;Random rng;bool v4=true;hrc_cards::AbstractionTables* tables=nullptr;
    uint64_t samples=0,epoch=0,scalar_calls=0,vector_calls=0,terminal_calls=0,constant_scalar_calls=0;
    uint64_t terminal_table_lookups=0,terminal_settlements=0;
    // Parallel workers, including the owner, keep mutable caches separate.
    // Threads==1 retains the original Terminal::value/cache representation.
    struct WorkerTerminalCache {Values value{};uint64_t cached_deal=UINT64_MAX;};
    static_assert(sizeof(WorkerTerminalCache)==88,"Worker terminal budget mismatch");
    std::unique_ptr<WorkerTerminalCache[]> worker_terminal_cache;
    uint64_t worker_terminal_bytes=0;
    struct TerminalPointer {uint64_t epoch=UINT64_MAX;const double* value=nullptr;};
    std::unique_ptr<TerminalPointer[]> terminal_pointer_cache;
    std::shared_ptr<const hrc_terminal_table::Tables> terminal_pointer_table;
    uint64_t terminal_pointer_bytes=0;
    // Called only with workers quiescent, after the shared table is published.
    // The owner keeps all cached immutable pointers alive for the engine.
    static bool prepare_terminal_pointers(const std::vector<Engine*>& engines,Tree& owner){
        const auto& table=owner.terminal_tables;
        if(!table||owner.raked||owner.fgs||engines.empty())return false;
        const size_t count=table->entries();if(!count)return false;
        bool ready=true;
        for(auto* engine:engines){
            if(engine->resources().terms.size()!=count||engine->tree.raked||engine->tree.fgs||bool(engine->tree.equity)!=bool(owner.equity))return false;
            if(std::any_of(engine->resources().terms.begin(),engine->resources().terms.end(),[](const Terminal& t){return t.synthetic;}))return false;
            if(engine->terminal_pointer_table&&engine->terminal_pointer_table!=table)throw std::logic_error("Terminal pointer table cannot change after preparation");
            ready&=bool(engine->terminal_pointer_cache);
        }
        if(ready)return true;
        for(auto* engine:engines)if(engine->terminal_pointer_cache)throw std::logic_error("Partial terminal pointer preparation");
        if(count>(UINT64_MAX-64)/sizeof(TerminalPointer))return false;
        const uint64_t each=uint64_t(count)*sizeof(TerminalPointer)+64;
        const uint64_t available=owner.max_memory-owner.estimated_memory;
        if(engines.size()>available/each)return false;
        std::vector<std::unique_ptr<TerminalPointer[]>> pending;
        try{pending.reserve(engines.size());for(size_t i=0;i<engines.size();++i)pending.push_back(std::make_unique<TerminalPointer[]>(count));}
        catch(const std::bad_alloc&){return false;}
        owner.reserve_budget(each*engines.size());
        for(size_t i=0;i<engines.size();++i){engines[i]->terminal_pointer_cache=std::move(pending[i]);engines[i]->terminal_pointer_table=table;engines[i]->terminal_pointer_bytes=each;}
        // All workers are quiescent and every fast-path cache is now installed.
        // Their table shared_ptr keeps the returned immutable values alive.
        for(auto* engine:engines)if(engine->worker_terminal_cache){
            if(engine->worker_terminal_bytes>owner.estimated_memory)throw std::logic_error("Worker terminal budget underflow");
            engine->worker_terminal_cache.reset();owner.estimated_memory-=engine->worker_terminal_bytes;engine->worker_terminal_bytes=0;
        }
        return true;
    }

    std::shared_ptr<const hrc_terminal_table::Tables> make_terminal_table(
        std::size_t budget,const std::function<bool()>& cancelled={}) {
        if(tree.raked||tree.fgs)return {};
        if(!tree.equity)return hrc_terminal_table::Tables::build(tree.terms,tree.players,tree.chip_scale,budget,cancelled);
        auto transform=[&](const Terminal& terminal,const int* ranks,double* values){
            hrc_equity::WinnerMasks eliminated{};hrc_equity::Chips final{};
            // Match the legacy settlement's last covering pot exactly,
            // including uncalled returns, ties and folded contributors.
            for(const auto& pot:terminal.pots){uint16_t winners=0;int best=0;bool have=false;
                for(int p=0;p<tree.players;++p)if(pot.eligible&(1u<<p)){
                    if(!have||ranks[p]>best){best=ranks[p];winners=uint16_t(1u<<p);have=true;}
                    else if(ranks[p]==best)winners|=uint16_t(1u<<p);
                }
                for(int p=0;p<tree.players;++p)if(pot.contributors&(1u<<p))eliminated[p]=winners;
            }
            for(int p=0;p<tree.players;++p){final[p]=std::llround(tree.initial[p]+values[p]);if(final[p])eliminated[p]=0;}
            const auto& result=tree.equity->compute_terminal(final,eliminated);
            const auto& baseline=tree.equity->baseline();
            for(int p=0;p<tree.players;++p)values[p]=result.total[p]-baseline.total[p];
        };
        return hrc_terminal_table::Tables::build_transformed(tree.terms,tree.players,1.0,budget,transform,cancelled);
    }

    int combo[MAXP]{},bucket[4][MAXP]{},rank[MAXP]{};uint64_t holes[MAXP]{},board[4]{};
    bool bucket_ready[4]{},rank_ready=false;uint32_t rank_mask=0;
    uint32_t bucket_mask[4]{};
    hrc_cards::BucketRow bucket_rows[4];
    // Per-engine, per-deal caches. They neither sample nor alter node storage.
    std::array<uint64_t,1<<MAXP> winner_epoch{};
    std::array<uint16_t,1<<MAXP> winner_masks{};
    Values root_sum{};
    std::shared_ptr<const SamplingScope> scope;
    bool root_mean_valid=true;
    uint64_t sampling_attempts=0,sampling_deals=0,scope_samples=0,ci_reserved=0;
    double ci_target=-1;
    std::unique_ptr<hrc_ci::Tracker> ci;
    std::vector<int> ci_nodes;
    const Tree* resources_tree=nullptr;
    std::vector<Node>* shared_nodes=nullptr;
    hrc_node_mutex::NodeMutex* node_mutexes=nullptr;
    std::vector<std::array<uint64_t,4>> parallel_rng;
    int training_threads=1;
    uint64_t checkpoint_writes=0;
    double checkpoint_seconds=0;
    const Tree& resources()const{return resources_tree?*resources_tree:tree;}
    Node& node(int id){return (shared_nodes?*shared_nodes:tree.nodes)[id];}
    std::unique_ptr<hrc_unlocked_read::EpsilonCache[]> unlocked_epsilon;
    uint64_t unlocked_cache_bytes=0;
    static bool prepare_unlocked_reads(const std::vector<Engine*>& engines,Tree& owner){
        if(engines.empty())return false;
        size_t prepared=0;for(const auto* e:engines)prepared+=bool(e->unlocked_epsilon);
        if(prepared){if(prepared!=engines.size())throw std::logic_error("Partial unlocked-read publication");return true;}
        bool eligible=false;for(const auto& n:owner.nodes)eligible|=n.can_unlock_read();
        if(!eligible)return false;
        const uint64_t per_worker=owner.nodes.size()*sizeof(hrc_unlocked_read::EpsilonCache)+64;
        const uint64_t bytes=per_worker*engines.size();
        if(bytes>owner.max_memory-owner.estimated_memory)return false;
        std::vector<std::unique_ptr<hrc_unlocked_read::EpsilonCache[]>> pending;
        try{pending.reserve(engines.size());for(size_t i=0;i<engines.size();++i)pending.push_back(std::make_unique<hrc_unlocked_read::EpsilonCache[]>(owner.nodes.size()));}
        catch(const std::bad_alloc&){return false;}
        owner.reserve_budget(bytes);
        for(size_t i=0;i<engines.size();++i){engines[i]->unlocked_epsilon=std::move(pending[i]);engines[i]->unlocked_cache_bytes=per_worker;}
        // Last: no worker may observe an enabled flag without its own cache.
        // The caller is quiescent and publishes the next run under control_.
        for(auto& n:owner.nodes)n.unlocked_read=n.can_unlock_read();
        return true;
    }
    int sample_snapshot(int k,const double* p,double epsilon){
        if(rng.unit()<epsilon)return int(rng.bound(k));
        for(int a=0;a<k;++a)if(p[a]>=1)return a;
        double u=rng.unit();for(int a=0;a<k;++a){u-=p[a];if(u<=0)return a;}return 0;
    }
    int choose(int id,Node& n,int h,double* p){
        if(n.unlocked_read){
            n.strategy_atomic(h,p);const double counter=hrc_unlocked_read::load(n.raw.data());
            auto& cache=unlocked_epsilon[id];
            if(counter!=cache.counter){cache.counter=counter;cache.epsilon=1/std::sqrt(counter+10000);}
            return sample_snapshot(n.k,p,cache.epsilon);
        }
        if(node_mutexes){std::lock_guard<hrc_node_mutex::NodeMutex> guard(node_mutexes[id]);n.strategy(h,p);return sample(n,p);}
        n.strategy(h,p);return sample(n,p);
    }
    void update(int id,Node& n,int h,const double* p,const double* q,double marker){
        if(node_mutexes){std::lock_guard<hrc_node_mutex::NodeMutex> guard(node_mutexes[id]);n.update(rng,h,p,q,1,marker);}
        else n.update(rng,h,p,q,1,marker);
    }
    explicit Engine(uint64_t seed):rng(seed){}
    int sampling_root()const{return scope?scope->root:tree.root;}
    void accept_deal(const hrc_chance::Deal& d){++epoch;++sampling_deals;sampling_attempts+=d.attempts;
        const auto& cards=hrc_cards::combo_cards();
        for(int p=0;p<tree.players;++p){combo[p]=d.combos[p];int high=cards.hi.at(combo[p]),low=cards.lo[combo[p]];holes[p]=(1ULL<<high)|(1ULL<<low);bucket[0][p]=cards.preflop[combo[p]];}
        std::copy(d.board.begin(),d.board.end(),board);bucket_ready[0]=true;for(int st=1;st<4;++st){bucket_ready[st]=false;bucket_mask[st]=0;}rank_ready=false;rank_mask=0;
    }
    hrc_chance::Deal chance_scratch;
    void scope_deal(int skip=-1){try{scope->sampler->sample_into(chance_scratch,[&](int b){return int(rng.bound(uint32_t(b)));},[&](){return rng.unit();},tree.chance_cancel,skip);accept_deal(chance_scratch);}
        catch(const hrc_chance::Cancelled& ex){throw hrc_fgs::Cancelled(ex.what());}catch(const hrc_chance::ResourceLimit& ex){throw NativeResourceLimit(ex.what());}}
    void deal(){
        if(resources().chance){try{resources().chance->sample_into(chance_scratch,[&](int bound){return int(rng.bound(uint32_t(bound)));},[&](){return rng.unit();},tree.chance_cancel);}catch(const hrc_chance::Cancelled& ex){throw hrc_fgs::Cancelled(ex.what());}catch(const hrc_chance::ResourceLimit& ex){throw NativeResourceLimit(ex.what());}accept_deal(chance_scratch);return;}
        ++sampling_attempts;++sampling_deals;
        ++epoch;uint64_t used=0;int deck[2*MAXP+5];int needed=2*tree.players+5;
        for(int i=0;i<needed;++i){int c;do{c=int(rng.bound(52));}while(used&(1ULL<<c));used|=1ULL<<c;deck[i]=c;}
        for(int p=0;p<tree.players;++p){int a=deck[2*p],b=deck[2*p+1],hi=std::max(a,b),lo=std::min(a,b);combo[p]=hi*(hi-1)/2+lo;holes[p]=(1ULL<<a)|(1ULL<<b);bucket[0][p]=hrc_cards::preflop_class(combo[p]);}
        int j=2*tree.players;board[0]=0;board[1]=(1ULL<<deck[j])|(1ULL<<deck[j+1])|(1ULL<<deck[j+2]);board[2]=board[1]|(1ULL<<deck[j+3]);board[3]=board[2]|(1ULL<<deck[j+4]);
        bucket_ready[0]=true;for(int st=1;st<4;++st){bucket_ready[st]=false;bucket_mask[st]=0;}rank_ready=false;rank_mask=0;
    }
    void ensure_ranks(uint32_t need){
        // rank_ready also permits explicit ranks supplied by settlement/export
        // probes. Otherwise each needed seat is evaluated at most once per deal.
        if(rank_ready)return;
        uint32_t missing=need&~rank_mask;
        while(missing){int p=hrc_cards::lowbit(missing);missing&=missing-1;rank[p]=hrc_cards::rank7(holes[p]|board[3]);}
        rank_mask|=need;rank_ready=rank_mask==((1u<<tree.players)-1);
    }
    uint32_t pot_winners(uint32_t eligible){
        if(winner_epoch[eligible]==epoch&&winner_masks[eligible])return winner_masks[eligible];
        ensure_ranks(eligible);int best=-1;uint32_t winners=0,remaining=eligible;
        while(remaining){int p=hrc_cards::lowbit(remaining);remaining&=remaining-1;
            if(rank[p]>best){best=rank[p];winners=1u<<p;}else if(rank[p]==best)winners|=1u<<p;}
        winner_epoch[eligible]=epoch;winner_masks[eligible]=uint16_t(winners);return winners;
    }
    int hand(const Node& n){
        // For 2/3 seats, fill one static row for all seats once. Larger tables
        // retain lazy actor mapping; dynamic tables always use their own path.
        if(!bucket_ready[n.street]&&n.street>0&&tree.players<=3&&!resources().chance){
            if(!tables)throw std::runtime_error("Missing abstraction tables");
            bucket_rows[n.street]=hrc_cards::prepare_bucket_row(n.street,board[n.street],*tables);
            for(int seat=0;seat<tree.players;++seat)
                bucket[n.street][seat]=hrc_cards::bucket_from_row(combo[seat],board[n.street],bucket_rows[n.street],tables->streets[n.street]);
            bucket_mask[n.street]=(1u<<tree.players)-1;bucket_ready[n.street]=true;
        }
        if(!bucket_ready[n.street]){uint32_t bit=1u<<n.actor;
            if(!(bucket_mask[n.street]&bit)){
                if(resources().chance){if(!resources().dynamic[n.street])throw std::runtime_error("Missing dynamic abstraction table");bucket[n.street][n.actor]=resources().dynamic[n.street]->bucket(n.actor,combo[n.actor],board);}
                else{if(!tables)throw std::runtime_error("Missing abstraction tables");if(!bucket_mask[n.street])bucket_rows[n.street]=hrc_cards::prepare_bucket_row(n.street,board[n.street],*tables);
                    bucket[n.street][n.actor]=hrc_cards::bucket_from_row(combo[n.actor],board[n.street],bucket_rows[n.street],tables->streets[n.street]);}
                bucket_mask[n.street]|=bit;bucket_ready[n.street]=bucket_mask[n.street]==((1u<<tree.players)-1);
            }
        }int h=bucket[n.street][n.actor];if(h<0||h>=n.buckets)throw std::runtime_error("Bucket outside node range");return h;
    }
    const double* terminal(int id){
        ++terminal_calls;
        if(terminal_pointer_cache){
            auto& cached=terminal_pointer_cache[id];
            if(cached.value&&(cached.epoch==epoch||cached.epoch==UINT64_MAX))return cached.value;
            const auto& table=*terminal_pointer_table;const uint32_t needed=table.rank_mask(size_t(id));
            ++terminal_table_lookups;ensure_ranks(needed);
            cached.value=table.lookup(size_t(id),rank);cached.epoch=needed?epoch:UINT64_MAX;
            return cached.value;
        }
        const auto& t=resources().terms[id];if(t.synthetic)return t.value.data();
        // Shared fields below are immutable. A worker never reads the owner's
        // mutable cached value/epoch; synthetic value is itself immutable.
        auto& value=worker_terminal_cache?worker_terminal_cache[id].value:tree.terms[id].value;
        auto& cached_deal=worker_terminal_cache?worker_terminal_cache[id].cached_deal:tree.terms[id].cached_deal;
        if(cached_deal==epoch||(!tree.fgs&&t.card_independent&&cached_deal!=UINT64_MAX))return value.data();
        if(const auto& table=resources().terminal_tables){
            ++terminal_table_lookups;ensure_ranks(table->rank_mask(size_t(id)));
            const double* values=table->lookup(size_t(id),rank);
            std::copy(values,values+tree.players,value.begin());cached_deal=epoch;
            return value.data();
        }
        value=t.base;cached_deal=epoch;
        ++terminal_settlements;
        if(tree.raked){
            ensure_ranks((1u<<tree.players)-1);
            std::vector<int64_t> remaining(tree.players),paid(tree.players);std::vector<int> ranks(rank,rank+tree.players);
            for(int p=0;p<tree.players;++p){remaining[p]=int64_t(t.remaining[p]);paid[p]=int64_t(t.paid[p]);}
            auto result=hrc_settlement::settle(remaining,paid,t.folded,ranks,t.dead_money,t.street,t.raise_count,tree.rake);
            for(int p=0;p<tree.players;++p)value[p]=(double(result.stacks[p])-tree.initial[p])/tree.chip_scale;
            return value.data();
        }
        uint32_t pending_winners=0;double pending_amount=0;hrc_equity::WinnerMasks elimination_winners{};bool tied_award=false;
        auto award=[&](){if(!pending_winners)return;int count=0,first=-1;for(int p=0;p<tree.players;++p)if(pending_winners&(1u<<p)){++count;if(first<0||t.paid[p]<t.paid[first]||(t.paid[p]==t.paid[first]&&p>first))first=p;}
            double each=std::floor(pending_amount/count),remainder=pending_amount-each*count;
            tied_award|=count>1;
            for(int p=0;p<tree.players;++p)if(pending_winners&(1u<<p))value[p]+=each;
            value[first]+=remainder;};
        for(const auto& pot:t.pots){uint32_t winners=pot.eligible;
            if(winners&(winners-1))winners=pot_winners(pot.eligible);
            if(pending_winners&&winners!=pending_winners){award();pending_amount=0;}
            if(tree.equity)for(int p=0;p<tree.players;++p)if(pot.contributors&(1u<<p))elimination_winners[p]=uint16_t(winners);
            pending_winners=winners;pending_amount+=pot.amount;
        }award();
        if(tree.equity){
            hrc_equity::Chips final{};for(int p=0;p<tree.players;++p){final[p]=std::llround(tree.initial[p]+value[p]);if(final[p])elimination_winners[p]=0;}
            if(tree.fgs){hrc_fgs::Outcome outcome;outcome.stacks.assign(final.begin(),final.begin()+tree.players);outcome.winner_masks.assign(elimination_winners.begin(),elimination_winners.begin()+tree.players);outcome.participants=t.participants;outcome.tied_award=tied_award;
                auto result=tree.fgs->terminal(tree.fgs_context,outcome);for(int p=0;p<tree.players;++p)value[p]=result[p]-tree.fgs_baseline[p];}
            else{const auto& result=tree.equity->compute_terminal(final,elimination_winners);
                const auto& baseline=tree.equity->baseline();for(int p=0;p<tree.players;++p)value[p]=result.total[p]-baseline.total[p];}
        }else for(int p=0;p<tree.players;++p)value[p]/=tree.chip_scale;
        return value.data();
    }
    int sample(const Node& n,const double* p){
        if(rng.unit()<n.exploration_probability())return int(rng.bound(n.k));
        for(int a=0;a<n.k;++a)if(p[a]>=1)return a;
        double u=rng.unit();for(int a=0;a<n.k;++a){u-=p[a];if(u<=0)return a;}return 0;
    }
    double scalar(int id,int target,int depth,double marker){
        ++scalar_calls;Node& n=node(id);if(!n.k)return terminal(n.terminal)[target];
        // The target has no decision anywhere in this subtree and cannot win
        // any pot; all leaves give it exactly the same chip value. No target
        // update is skipped. Removing these draws changes the RNG trajectory.
        if(n.constant_scalar_mask&(1u<<target)){++constant_scalar_calls;return resources().terms[n.constant_scalar_terminal].base[target]/tree.chip_scale;}
        double p[MAXA],q[MAXA];int h=hand(n);int chosen=choose(id,n,h,p);
        if(n.actor==target&&(!v4||rng.bound(depth+2)!=0)){
            for(int a=0;a<n.k;++a)q[a]=scalar(resources().children[n.first+a],target,depth,a==chosen?marker:0);
            update(id,n,h,p,q,marker);return q[chosen];
        }return scalar(resources().children[n.first+chosen],target,depth+(n.actor==target),marker);
    }
    const double* vector(int id){
        ++vector_calls;Node& n=node(id);if(!n.k)return terminal(n.terminal);
        double p[MAXA],q[MAXA];int h=hand(n);int chosen=choose(id,n,h,p);const double* result=nullptr;
        for(int a=0;a<n.k;++a){int child=resources().children[n.first+a];
            if(a==chosen){result=vector(child);q[a]=result[n.actor];}
            else if(a==0&&n.special==2&&rng.unit()<.01)q[a]=vector(child)[n.actor];
            else q[a]=scalar(child,n.actor,0,0);
        }update(id,n,h,p,q,1);return result;
    }
    void step(){
        if(scope&&scope->selected&&scope->mode==2){
            for(int target:scope->targets){scope_deal(target);scalar(scope->root,target,0,scope->reach[target][bucket[0][target]]);}
        }else{if(scope&&scope->selected&&scope->mode==1)scope_deal();else deal();const double* v=vector(sampling_root());
            if(root_mean_valid)for(int p=0;p<tree.players;++p)root_sum[p]+=v[p];}
        ++samples;++scope_samples;
    }
    std::vector<hrc_ci::Snapshot> ci_snapshots(){std::vector<hrc_ci::Snapshot> result;result.reserve(ci_nodes.size());for(int id:ci_nodes){auto& n=tree.nodes[id];n.flush();hrc_ci::Snapshot s;s.count=n.counter();s.policy.resize(size_t(n.buckets)*n.k);for(int b=0;b<n.buckets;++b)n.display_into(b,s.policy.data()+size_t(b)*n.k);result.push_back(std::move(s));}return result;}
    void reserve_ci_memory(){if(!tree.track_ci)return;ci_nodes.clear();int street=tree.nodes[sampling_root()].street;std::vector<int> stack{sampling_root()};std::vector<uint8_t> seen(tree.nodes.size(),0);uint64_t bytes=0;
        while(!stack.empty()){int id=stack.back();stack.pop_back();if(seen[id])continue;seen[id]=1;auto& n=tree.nodes[id];if(!n.k||n.street!=street||(street!=0&&!(n.format()&2)))continue;ci_nodes.push_back(id);bytes+=3*(sizeof(hrc_ci::Snapshot)+8*uint64_t(n.k)*n.buckets)+sizeof(int);for(int a=n.k-1;a>=0;--a)stack.push_back(tree.children[n.first+a]);}
        if(bytes>ci_reserved){tree.reserve_budget(bytes-ci_reserved);ci_reserved=bytes;}}
    void start_ci(int64_t now){if(!tree.track_ci)return;reserve_ci_memory();ci=std::make_unique<hrc_ci::Tracker>(ci_snapshots(),now);}
    void poll_ci(int64_t now){if(!ci||now-ci->last_time<ci->interval)return;auto start=std::chrono::steady_clock::now();auto snapshots=ci_snapshots();auto duration=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();ci->update(now,samples,std::move(snapshots),duration);}
    void reset(bool r,bool a){for(size_t id=0;id<tree.nodes.size();++id)if(!scope||scope->contains(int(id)))tree.nodes[id].reset(r,a);}
    void write_ci(std::ostream& out)const{if(!ci){out<<"null";return;}out<<"{\"value\":";if(std::isfinite(ci->ci))out<<ci->ci;else out<<"null";
        out<<",\"target\":";if(ci_target>0)out<<ci_target;else out<<"null";
        double progress=ci_target>0&&std::isfinite(ci->ci)&&ci->has_first?ci->progress(ci_target,&ci->first_record):std::numeric_limits<double>::quiet_NaN();
        out<<",\"progress\":";if(std::isfinite(progress))out<<progress;else out<<"null";
        out<<",\"eta_seconds\":";if(ci->history.size()>1&&std::isfinite(progress)&&progress>0&&progress<1){double elapsed=(ci->history.back().timestamp-ci->first_time)/1000.;out<<elapsed*(1-progress)/progress;}else if(progress==1)out<<0;else out<<"null";
        out<<",\"eta_method\":\"recent_ci_power_progress_not_error_bound\",\"root_node_id\":"<<sampling_root()<<",\"samples_per_second\":"<<ci->samples_per_second()<<",\"selected_nodes\":"<<ci_nodes.size()<<",\"interval_ms\":"<<ci->interval<<",\"history\":[";for(size_t i=0;i<ci->history.size();++i){if(i)out<<',';auto r=ci->history[i];out<<"{\"ordinal\":"<<r.ordinal<<",\"timestamp_ms\":"<<r.timestamp<<",\"samples\":"<<r.samples<<",\"value\":"<<r.ci<<'}';}out<<"]}";}
    void write_scope(std::ostream& out)const{out<<",\"sampling_scope\":\""<<(scope&&scope->selected?"selected_subtree":"entire_tree")<<"\",\"sampling_root_node_id\":"<<sampling_root()<<",\"sampling_mode\":"<<(scope&&scope->selected?scope->mode:resources().chance?1:0)<<",\"sampling_attempts\":"<<sampling_attempts<<",\"sampling_deals\":"<<sampling_deals<<",\"scope_effective_samples\":"<<scope_samples<<",\"sampling_counter_scope\":\"current_invocation\",\"attempt_semantics\":\"candidate_joint_range_assignments_across_target_deals\",\"root_mean_valid\":"<<(root_mean_valid?"true":"false");
        if(scope&&scope->selected){out<<",\"prefix_policy\":\"frozen_display_without_exploration\",\"prefix_reach_sha256\":\""<<scope->reach_sha256<<"\",\"sampling_path\":[";for(size_t i=0;i<scope->path.size();++i){if(i)out<<',';out<<scope->path[i];}out<<"],\"sampling_targets\":[";for(size_t i=0;i<scope->targets.size();++i){if(i)out<<',';out<<scope->targets[i];}out<<']';}}
    void save(const fs::path& folder){
        auto saving_start=std::chrono::steady_clock::now();
        fs::create_directories(folder);auto temp=folder/"checkpoint.tmp";
        std::array<char,65536> binary_buffer,index_buffer;
        std::ofstream out;out.rdbuf()->pubsetbuf(binary_buffer.data(),binary_buffer.size());out.open(temp,std::ios::binary);out.write("HRSOLV03",8);
        write(out,tree.identity);write(out,samples);write(out,uint32_t(tree.nodes.size()));write(out,uint32_t(tree.players));write(out,uint32_t(v4));write_array(out,rng.s,4);write_array(out,root_sum.data(),tree.players);
        // tellp() may flush file buffers. Track byte offsets instead of querying
        // the file twice per node (almost a million queries on the 9p40 tree).
        uint64_t offset=uint64_t(out.tellp());
        bool inherited_history=false;for(const auto& node:tree.nodes){uint64_t visits=0;for(auto count:node.visits)visits+=count;if(node.updates>visits)inherited_history=true;}
        std::ofstream index;index.rdbuf()->pubsetbuf(index_buffer.data(),index_buffer.size());index.open(folder/"index.tmp");index<<std::setprecision(17)<<"{\"version\":3,\"samples\":"<<samples<<",\"fresh_zero_origin\":"<<(inherited_history?"false":"true")<<",\"utility\":\""<<(tree.equity?"net_payout":"net_bb")<<"\",\"algorithm\":\"audited_v"<<(v4?4:3)<<(training_threads>1?"_async_shared":"_single_thread")<<(tree.constant_scalar_shortcuts?"_constant_scalar":"")<<"\",\"training_threads\":"<<training_threads<<",\"constant_scalar_shortcuts\":"<<(tree.constant_scalar_shortcuts?"true":"false")<<",\"constant_scalar_nodes\":"<<tree.constant_scalar_nodes<<",\"ci\":";write_ci(index);write_scope(index);index<<",\"nodes\":[";
        for(size_t i=0;i<tree.nodes.size();++i){auto& n=tree.nodes[i];if(i)index<<',';write(out,n.updates);write(out,uint32_t(n.format()));uint64_t visits_offset=offset+sizeof(uint64_t)+sizeof(uint32_t);write_array(out,n.visits.data(),n.visits.size());uint64_t raw_offset=visits_offset+sizeof(uint64_t)*n.visits.size();write_array(out,n.storage().data(),n.storage().size());offset=raw_offset+sizeof(double)*n.storage().size();
            index<<"{\"id\":"<<i<<",\"actor\":"<<n.actor<<",\"street\":"<<n.street<<",\"buckets\":"<<n.buckets<<",\"actions\":"<<n.k<<",\"updates\":"<<n.updates<<",\"visits_offset\":"<<visits_offset<<",\"raw_offset\":"<<raw_offset<<",\"raw_count\":"<<n.storage().size()<<",\"format\":"<<n.format()<<",\"special\":"<<n.special;
            uint64_t visit_count=0;for(auto value:n.visits)visit_count+=value;if(n.updates>visit_count)index<<",\"history_unknown\":true,\"imported_updates_baseline\":"<<(n.updates-visit_count);
            if(n.frequency){auto& f=*n.frequency;index<<",\"frequency_state_offset\":"<<offset;write(out,f.minimum);write(out,f.maximum);write_array(out,f.edges.data(),n.k);write_array(out,f.edge_sums.data(),n.k);write_array(out,f.shared_sums.data(),n.k);write_array(out,f.targets.data(),n.k);offset+=sizeof(double)*(2+4*n.k);index<<",\"targets\":[";for(int a=0;a<n.k;++a){if(a)index<<',';if(std::isnan(f.targets[a]))index<<"null";else index<<f.targets[a];}index<<']';}
            else if(n.k&&n.base_format()==31){index<<",\"shared_state_offset\":"<<offset;write_array(out,n.shared_sums.data(),n.k);offset+=sizeof(double)*n.k;}
            if(n.locks){index<<",\"locks\":[";for(int a=0;a<n.k;++a){if(a)index<<',';auto& row=n.locks->rows[a];if(row.empty())index<<"null";else{index<<'[';for(int b=0;b<n.buckets;++b){if(b)index<<',';index<<row[b];}index<<']';}}index<<']';}
            index<<'}';}
        index<<"],\""<<(tree.equity?"root_mean_net_payout":"root_mean_net_bb")<<"\":";if(!root_mean_valid)index<<"null";else{index<<'[';for(int p=0;p<tree.players;++p){if(p)index<<',';index<<(samples?root_sum[p]/samples:0);}index<<']';}index<<",\"utility_baseline\":";if(tree.fgs&&tree.fgs_baseline.empty())index<<"null";else{index<<'[';for(int p=0;p<tree.players;++p){if(p)index<<',';index<<(tree.fgs?tree.fgs_baseline[p]:tree.equity?tree.equity->baseline().total[p]:tree.initial[p]/tree.chip_scale);}index<<']';}index<<'}';
        if(parallel_rng.size()>1){out.write("HRPAR001",8);write(out,uint32_t(parallel_rng.size()));for(const auto& state:parallel_rng)write_array(out,state.data(),4);}
        out.close();index.close();
        if(!out||!index)throw std::runtime_error("Checkpoint write failed");
        // Replacing only this run's own checkpoint files, after complete writes.
        fs::path target=folder/"checkpoint.bin";std::error_code ec;fs::remove(target,ec);fs::rename(temp,target);target=folder/"index.json";fs::remove(target,ec);fs::rename(folder/"index.tmp",target);
        ++checkpoint_writes;checkpoint_seconds+=std::chrono::duration<double>(std::chrono::steady_clock::now()-saving_start).count();
    }
    void resume(const fs::path& path){
        {std::ifstream metadata(path.parent_path()/"index.json",std::ios::binary);std::string prefix(8192,'\0');metadata.read(prefix.data(),prefix.size());prefix.resize(size_t(metadata.gcount()));auto at=prefix.find("\"root_mean_valid\"");if(at!=std::string::npos){at=prefix.find(':',at);if(at!=std::string::npos){at=prefix.find_first_not_of(" \r\n\t",at+1);if(at!=std::string::npos&&prefix.compare(at,5,"false")==0)root_mean_valid=false;}}}
        std::ifstream in(path,std::ios::binary);char magic[8];read_array(in,magic,8);bool targets_stored=!std::memcmp(magic,"HRSOLV03",8),extended=targets_stored||!std::memcmp(magic,"HRSOLV02",8);if(!extended&&std::memcmp(magic,"HRSOLV01",8))throw std::runtime_error("Checkpoint version");
        if(read<uint64_t>(in)!=tree.identity)throw std::runtime_error("Checkpoint tree identity mismatch");samples=read<uint64_t>(in);if(read<uint32_t>(in)!=tree.nodes.size()||read<uint32_t>(in)!=tree.players||read<uint32_t>(in)!=uint32_t(v4))throw std::runtime_error("Checkpoint shape/mode mismatch");
        read_array(in,rng.s,4);read_array(in,root_sum.data(),tree.players);for(auto& n:tree.nodes){n.updates=read<uint64_t>(in);if(extended){if(read<uint32_t>(in)!=uint32_t(n.format()))throw std::runtime_error("Checkpoint store format mismatch");}else if(n.frequency||n.locks)throw std::runtime_error("Legacy checkpoint has no policy extension");read_array(in,n.visits.data(),n.visits.size());read_array(in,n.storage().data(),n.storage().size());
            if(n.frequency){auto& f=*n.frequency;f.updates=n.updates;f.minimum=read<double>(in);f.maximum=read<double>(in);read_array(in,f.edges.data(),n.k);read_array(in,f.edge_sums.data(),n.k);read_array(in,f.shared_sums.data(),n.k);if(targets_stored){read_array(in,f.targets.data(),n.k);for(double target:f.targets)if(!std::isnan(target)&&(!std::isfinite(target)||target<0||target>1))throw std::runtime_error("Invalid checkpoint frequency target");}}
            else if(n.k&&n.base_format()==31)read_array(in,n.shared_sums.data(),n.k);}
        if(in.peek()!=std::char_traits<char>::eof()){
            char tag[8];read_array(in,tag,8);auto count=read<uint32_t>(in);
            if(std::memcmp(tag,"HRPAR001",8)||count<2||count>32)throw std::runtime_error("Invalid parallel checkpoint trailer");
            parallel_rng.resize(count);for(auto& state:parallel_rng){read_array(in,state.data(),4);if(!(state[0]|state[1]|state[2]|state[3]))throw std::runtime_error("Invalid worker RNG state");}
            for(size_t i=0;i<parallel_rng.size();++i)for(size_t j=0;j<i;++j)if(parallel_rng[i]==parallel_rng[j])throw std::runtime_error("Duplicate worker RNG state");
            if(!std::equal(parallel_rng[0].begin(),parallel_rng[0].end(),rng.s)||in.peek()!=std::char_traits<char>::eof())throw std::runtime_error("Parallel checkpoint RNG mismatch or trailing data");
        }
    }
};

#include "hrc_parallel.hpp"

void array_json(const double* p,size_t n){std::cout<<'[';for(size_t i=0;i<n;++i){if(i)std::cout<<',';std::cout<<p[i];}std::cout<<']';}
void probe_row(const std::string& id,const double* actual,size_t n){std::cout<<"{\"id\":\""<<id<<"\",\"actual\":";array_json(actual,n);std::cout<<"}\n";}
void probes(){
    std::cout<<std::setprecision(17);Random rng;rng.scripted=true;
    {using C=CheckpointSchedule::Clock;auto t=C::time_point{};CheckpointSchedule s(t,.01);
        double boundaries[]={double(s.due(t+std::chrono::seconds(29))),double(s.due(t+std::chrono::seconds(30)))};
        probe_row("checkpoint.fast_write_time_boundaries",boundaries,2);
        s.saved(t+std::chrono::seconds(32),7.);double expensive[]={s.interval_seconds,double(s.due(t+std::chrono::seconds(171))),double(s.due(t+std::chrono::seconds(172)))};
        probe_row("checkpoint.expensive_write_backoff",expensive,3);
        double limits[]={CheckpointSchedule::interval(0),CheckpointSchedule::interval(1000)};probe_row("checkpoint.recovery_interval_bounds",limits,2);}
    {Engine e(42);e.tree.players=MAXP;e.rank_ready=true;uint64_t mismatches=0;
        // Exercise every eligible subset, ties, the top seat, repeated reads,
        // epoch zero and reuse across deals with different winner orders.
        for(uint64_t deal=0;deal<24;++deal){e.epoch=deal;for(int p=0;p<MAXP;++p)e.rank[p]=int((p*7+deal*3)%(deal%5+2));
            for(uint32_t mask=1;mask<(1u<<MAXP);++mask){int best=-1;uint32_t expected=0;
                for(int p=0;p<MAXP;++p)if(mask&(1u<<p)){if(e.rank[p]>best){best=e.rank[p];expected=1u<<p;}else if(e.rank[p]==best)expected|=1u<<p;}
                mismatches+=e.pot_winners(mask)!=expected;mismatches+=e.pot_winners(mask)!=expected;
            }
        }double result[]={double(mismatches),24*1023*2};probe_row("winner_cache.exhaustive_subsets_and_epochs",result,2);}
    {Engine e(42);auto& t=e.tree;t.players=3;t.chip_scale=100;t.nodes.resize(3);t.terms.resize(2);t.children={1,0};t.root=2;
        t.nodes[0].terminal=0;t.nodes[1].terminal=1;auto& n=t.nodes[2];n.actor=1;n.k=2;n.first=0;
        t.terms[0].base={-50,0,-100};t.terms[1].base={-50,0,-200};
        for(auto& term:t.terms)term.pots.push_back({150,2,7});
        t.prepare_constant_scalars(true);double value=e.scalar(2,0,0,0);
        double result[]={double(n.constant_scalar_mask),value,double(e.rng.double_calls+e.rng.bounded_calls+e.rng.int_calls)};
        probe_row("constant_scalar.reordered_tree_exact_value",result,3);
        n.actor=0;t.prepare_constant_scalars(true);double actor_mask[]={double(n.constant_scalar_mask)};probe_row("constant_scalar.never_skips_target_decision",actor_mask,1);
        t.raked=true;t.prepare_constant_scalars(true);double rake_mask[]={double(t.constant_scalar_nodes),double(t.constant_scalar_shortcuts)};probe_row("constant_scalar.rake_disabled",rake_mask,2);}
    const std::vector<std::vector<double>> cases={{4.5,-1.5},{0,0},{-5,-2,-1},{9,-8},{100,-3,-5},{100,-5,-5},{100,-3,-5,-3},{-2,3,1}};
    for(size_t i=0;i<cases.size();++i){double p[MAXA];normalize(cases[i].data(),int(cases[i].size()),i>=3&&i<=6,p);probe_row("normalization."+std::to_string(i),p,cases[i].size());}
    for(int st=0;st<2;++st)for(double z:{0.,1.,100.}){Node n;n.actor=0;n.k=2;n.buckets=1;n.street=st;n.init();double p[]={.25,.75},q[]={4,-2};n.update(rng,0,p,q,1,z);probe_row("store."+std::to_string(st)+".z"+std::to_string(int(z))+".first",n.raw.data(),n.raw.size());p[0]=p[1]=.5;q[0]=2;q[1]=6;n.update(rng,0,p,q,1,z);probe_row("store."+std::to_string(st)+".z"+std::to_string(int(z))+".second",n.raw.data(),n.raw.size());}
    {Node n;n.actor=0;n.k=2;n.buckets=1;n.street=0;n.init();double p[]={.25,.75},q[]={4,-2};rng.scripted_integer=1;
        for(int i=0;i<5;++i)n.update(rng,0,p,q,1,0);probe_row("cached_counter.after5",n.raw.data(),n.raw.size());
        rng.scripted_integer=0;n.update(rng,0,p,q,1,0);probe_row("cached_counter.after6refresh",n.raw.data(),n.raw.size());
        n.raw.assign(6,0);n.raw[0]=60000000;n.updates=60000000;n.update(rng,0,p,q,1,0);probe_row("counter_60m_double",n.raw.data(),n.raw.size());}
    for(bool v4:{false,true})for(int gate:{0,1})for(bool scalar:{false,true}){
        Engine e(42);e.v4=v4;e.rng.scripted=true;e.rng.gate=gate;e.tree.players=2;e.tree.nodes.resize(3);e.tree.children={1,2};e.tree.terms.resize(2);
        auto& n=e.tree.nodes[0];n.actor=0;n.street=0;n.k=2;n.buckets=1;n.init();e.tree.nodes[1].terminal=0;e.tree.nodes[2].terminal=1;
        e.tree.terms[0].synthetic=e.tree.terms[1].synthetic=true;e.tree.terms[0].value={-1,1};e.tree.terms[1].value={30,-30};e.bucket_ready[0]=true;
        double value=scalar?e.scalar(0,0,0,1):e.vector(0)[0];double a[]={value,double(n.updates),double(e.rng.bounded_calls)};
        std::string id=std::string(scalar?"scalar":"vector")+".v"+(v4?"4":"3")+".gate"+std::to_string(gate);probe_row(id+".return_counter_rng",a,3);probe_row(id+".raw",n.raw.data(),n.raw.size());
    }
    // Equal winner set across dead-money contribution levels must merge before
    // integer division: pot 303 split three ways is 101 each, not 100/100/103.
    {Engine e(42);e.tree.players=5;e.tree.terms.resize(1);auto& t=e.tree.terms[0];t.base={-100,-100,-100,-1,-2};t.paid={100,100,100,1,2};t.pots={{5,7},{4,7},{294,7}};e.rank_ready=true;e.rank[0]=e.rank[1]=e.rank[2]=100;e.rank[3]=e.rank[4]=0;probe_row("settlement.merged_tie_tiers",e.terminal(0),5);}
    {Engine e(42);e.tree.players=5;e.tree.terms.resize(1);auto& t=e.tree.terms[0];t.base={-100,-100,-100,-1,-1};t.paid={100,100,100,1,1};t.pots={{5,7},{297,7}};e.rank_ready=true;e.rank[0]=e.rank[1]=e.rank[2]=100;probe_row("settlement.odd_remainder_to_high_seat",e.terminal(0),5);}
    // The side-pot winner, rather than the main-pot winner, receives seat 1's bounty.
    {Engine e(42);e.tree.players=4;e.tree.initial={50,100,150,200};e.tree.terms.resize(1);
        auto& t=e.tree.terms[0];t.base={-50,-100,-150,-200};t.paid={50,100,150,200};t.pots={{200,15,15},{150,14,14},{100,12,12},{50,8,8}};
        e.rank_ready=true;e.rank[0]=4;e.rank[1]=2;e.rank[2]=3;e.rank[3]=1;
        hrc_equity::EquityConfig c;c.mode=hrc_equity::Mode::ICM;c.bounty_mode=hrc_equity::BountyMode::Progressive;
        c.initial_stacks={50,100,150,200};c.payouts={0};c.bounties={10,20,30,40};c.immediate_fraction=.5;
        e.tree.equity=std::make_unique<hrc_equity::Calculator>(c);probe_row("settlement.pko_side_pot_killer",e.terminal(0),4);}
    {Engine e(42);e.tree.players=3;e.tree.initial={100,100,100};e.tree.terms.resize(1);
        auto& t=e.tree.terms[0];t.base={-100,-100,-100};t.paid={100,100,100};t.pots={{300,7,7}};
        e.rank_ready=true;e.rank[0]=e.rank[2]=2;e.rank[1]=1;
        hrc_equity::EquityConfig c;c.mode=hrc_equity::Mode::ICM;c.bounty_mode=hrc_equity::BountyMode::Fixed;
        c.initial_stacks={100,100,100};c.payouts={0};c.bounties={10,10,10};
        e.tree.equity=std::make_unique<hrc_equity::Calculator>(c);probe_row("settlement.ko_shared_killer",e.terminal(0),3);}
    {Engine e(42);e.tree.players=2;e.tree.track_ci=true;e.tree.nodes.resize(1);auto& n=e.tree.nodes[0];n.k=2;n.buckets=1;n.actor=0;n.init();n.first=0;e.tree.children={0,0};
        // Direct integration fixture: the snapshot node set is supplied here,
        // avoiding a cyclic topology traversal in start_ci.
        e.ci_nodes={0};e.ci=std::make_unique<hrc_ci::Tracker>(e.ci_snapshots(),0);
        Random r;r.scripted=true;double p[]={.25,.75},q[]={4,-2};n.update(r,0,p,q,1,1);e.samples=1;e.poll_ci(15000);
        double out[]={e.ci->ci,n.raw[0],double(e.ci->history.size())};probe_row("ci.integrated_store_flush",out,3);}
    {Node n;n.k=2;n.buckets=1;n.actor=0;n.init();n.frequency=std::make_unique<hrc_policy::FrequencyStore>(1,2,std::vector<double>{.25,hrc_policy::nan()});Random r;r.scripted=true;double p[]={.5,.5},q[]={4,0};n.update(r,0,p,q,1,1);p[0]=1;p[1]=0;q[0]=0;q[1]=8;n.update(r,0,p,q,2,0);probe_row("frequency.integrated_raw",n.storage().data(),n.storage().size());n.strategy(0,p);probe_row("frequency.integrated_strategy",p,2);}
}

int main(int argc,char** argv){auto invocation_start=std::chrono::steady_clock::now(),training_start=invocation_start;bool training_started=false;std::string interrupted_reason="cancelled";double time_goal=-1,hard_time=-1;try{
    if(argc==2&&std::string(argv[1])=="--self-test"){probes();return 0;}
    if(argc<7)throw std::runtime_error("Usage: solver tree.bin resources samples seed output_dir v4|v3 [resume.bin]");
    uint64_t goal=std::stoull(argv[3]),seed=std::stoull(argv[4]);
    bool explicit_additional_budget=argc>19;
    uint64_t additional_budget=explicit_additional_budget?std::stoull(argv[19]):1000000000ULL;
    if(!additional_budget||additional_budget>1000000000000ULL)throw std::runtime_error("Additional sample budget must be 1..1000000000000");
    if(goal>(explicit_additional_budget?1000000000000ULL:1000000000ULL))throw std::runtime_error(explicit_additional_budget?"Maximum cumulative samples is 1000000000000":"Maximum 1000000000 samples");
    time_goal=argc>10?std::stod(argv[10]):-1;double ci_goal=argc>11?std::stod(argv[11]):-1;hard_time=argc>12?std::stod(argv[12]):-1;
    for(double t:{time_goal,hard_time})if(t!=-1&&(!std::isfinite(t)||t<.1||t>86400))throw std::runtime_error("Invalid seconds target");if(ci_goal!=-1&&(!std::isfinite(ci_goal)||ci_goal<=0))throw std::runtime_error("Invalid CI target");
    auto last_cancel_poll=invocation_start-std::chrono::seconds(1);std::mutex cancellation_mutex;
    auto cancelled_or_timed=[&](){std::lock_guard<std::mutex> guard(cancellation_mutex);auto now=std::chrono::steady_clock::now();if(std::chrono::duration<double>(now-last_cancel_poll).count()<.025)return false;last_cancel_poll=now;
        if(fs::exists(fs::path(argv[5])/"cancel.request")){interrupted_reason="cancelled";return true;}
        if(training_started){double seconds=std::chrono::duration<double>(now-training_start).count();if(time_goal>0&&seconds>=time_goal){interrupted_reason="time_target";return true;}if(hard_time>0&&seconds>=hard_time){interrupted_reason="hard_time";return true;}}return false;};
    uint64_t memory_budget=argc>13?std::stoull(argv[13]):uint64_t(1)<<30;
    int training_threads=argc>14?std::stoi(argv[14]):1;if(training_threads<1||training_threads>32)throw std::runtime_error("Training threads require 1..32");
    bool constant_scalar_requested=true;if(argc>15){std::string option=argv[15];if(option!="0"&&option!="1")throw std::runtime_error("Constant scalar shortcuts require 0 or 1");constant_scalar_requested=option=="1";}
    auto runtime_flag=[&](int position,const char* name){if(argc<=position)return true;std::string option=argv[position];if(option!="0"&&option!="1")throw std::invalid_argument(std::string(name)+" requires 0 or 1");return option=="1";};
    const bool native_qos_requested=runtime_flag(23,"Native process HighQoS");
    const bool native_qos_active=configure_native_high_qos(native_qos_requested);
    const bool terminal_table_requested=runtime_flag(20,"Terminal tables"),adaptive_parallel_requested=runtime_flag(21,"Adaptive parallel scheduler");
    Engine e(seed);if(std::string(argv[6])!="v4"&&std::string(argv[6])!="v3")throw std::runtime_error("Unknown solver mode");e.v4=std::string(argv[6])=="v4";e.tree.load(argv[1],argv[2],cancelled_or_timed,memory_budget);
    int runtime_ci=argc>17?std::stoi(argv[17]):-1;if(runtime_ci < -1||runtime_ci>1)throw std::invalid_argument("Runtime CI requires -1, 0 or 1");if(runtime_ci>=0)e.tree.track_ci=runtime_ci!=0;e.ci_target=ci_goal;
    e.tree.prepare_constant_scalars(constant_scalar_requested);
    if(ci_goal>0&&!e.tree.track_ci)throw std::runtime_error("CI target requires tracking enabled in tree");
    bool needs_post=false;for(auto& n:e.tree.nodes)if(n.k&&n.street>0)needs_post=true;
    std::unique_ptr<hrc_cards::AbstractionTables> tables;if(needs_post&&!e.tree.chance){uint64_t bytes=32768;for(int st=1;st<=3;++st){auto prefix=fs::path(argv[2])/("street"+std::to_string(st));bytes+=fs::file_size(prefix.string()+".buckets.u16")/(st==1?1:2)+hrc_cards::FlatBoardRowMap::memory_bytes_for(2*(fs::file_size(prefix.string()+".boards.u64")/sizeof(uint64_t)))+fs::file_size(prefix.string()+".boards.u64");}e.tree.reserve_budget(bytes);tables=std::make_unique<hrc_cards::AbstractionTables>(argv[2]);e.tables=tables.get();}
    if(e.tree.equity)e.tree.reserve_budget(e.tree.equity->cache_bytes());
    if(e.tree.fgs)e.tree.reserve_budget(e.tree.fgs->cache_memory_bound());
    if(argc>=8&&std::string(argv[7])!="-")e.resume(argv[7]);
    if(goal>e.samples&&goal-e.samples>additional_budget)throw std::runtime_error("Requested additional samples exceed the sample budget");
    int root_mean_override=argc>18?std::stoi(argv[18]):-1;if(root_mean_override < -1||root_mean_override>1)throw std::invalid_argument("Root mean validity requires -1, 0 or 1");if(root_mean_override>=0)e.root_mean_valid=e.root_mean_valid&&root_mean_override!=0;
    e.scope=std::make_shared<SamplingScope>(e.tree,argc>16?argv[16]:"-");if(e.scope->selected)e.root_mean_valid=false;
    bool reset_r=argc>=9&&std::string(argv[8])=="1",reset_a=argc>=10&&std::string(argv[9])=="1";if(reset_r||reset_a)e.reset(reset_r,reset_a);fs::path output=argv[5];fs::create_directories(output);
    if(training_threads==1)e.parallel_rng.clear();e.training_threads=e.parallel_rng.empty()?1:int(e.parallel_rng.size());
    // FGS can fail or cancel inside baseline evaluation: keep the pre-baseline
    // boundary. Other models need only one startup save, after worker RNG setup.
    if(e.tree.fgs){e.save(output);e.tree.fgs_baseline=e.tree.fgs->equities(e.tree.fgs_context);}
    std::unique_ptr<ParallelTrainer> parallel;
    try {if(training_threads>1)parallel=std::make_unique<ParallelTrainer>(e,training_threads,seed);}
    catch(...){if(!e.tree.fgs)e.save(output);throw;} // No worker has trained yet.
    // Optional acceleration must not consume memory needed by the requested CI
    // snapshots. Reserve only; the original post-save flush/snapshot stays put.
    try {e.reserve_ci_memory();}catch(...){e.save(output);throw;}
    const auto terminal_table_start=std::chrono::steady_clock::now();
    if(terminal_table_requested&&e.samples<goal&&!e.tree.raked&&!e.tree.fgs){
        const uint64_t table_budget=std::min(uint64_t(64)<<20,(e.tree.max_memory-e.tree.estimated_memory)/4);
        try {auto table=e.make_terminal_table(size_t(table_budget),cancelled_or_timed);
            if(table){e.tree.reserve_budget(table->bytes());e.tree.terminal_tables=std::move(table);}}
        catch(const hrc_terminal_table::Cancelled&){e.save(output);throw hrc_fgs::Cancelled("Terminal table preparation cancelled");}
    }
    const bool unlocked_strategy_reads=parallel?parallel->prepare_unlocked_reads():Engine::prepare_unlocked_reads({&e},e.tree);
    const bool terminal_pointer_enabled=parallel?parallel->prepare_terminal_pointers():Engine::prepare_terminal_pointers({&e},e.tree);
    const double terminal_table_setup_seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-terminal_table_start).count();
    auto write_optimization=[&](){const auto& table=e.tree.terminal_tables;
        std::cout<<",\"native_qos_requested\":"<<(native_qos_requested?"true":"false")<<",\"native_qos_active\":"<<(native_qos_active?"true":"false");
        std::cout<<",\"terminal_pointer_cache\":"<<(terminal_pointer_enabled?"true":"false")<<",\"terminal_pointer_cache_bytes\":"<<(e.terminal_pointer_bytes*training_threads);
        std::cout<<",\"unlocked_strategy_reads\":"<<(unlocked_strategy_reads?"true":"false")<<",\"unlocked_read_cache_bytes\":"<<e.unlocked_cache_bytes*training_threads;
        std::cout<<",\"terminal_tables\":"<<(table?"true":"false")<<",\"terminal_table_bytes\":"<<(table?table->bytes():0)<<",\"terminal_table_outcomes\":"<<(table?table->outcomes():0)
            <<",\"terminal_table_setup_seconds\":"<<terminal_table_setup_seconds<<",\"terminal_table_lookups\":"<<e.terminal_table_lookups<<",\"terminal_settlements\":"<<e.terminal_settlements
            <<",\"parallel_scheduler\":\""<<(parallel?(adaptive_parallel_requested?"independent_blocks":"synchronized_batches"):"serial")<<"\",\"parallel_control_rounds\":"<<(parallel?parallel->control_rounds():0)
            <<",\"parallel_claimed_blocks\":"<<(parallel?parallel->claimed_blocks():0);};
    double before_save=e.checkpoint_seconds;e.save(output);
    auto start=std::chrono::steady_clock::now(),last=start;uint64_t initial=e.samples;bool cancelled=false;double initial_checkpoint_seconds=e.checkpoint_seconds;
    CheckpointSchedule checkpoint_schedule(start,e.checkpoint_seconds-before_save);
    training_start=start;training_started=true;std::string stop_reason;bool target_reached=false;
    e.start_ci(0);
    // CI initialization flushes stores and adds index metadata even without a
    // new sample. With CI off, the startup save already covers a no-work run.
    bool checkpoint_current=!e.ci;
    std::cout<<"{\"kind\":\"started\",\"iteration\":"<<e.samples<<",\"total\":"<<goal<<",\"training_threads\":"<<training_threads<<",\"fresh_zero\":"<<(initial==0?"true":"false")<<",\"estimated_memory_bytes\":"<<e.tree.estimated_memory<<",\"max_memory_bytes\":"<<e.tree.max_memory;write_optimization();e.write_scope(std::cout);std::cout<<"}"<<std::endl;
    while(e.samples<goal){
        if(parallel&&adaptive_parallel_requested)parallel->run_adaptive(goal-e.samples,std::chrono::steady_clock::now()+std::chrono::milliseconds(50));
        else{uint64_t limit=std::min(goal,e.samples+250*uint64_t(training_threads));if(parallel)parallel->run(limit-e.samples);else while(e.samples<limit)e.step();}
        checkpoint_current=false;
        if(fs::exists(output/"cancel.request")){cancelled=true;stop_reason="cancelled";break;}
        auto now=std::chrono::steady_clock::now();double seconds=std::chrono::duration<double>(now-start).count();
        e.poll_ci(std::chrono::duration_cast<std::chrono::milliseconds>(now-start).count());
        if(std::chrono::duration<double>(now-last).count()>=.5||e.samples==goal){std::cout<<std::setprecision(12)<<"{\"kind\":\"progress\",\"iteration\":"<<e.samples<<",\"total\":"<<goal<<",\"elapsed_seconds\":"<<seconds<<",\"samples_per_second\":"<<(e.samples-initial)/std::max(seconds,1e-9)<<",\"ci\":";e.write_ci(std::cout);e.write_scope(std::cout);std::cout<<"}"<<std::endl;last=now;}
        if(ci_goal>0&&e.ci&&std::isfinite(e.ci->ci)&&e.ci->ci<ci_goal){stop_reason="ci_target";target_reached=true;break;}
        if(time_goal>0&&seconds>=time_goal){stop_reason="time_target";target_reached=true;break;}
        if(hard_time>0&&seconds>=hard_time){stop_reason="hard_time";break;}
        if(e.samples<goal&&checkpoint_schedule.due(std::chrono::steady_clock::now())){
            before_save=e.checkpoint_seconds;e.save(output);checkpoint_current=true;
            checkpoint_schedule.saved(std::chrono::steady_clock::now(),e.checkpoint_seconds-before_save);
        }
    }
    if(stop_reason.empty()){stop_reason=(time_goal>0||ci_goal>0)?"sample_cap":"sample_target";target_reached=stop_reason=="sample_target";}
    if(!checkpoint_current)e.save(output);double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::cout<<"{\"kind\":\"finished\",\"iteration\":"<<e.samples<<",\"total\":"<<goal<<",\"training_threads\":"<<training_threads<<",\"parallel_mode\":\""<<(parallel?"async_shared":"serial")<<"\",\"cancelled\":"<<(cancelled?"true":"false")<<",\"stop_reason\":\""<<stop_reason<<"\",\"target_reached\":"<<(target_reached?"true":"false")<<",\"elapsed_seconds\":"<<elapsed<<",\"vector_calls\":"<<e.vector_calls<<",\"scalar_calls\":"<<e.scalar_calls<<",\"terminal_calls\":"<<e.terminal_calls<<",\"constant_scalar_shortcuts\":"<<(e.tree.constant_scalar_shortcuts?"true":"false")<<",\"constant_scalar_nodes\":"<<e.tree.constant_scalar_nodes<<",\"constant_scalar_calls\":"<<e.constant_scalar_calls<<",\"checkpoint_writes\":"<<e.checkpoint_writes<<",\"checkpoint_seconds\":"<<e.checkpoint_seconds<<",\"training_checkpoint_seconds\":"<<(e.checkpoint_seconds-initial_checkpoint_seconds)<<",\"checkpoint_policy\":\"adaptive_wall_time\",\"checkpoint_interval_seconds\":"<<checkpoint_schedule.interval_seconds<<",\"ci\":";e.write_ci(std::cout);write_optimization();e.write_scope(std::cout);if(e.tree.fgs){const auto&s=e.tree.fgs->stats();std::cout<<",\"fgs\":{\"states\":"<<s.states<<",\"sweeps\":"<<s.sweeps<<",\"cache_hits\":"<<s.cache_hits<<",\"terminal_calls\":"<<s.terminal_calls<<",\"terminal_cache_hits\":"<<s.terminal_cache_hits<<",\"work_seconds\":"<<e.tree.fgs->work_seconds()<<",\"stats_scope\":\"worker0\",\"resource_budget_scope\":\"per_worker\"}";}std::cout<<"}"<<std::endl;return 0;
}catch(const hrc_fgs::Cancelled& ex){uint64_t saved=0;try{std::ifstream in(fs::path(argv[5])/"checkpoint.bin",std::ios::binary);in.seekg(16);saved=read<uint64_t>(in);}catch(...){}double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-(training_started?training_start:invocation_start)).count();std::cout<<"{\"kind\":\"finished\",\"iteration\":"<<saved<<",\"total\":"<<argv[3]<<",\"cancelled\":"<<(interrupted_reason=="cancelled"?"true":"false")<<",\"stop_reason\":\""<<interrupted_reason<<"\",\"target_reached\":"<<(interrupted_reason=="time_target"?"true":"false")<<",\"elapsed_seconds\":"<<elapsed<<",\"rolled_back_to_checkpoint\":true,\"partial_iteration_saved\":false}"<<std::endl;return 0;
}catch(const hrc_fgs::ResourceLimit& ex){std::cout<<"{\"kind\":\"failed\",\"resource_limit\":true,\"partial_iteration_saved\":false}"<<std::endl;std::cerr<<ex.what()<<std::endl;return 2;
}catch(const NativeResourceLimit& ex){std::cout<<"{\"kind\":\"failed\",\"resource_limit\":true,\"partial_iteration_saved\":false}"<<std::endl;std::cerr<<ex.what()<<std::endl;return 2;
}catch(const std::exception& ex){std::cerr<<ex.what()<<std::endl;return 1;}}
