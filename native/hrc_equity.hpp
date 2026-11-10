// Independent terminal-value implementation of the audited HRC 4.1 mathematics.
// Evidence: research/HRC-EQUITY-ABSTRACTION.md, original kW/kC/kB/kE/ll/lk/lj.
// This header neither loads HRC classes nor supplies a future knockout game model.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace hrc_equity {
constexpr std::size_t MAX_PLAYERS = 10;
using Chips = std::array<std::int64_t, MAX_PLAYERS>;
using WinnerMasks = std::array<std::uint16_t, MAX_PLAYERS>;
using Values = std::array<double, MAX_PLAYERS>;
enum class Mode : std::uint32_t { Chips = 0, ICM = 1, MTT = 2 };
enum class BountyMode : std::uint32_t { None = 0, Fixed = 1, Progressive = 2 };

struct EquityConfig {
    Mode mode = Mode::Chips;
    BountyMode bounty_mode = BountyMode::None;
    std::vector<std::int64_t> initial_stacks; // Positive, same integer unit as terminal stacks.
    std::vector<double> payouts;              // Absolute monetary units, descending; omitted ranks pay zero.
    std::vector<double> bounties;             // Full current heads, not only the cashable fraction.
    std::vector<double> other_stacks;         // Same chip unit as initial_stacks; MTT only.
    std::vector<double> other_bounties;        // MTT only; only the sum matters to HRC's future-pool model.
    double immediate_fraction = 1.0;          // PKO alpha: paid now; (1-alpha) rolls into the killer's head.
    double chip_unit = 1.0;                   // Chips mode absolute utility = final_stacks * chip_unit.
    std::size_t cache_capacity = 65536;       // Direct-mapped bounded cache; 0 disables it.
};

struct EquityResult {
    Values total{};
    Values immediate_prizes{};
    Values immediate_bounties{};
    Values future_equities{};                 // Survivor ICM + proportionate remaining bounty pool.
    Values remaining_bounties{};              // Survivor heads after rolling over PKO winnings.
};

// An explicit extension point. No MTT approximation is silently substituted.
// The callback returns only ordinary prize equities, in survivor input order.
using MttEvaluator = std::function<std::vector<double>(
    const std::vector<double>&, const std::vector<double>&, const std::vector<double>&)>;

struct CacheStats {
    std::uint64_t hits = 0, misses = 0, collisions = 0;
    std::size_t entries = 0, capacity = 0;
};

inline unsigned population(std::uint32_t mask) {
    unsigned n = 0;
    while (mask) { mask &= mask - 1; ++n; }
    return n;
}

inline void validate_payouts(const std::vector<double>& payouts) {
    double previous = std::numeric_limits<double>::infinity();
    for (double x : payouts) {
        if (!std::isfinite(x) || x < 0 || x > previous)
            throw std::invalid_argument("Payouts must be finite, nonnegative and nonincreasing");
        previous = x;
    }
}

// Positive-stack 1..10-player exact ICM, independently expressed as forward
// probability flow over sets of previous finishers. kW uses the reverse subset
// recurrence; tests compare this version against its retained original output.
inline std::vector<double> icm_equities(const std::vector<double>& stacks,
                                       const std::vector<double>& payouts) {
    const std::size_t n = stacks.size();
    if (n == 0 || n > MAX_PLAYERS) throw std::invalid_argument("Exact ICM requires 1..10 positive stacks");
    for (double x : stacks)
        if (!std::isfinite(x) || x <= 0) throw std::invalid_argument("ICM stacks must be finite and positive");
    validate_payouts(payouts);
    std::vector<double> result(n, 0.0);
    if (payouts.empty()) return result;
    // Scale before summing: ICM is scale invariant and extreme finite inputs
    // must not overflow their total. Sum only unselected stacks, avoiding loss
    // from subtracting a nearly equal selected sum from the total.
    const double scale = *std::max_element(stacks.begin(), stacks.end());
    std::array<long double, MAX_PLAYERS> scaled{};
    for (std::size_t i = 0; i < n; ++i) scaled[i] = static_cast<long double>(stacks[i]) / scale;
    std::array<long double, 1u << MAX_PLAYERS> mass{};
    mass[0] = 1;
    const std::uint32_t limit = 1u << n;
    const std::size_t paid = std::min(n, payouts.size());
    std::array<long double, MAX_PLAYERS> accumulated{};
    for (std::uint32_t mask = 0; mask + 1 < limit; ++mask) {
        const unsigned rank = population(mask);
        if (rank >= paid || mass[mask] == 0) continue;
        long double remaining = 0;
        for (std::size_t i = 0; i < n; ++i) if (!(mask & (1u << i))) remaining += scaled[i];
        for (std::size_t i = 0; i < n; ++i) if (!(mask & (1u << i))) {
            const long double chance = mass[mask] * (scaled[i] / remaining);
            accumulated[i] += chance * payouts[rank];
            mass[mask | (1u << i)] += chance;
        }
    }
    for (std::size_t i = 0; i < n; ++i) result[i] = static_cast<double>(accumulated[i]);
    return result;
}

