#pragma once
// Independent implementation of audited HRC my/mx/mz numeric semantics.
// No application classes, saved policies, or solver calls are used.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace hrc_policy {
inline void require(bool ok, const char* message) { if (!ok) throw std::invalid_argument(message); }
inline double nan() { return std::numeric_limits<double>::quiet_NaN(); }
inline std::vector<double> positive_normalize(const double* p, int k) {
    std::vector<double> out(k); double sum=0;
    for(int a=0;a<k;++a) sum+=(out[a]=std::max(0.0,p[a]));
    if(sum>0) for(double& v:out) v/=sum;
    else std::fill(out.begin(),out.end(),1.0/k);
    return out;
}

// rows[action] empty = unlocked; otherwise exactly buckets probabilities.
// Empty wrapper should not replace the underlying store's normalization.
struct BucketLocks {
    int actions, buckets;
    std::vector<std::vector<double>> rows;
    BucketLocks(int k,int h,std::vector<std::vector<double>> r={}) : actions(k),buckets(h),rows(std::move(r)) {
        require(k>=2 && k<=16 && h>0,"Invalid lock dimensions");
        if(rows.empty()) rows.resize(k);
        require(int(rows.size())==k,"Lock action count mismatch");
        for(const auto& row:rows) {
            require(row.empty() || int(row.size())==h,"Lock bucket count mismatch");
            for(double p:row) require(std::isfinite(p)&&p>=0&&p<=1,"Lock probabilities must be finite in [0,1]");
        }
        for(int b=0;b<h;++b) { double s=0; for(const auto& row:rows) if(!row.empty()) s+=row[b];
            require(s<=1.0+1e-12,"Locked probabilities exceed one"); }
    }
    int count() const { int n=0; for(const auto& r:rows)n+=!r.empty(); return n; }
    bool active() const { return count()!=0; }
    // Literal mx.a([DI[Z[DDIZ)[D behavior, including all-locked mass < 1.
    void compose_into(const double* base,int bucket,bool training,double* out,bool special=false) const {
        require(bucket>=0&&bucket<buckets,"Lock bucket out of range");
        const int n=count(); double mass=0;
        double value[16];std::fill(value,value+actions,nan());std::fill(out,out+actions,0);
        for(int a=0;a<actions;++a) if(!rows[a].empty()) {value[a]=rows[a][bucket];mass+=value[a];}
        if(training&&special) value[0]=(n+1>=actions)?nan():0.0;
        if(n==actions) {std::copy(value,value+actions,out);return;}
        if(mass>=1) {for(int a=0;a<actions;++a)if(!rows[a].empty())out[a]=value[a];return;}
        if(n==actions-1) {for(int a=0;a<actions;++a)out[a]=rows[a].empty()?1-mass:value[a];return;}
        double threshold=0;
        if(training&&mass>0&&mass<1) {
            int positive=0; for(int a=0;a<actions;++a)positive+=!rows[a].empty()&&value[a]>0;
            if(positive>1) {
                int best=-1;
                for(int a=0;a<actions;++a) if(rows[a].empty()) {if(best<0||base[best]<base[a])best=a;} else out[a]=value[a];
                out[best]=1-mass;return;
            }
            for(int a=0;a<actions;++a)if(!rows[a].empty()&&value[a]<1)threshold-=base[a]*value[a]/(1-value[a]);
        }
        double sum=0;for(int a=0;a<actions;++a)if(rows[a].empty())sum+=std::max(0.0,base[a]-threshold);
        bool first=true;
        for(int a=0;a<actions;++a) {
            if(!rows[a].empty())out[a]=value[a];
            else if(sum==0){out[a]=first?1-mass:0;first=false;}
            else out[a]=(1-mass)*std::max(0.0,base[a]-threshold)/sum;
        }
        if(sum!=0){double check=0;for(int a=0;a<actions;++a)check+=out[a];if(std::abs(check-1)>=1e-12)throw std::runtime_error("Unexpected locked strategy sum");}
    }
    std::vector<double> compose(const double* base,int bucket,bool training,bool special=false) const {
        std::vector<double> out(actions);compose_into(base,bucket,training,out.data(),special);
        return out;
    }
    // my edit: preserve edited action, proportionally reduce other locks if necessary.
    void edit(int action,const std::vector<double>& values) {
        require(action>=0&&action<actions&&int(values.size())==buckets,"Invalid lock edit");
        for(double p:values)require(std::isfinite(p),"Nonfinite lock edit");
        rows[action]=values;for(double& p:rows[action])p=std::min(1.0,std::max(0.0,p));
        for(int b=0;b<buckets;++b) {
            double sum=0;for(const auto& row:rows)if(!row.empty())sum+=row[b];
            if(sum>1) {double scale=(1-rows[action][b])/(sum-rows[action][b]);
                for(int a=0;a<actions;++a)if(a!=action&&!rows[a].empty())rows[a][b]*=scale;}
        }
    }
    void unlock(int action) { require(action>=0&&action<actions,"Invalid lock action");rows[action].clear(); }
    // Caller supplies current composed display values, one per bucket.
    void lock_current(int action,const std::vector<double>& current) {
        require(action>=0&&action<actions,"Invalid lock action");
        if(!rows[action].empty())return;
        require(int(current.size())==buckets,"Lock bucket count mismatch");
        for(double p:current)require(std::isfinite(p)&&p>=0&&p<=1,"Invalid current lock probabilities");
        rows[action]=current;
    }
};

