#pragma once
// A non-recursive BasicLockable for short node critical sections. This lock
// supplies acquire/release synchronization, not fairness or owner tracking.
// Keep condition-variable/control locks on std::mutex.
#include <atomic>
#include <cstdint>
#include <thread>
#if defined(_M_IX86) || defined(_M_X64) || defined(__i386__) || defined(__x86_64__)
#include <immintrin.h>
#elif defined(_MSC_VER) && (defined(_M_ARM) || defined(_M_ARM64))
#include <intrin.h>
#endif

namespace hrc_node_mutex {
class alignas(64) NodeMutex {
    std::atomic<std::uint32_t> state_{0};
    static void pause_cpu() noexcept {
#if defined(_M_IX86) || defined(_M_X64) || defined(__i386__) || defined(__x86_64__)
        _mm_pause();
#elif defined(_MSC_VER) && (defined(_M_ARM) || defined(_M_ARM64))
        __yield();
#elif defined(__aarch64__) || defined(__arm__)
        __asm__ __volatile__("yield");
#else
        std::atomic_signal_fence(std::memory_order_seq_cst);
#endif
    }
    static void backoff(unsigned& spins) noexcept {
        pause_cpu();
        if (++spins == 64) {
            spins = 0;
            std::this_thread::yield();
        }
    }
public:
    NodeMutex() noexcept = default;
    NodeMutex(const NodeMutex&) = delete;
    NodeMutex& operator=(const NodeMutex&) = delete;
    NodeMutex(NodeMutex&&) = delete;
    NodeMutex& operator=(NodeMutex&&) = delete;
    void lock() noexcept {
        if (state_.exchange(1, std::memory_order_acquire) == 0) return;
        unsigned spins = 0;
        for (;;) {
            while (state_.load(std::memory_order_relaxed) != 0) backoff(spins);
            if (state_.exchange(1, std::memory_order_acquire) == 0) return;
            backoff(spins);
        }
    }
    bool try_lock() noexcept {
        return state_.exchange(1, std::memory_order_acquire) == 0;
    }
    void unlock() noexcept { state_.store(0, std::memory_order_release); }
};
static_assert(std::atomic<std::uint32_t>::is_always_lock_free,
              "NodeMutex requires lock-free 32-bit atomics");
static_assert(sizeof(NodeMutex) == 64 && alignof(NodeMutex) == 64,
              "NodeMutex budget and cache-line isolation require 64 bytes");
} // namespace hrc_node_mutex
