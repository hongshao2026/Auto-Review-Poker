#include "../../native/hrc_policy.hpp"
#include "../../native/hrc_ci.hpp"
#include <iostream>
#include <iomanip>
#include <sstream>
#include <string>
#include <memory>
using V=std::vector<double>;
std::vector<std::string> split(const std::string&s,char d){std::vector<std::string> out;std::stringstream in(s);std::string t;while(std::getline(in,t,d))out.push_back(t);return out;}
V nums(const std::string&s){V v;if(s!="-")for(auto x:split(s,','))v.push_back(std::stod(x));return v;}
void num(double x){if(std::isnan(x))std::cout<<"NaN";else std::cout<<x;}
void vec(const V&v){std::cout<<'[';for(size_t i=0;i<v.size();++i){if(i)std::cout<<',';num(v[i]);}std::cout<<']';}
template<class F>void matrix(int h,F f){std::cout<<'[';for(int b=0;b<h;++b){if(b)std::cout<<',';vec(f(b));}std::cout<<']';}
void frequency(hrc_policy::FrequencyStore&s){std::cout<<"{\"raw\":";vec(s.raw);std::cout<<",\"edges\":";vec(s.edges);std::cout<<",\"edge_sums\":";vec(s.edge_sums);std::cout<<",\"shared_sums\":";vec(s.shared_sums);std::cout<<",\"updates\":"<<s.updates<<",\"minimum\":";num(s.minimum);std::cout<<",\"maximum\":";num(s.maximum);std::cout<<",\"strategy\":";matrix(s.buckets,[&](int b){return s.strategy(b);});std::cout<<",\"special\":";matrix(s.buckets,[&](int b){return s.strategy(b,true);});std::cout<<",\"display\":";matrix(s.buckets,[&](int b){return s.display(b);});std::cout<<",\"ev\":";matrix(s.buckets,[&](int b){return s.relative_ev(b);});std::cout<<'}';}
int main(){std::cout<<std::setprecision(17);std::string line;while(std::getline(std::cin,line)){if(line.empty())continue;auto p=split(line,'\t');try{
 if(p[0]=="L"){int k=std::stoi(p[2]),h=std::stoi(p[3]);V r=nums(p[4]),av=nums(p[5]);std::vector<V> rows;for(auto s:split(p[6],'/'))rows.push_back(nums(s));hrc_policy::BucketLocks l(k,h,rows);
  if(p[7]!="-")for(auto edit:split(p[7],';')){auto e=split(edit,':');int a=std::stoi(e[0]);if(e[1]=="-")l.unlock(a);else if(e[1]=="+"){V cur(h);for(int b=0;b<h;++b)cur[b]=l.active()?l.compose(av.data()+b*k,b,false)[a]:hrc_policy::positive_normalize(av.data()+b*k,k)[a];l.lock_current(a,cur);}else l.edit(a,nums(e[1]));}
  std::cout<<"{\"id\":\""<<p[1]<<"\",\"display\":";matrix(h,[&](int b){return l.active()?l.compose(av.data()+b*k,b,false):hrc_policy::positive_normalize(av.data()+b*k,k);});
  std::cout<<",\"training\":";matrix(h,[&](int b){return l.compose(r.data()+b*k,b,true,std::stoi(p[8]));});std::cout<<",\"rows\":[";for(int a=0;a<k;++a){if(a)std::cout<<',';vec(l.rows[a]);}std::cout<<"]}\n";
 }else if(p[0]=="F"){hrc_policy::FrequencyStore s(std::stoi(p[2]),std::stoi(p[3]),nums(p[4]),nums(p[5]));std::cout<<"{\"id\":\""<<p[1]<<"\",\"snapshots\":[";frequency(s);
  for(auto st:split(p[6],'|')){auto v=split(st,';');int b=std::stoi(v[0]),rng=std::stoi(v[3]);V pr=nums(v[4]),q=nums(v[5]);s.update(b,pr.data(),q.data(),std::stod(v[1]),std::stod(v[2]),[&](double x){return rng%int(std::floor(std::sqrt(x)))==0;});if(std::stoi(v[6]))s.flush();if(std::stoi(v[7])||std::stoi(v[8]))s.reset(std::stoi(v[7]),std::stoi(v[8]));std::cout<<',';frequency(s);}std::cout<<"]}\n";
 }else if(p[0]=="C"){auto counts=nums(p[2]);auto policies=split(p[3],'/');std::vector<hrc_ci::Snapshot> snaps;for(size_t i=0;i<counts.size();++i)snaps.push_back({counts[i],nums(policies[i])});hrc_ci::Tracker tracker(snaps,0);std::cout<<"{\"id\":\""<<p[1]<<"\",\"snapshots\":[";bool first=true;
  for(auto st:split(p[4],'|')){auto v=split(st,';');int64_t now=std::stoll(v[0]),duration=std::stoll(v[2]);counts=nums(v[3]);policies=split(v[4],'/');snaps.clear();for(size_t i=0;i<counts.size();++i)snaps.push_back({counts[i],nums(policies[i])});if(std::stoi(v[5]))tracker.restart(snaps,now);bool accepted=tracker.update(now,std::stoull(v[1]),snaps,duration);if(!first)std::cout<<',';first=false;std::cout<<"{\"accepted\":"<<(accepted?"true":"false")<<",\"ci\":";num(tracker.ci);std::cout<<",\"speed\":";num(tracker.samples_per_second());std::cout<<",\"interval\":"<<tracker.interval<<",\"last_time\":"<<tracker.last_time<<",\"history\":[";for(size_t i=0;i<tracker.history.size();++i){if(i)std::cout<<',';auto rec=tracker.history[i];std::cout<<'['<<rec.ordinal<<','<<rec.timestamp<<','<<rec.samples<<',';num(rec.ci);std::cout<<']';}std::cout<<"],\"progress\":[";int ti=0;for(double target:{1.,5.,50.,500.}){if(ti++)std::cout<<',';num(tracker.progress(target,tracker.has_first?&tracker.first_record:nullptr));}std::cout<<"]}";}std::cout<<"]}\n";
 }else throw std::runtime_error("Unknown opcode");
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 2;}}
}
