#pragma once
// Audited mq/mr/ms recent-policy-drift statistic, not an exploitability bound.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <limits>
#include <stdexcept>
#include <vector>
namespace hrc_ci {
struct Snapshot { double count=0; std::vector<double> policy; };
struct Record { int ordinal=0; int64_t timestamp=0; uint64_t samples=0; double ci=0; };
struct Tracker {
    std::vector<Snapshot> previous;
    std::deque<Record> history;
    double ci=std::numeric_limits<double>::quiet_NaN(),speed_per_ms=0,total=0;
    int64_t last_time=0,interval=15000,first_time=0;
    bool has_first=false;
    Record first_record;
    explicit Tracker(std::vector<Snapshot> snapshots={},int64_t now=0){restart(std::move(snapshots),now);}
    void restart(std::vector<Snapshot> snapshots,int64_t now) {
        previous=std::move(snapshots);total=0;
        for(const auto& s:previous){if(!std::isfinite(s.count)||s.count<0)throw std::invalid_argument("Invalid CI count");total+=s.count;}
        history.clear();ci=std::numeric_limits<double>::quiet_NaN();speed_per_ms=0;last_time=now;interval=15000;has_first=false;first_time=0;
    }
    // Timestamps supplied by caller in milliseconds. duration is measured work
    // time. An application's wall clock is not read inside this pure module.
    bool update(int64_t now,uint64_t samples,std::vector<Snapshot> snapshots,int64_t duration=0) {
        if(now-last_time<interval)return false;
        if(snapshots.size()!=previous.size()||duration<0)throw std::invalid_argument("Invalid CI snapshot dimensions/time");
        double next=0,numerator=0,denominator=0;
        for(size_t i=0;i<snapshots.size();++i){const auto& n=snapshots[i];const auto& old=previous[i];
            if(!std::isfinite(n.count)||n.count<old.count||n.policy.size()!=old.policy.size())throw std::invalid_argument("CI counts decreased or dimensions changed; restart tracker");
            double weight=std::sqrt(n.count-old.count),distance=0;
            for(size_t j=0;j<n.policy.size();++j){if(!std::isfinite(n.policy[j]))throw std::invalid_argument("Nonfinite CI policy");distance+=std::abs(n.policy[j]-old.policy[j]);}
            next+=n.count;numerator+=weight*distance/2;denominator+=weight;
        }
        previous=std::move(snapshots);
        if(next-total>0){double raw=std::sqrt(numerator/denominator*previous.size()/(next-total)*1e8);Record rec;
            if(!has_first){ci=raw;rec={0,now,samples,ci};has_first=true;first_time=now;first_record=rec;}
            else{double alpha=std::min(history.back().ordinal*.05,.75);ci=alpha*ci+(1-alpha)*raw;
                speed_per_ms=double(samples-history.back().samples)/double(now-last_time);rec={history.back().ordinal+1,now,samples,ci};}
            history.push_back(rec);int64_t cutoff=now-int64_t(std::min((now-first_time)*.75,7200000.0));
            while(history.size()>3&&history.front().timestamp<cutoff)history.pop_front();
        }
        total=next;interval=std::max<int64_t>(15000,duration*50);last_time=now+duration;return true;
    }
    double samples_per_second() const {return speed_per_ms*1000;}
    double progress(double target,const Record* reference) const {
        if(!reference||reference->ci<ci)return 0;
        if(ci<=target)return 1;
        double first=std::pow(reference->ci,-1.7),current=std::pow(ci,-1.7),goal=std::pow(target,-1.7);
        return std::max(0.0,1-(goal-current)/(goal-first));
    }
};
} // namespace hrc_ci