class Calculator {
    struct Key { Chips stacks{}; WinnerMasks masks{}; };
    struct Entry { Key key{}; EquityResult result{}; bool occupied = false; };
    EquityConfig config_;
    MttEvaluator mtt_;
    std::size_t players_ = 0;
    std::vector<Entry> cache_;
    CacheStats stats_{};
    EquityResult uncached_{};
    EquityResult baseline_{};

    static void finite_nonnegative(const std::vector<double>& xs, const char* message) {
        long double sum = 0;
        for (double x : xs) {
            if (!std::isfinite(x) || x < 0) throw std::invalid_argument(message);
            sum += x;
        }
        if (sum > std::numeric_limits<double>::max()) throw std::invalid_argument(message);
    }

    void validate_config() {
        if (players_ < 2 || players_ > MAX_PLAYERS) throw std::invalid_argument("A table requires 2..10 players");
        for (auto x : config_.initial_stacks) if (x <= 0) throw std::invalid_argument("Initial stacks must be positive");
        if (config_.mode != Mode::Chips && config_.mode != Mode::ICM && config_.mode != Mode::MTT)
            throw std::invalid_argument("Unknown equity mode");
        if (config_.bounty_mode != BountyMode::None && config_.bounty_mode != BountyMode::Fixed && config_.bounty_mode != BountyMode::Progressive)
            throw std::invalid_argument("Unknown bounty mode");
        validate_payouts(config_.payouts);
        finite_nonnegative(config_.payouts, "Payout total must be finite");
        finite_nonnegative(config_.bounties, "Bounties must be finite and nonnegative");
        finite_nonnegative(config_.other_bounties, "Other bounties must be finite and nonnegative");
        if (!std::isfinite(config_.immediate_fraction) || config_.immediate_fraction < 0 || config_.immediate_fraction > 1)
            throw std::invalid_argument("Immediate fraction must lie in [0,1]");
        if (!std::isfinite(config_.chip_unit) || config_.chip_unit <= 0)
            throw std::invalid_argument("Chip utility multiplier must be finite and positive");
        if (config_.cache_capacity > (1u << 20)) throw std::invalid_argument("Equity cache exceeds 1048576 entries");
        if (config_.mode != Mode::MTT && (!config_.other_stacks.empty() || !config_.other_bounties.empty()))
            throw std::invalid_argument("Outside-table data requires MTT mode");
        for (double x : config_.other_stacks)
            if (!std::isfinite(x) || x <= 0) throw std::invalid_argument("Other stacks must be finite and positive");
        if (config_.mode == Mode::MTT && !mtt_) throw std::invalid_argument("MTT requires an explicit prize-equity evaluator");
        if (config_.mode == Mode::Chips && config_.bounty_mode != BountyMode::None)
            throw std::invalid_argument("Bounties require monetary ICM or MTT utility");
        if (config_.bounty_mode == BountyMode::None) {
            if (!config_.bounties.empty() || !config_.other_bounties.empty())
                throw std::invalid_argument("Bounty vectors require a bounty mode");
        } else {
            if (config_.bounties.size() != players_) throw std::invalid_argument("One full bounty per table player is required");
            if (config_.bounty_mode == BountyMode::Fixed) {
                if (config_.immediate_fraction != 1.0) throw std::invalid_argument("Fixed KO pays the entire eliminated bounty immediately");
                for (double x : config_.bounties) if (x != config_.bounties[0])
                    throw std::invalid_argument("Original fixed KO uses one identical bounty for every player");
                if (!config_.other_bounties.empty()) {
                    if (config_.other_bounties.size() != config_.other_stacks.size())
                        throw std::invalid_argument("Other bounty count must match other stack count");
                    for (double x : config_.other_bounties) if (x != config_.bounties[0])
                        throw std::invalid_argument("Fixed KO outside bounties must equal the fixed bounty");
                }
            } else if (config_.other_bounties.size() != config_.other_stacks.size()) {
                throw std::invalid_argument("Progressive MTT requires one bounty per outside player (average may be repeated)");
            }
        }
    }

