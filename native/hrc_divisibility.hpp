#pragma once

#include <cstdint>
#include <limits>
#include <stdexcept>

// Exact signed-int32 divisibility by a cached positive divisor. This changes
// neither the random input nor its consumption; it replaces only value % d == 0.
namespace hrc_divisibility {

class CachedDivisor {
    std::int32_t divisor_ = 1;
    std::uint32_t mask_ = 0;
    std::uint32_t inverse_ = 1;
    std::uint32_t threshold_ = std::numeric_limits<std::uint32_t>::max();
    unsigned shift_ = 0;

public:
    CachedDivisor() = default;
    explicit CachedDivisor(std::int32_t divisor) { set(divisor); }

    // Return whether the cached divisor changed. Repeated floating-point clock
    // changes producing the same floor(sqrt(clock)) do not rebuild this cache.
    bool set(std::int32_t divisor) {
        if (divisor <= 0) throw std::invalid_argument("Divisor must be a positive int32");
        if (divisor == divisor_) return false;
        std::uint32_t odd = static_cast<std::uint32_t>(divisor);
        unsigned shift = 0;
        while ((odd & 1U) == 0) { odd >>= 1; ++shift; }
        // Starting at 1 gives one correct low bit for odd inputs. Each unsigned
        // Newton step doubles the correct bits, reaching all 32 after five steps.
        std::uint32_t inverse = 1;
        for (int i = 0; i < 5; ++i) inverse *= 2U - odd * inverse;
        divisor_ = divisor;
        shift_ = shift;
        mask_ = (std::uint32_t(1) << shift) - 1U;
        inverse_ = inverse;
        threshold_ = std::numeric_limits<std::uint32_t>::max() / odd;
        return true;
    }

    std::int32_t divisor() const noexcept { return divisor_; }

    bool divides(std::int32_t value) const noexcept {
        // Unsigned subtraction also handles INT_MIN; signed abs/negation would
        // overflow there. Positive d means signed % equals zero iff |value| does.
        std::uint32_t magnitude = static_cast<std::uint32_t>(value);
        if (value < 0) magnitude = 0U - magnitude;
        const std::uint32_t quotient = (magnitude >> shift_) * inverse_;
        // For odd m, q=(y/m) mod 2^32. q <= UINT32_MAX/m iff q*m
        // does not wrap; its congruence with y then makes it exactly equal to y.
        return ((magnitude & mask_) == 0U) & (quotient <= threshold_);
    }
};

} // namespace hrc_divisibility
