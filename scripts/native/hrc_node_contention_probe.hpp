#pragma once

#include <chrono>
#include <cstdint>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace hrc_lock_probe {

enum class Access : uint32_t { read = 1, write = 2, write_with_average = 3 };

struct Event {
    uint32_t node, request, holder, wait_ns;
};
static_assert(sizeof(Event) == 16, "Expected four packed uint32 fields");

class Worker {
    uint32_t random_ = 0;
    uint32_t countdown_ = 0, offset_ = 0;
    std::vector<Event> events_;
    uint64_t dropped_ = 0;

    uint32_t next_offset() noexcept {
        random_ ^= random_ << 13;
        random_ ^= random_ >> 17;
        random_ ^= random_ << 5;
        return random_ & (interval - 1);
    }

public:
    static constexpr uint32_t interval = 512;
    static constexpr size_t capacity = 1 << 18;

    void init(uint32_t worker) {
        events_.reserve(capacity);
        random_ = 0x9e3779b9u * (worker + 1);
        offset_ = next_offset();
        countdown_ = offset_ + 1;
    }

    bool sample() noexcept {
        if (--countdown_ != 0) return false;
        // Draw one independent position in each successive block of requests.
        const uint32_t next = next_offset();
        countdown_ = interval - offset_ + next;
        offset_ = next;
        return true;
    }

    void record(Event event) noexcept {
        if (events_.size() == capacity) {
            ++dropped_;
            return;
        }
        events_.push_back(event);
    }

    void write(std::ofstream& out) const {
        const uint64_t count = events_.size();
        out.write(reinterpret_cast<const char*>(&count), sizeof(count));
        out.write(reinterpret_cast<const char*>(&dropped_), sizeof(dropped_));
        out.write(reinterpret_cast<const char*>(events_.data()), count * sizeof(Event));
    }
};

class Guard {
    hrc_node_mutex::NodeMutex& mutex_;
    Worker& worker_;
    Event event_;
    bool sampled_;

public:
    Guard(hrc_node_mutex::NodeMutex& mutex, Worker& worker, int node, int bucket, Access access) noexcept
        : mutex_(mutex), worker_(worker), event_{uint32_t(node), (uint32_t(bucket) << 2) | uint32_t(access), 0, 0},
          sampled_(worker.sample()) {
        const uint32_t holder = mutex_.try_tagged(event_.request);
        if (holder == 0) return;
        if (!sampled_) {
            mutex_.wait_tagged(event_.request);
            return;
        }
        event_.holder = holder;
        const auto start = std::chrono::steady_clock::now();
        mutex_.wait_tagged(event_.request);
        const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - start).count();
        constexpr auto max = std::numeric_limits<uint32_t>::max();
        event_.wait_ns = ns < max ? uint32_t(ns) : max;
    }

    ~Guard() {
        mutex_.unlock();
        if (sampled_) worker_.record(event_);
    }
    Guard(const Guard&) = delete;
    Guard& operator=(const Guard&) = delete;
};

} // namespace hrc_lock_probe