    void validate_terminal(const Chips& final, const WinnerMasks& masks) const {
        std::uint16_t survivors = 0;
        for (std::size_t i = 0; i < players_; ++i) {
            if (final[i] < 0) throw std::invalid_argument("Terminal stacks cannot be negative");
            if (final[i] > 0) survivors |= std::uint16_t(1u << i);
        }
        if (!survivors) throw std::invalid_argument("At least one table player must survive");
        for (std::size_t i = 0; i < players_; ++i) {
            if (final[i] > 0 && masks[i]) throw std::invalid_argument("A surviving player cannot have elimination winners");
            if (masks[i] & ~survivors) throw std::invalid_argument("Elimination winners must be surviving table players");
            if (!final[i] && !masks[i] && config_.bounty_mode != BountyMode::None)
                throw std::invalid_argument("Every eliminated bounty player requires a nonempty winner mask");
        }
        for (std::size_t i = players_; i < MAX_PLAYERS; ++i)
            if (final[i] || masks[i]) throw std::invalid_argument("Unused seats must be zero");
    }

    std::uint64_t hash(const Key& key) const {
        std::uint64_t h = 0x9e3779b97f4a7c15ULL;
        for (std::size_t i = 0; i < players_; ++i) {
            std::uint64_t x = std::uint64_t(key.stacks[i]) ^ (std::uint64_t(key.masks[i]) << 48);
            x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
            x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
            h ^= (x ^ (x >> 31)) + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
        }
        return h;
    }

