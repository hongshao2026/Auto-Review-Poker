// Exercise the production index and resource reader. The row/bucket oracle
// uses an ordinary map and sequential legal-hole enumeration, respectively.
#include "../../native/hrc_cards.hpp"
#include <atomic>
#include <filesystem>
#include <iostream>
#include <thread>
#include <unordered_map>

using hrc_cards::FlatBoardRowMap;
static void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
template<class E,class F>static void rejects(F action,const char* why){bool yes=false;try{action();}catch(const E&){yes=true;}require(yes,why);}
static void quoted(const std::string& text){std::cout<<'"';for(unsigned char c:text){if(c=='"'||c=='\\')std::cout<<'\\'<<char(c);else if(c=='\n')std::cout<<"\\n";else if(c=='\r')std::cout<<"\\r";else if(c=='\t')std::cout<<"\\t";else std::cout<<char(c);}std::cout<<'"';}

static void unit(){
    FlatBoardRowMap map;uint32_t out=77;
    require(!map.lookup(0,out)&&out==77,"empty lookup changed output");
    rejects<std::logic_error>([&]{map.emplace(1,1);},"insert before reserve accepted");
    rejects<std::length_error>([&]{map.reserve(SIZE_MAX);},"capacity overflow accepted");
    rejects<std::length_error>([]{FlatBoardRowMap::memory_bytes_for(SIZE_MAX);},"budget overflow accepted");
    require(map.capacity()==0&&map.size()==0,"failed reserve changed state");
    map.reserve(128);
    std::vector<uint64_t> keys;
    for(uint64_t key=0;keys.size()<64;++key)if((FlatBoardRowMap::mixed_key(key)&127)==127)keys.push_back(key);
    for(size_t i=0;i<keys.size();++i)map.emplace(keys[i],uint32_t(i+100));
    for(size_t i=0;i<keys.size();++i)require(map.lookup(keys[i],out)&&out==i+100,"colliding/wrapping lookup failed");
    for(uint64_t i=1;i<=10000;++i){out=77;require(!map.lookup(UINT64_MAX-i,out)&&out==77,"missing lookup changed output");}
    rejects<std::invalid_argument>([&]{map.emplace(keys[1],999);},"duplicate accepted");
    require(map.lookup(keys[1],out)&&out==101,"duplicate overwrote value");
    rejects<std::invalid_argument>([&]{map.emplace(UINT64_MAX,9);},"sentinel accepted");
    rejects<std::length_error>([&]{map.emplace(1234567,9);},"half-full limit not enforced");
    rejects<std::logic_error>([&]{map.reserve(256);},"second reserve accepted");
    require(map.size()==64&&map.capacity()==128,"failed insertion changed size");
    require(map.allocated_bytes()<=FlatBoardRowMap::memory_bytes_for(128),"map budget below actual arrays");
    out=77;require(!map.lookup(UINT64_MAX,out)&&out==77,"sentinel lookup");
    FlatBoardRowMap edge;edge.reserve(1);edge.emplace(0,UINT32_MAX);edge.emplace(UINT64_MAX-1,0);
    require(edge.lookup(0,out)&&out==UINT32_MAX&&edge.lookup(UINT64_MAX-1,out)&&out==0,"extreme keys/values");
    // Street publication uses move construction/assignment, then const reads.
    FlatBoardRowMap moved=std::move(edge);
    require(moved.lookup(0,out)&&out==UINT32_MAX&&moved.lookup(UINT64_MAX-1,out)&&out==0,"move lost mapping");
    std::atomic<bool> failed{false};std::vector<std::thread> readers;
    const FlatBoardRowMap& immutable=map;
    for(int worker=0;worker<4;++worker)readers.emplace_back([&]{for(int i=0;i<20000;++i){uint32_t value=0;int at=i%64;if(!immutable.lookup(keys[at],value)||value!=uint32_t(at+100))failed.store(true);}});
    for(auto& reader:readers)reader.join();require(!failed.load(),"concurrent immutable read");
    for(size_t request:{size_t(0),size_t(3),size_t(4),size_t(5),size_t(1755*2),size_t(16432*2),size_t(134459*2)}){
        const size_t cap=FlatBoardRowMap::capacity_for(request);
        require(cap>=request&&cap>=4&&(cap&(cap-1))==0,"capacity rounding");
        require(FlatBoardRowMap::memory_bytes_for(request)>=cap*12+sizeof(FlatBoardRowMap),"capacity budget");
    }
    hrc_cards::AbstractionTables empty;
    rejects<std::runtime_error>([&]{hrc_cards::prepare_bucket_row(1,0,empty);},"invalid board accepted");
    rejects<std::runtime_error>([&]{hrc_cards::prepare_bucket_row(4,7,empty);},"invalid street accepted");
    rejects<std::runtime_error>([&]{hrc_cards::prepare_bucket_row(1,7,empty);},"missing canonical row accepted");
    std::cout<<"{\"ok\":true,\"collision_chain\":64,\"wraparound\":true,\"missing_keys\":10000,\"duplicate_preserves_value\":true,\"overflow_rejected_before_allocation\":true,\"load_factor_limit\":0.5,\"concurrent_reads\":80000,\"move_preserves_mapping\":true}\n";
}

