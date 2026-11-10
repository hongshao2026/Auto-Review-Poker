#pragma once
// Independently implemented immutable-after-build board -> row index.
// The resource mask is the key; hashing is not part of its observable mapping.
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace hrc_cards {
class FlatBoardRowMap {
    static constexpr uint64_t empty_key = UINT64_MAX;
    std::vector<uint64_t> keys_;
    std::vector<uint32_t> values_;
    size_t used_ = 0;

public:
    static size_t capacity_for(size_t requested_slots) {
        size_t capacity = 4;
        while (capacity < requested_slots) {
            if (capacity > std::numeric_limits<size_t>::max() / 2)
                throw std::length_error("Board index capacity overflow");
            capacity *= 2;
        }
        if (capacity > std::numeric_limits<size_t>::max() / (sizeof(uint64_t) + sizeof(uint32_t)))
            throw std::length_error("Board index byte size overflow");
        return capacity;
    }
    static uint64_t memory_bytes_for(size_t requested_slots) {
        // Fixed allocator/container allowance; excludes input board temporary.
        return uint64_t(capacity_for(requested_slots)) * (sizeof(uint64_t) + sizeof(uint32_t))
               + sizeof(FlatBoardRowMap) + 128;
    }
    static uint64_t mixed_key(uint64_t key) noexcept {
        // A generic avalanche mix prevents the rank/suit bit layout from
        // clustering in the low capacity bits. No HRC hash implementation used.
        key ^= key >> 30;
        key *= UINT64_C(0xbf58476d1ce4e5b9);
        key ^= key >> 27;
        key *= UINT64_C(0x94d049bb133111eb);
        return key ^ (key >> 31);
    }
    void reserve(size_t requested_slots) {
        if (!keys_.empty()) throw std::logic_error("Board index already allocated");
        const size_t capacity = capacity_for(requested_slots);
        // Allocate in locals, preserving the empty state on allocation failure.
        std::vector<uint64_t> keys(capacity, empty_key);
        std::vector<uint32_t> values(capacity);
        keys_.swap(keys);
        values_.swap(values);
    }
    void emplace(uint64_t key, uint32_t value) {
        if (key == empty_key) throw std::invalid_argument("Invalid board index sentinel key");
        if (keys_.empty()) throw std::logic_error("Board index not allocated");
        const size_t mask = keys_.size() - 1;
        size_t slot = size_t(mixed_key(key)) & mask;
        while (keys_[slot] != empty_key) {
            if (keys_[slot] == key) throw std::invalid_argument("Duplicate board index key");
            slot = (slot + 1) & mask;
        }
        if (used_ >= keys_.size() / 2) throw std::length_error("Board index capacity exceeded");
        values_[slot] = value;
        keys_[slot] = key;
        ++used_;
    }
    bool lookup(uint64_t key, uint32_t& value) const noexcept {
        if (key == empty_key || keys_.empty()) return false;
        const size_t mask = keys_.size() - 1;
        size_t slot = size_t(mixed_key(key)) & mask;
        while (keys_[slot] != empty_key) {
            if (keys_[slot] == key) { value = values_[slot]; return true; }
            slot = (slot + 1) & mask;
        }
        return false;
    }
    size_t size() const noexcept { return used_; }
    size_t capacity() const noexcept { return keys_.size(); }
    uint64_t allocated_bytes() const noexcept {
        return uint64_t(keys_.capacity()) * sizeof(uint64_t)
               + uint64_t(values_.capacity()) * sizeof(uint32_t) + sizeof(*this);
    }
};
} // namespace hrc_cards