    EquityResult evaluate(const Chips& final, const WinnerMasks& masks) const {
        EquityResult result;
        if (config_.mode == Mode::Chips) {
            for (std::size_t i = 0; i < players_; ++i) {
                result.total[i] = result.future_equities[i] = final[i] * config_.chip_unit;
                if (!std::isfinite(result.total[i])) throw std::overflow_error("Chip utility overflow");
            }
            return result;
        }
        std::vector<std::size_t> alive, dead;
        std::vector<double> survivor_stacks;
        for (std::size_t i = 0; i < players_; ++i) {
            if (final[i]) { alive.push_back(i); survivor_stacks.push_back(double(final[i])); }
            else dead.push_back(i);
        }
        // kC: rank eliminated players by pre-hand stack, equal stacks share all
        // affected prize positions (including unpaid zero-prize positions).
        std::sort(dead.begin(), dead.end(), [&](std::size_t a, std::size_t b) {
            return config_.initial_stacks[a] > config_.initial_stacks[b];
        });
        const std::size_t rank_offset = config_.mode == Mode::MTT ? config_.other_stacks.size() : 0;
        for (std::size_t start = 0; start < dead.size();) {
            std::size_t end = start + 1;
            while (end < dead.size() && config_.initial_stacks[dead[end]] == config_.initial_stacks[dead[start]]) ++end;
            long double prize = 0;
            for (std::size_t j = start; j < end; ++j) {
                const std::size_t place = rank_offset + alive.size() + j;
                if (place < config_.payouts.size()) prize += config_.payouts[place];
            }
            const double share = double(prize / (end - start));
            for (std::size_t j = start; j < end; ++j) result.immediate_prizes[dead[j]] = share;
            start = end;
        }
        if (config_.bounty_mode != BountyMode::None) {
            for (auto i : alive) result.remaining_bounties[i] = config_.bounties[i];
            const double alpha = config_.bounty_mode == BountyMode::Fixed ? 1.0 : config_.immediate_fraction;
            for (auto victim : dead) {
                const double share = config_.bounties[victim] / population(masks[victim]);
                for (auto killer : alive) if (masks[victim] & (1u << killer)) {
                    result.immediate_bounties[killer] += alpha * share;
                    if (config_.bounty_mode == BountyMode::Progressive)
                        result.remaining_bounties[killer] += (1.0 - alpha) * share;
                }
            }
        }
        const auto prizes = config_.mode == Mode::MTT
            ? mtt_(survivor_stacks, config_.payouts, config_.other_stacks)
            : icm_equities(survivor_stacks, config_.payouts);
        if (prizes.size() != alive.size()) throw std::runtime_error("Prize evaluator returned the wrong survivor count");
        long double total_chips = 0, pool = 0;
        for (auto i : alive) { total_chips += final[i]; pool += result.remaining_bounties[i]; }
        if (config_.mode == Mode::MTT) {
            for (double x : config_.other_stacks) total_chips += x;
            if (config_.bounty_mode == BountyMode::Fixed) pool += config_.other_stacks.size() * config_.bounties[0];
            else for (double x : config_.other_bounties) pool += x;
        }
        for (std::size_t j = 0; j < alive.size(); ++j) {
            if (!std::isfinite(prizes[j]) || prizes[j] < 0) throw std::runtime_error("Prize evaluator returned a non-finite or negative equity");
            const auto i = alive[j];
            result.future_equities[i] = prizes[j] + double(pool * (static_cast<long double>(final[i]) / total_chips));
        }
        for (std::size_t i = 0; i < players_; ++i) {
            result.total[i] = result.immediate_prizes[i] + result.immediate_bounties[i] + result.future_equities[i];
            if (!std::isfinite(result.total[i]) || !std::isfinite(result.remaining_bounties[i]))
                throw std::overflow_error("Terminal monetary equity overflow");
        }
        return result;
    }

public:
    explicit Calculator(EquityConfig config, MttEvaluator mtt = {})
        : config_(std::move(config)), mtt_(std::move(mtt)), players_(config_.initial_stacks.size()) {
        validate_config();
        Chips initial{};
        std::copy(config_.initial_stacks.begin(), config_.initial_stacks.end(), initial.begin());
        baseline_ = evaluate(initial, WinnerMasks{});
        cache_.resize(config_.cache_capacity);
        stats_.capacity = cache_.size();
    }
    const EquityConfig& config() const { return config_; }
    std::size_t players() const { return players_; }
    const EquityResult& baseline() const { return baseline_; }
    const CacheStats& cache_stats() const { return stats_; }
    std::size_t cache_bytes() const { return cache_.capacity()*sizeof(Entry); }
    std::unique_ptr<Calculator> fork() const { return std::make_unique<Calculator>(config_,mtt_); }
    void clear_cache() {
        for (auto& entry : cache_) entry.occupied = false;
        stats_ = CacheStats{}; stats_.capacity = cache_.size();
    }
    // Returned reference remains valid until this Calculator's next evaluation
    // or cache reset. Use one Calculator per training thread; no global cache.
    const EquityResult& compute_terminal(const Chips& final, const WinnerMasks& winners = {}) {
        const Key key{final, winners};
        if (cache_.empty()) { validate_terminal(final, winners); ++stats_.misses; uncached_ = evaluate(final, winners); return uncached_; }
        auto& entry = cache_[hash(key) % cache_.size()];
        // Every occupied entry was validated before insertion. Compare the full
        // key, including unused seats, before skipping repeated validation.
        if (entry.occupied && entry.key.stacks == final && entry.key.masks == winners) { ++stats_.hits; return entry.result; }
        validate_terminal(final, winners);
        ++stats_.misses;
        auto value = evaluate(final, winners);
        if (entry.occupied) ++stats_.collisions; else ++stats_.entries;
        entry.key = key; entry.result = value; entry.occupied = true;
        return entry.result;
    }
};
} // namespace hrc_equity
