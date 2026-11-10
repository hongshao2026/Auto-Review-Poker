#include "../../native/hrc_dynamic.hpp"
#include <fstream>
#include <iostream>

static std::uint64_t integer(std::istream& in,int bytes){std::uint64_t n=0;for(int i=0;i<bytes;++i){int b=in.get();if(b==EOF)throw std::runtime_error("Truncated test query");n|=std::uint64_t(b)<<(8*i);}return n;}
static void emit(std::ostream& out,int value){auto n=std::uint32_t(value);for(int i=0;i<4;++i)out.put(char(n>>(8*i)));}
int main(int argc,char**argv){try{
    if(argc!=4)return 2;
    auto table=hrc_dynamic::Table::read(argv[1]);std::ifstream queries(argv[2],std::ios::binary);std::ofstream out(argv[3],std::ios::binary);
    auto count=integer(queries,4);
    for(std::uint64_t i=0;i<count;++i){std::array<std::uint64_t,4> board{};for(auto& b:board)b=integer(queries,8);
        for(int player=0;player<table.players();++player)for(int combo=0;combo<1326;++combo)emit(out,table.bucket(player,combo,board.data()));}
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
