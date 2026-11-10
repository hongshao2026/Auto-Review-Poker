#include "../../native/hrc_chance.hpp"
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

static std::vector<std::string> split(const std::string&s,char separator) {
    std::vector<std::string> values;size_t start=0;
    for(;;){auto end=s.find(separator,start);values.push_back(s.substr(start,end-start));if(end==std::string::npos)break;start=end+1;}
    return values;
}
template<class T>void array(const T&values){std::cout<<'[';bool first=true;for(auto x:values){if(!first)std::cout<<',';first=false;std::cout<<x;}std::cout<<']';}
int main(int argc,char**argv) {
 try {
    std::ifstream input(argv[1]);std::string line;std::filesystem::create_directories(argv[2]);
    hrc_chance::Deal scratch;
    while(std::getline(input,line)) {
        if(line.empty())continue;if(line.back()=='\r')line.pop_back();auto v=split(line,'\t');hrc_chance::Config cfg;cfg.max_attempts=10000;
        cfg.board_history.clear();for(auto text:split(v[1],','))cfg.board_history.push_back(std::stoull(text));
        for(auto text:split(v[2],';')) {
            if(text=="-"){cfg.ranges.emplace_back();continue;}
            auto fields=split(text,'|');std::vector<double> weights(1326,std::stod(fields[0]));
            if(!fields[1].empty())for(auto term:split(fields[1],',')){auto pair=split(term,':');weights.at(std::stoi(pair[0]))=std::stod(pair[1]);}
            cfg.ranges.push_back(std::move(weights));
        }
        std::vector<double> doubles;std::vector<uint64_t> integers;
        for(auto text:split(v[3],','))doubles.push_back(std::stod(text));for(auto text:split(v[4],','))integers.push_back(std::stoull(text));
        uint64_t di=0,ii=0;std::vector<unsigned char> calls;
        auto record=[&](uint32_t tag,uint64_t value){for(int b=0;b<4;++b)calls.push_back(tag>>(b*8));for(int b=0;b<8;++b)calls.push_back(value>>(b*8));};
        auto next_int=[&](int bound){int n=int(integers[ii++%integers.size()]%bound);record(bound,n);return n;};
        auto next_double=[&](){double u=doubles[di++%doubles.size()];uint64_t bits;std::memcpy(&bits,&u,8);record(0,bits);return u;};
        hrc_chance::Sampler sampler(std::move(cfg));std::cout<<"{\"id\":\""<<v[0]<<"\",";
        try {
            hrc_chance::Deal deal;
            if(argc>3&&std::string(argv[3])=="--reuse"){
                sampler.sample_into(scratch,next_int,next_double,{},std::stoi(v[5]));deal=scratch;
            }else deal=sampler.sample(next_int,next_double,{},std::stoi(v[5]));
            std::cout<<"\"combos\":";array(deal.combos);std::cout<<",\"board\":";array(deal.board);
            std::cout<<",\"used\":"<<deal.used<<",\"attempts\":"<<deal.attempts<<",\"status\":\"ok\"";
        }catch(const hrc_chance::ResourceLimit& e){std::cout<<"\"status\":\"resource_limit\"";}
        std::cout<<",\"double_calls\":"<<di<<",\"integer_calls\":"<<ii<<"}\n";
        std::ofstream output(std::filesystem::path(argv[2])/(v[0]+".calls"),std::ios::binary);output.write(reinterpret_cast<char*>(calls.data()),calls.size());
    }
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
