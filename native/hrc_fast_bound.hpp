#pragma once
// Exact remainder acceleration for small, runtime-selected integer bounds.
// The quotient uses a floor reciprocal, never a floating approximation.
#include <array>
#include <cstdint>
#include <limits>
#if defined(_MSC_VER) && defined(_M_X64) && !defined(__SIZEOF_INT128__)
#include <intrin.h>
#endif

namespace hrc_fast_bound {
constexpr uint32_t maximum=64;
struct Divisor {uint64_t reciprocal=0, rejection=0;};
constexpr auto divisors(){
    std::array<Divisor,maximum+1> out{};
    for(uint32_t n=2;n<=maximum;++n)
        out[n]={std::numeric_limits<uint64_t>::max()/n,(uint64_t(0)-uint64_t(n))%n};
    return out;
}
inline constexpr auto table=divisors();

inline uint64_t high_product(uint64_t a,uint64_t b){
#if defined(__SIZEOF_INT128__) && !defined(HRC_FAST_BOUND_PORTABLE)
    return uint64_t((static_cast<__uint128_t>(a)*b)>>64);
#elif defined(_MSC_VER) && defined(_M_X64) && !defined(HRC_FAST_BOUND_PORTABLE)
    return __umulh(a,b);
#else
    // Exact 32-bit limbs on hosts without a native multiply-high intrinsic.
    uint64_t low_low=uint64_t(uint32_t(a))*uint32_t(b);
    uint64_t high_low=(a>>32)*uint32_t(b)+(low_low>>32);
    uint64_t low_high=uint64_t(uint32_t(a))*(b>>32)+uint32_t(high_low);
    return (a>>32)*(b>>32)+(high_low>>32)+(low_high>>32);
#endif
}

// Preconditions: 1 <= n <= maximum. Powers of two include n=1; they need
// neither a representable reciprocal for 2^64/1 nor a rejection threshold.
inline uint32_t remainder(uint64_t value,uint32_t n){
    if(!(n&(n-1)))return uint32_t(value)&(n-1);
    // For nonpowers of two m=floor(2^64/n)=floor((2^64-1)/n).
    // floor(value*m/2^64) is the exact quotient or one below it; the residual
    // is below 2*n. One subtraction produces value%n without lost bits.
    uint64_t quotient=high_product(value,table[n].reciprocal);
    uint64_t residual=value-quotient*n;
    if(residual>=n)residual-=n;
    return uint32_t(residual);
}
} // namespace hrc_fast_bound
