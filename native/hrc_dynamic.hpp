#pragma once
// Independent fixed-board/player-range dense-map reader. No original code/data.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace hrc_dynamic {
class Table {
    int street_=0;
    std::uint32_t rows_=0;
    std::vector<std::uint64_t> prefix_;
    std::vector<std::int32_t> player_map_;
    std::vector<std::uint32_t> effective_;
    std::vector<std::vector<std::int32_t>> maps_;
    static std::uint64_t read_integer(std::istream& stream,int bytes) {
        std::uint64_t value=0;
        for(int i=0;i<bytes;++i){int b=stream.get();if(b==EOF)throw std::runtime_error("Truncated dynamic abstraction cache");value|=std::uint64_t(b)<<(8*i);}
        return value;
    }
    static int bits(std::uint64_t value){int count=0;while(value){value&=value-1;++count;}return count;}
    static int card(std::uint64_t value){if(!value||(value&(value-1)))throw std::invalid_argument("Dynamic board transition must add exactly one card");int index=0;while(!(value&1)){value>>=1;++index;}return index;}
public:
    static Table read(const std::string& path,std::uint64_t max_bytes=std::uint64_t(1)<<30) {
        std::ifstream stream(path,std::ios::binary|std::ios::ate);
        if(!stream)throw std::runtime_error("Dynamic abstraction cache not found");
        auto length=stream.tellg();if(length<0||std::uint64_t(length)>max_bytes)throw std::runtime_error("Dynamic abstraction file exceeds memory budget");stream.seekg(0);
        char magic[8];stream.read(magic,8);if(!stream||std::string(magic,8)!="HRDYN001")throw std::invalid_argument("Invalid dynamic abstraction cache header");
        Table table;table.street_=int(read_integer(stream,4));auto prefixes=read_integer(stream,4),players=read_integer(stream,4);table.rows_=std::uint32_t(read_integer(stream,4));auto unique=read_integer(stream,4);
        if(table.street_<1||table.street_>3||prefixes<2||prefixes>4||prefixes>std::uint64_t(table.street_+1)||players<1||players>10||unique>players)
            throw std::invalid_argument("Invalid dynamic abstraction dimensions");
        std::uint32_t expected_rows=1;for(int i=int(prefixes);i<table.street_+1;++i)expected_rows*=52;
        std::uint64_t expected_bytes=28+8*prefixes+8*players+4*unique*expected_rows*1326;
        if(table.rows_!=expected_rows||expected_bytes!=std::uint64_t(length))throw std::invalid_argument("Dynamic abstraction layout length mismatch");
        for(std::uint64_t i=0;i<prefixes;++i){auto board=read_integer(stream,8);if((i==0&&board!=0)||(i>0&&(board>>52||bits(board)!=int(i+2)||(board&table.prefix_.back())!=table.prefix_.back())))throw std::invalid_argument("Invalid fixed board history");table.prefix_.push_back(board);}
        for(std::uint64_t p=0;p<players;++p){auto raw=read_integer(stream,4);std::int32_t index=raw==0xffffffffu?-1:std::int32_t(raw);if(index< -1||(index>=0&&std::uint64_t(index)>=unique))throw std::invalid_argument("Dynamic player map index invalid");table.player_map_.push_back(index);}
        for(std::uint64_t p=0;p<players;++p){auto count=read_integer(stream,4);if(count>std::uint64_t(std::numeric_limits<std::int32_t>::max())||(table.player_map_[p]<0&&count))throw std::invalid_argument("Invalid effective bucket count");table.effective_.push_back(std::uint32_t(count));}
        std::vector<std::uint32_t> counts(unique,std::numeric_limits<std::uint32_t>::max());
        for(std::uint64_t p=0;p<players;++p)if(table.player_map_[p]>=0){auto& count=counts[table.player_map_[p]];if(count!=std::numeric_limits<std::uint32_t>::max()&&count!=table.effective_[p])throw std::invalid_argument("Shared maps have inconsistent effective counts");count=table.effective_[p];}
        for(std::uint64_t i=0;i<unique;++i){if(counts[i]==std::numeric_limits<std::uint32_t>::max())throw std::invalid_argument("Unused dynamic mapping payload");
            std::vector<std::int32_t> map(std::size_t(expected_rows)*1326);std::int32_t maximum=-1;
            // Decode explicitly: cache byte order is independent of the host.
            std::vector<unsigned char> bytes(map.size()*4);stream.read(reinterpret_cast<char*>(bytes.data()),bytes.size());if(!stream)throw std::runtime_error("Truncated dynamic map");
            for(std::size_t j=0;j<map.size();++j){std::uint32_t value=0;for(int b=0;b<4;++b)value|=std::uint32_t(bytes[j*4+b])<<(8*b);map[j]=value==0xffffffffu?-1:std::int32_t(value);
                if(map[j]< -1||(map[j]>=0&&std::uint32_t(map[j])>=counts[i]))throw std::invalid_argument("Dynamic bucket ID out of range");maximum=std::max(maximum,map[j]);}
            if(std::uint32_t(maximum+1)!=counts[i])throw std::invalid_argument("Dynamic effective count differs from maximum bucket");table.maps_.push_back(std::move(map));
        }
        return table;
    }
    int street()const{return street_;}
    int players()const{return int(player_map_.size());}
    std::uint32_t effective(int player)const{return effective_.at(player);}
    const std::vector<std::uint64_t>& prefix()const{return prefix_;}
    int bucket(int player,int combo,const std::uint64_t* board,int board_length=4)const{
        if(player<0||player>=players()||combo< -1||combo>=1326)throw std::invalid_argument("Invalid dynamic player/combo");
        if(board_length<=street_)throw std::invalid_argument("Incomplete dynamic board history");
        for(std::size_t i=0;i<prefix_.size();++i)if(board[i]!=prefix_[i])throw std::invalid_argument("Fixed board prefix differs from cache");
        std::uint32_t row=0;auto previous=prefix_.back();for(int i=int(prefix_.size());i<=street_;++i){if(board[i]>>52||(board[i]&previous)!=previous)throw std::invalid_argument("Invalid dynamic board extension");row=row*52+card(board[i]^previous);previous=board[i];}
        if(player_map_[player]<0||combo<0)return -1;
        return maps_[player_map_[player]][std::size_t(row)*1326+combo];
    }
    void fill(const int* combos,int count,const std::uint64_t* board,int* output,int board_length=4)const{
        if(count!=players())throw std::invalid_argument("Dynamic map player count differs from deal");
        for(int p=0;p<count;++p)output[p]=bucket(p,combos[p],board,board_length);
    }
};
}
