// ============================================================
// Lumina BSC Tier 1 — Lock-Free SPSC Queue (header-only, template)
// ============================================================
// Single-Producer Single-Consumer bounded queue for inter-thread
// communication between pipeline stages. Cache-line padded to
// avoid false sharing. ~5 ns/op throughput.
//
// NOTE: Template class — must remain header-only.
// ============================================================
#pragma once
#include <array>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <optional>
#include <type_traits>

namespace lumina {

template <typename T, size_t N>
class SPSCQueue {
    static_assert((N & (N - 1)) == 0, "N must be power of 2");
    static_assert(std::is_trivially_copyable_v<T>);
public:
    SPSCQueue() : head_(0), tail_(0) {}
    SPSCQueue(const SPSCQueue&) = delete;
    SPSCQueue& operator=(const SPSCQueue&) = delete;

    bool try_push(const T& item) noexcept {
        uint64_t h = head_.load(std::memory_order_relaxed);
        uint64_t t = tail_.load(std::memory_order_acquire);
        if (h - t >= N) return false;
        buffer_[h & MASK] = item;
        head_.store(h + 1, std::memory_order_release);
        return true;
    }

    void push(const T& item) noexcept {
        while (!try_push(item)) {
#if defined(__x86_64__)
            __builtin_ia32_pause();
#endif
        }
    }

    std::optional<T> try_pop() noexcept {
        uint64_t t = tail_.load(std::memory_order_relaxed);
        uint64_t h = head_.load(std::memory_order_acquire);
        if (t >= h) return std::nullopt;
        T item = buffer_[t & MASK];
        tail_.store(t + 1, std::memory_order_release);
        return item;
    }

    T pop() noexcept {
        while (true) {
            auto item = try_pop();
            if (item) return *item;
#if defined(__x86_64__)
            __builtin_ia32_pause();
#endif
        }
    }

    std::optional<T> pop_timeout(uint64_t timeout_us) noexcept {
        auto start = std::chrono::steady_clock::now();
        while (true) {
            auto item = try_pop();
            if (item) return item;
            auto el = std::chrono::duration_cast<std::chrono::microseconds>(
                std::chrono::steady_clock::now() - start).count();
            if (static_cast<uint64_t>(el) >= timeout_us) return std::nullopt;
#if defined(__x86_64__)
            __builtin_ia32_pause();
#endif
        }
    }

    size_t size() const noexcept {
        uint64_t h = head_.load(std::memory_order_acquire);
        uint64_t t = tail_.load(std::memory_order_acquire);
        return (h >= t) ? (h - t) : 0;
    }

    bool empty() const noexcept { return size() == 0; }
    static constexpr size_t capacity() { return N; }

private:
    static constexpr uint64_t MASK = N - 1;
    alignas(64) std::atomic<uint64_t> head_;
    alignas(64) std::atomic<uint64_t> tail_;
    alignas(64) std::array<T, N> buffer_;
};

} // namespace lumina
