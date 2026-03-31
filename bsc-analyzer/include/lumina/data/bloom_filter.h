// ============================================================
// Lumina BSC Tier 1 — Bloom Filter (header-only, template)
// ============================================================
// Probabilistic set membership test for O(1) blacklist/scam
// lookups. 3-hash FNV-1a, 2M bits default (~256 KB).
// False positive rate ~0.24% at 100K entries.
// Used by: BlacklistDB, BytecodeDB.
//
// NOTE: Template class — must remain header-only.
// ============================================================
#pragma once
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace lumina {

template <size_t NUM_BITS = 2097152>
class BloomFilter {
public:
    BloomFilter() { bits_.fill(0); }
    void clear()  { bits_.fill(0); count_ = 0; }

    void insert(const void* data, size_t len) noexcept {
        set_bit(hash1(data, len) % NUM_BITS);
        set_bit(hash2(data, len) % NUM_BITS);
        set_bit(hash3(data, len) % NUM_BITS);
        ++count_;
    }

    template <size_t N>
    void insert(const std::array<uint8_t, N>& a) noexcept {
        insert(a.data(), N);
    }

    bool maybe_contains(const void* data, size_t len) const noexcept {
        return get_bit(hash1(data, len) % NUM_BITS) &&
               get_bit(hash2(data, len) % NUM_BITS) &&
               get_bit(hash3(data, len) % NUM_BITS);
    }

    template <size_t N>
    bool maybe_contains(const std::array<uint8_t, N>& a) const noexcept {
        return maybe_contains(a.data(), N);
    }

    size_t count() const { return count_; }

    double estimated_fpr() const {
        double m = NUM_BITS, k = 3.0, n = count_;
        return std::pow(1.0 - std::exp(-k * n / m), k);
    }

private:
    static uint64_t fnv1a(const void* d, size_t l, uint64_t s) noexcept {
        auto* p = static_cast<const uint8_t*>(d);
        uint64_t h = s;
        for (size_t i = 0; i < l; ++i) { h ^= p[i]; h *= 1099511628211ULL; }
        return h;
    }
    static uint64_t hash1(const void* d, size_t l) noexcept { return fnv1a(d, l, 14695981039346656037ULL); }
    static uint64_t hash2(const void* d, size_t l) noexcept { return fnv1a(d, l, 7562837012836490711ULL); }
    static uint64_t hash3(const void* d, size_t l) noexcept { return fnv1a(d, l, 2870177450012600261ULL); }

    void set_bit(size_t i) noexcept { bits_[i / 64] |= (1ULL << (i % 64)); }
    bool get_bit(size_t i) const noexcept { return (bits_[i / 64] >> (i % 64)) & 1ULL; }

    static constexpr size_t NUM_WORDS = (NUM_BITS + 63) / 64;
    std::array<uint64_t, NUM_WORDS> bits_;
    size_t count_ = 0;
};

} // namespace lumina