static void resources(const std::string& dir){
    hrc_cards::AbstractionTables tables(dir);
    const size_t counts[4]={0,1755,16432,134459};
    const size_t columns[4]={0,1176,1128,1081};
    uint64_t keys=0,compared=0,sampled_rows=0,map_bytes=0,map_budget=0,payload_bytes=0,total_budget=32768,max_board_temporary=0;
    for(int st=1;st<=3;++st){
        const std::string prefix=dir+"/street"+std::to_string(st);
        auto boards=hrc_cards::read_binary<uint64_t>(prefix+".boards.u64",counts[st]);
        std::unordered_map<uint64_t,uint32_t> oracle;
        oracle.reserve(boards.size()*2);
        for(size_t row=0;row<boards.size();++row)require(oracle.emplace(boards[row],uint32_t(row)).second,"duplicate oracle board");
        const auto& data=tables.streets[st];
        require(data.row.size()==counts[st],"wrong resource row count");
        for(size_t row=0;row<boards.size();++row){uint32_t value=UINT32_MAX;
            require(data.row.lookup(boards[row],value)&&value==oracle.at(boards[row])&&value==row,"resource row mismatch");++keys;
        }
        uint32_t value=123;require(!data.row.lookup(UINT64_C(1)<<63,value)&&value==123,"absent resource key");
        const uint64_t board_bytes=boards.capacity()*sizeof(uint64_t);
        max_board_temporary=std::max(max_board_temporary,board_bytes);
        map_bytes+=data.row.allocated_bytes();map_budget+=FlatBoardRowMap::memory_bytes_for(2*counts[st]);
        payload_bytes+=data.values.capacity()*sizeof(uint16_t)+data.compact_values.capacity()*sizeof(uint8_t);
        total_budget+=std::filesystem::file_size(prefix+".buckets.u16")/(st==1?1:2)
                      +FlatBoardRowMap::memory_bytes_for(2*counts[st])+std::filesystem::file_size(prefix+".boards.u64");
        std::ifstream raw(prefix+".buckets.u16",std::ios::binary);require(bool(raw),"cannot read resource oracle");
        std::vector<uint16_t> row_values(columns[st]);
        for(size_t sample=0;sample<256;++sample){
            const size_t row=sample*(boards.size()-1)/255;
            const uint64_t board=boards[row];
            raw.seekg(std::streamoff(row*columns[st]*sizeof(uint16_t)));
            raw.read(reinterpret_cast<char*>(row_values.data()),std::streamsize(row_values.size()*sizeof(uint16_t)));
            require(bool(raw),"truncated oracle row");
            const auto prepared=hrc_cards::prepare_bucket_row(st,board,tables);
            require(prepared.canonical.mask==board&&prepared.offset==row*columns[st],"canonical row preparation");
            size_t column=0;
            for(int high=1;high<52;++high)for(int low=0;low<high;++low){
                const uint64_t hole=(UINT64_C(1)<<high)|(UINT64_C(1)<<low);
                if(board&hole)continue;
                const int combo=high*(high-1)/2+low;
                const int got=hrc_cards::bucket_from_row(combo,board,prepared,data);
                require(column<row_values.size()&&got==row_values[column],"legal-hole enumeration bucket mismatch");
                ++column;++compared;
            }
            require(column==columns[st],"legal-hole row width");++sampled_rows;
        }
    }
    const uint64_t conservative_peak=payload_bytes+map_bytes+max_board_temporary+32768+sizeof(tables);
    require(map_bytes<=map_budget&&conservative_peak<=total_budget,"resource estimate below arrays and load temporary");
    std::cout<<"{\"ok\":true,\"resource_keys\":"<<keys<<",\"sampled_canonical_rows\":"<<sampled_rows
             <<",\"legal_bucket_comparisons\":"<<compared<<",\"map_allocated_bytes\":"<<map_bytes
             <<",\"map_budget_bytes\":"<<map_budget<<",\"payload_array_bytes\":"<<payload_bytes
             <<",\"load_peak_array_bound_bytes\":"<<conservative_peak<<",\"production_resource_budget_bytes\":"<<total_budget<<"}\n";
}

int main(int argc,char** argv){try{
    if(argc==2&&std::string(argv[1])=="--unit")unit();
    else if(argc==3&&std::string(argv[1])=="--resources")resources(argv[2]);
    else if(argc==3&&std::string(argv[1])=="--load"){
        try{hrc_cards::AbstractionTables tables(argv[2]);std::cout<<"{\"loaded\":true}\n";}
        catch(const std::exception& e){std::cout<<"{\"loaded\":false,\"error\":";quoted(e.what());std::cout<<"}\n";}
    }else throw std::runtime_error("Expected --unit, --resources DIR, or --load DIR");
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
