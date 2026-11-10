#include "../../native/hrc_settlement.hpp"
#include <iostream>
#include <sstream>
#include <string>

template<class T>void array(const std::vector<T>& values){std::cout<<'[';for(size_t i=0;i<values.size();++i){if(i)std::cout<<',';std::cout<<values[i];}std::cout<<']';}
std::vector<int64_t> ints(std::string s){for(char&c:s)if(c==',')c=' ';std::istringstream in(s);int64_t v;std::vector<int64_t> out;while(in>>v)out.push_back(v);return out;}
int main(){
    for(std::string line;std::getline(std::cin,line);){
        std::vector<std::string> fields;std::istringstream input(line);for(std::string v;std::getline(input,v,'\t');)fields.push_back(v);
        try{
            if(fields.size()!=11)throw std::invalid_argument("Expected 11 fields");
            auto r=ints(fields[1]),p=ints(fields[2]),raw_rank=ints(fields[4]);std::vector<int> rank(raw_rank.begin(),raw_rank.end());
            hrc_settlement::RakeConfig config{hrc_settlement::RakeMode(std::stoi(fields[8])),std::stod(fields[9]),std::stoll(fields[10])};
            auto out=hrc_settlement::settle(r,p,uint16_t(std::stoi(fields[3])),rank,std::stoll(fields[5]),std::stoi(fields[6]),std::stoi(fields[7]),config);
            std::cout<<"{\"id\":\""<<fields[0]<<"\",\"stacks\":";array(out.stacks);std::cout<<",\"winner_masks\":";array(out.winner_masks);
            std::cout<<",\"rake\":"<<out.rake<<",\"tied_award\":"<<(out.tied_award?"true":"false")<<",\"pots\":[";
            for(size_t i=0;i<out.pots.size();++i){if(i)std::cout<<',';auto&pot=out.pots[i];std::cout<<"{\"rake\":"<<pot.rake<<",\"awards\":";array(pot.awards);std::cout<<'}';}
            std::cout<<"]}\n";
        }catch(const std::exception&e){std::cout<<"{\"id\":\""<<(fields.empty()?"":fields[0])<<"\",\"error\":\""<<e.what()<<"\"}\n";}
    }
}
