// ============================================================
// Lumina BSC Tier 1 — Thread-Safe Logger
// ============================================================
// Minimal logging with severity levels (DBG/INF/WRN/ERR).
// Mutex-protected printf with timestamps. Compile-time level
// filtering via NDEBUG (debug logs stripped in Release builds).
// Also tracks pipeline stats: event counts, decision counts,
// latency histogram.
// ============================================================
#pragma once
#include "lumina/core/types.h"
#include <atomic>
#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <mutex>

namespace lumina {

class Logger {
public:
    enum Level { DEBUG, INFO, WARN, ERROR };

    static Logger& instance();

    void set_level(Level l);
    void log(Level level, const char* fmt, ...);

    // Stats tracking
    void record_event(EventType type);
    void record_decision(Decision d);
    void record_latency_ns(uint64_t ns);
    void print_stats();
    void reset_stats();

private:
    Logger();

    Level level_;
    std::mutex mutex_;

    static constexpr int MAX_BUCKETS = 20;
    std::atomic<uint64_t> total_events_{0};
    std::atomic<uint64_t> peak_latency_us_{0};
    std::atomic<uint64_t> event_counts_[8]{};
    std::atomic<uint64_t> decision_counts_[3]{};
    std::atomic<uint64_t> latency_hist_[MAX_BUCKETS]{};
};

// Convenience macros
#define LOG_DBG(fmt, ...) lumina::Logger::instance().log(lumina::Logger::DEBUG, fmt, ##__VA_ARGS__)
#define LOG_INF(fmt, ...) lumina::Logger::instance().log(lumina::Logger::INFO,  fmt, ##__VA_ARGS__)
#define LOG_WRN(fmt, ...) lumina::Logger::instance().log(lumina::Logger::WARN,  fmt, ##__VA_ARGS__)
#define LOG_ERR(fmt, ...) lumina::Logger::instance().log(lumina::Logger::ERROR, fmt, ##__VA_ARGS__)

} // namespace lumina
