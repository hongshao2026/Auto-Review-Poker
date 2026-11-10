// Independent terminal precomputation. Original policies/payoffs are
// never inputs. Outcome keys retain each paid-descending prefix's best rank.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <vector>

namespace hrc_terminal_table {
constexpr int max_players = 10;
struct Cancelled : std::runtime_error {
    Cancelled() : std::runtime_error("Terminal table initialization cancelled") {}
};

// Immutable after build; safe to share across workers. Each returned pointer
// remains valid for this object's lifetime and contains exactly players values.
// Caller must gate this optimization to !raked && !fgs. Monetary tables must
// transform independently settled net chips to net equity before publication.
class Tables {
    struct Entry {
        std::size_t offset = 0;
        uint32_t count = 1;
        uint16_t live = 0;
        uint16_t needed = 0;
        uint8_t length = 0;
        std::array<uint8_t,max_players> order{};
    };
    int players_ = 0;
    std::size_t bytes_ = 0;
    uint64_t outcomes_ = 0;
    std::vector<Entry> entries_;
    std::vector<double> values_;

    static void checkpoint(const std::function<bool()>& cancelled) {
        if (cancelled && cancelled()) throw Cancelled();
    }

    template<class Terminal> static Entry describe(const Terminal& t, int players) {
        if (t.synthetic) throw std::invalid_argument("Synthetic terminal is not a ChipEV state");
        if (uint32_t(t.folded) >> players) throw std::invalid_argument("Invalid terminal folded mask");
        Entry e;
        e.live = uint16_t(((1u << players)-1) & ~uint32_t(t.folded));
        for (int p=0;p<players;++p) {
            if (!std::isfinite(t.base[p]) || !std::isfinite(t.paid[p]) ||
                t.paid[p]<0 || t.paid[p]!=std::floor(t.paid[p]))
                throw std::invalid_argument("Invalid ChipEV terminal chip state");
            if (e.live & (1u<<p)) e.order[e.length++]=uint8_t(p);
        }
        if (!e.length) throw std::invalid_argument("Terminal has no live seat");
        std::sort(e.order.begin(),e.order.begin()+e.length,[&](int a,int b) {
            return t.paid[a]!=t.paid[b] ? t.paid[a]>t.paid[b] : a<b;
        });
        for (int p=1;p<e.length;++p) e.count*=3;
        // Prefix-best keys are valid only for nested sidepot eligibility in
        // contribution order. Reject arbitrary pot subsets, rather than alias
        // outcomes that the ternary representation cannot distinguish.
        uint32_t previous=e.live;
        for (const auto& pot:t.pots) {
            const uint32_t eligible=pot.eligible;
            if (!std::isfinite(pot.amount) || pot.amount<=0 || pot.amount!=std::floor(pot.amount) ||
                !eligible || (eligible & ~uint32_t(e.live)) || (eligible & ~previous))
                throw std::invalid_argument("Invalid or nonnested terminal pot");
            bool excluded=false;
            for (int i=0;i<e.length;++i) {
                int seat=e.order[i];
                if (eligible & (1u<<seat)) {
                    if (excluded) throw std::invalid_argument("Pot is not a paid-order prefix");
                } else {
                    if (i && (eligible&(1u<<e.order[i-1])) && t.paid[seat]==t.paid[e.order[i-1]])
                        throw std::invalid_argument("Pot splits equally invested live seats");
                    excluded=true;
                }
            }
            previous=eligible;
            if (eligible&(eligible-1)) e.needed|=uint16_t(eligible);
        }
        return e;
    }

    static uint32_t key(const Entry& e,const int* ranks,bool only_needed=false) noexcept {
        if (only_needed && !e.needed) return 0;
        uint32_t index=0;
        auto rank_at=[&](int seat) {return !only_needed || (e.needed&(1u<<seat)) ? ranks[seat] : 0;};
        int best=rank_at(e.order[0]);
        for (int i=1;i<e.length;++i) {
            int rank=rank_at(e.order[i]);
            index=3*index+uint32_t(1+(rank>best)-(rank<best));
            if (rank>best) best=rank;
        }
        return index;
    }

    static std::array<int,max_players> representative(const Entry& e,uint32_t index) noexcept {
        std::array<int,max_players> ranks{};
        int best=max_players-1;
        for (int i=e.length-1;i>=0;--i) {
            int digit=int(index%3)-1;index/=3;
            ranks[e.order[i]]=digit<0 ? 0 : best;
            if (digit>0) --best;
        }
        ranks[e.order[0]]=best;
        return ranks;
    }

    // The existing independent kernel's ChipEV semantics: consecutive pot
    // layers with identical winners merge before integer division; the whole
    // remainder goes to the tied winner with least paid, then highest seat.
    // Single-eligible upper layers also implement uncalled-chip returns.
    // Double operations intentionally keep the legacy kernel's exact order.
    template<class Terminal> static void settle(const Terminal& t,int players,double scale,
                                                const int* ranks,double* out) {
        for (int p=0;p<players;++p) out[p]=t.base[p];
        uint32_t pending=0;double amount=0;
        auto award=[&]() {
            if (!pending) return;
            int count=0,first=-1;
            for (int p=0;p<players;++p) if (pending&(1u<<p)) {
                ++count;
                if (first<0 || t.paid[p]<t.paid[first] || (t.paid[p]==t.paid[first] && p>first)) first=p;
            }
            double each=std::floor(amount/count),odd=amount-each*count;
            for (int p=0;p<players;++p) if (pending&(1u<<p)) out[p]+=each;
            out[first]+=odd;
        };
        for (const auto& pot:t.pots) {
            uint32_t winners=0;int best=0;bool have=false;
            for (int p=0;p<players;++p) if (pot.eligible&(1u<<p)) {
                if (!have || ranks[p]>best) {best=ranks[p];winners=1u<<p;have=true;}
                else if (ranks[p]==best) winners|=1u<<p;
            }
            if (pending && winners!=pending) {award();amount=0;}
            pending=winners;amount+=pot.amount;
        }
        award();
        for (int p=0;p<players;++p) {
            out[p]/=scale;
            if (!std::isfinite(out[p])) throw std::invalid_argument("Nonfinite ChipEV terminal result");
        }
    }