// Format63 is a distinct learning store, NOT an mE update followed by clipping.
// Single worker numeric semantics; root owns synchronization for shared use.
struct FrequencyStore {
    int buckets,actions,underlying_format;
    std::vector<double> raw,targets,edges,edge_sums,shared_sums;
    uint64_t updates=0;
    double minimum=double(std::numeric_limits<float>::max());
    double maximum=double(std::numeric_limits<float>::denorm_min());
    FrequencyStore(int h,int k,std::vector<double> target={},std::vector<double> edge={},int format=23)
      :buckets(h),actions(k),underlying_format(format),raw(1+k+h*(2*k+1),0),targets(std::move(target)),edges(std::move(edge)),shared_sums(k,0) {
        require(h>0&&k>=2&&k<=16,"Invalid frequency dimensions");
        if(targets.empty())targets.assign(k,nan());if(edges.empty())edges.assign(k,0);
        require(int(targets.size())==k&&int(edges.size())==k,"Frequency dimensions mismatch");
        double sum=0;for(double t:targets){require(std::isnan(t)||(std::isfinite(t)&&t>=0&&t<=1),"Invalid frequency target");if(!std::isnan(t))sum+=t;}
        require(sum<=1+1e-12,"Frequency targets exceed one");
        for(double e:edges)require(std::isfinite(e),"Nonfinite edge");edge_sums=edges;
    }
    int offset(int b) const {require(b>=0&&b<buckets,"Frequency bucket out of range");return 1+actions+b*(2*actions+1);}
    void relative_ev_into(int b,double* out) const {
        int r=offset(b);std::fill(out,out+actions,nan());double d=raw[r+actions];
        if(d>0)for(int a=0;a<actions;++a)out[a]=(raw[r+a]-raw[r])/d;
    }
    std::vector<double> relative_ev(int b) const {
        std::vector<double> out(actions);relative_ev_into(b,out.data());return out;
    }
    void strategy_into(int b,double* out,bool special=false) const {
        double ev[16];relative_ev_into(b,ev);int best=special?1:0;
        for(int a=best;a<actions;++a){ev[a]+=edges[a];if(ev[best]<ev[a])best=a;}
        std::fill(out,out+actions,0);out[best]=1;
    }
    std::vector<double> strategy(int b,bool special=false) const {
        std::vector<double> out(actions);strategy_into(b,out.data(),special);return out;
    }
    std::vector<double> display(int b) const {return positive_normalize(raw.data()+offset(b)+actions+1,actions);}
    void flush(){raw[0]=double(updates);for(int a=0;a<actions;++a){raw[1+a]=shared_sums[a];edges[a]=edge_sums[a];}}
    void sync_from_raw(){updates=uint64_t(std::floor(raw[0]+.5));for(int a=0;a<actions;++a){shared_sums[a]=raw[1+a];edge_sums[a]=edges[a];}}
    std::vector<double> aggregate(){flush();return positive_normalize(raw.data()+1,actions);}
    // refresh(x) must consume original ma.a(x) RNG: nextInt()%floor(sqrt(x))==0.
    // Return true means the single-thread cached-counter/edge CAS succeeds.
    template<class Refresh> void update(int b,const double* p,const double* q,double w,double z,Refresh&& refresh) {
        require(std::isfinite(w)&&std::isfinite(z),"Nonfinite frequency update weight");
        if(w<=0)return;
        int r=offset(b);double v=0;for(int a=0;a<actions;++a)if(p[a]>0)v+=p[a]*q[a];
        ++updates;double t=raw[0]+1;if(refresh(t))raw[0]=t=double(updates);
        for(int a=0;a<actions;++a){raw[r+a]+=w*(q[a]-v);raw[r+actions+1+a]+=t*p[a];}
        raw[r+actions]+=w;
        if(z>0) {
            bool cache=refresh(std::sqrt(t));double step=z/std::pow(t,1/std::sqrt(2.0));
            for(int a=0;a<actions;++a){if(q[a]<minimum)minimum=q[a];if(q[a]>maximum)maximum=q[a];}
            double span=std::max(maximum-minimum,0.0);
            for(int a=0;a<actions;++a)if(!std::isnan(targets[a])){edge_sums[a]+=span*step*(targets[a]-p[a]);if(cache)edges[a]=edge_sums[a];}
            z*=t;for(int a=0;a<actions;++a)shared_sums[a]+=z*p[a];
        }
    }
    void reset(bool regret,bool average) {
        if(regret){minimum=double(std::numeric_limits<float>::max());maximum=double(std::numeric_limits<float>::denorm_min());for(int a=0;a<actions;++a)if(!std::isnan(targets[a]))edges[a]=0;}
        if(average){for(int a=0;a<actions;++a)raw[1+a]*=1e-20;for(int b=0;b<buckets;++b)for(int a=0;a<actions;++a)raw[offset(b)+actions+1+a]*=1e-20;sync_from_raw();}
        if(regret){for(int b=0;b<buckets;++b)for(int a=0;a<=actions;++a)raw[offset(b)+a]*=1e-20;raw[0]=0;sync_from_raw();}
    }
};
} // namespace hrc_policy
