#pragma once
// Independent card rules and reader for local, user-installed abstraction data.
// No HRC executable code, strategy, or hand-ranking table is used here.
// Card IDs: rank*4+suit, 2c=0, As=51. rank7 returns larger for stronger hands.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <stdexcept>
#include <string>
#include "hrc_flat_board_map.hpp"
#include <vector>
#ifdef _MSC_VER
#include <intrin.h>
#endif

namespace hrc_cards {
inline int popcount(uint64_t x) {
#ifdef _MSC_VER
    return static_cast<int>(__popcnt64(x));
#else
    return __builtin_popcountll(x);
#endif
}
inline int lowbit(uint64_t x) {
#ifdef _MSC_VER
    unsigned long index; _BitScanForward64(&index,x); return static_cast<int>(index);
#else
    return __builtin_ctzll(x);
#endif
}
inline int highbit(uint32_t x) {
#ifdef _MSC_VER
    unsigned long index; _BitScanReverse(&index,x); return static_cast<int>(index);
#else
    return 31-__builtin_clz(x);
#endif
}

struct RankTables {
    std::array<uint32_t,8192> top5{};
    std::array<int,8192> straight{};
    RankTables() {
        for (int m=0;m<8192;++m) {
            uint32_t q=m, value=0; int shift=16;
            while(q && shift>=0) {int r=highbit(q); value|=uint32_t(r+2)<<shift; q&=~(1u<<r); shift-=4;}
            top5[m]=value; straight[m]=-1;
            for(int r=12;r>=4;--r) if((m & (31<<(r-4)))==(31<<(r-4))) {straight[m]=r;break;}
            if(straight[m]<0 && (m & 0x100f)==0x100f) straight[m]=3;
        }
    }
};
inline int rank7(uint64_t cards) {
    // Caller supplies exactly seven distinct legal cards. Numeric values are
    // independent category/kicker encodings, not commercial evaluator ranks.
    static const RankTables t;
    uint32_t suits[4]={0,0,0,0}, one=0,two=0,three=0,four=0;
    while(cards) {
        const int c=lowbit(cards); cards&=cards-1;
        const uint32_t bit=1u<<(c>>2);
        four|=three&bit; three|=two&bit; two|=one&bit; one|=bit; suits[c&3]|=bit;
    }
    for(int s=0;s<4;++s) if(popcount(suits[s])>=5) {
        if(t.straight[suits[s]]>=0) return (8<<20)|((t.straight[suits[s]]+2)<<16);
        // Seven cards with a flush cannot also form quads or a full house.
        return (5<<20)|t.top5[suits[s]];
    }
    if(four) {int r=highbit(four); return (7<<20)|((r+2)<<16)|((highbit(one&~(1u<<r))+2)<<12);}
    if(three) {
        int r=highbit(three); uint32_t pairs=two&~(1u<<r);
        if(pairs) return (6<<20)|((r+2)<<16)|((highbit(pairs)+2)<<12);
    }
    if(t.straight[one]>=0) return (4<<20)|((t.straight[one]+2)<<16);
    if(three) {int r=highbit(three); return (3<<20)|((r+2)<<16)|((t.top5[one&~(1u<<r)]>>4)&0xff00);}
    if(popcount(two)>=2) {
        int a=highbit(two),b=highbit(two&~(1u<<a));
        return (2<<20)|((a+2)<<16)|((b+2)<<12)|((highbit(one&~((1u<<a)|(1u<<b)))+2)<<8);
    }
    if(two) {int r=highbit(two); return (1<<20)|((r+2)<<16)|((t.top5[one&~(1u<<r)]>>4)&0xfff0);}
    return t.top5[one];
}

struct ComboCards {
    std::array<int,1326> lo{},hi{},preflop{};
    ComboCards() {
        for(int h=1;h<52;++h) for(int l=0;l<h;++l) {
            int i=h*(h-1)/2+l; lo[i]=l;hi[i]=h;
            int a=h/4,b=l/4;
            preflop[i]=a==b?a*13+a:((h&3)==(l&3)?a*13+b:b*13+a);
        }
    }
};
inline const ComboCards& combo_cards() {static const ComboCards c;return c;}
inline int preflop_class(int combo) {return combo_cards().preflop.at(combo);}

struct CanonicalBoard {
    uint64_t mask=0; std::array<int,4> suit_map{};
};
inline CanonicalBoard canonical_board(uint64_t board) {
    constexpr uint64_t M=0x1111111111111ULL;
    std::array<int,4> order{{0,1,2,3}};
    const uint64_t v[4]={board&M,(board>>1)&M,(board>>2)&M,(board>>3)&M};
    // Stable ties agree with the established board reader convention.
    for(int i=1;i<4;++i) {int j=i,s=order[i];while(j && v[order[j-1]]>v[s]) {order[j]=order[j-1];--j;}order[j]=s;}
    CanonicalBoard c;
    for(int s=0;s<4;++s) {c.mask|=v[order[s]]<<s;c.suit_map[order[s]]=s;}
    return c;
}
inline int legal_hole_column(uint64_t canonical_mask,int lo,int hi) {
    if(lo>hi) std::swap(lo,hi);
    const int a=lo-popcount(canonical_mask&((1ULL<<lo)-1));
    const int b=hi-popcount(canonical_mask&((1ULL<<hi)-1));
    return b*(b-1)/2+a;
}

template<typename T> inline std::vector<T> read_binary(const std::string& path,size_t count) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f || f.tellg()!=std::streamoff(count*sizeof(T))) throw std::runtime_error("Wrong abstraction size: "+path);
    std::vector<T> result(count);f.seekg(0);f.read(reinterpret_cast<char*>(result.data()),count*sizeof(T));
    if(!f) throw std::runtime_error("Cannot read abstraction: "+path);
    return result;
}
// Disk profiles remain little-endian u16. Convert the 256-bucket streets in
// bounded chunks, validating before narrowing without a full-size u16 copy.
inline std::vector<uint8_t> read_compact_buckets(const std::string& path,size_t count) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f || f.tellg()!=std::streamoff(count*sizeof(uint16_t))) throw std::runtime_error("Wrong abstraction size: "+path);
    std::vector<uint8_t> result(count);std::array<uint16_t,16384> chunk{};f.seekg(0);
    for(size_t offset=0;offset<count;){
        const size_t n=std::min(chunk.size(),count-offset);
        f.read(reinterpret_cast<char*>(chunk.data()),n*sizeof(uint16_t));
        if(!f) throw std::runtime_error("Cannot read abstraction: "+path);
        for(size_t i=0;i<n;++i){if(chunk[i]>=256)throw std::runtime_error("Abstraction bucket outside profile bounds");result[offset+i]=uint8_t(chunk[i]);}
        offset+=n;
    }
    return result;
}
class AbstractionTables {
public:
    struct Street {
        int hole_columns=0,buckets=0;
        FlatBoardRowMap row;
        std::vector<uint16_t> values;
        std::vector<uint8_t> compact_values;
        int value(size_t index)const{return compact_values.empty()?values[index]:compact_values[index];}
    };
    std::array<Street,4> streets;
    AbstractionTables()=default;
    explicit AbstractionTables(const std::string& dir) {load(dir);}
    void load(const std::string& dir) {
        const uint16_t endian=1;
        if(*reinterpret_cast<const uint8_t*>(&endian)!=1) throw std::runtime_error("Abstraction files require little-endian host");
        const size_t rows[4]={0,1755,16432,134459};
        const int cols[4]={0,1176,1128,1081},buckets[4]={169,1024,256,256};
        for(int s=1;s<=3;++s) {
            Street data;data.hole_columns=cols[s];data.buckets=buckets[s];
            std::string prefix=dir+"/street"+std::to_string(s);
            auto boards=read_binary<uint64_t>(prefix+".boards.u64",rows[s]);
            if(buckets[s]<=256)data.compact_values=read_compact_buckets(prefix+".buckets.u16",rows[s]*cols[s]);
            else{
                data.values=read_binary<uint16_t>(prefix+".buckets.u16",rows[s]*cols[s]);
                for(uint16_t v:data.values)if(v>=buckets[s])throw std::runtime_error("Abstraction bucket outside profile bounds");
            }
            data.row.reserve(rows[s]*2);
            for(uint32_t r=0;r<rows[s];++r) {
                if((r && boards[r]<=boards[r-1]) || popcount(boards[r])!=s+2) throw std::runtime_error("Invalid canonical board index");
                data.row.emplace(boards[r],r);
            }
            streets[s]=std::move(data);
        }
    }
};
struct BucketRow {
    CanonicalBoard canonical;
    size_t offset=0;
};
inline BucketRow prepare_bucket_row(int street,uint64_t board,const AbstractionTables& tables) {
    if(street<1 || street>3 || popcount(board)!=street+2) throw std::runtime_error("Invalid street/board");
    CanonicalBoard c=canonical_board(board);const auto& data=tables.streets[street];
    uint32_t row=0;
    if(!data.row.lookup(c.mask,row)) throw std::runtime_error("Canonical board missing from local abstraction");
    return {c,size_t(row)*data.hole_columns};
}
inline int bucket_from_row(int combo,uint64_t board,const BucketRow& row,const AbstractionTables::Street& data) {
    const auto& cc=combo_cards();int l=cc.lo.at(combo),h=cc.hi.at(combo);
    if(board&((1ULL<<l)|(1ULL<<h))) throw std::runtime_error("Hole cards overlap board");
    l=(l&~3)|row.canonical.suit_map[l&3];h=(h&~3)|row.canonical.suit_map[h&3];
    return data.value(row.offset+legal_hole_column(row.canonical.mask,l,h));
}
inline void fill_street_buckets(int street,const int* combo,int players,uint64_t board,
                               const AbstractionTables& tables,int* out) {
    const auto& cc=combo_cards();
    if(street==0) {for(int p=0;p<players;++p) out[p]=cc.preflop[combo[p]];return;}
    const auto row=prepare_bucket_row(street,board,tables);
    for(int p=0;p<players;++p)out[p]=bucket_from_row(combo[p],board,row,tables.streets[street]);
}
class CardModel : public AbstractionTables {
public:
    using AbstractionTables::AbstractionTables;
    int bucket(int street,int combo,uint64_t board) const {int out;fill_street_buckets(street,&combo,1,board,*this,&out);return out;}
    int rank7(uint64_t mask) const {return hrc_cards::rank7(mask);}
};
} // namespace hrc_cards
