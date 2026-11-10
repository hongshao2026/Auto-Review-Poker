// Correctness stress only: no throughput or latency measurements.
#include "../../native/hrc_node_mutex.hpp"
#include <array>
#include <chrono>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <vector>
#if defined(_WIN32)
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#elif defined(__linux__)
#include <sched.h>
#endif

using hrc_node_mutex::NodeMutex;
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

// Limit only this disposable probe process to two available CPUs, so 32
// contenders oversubscribe even on machines with more than 32 logical CPUs.
struct Affinity {
    bool limited = false;
#if defined(_WIN32)
    DWORD_PTR old_mask = 0;
    Affinity() {
        DWORD_PTR system = 0, selected = 0;
        if (!GetProcessAffinityMask(GetCurrentProcess(), &old_mask, &system)) return;
        unsigned count = 0;
        for (unsigned i = 0; i < sizeof(DWORD_PTR)*8 && count < 2; ++i)
            if (old_mask & (DWORD_PTR(1) << i)) { selected |= DWORD_PTR(1) << i; ++count; }
        limited = count != 0 && SetProcessAffinityMask(GetCurrentProcess(), selected);
    }
    ~Affinity() { if (limited) SetProcessAffinityMask(GetCurrentProcess(), old_mask); }
#elif defined(__linux__)
    cpu_set_t old_mask{};
    Affinity() {
        if (sched_getaffinity(0, sizeof(old_mask), &old_mask)) return;
        cpu_set_t selected; CPU_ZERO(&selected); unsigned count = 0;
        for (unsigned i = 0; i < CPU_SETSIZE && count < 2; ++i)
            if (CPU_ISSET(i, &old_mask)) { CPU_SET(i, &selected); ++count; }
        limited = count != 0 && sched_setaffinity(0, sizeof(selected), &selected) == 0;
    }
    ~Affinity() { if (limited) sched_setaffinity(0, sizeof(old_mask), &old_mask); }
#else
    Affinity() = default;
#endif
};

int main() try {
    Affinity affinity;
    auto locks = std::make_unique<NodeMutex[]>(33);
    for (unsigned i = 0; i < 33; ++i) {
        require(reinterpret_cast<std::uintptr_t>(&locks[i]) % 64 == 0, "array alignment");
        require(locks[i].try_lock(), "initially unlocked");
        require(!locks[i].try_lock(), "held try_lock rejected");
        locks[i].unlock();
    }
    constexpr unsigned workers = 32, repetitions = 2000;
    std::atomic<unsigned> ready{0}, errors{0}, exceptions{0};
    std::atomic<bool> start{false};
    std::uint64_t count = 0, mirror = 0;
    std::array<unsigned, workers> progress{};
    std::vector<std::thread> threads;
    struct Injected {};
    for (unsigned worker = 0; worker < workers; ++worker) threads.emplace_back([&, worker] {
        ready.fetch_add(1, std::memory_order_release);
        while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
        for (unsigned i = 0; i < repetitions; ++i) {
            try {
                std::lock_guard<NodeMutex> guard(locks[0]);
                if (mirror != count * 3) errors.fetch_add(1);
                ++count;
                if (i % 251 == 0) std::this_thread::yield();
                mirror = count * 3;
                ++progress[worker];
                if (i % 17 == 0) throw Injected{};
            } catch (const Injected&) { exceptions.fetch_add(1); }
        }
    });
    while (ready.load(std::memory_order_acquire) != workers) std::this_thread::yield();
    start.store(true, std::memory_order_release);
    for (auto& worker : threads) worker.join();
    require(errors == 0 && count == workers * repetitions && mirror == count * 3,
            "protected data invariant or lost update");
    for (auto completed : progress) require(completed == repetitions, "worker failed to finish");
    require(exceptions == workers * ((repetitions + 16) / 17), "exception coverage");

    // Hold the lock until every contender has announced its acquisition
    // attempt, then deliberately deschedule the holder. None may enter early.
    threads.clear(); ready = 0; std::atomic<unsigned> entered{0};
    locks[0].lock();
    for (unsigned worker = 0; worker < workers; ++worker) threads.emplace_back([&] {
        ready.fetch_add(1, std::memory_order_release);
        std::lock_guard<NodeMutex> guard(locks[0]);
        entered.fetch_add(1);
    });
    while (ready.load(std::memory_order_acquire) != workers) std::this_thread::yield();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    const bool excluded = entered.load() == 0;
    locks[0].unlock();
    for (auto& worker : threads) worker.join();
    require(excluded && entered == workers, "slow holder exclusion or recovery");
    require(locks[0].try_lock(), "lock reusable after all stress"); locks[0].unlock();
    std::cout << "{\"ok\":true,\"threads\":" << workers
              << ",\"affinity_limited_to_at_most_two_cpus\":" << (affinity.limited ? "true" : "false")
              << ",\"updates\":" << count << ",\"exceptions\":" << exceptions
              << ",\"all_workers_finished\":true,\"slow_holder_waiters\":" << entered
              << ",\"early_entries\":0,\"lock_bytes\":" << sizeof(NodeMutex)
              << ",\"alignment\":" << alignof(NodeMutex) << "}\n";
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