    Tables()=default;
public:
    // Template fields: t.base[], t.paid[], t.folded, t.synthetic, t.pots;
    // pot fields: amount (integral chips), eligible (seat mask).
    // The pool must already have independent, validated conservation/pot state.
    // Budget/allocation refusal returns null (old evaluation stays available).
    // Invalid input and cancellation are explicit errors, not silent fallback.
    template<class Terminals> static std::shared_ptr<const Tables> build(
        const Terminals& terminals,int players,double chip_scale,std::size_t max_bytes,
        const std::function<bool()>& cancelled={}) {
        return build_transformed(terminals,players,chip_scale,max_bytes,
            [](const auto&,const int*,double*){},cancelled);
    }

    // The callback receives net chips (chip_scale=1 for monetary utilities),
    // not normalized strategy values. It may replace the result with a pure
    // function of this terminal and its complete pot-winning rank signature.
    // Construction is single-threaded; only the completed immutable table is
    // published. This callback must not touch RNG or any learned node state.
    template<class Terminals,class Transform> static std::shared_ptr<const Tables> build_transformed(
        const Terminals& terminals,int players,double chip_scale,std::size_t max_bytes,
        Transform&& transform,const std::function<bool()>& cancelled={}) {
        if (players<2 || players>max_players || !std::isfinite(chip_scale) || chip_scale<=0)
            throw std::invalid_argument("Invalid ChipEV table players/scale");
        checkpoint(cancelled);
        constexpr std::size_t overhead=sizeof(Tables)+128; // shared control block/alignment reserve
        if (max_bytes<overhead || terminals.size()>(max_bytes-overhead)/sizeof(Entry)) return {};
        std::size_t bytes=overhead+terminals.size()*sizeof(Entry),elements=0;
        uint64_t outcomes=0;
        for (const auto& t:terminals) {
            checkpoint(cancelled);
            Entry e=describe(t,players);
            std::size_t n=std::size_t(e.count)*players;
            if (n>(max_bytes-bytes)/sizeof(double)) return {};
            bytes+=n*sizeof(double);elements+=n;outcomes+=e.count;
        }
        try {
            auto result=std::shared_ptr<Tables>(new Tables());
            result->players_=players;result->bytes_=bytes;result->outcomes_=outcomes;
            result->entries_.resize(terminals.size());result->values_.resize(elements);
            // Account for any allocator/container growth beyond requested size.
            std::size_t actual=overhead+result->entries_.capacity()*sizeof(Entry);
            if (actual>max_bytes || result->values_.capacity()>(max_bytes-actual)/sizeof(double)) return {};
            result->bytes_=actual+result->values_.capacity()*sizeof(double);
            std::size_t offset=0,id=0;
            for (const auto& t:terminals) {
                checkpoint(cancelled);
                Entry e=describe(t,players);e.offset=offset;result->entries_[id++]=e;
                for (uint32_t code=0;code<e.count;++code) {
                    if (!(code&63)) checkpoint(cancelled);
                    auto ranks=representative(e,code);
                    // This is an invariant of the representation, independent
                    // of chips/pots; do not publish a partially built table.
                    if (key(e,ranks.data())!=code) throw std::logic_error("Terminal outcome key does not roundtrip");
                    settle(t,players,chip_scale,ranks.data(),result->values_.data()+offset);
                    transform(t,ranks.data(),result->values_.data()+offset);
                    for(int p=0;p<players;++p)if(!std::isfinite(result->values_[offset+p]))
                        throw std::invalid_argument("Nonfinite transformed terminal result");
                    offset+=players;
                }
            }
            checkpoint(cancelled);
            return result;
        } catch (const std::bad_alloc&) {return {};}
    }

    int players() const noexcept {return players_;}
    std::size_t entries() const noexcept {return entries_.size();}
    std::size_t bytes() const noexcept {return bytes_;}
    uint64_t outcomes() const noexcept {return outcomes_;}
    uint16_t live_mask(std::size_t id) const {return entries_.at(id).live;}
    // Only these ranks can affect a contested pot. lookup never reads ranks
    // outside this mask, and accepts a null ranks pointer when the mask is zero.
    uint16_t rank_mask(std::size_t id) const {return entries_.at(id).needed;}
    uint32_t outcome_count(std::size_t id) const {return entries_.at(id).count;}
    uint32_t outcome_index(std::size_t id,const int* ranks) const {return key(entries_.at(id),ranks,true);}
    const double* lookup(std::size_t id,const int* ranks) const {
        const Entry& e=entries_.at(id);
        return values_.data()+e.offset+std::size_t(key(e,ranks,true))*players_;
    }
};
} // namespace hrc_terminal_table
