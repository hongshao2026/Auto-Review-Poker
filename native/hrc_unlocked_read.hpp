#pragma once
#include <stdexcept>
// GNU/Clang may enable relaxed 64-bit reads; other compilers retain the old
// node mutex path. Unsupported helpers fail loudly if incorrectly dispatched.
namespace hrc_unlocked_read {
#if (defined(__clang__) || defined(__GNUC__)) && !defined(HRC_DISABLE_UNLOCKED_READS)
inline constexpr bool supported = sizeof(double)==8 && alignof(double)>=8 &&
    __atomic_always_lock_free(sizeof(double),nullptr);
inline double load(const double* p){
    if constexpr(supported){double v;__atomic_load(p,&v,__ATOMIC_RELAXED);return v;}
    else throw std::logic_error("Unlocked strategy reads are unavailable on this target");
}
inline void store(double* p,double v){
    if constexpr(supported)__atomic_store(p,&v,__ATOMIC_RELAXED);
    else throw std::logic_error("Unlocked strategy reads are unavailable on this target");
}
#else
inline constexpr bool supported=false;
inline double load(const double*){throw std::logic_error("Unlocked strategy reads are unavailable on this compiler");}
inline void store(double*,double){throw std::logic_error("Unlocked strategy reads are unavailable on this compiler");}
#endif
struct EpsilonCache {double counter=-1,epsilon=0;};
static_assert(sizeof(EpsilonCache)==16,"Cache budget assumes 16 bytes");
}
