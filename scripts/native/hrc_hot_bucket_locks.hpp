#pragma once

#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <mutex>

namespace hrc_hot_bucket {

constexpr int first_node = 1;
constexpr int node_count = 3;
constexpr size_t stripe_count = 8;
constexpr uint64_t tree_identity = 17353740244742836947ull;

// One writer per counter. Other workers read it only on a rare raw[0]
// refresh. Keep counters for different workers on separate cache lines.
struct alignas(64) WorkerNode {
    std::atomic<uint64_t> updates{0};
    double divisor_key = -1;
    int divisor = 1;

    int refresh_divisor(double value) {
        if (value != divisor_key) {
            divisor_key = value;
            divisor = int(std::floor(std::sqrt(value)));
        }
        return divisor;
    }
};

struct HotNode {
    std::array<hrc_node_mutex::NodeMutex, stripe_count> locks;
    std::array<WorkerNode*, 32> workers{};
    size_t worker_count = 0;
    uint64_t initial_updates = 0;

    uint64_t total_updates() const {
        uint64_t total = initial_updates;
        for (size_t i = 0; i < worker_count; ++i)
            total += workers[i]->updates.load(std::memory_order_relaxed);
        return total;
    }
};

// Concurrent refreshes may observe different totals. Publish the latest
// available count without allowing a delayed refresh to move raw[0] backwards.
inline double publish_count(double* cell, double count) {
#if (defined(__clang__) || defined(__GNUC__)) && !defined(HRC_DISABLE_UNLOCKED_READS)
    if constexpr (hrc_unlocked_read::supported) {
        double observed = hrc_unlocked_read::load(cell);
        while (observed < count) {
            if (__atomic_compare_exchange(cell, &observed, &count, false, __ATOMIC_RELAXED, __ATOMIC_RELAXED))
                return count;
        }
        return observed;
    }
#endif
    throw std::logic_error("Bucket locks require lock-free counter publication");
}

// Format 23 only. Each bucket has independent regret, visits and average
// storage. Strategy readers still use relaxed atomic loads for regret.
template<class Node, class Random>
void update(Node& node, Random& rng, HotNode& hot, WorkerNode& local,
            int bucket, const double* p, const double* q) {
    double value = 0;
    for (int a = 0; a < node.k; ++a)
        if (p[a] > 0) value += p[a] * q[a];

    const std::lock_guard<hrc_node_mutex::NodeMutex> guard(hot.locks[size_t(bucket) % stripe_count]);
    local.updates.store(local.updates.load(std::memory_order_relaxed) + 1, std::memory_order_relaxed);
    ++node.visits[bucket];
    double* const data = node.raw.data();
    double weight = hrc_unlocked_read::load(data) + 1;
    const int divisor = local.refresh_divisor(weight);
    if (rng.integer() % divisor == 0)
        weight = publish_count(data, double(hot.total_updates()));

    const size_t regret = node.regret(bucket);
    for (int a = 0; a < node.k; ++a) {
        const double old = hrc_unlocked_read::load(data + regret + a);
        hrc_unlocked_read::store(data + regret + a, old + weight * (q[a] - value));
    }
    const size_t average = node.average(bucket);
    for (int a = 0; a < node.k; ++a) data[average + a] += weight * p[a];
    data[regret + node.k] += weight;
}

} // namespace hrc_hot_bucket
