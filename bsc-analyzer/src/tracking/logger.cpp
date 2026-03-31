// ============================================================
// Lumina BSC Tier 1 — Logger Implementation
// ============================================================
#include "lumina/tracking/logger.h"

namespace lumina {

Logger::Logger() : level_(INFO) {}

Logger& Logger::instance() {
    static Logger logger;
    return logger;
}

void Logger::set_level(Level l) { level_ = l; }

void Logger::log(Level level, const char* fmt, ...) {
    if (level < level_) return;
    std::lock_guard<std::mutex> lock(mutex_);

    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()).count() % 1000;

    char time_buf[32];
    std::strftime(time_buf, sizeof(time_buf), "%H:%M:%S", std::localtime(&time_t));

    const char* level_str[] = {"DBG", "INF", "WRN", "ERR"};
    std::fprintf(stderr, "[%s.%03ld] [%s] ", time_buf, ms, level_str[level]);

    va_list args;
    va_start(args, fmt);
    std::vfprintf(stderr, fmt, args);
    va_end(args);
    std::fprintf(stderr, "\n");
}

void Logger::record_event(EventType type) {
    event_counts_[static_cast<int>(type)].fetch_add(1, std::memory_order_relaxed);
}

void Logger::record_decision(Decision d) {
    decision_counts_[static_cast<int>(d)].fetch_add(1, std::memory_order_relaxed);
}

void Logger::record_latency_ns(uint64_t ns) {
    total_events_.fetch_add(1, std::memory_order_relaxed);
    uint64_t us = ns / 1000;
    int bucket = 0;
    uint64_t v = us;
    while (v > 1 && bucket < MAX_BUCKETS - 1) { v >>= 1; bucket++; }
    latency_hist_[bucket].fetch_add(1, std::memory_order_relaxed);
    if (us > peak_latency_us_.load(std::memory_order_relaxed)) {
        peak_latency_us_.store(us, std::memory_order_relaxed);
    }
}

void Logger::print_stats() {
    std::lock_guard<std::mutex> lock(mutex_);
    uint64_t total = total_events_.load();
    std::fprintf(stderr, "\n===== Lumina Tier 1 Stats =====\n");
    std::fprintf(stderr, "Total events processed: %lu\n", total);
    std::fprintf(stderr, "Peak latency: %lu us\n",
                 peak_latency_us_.load(std::memory_order_relaxed));

    std::fprintf(stderr, "\nDecisions:\n");
    std::fprintf(stderr, "  HARD_REJECT:   %lu\n", decision_counts_[0].load(std::memory_order_relaxed));
    std::fprintf(stderr, "  FORWARD_TIER2: %lu\n", decision_counts_[1].load(std::memory_order_relaxed));
    std::fprintf(stderr, "  FAST_PASS:     %lu\n", decision_counts_[2].load(std::memory_order_relaxed));

    std::fprintf(stderr, "\nEvent types:\n");
    const char* names[] = {"UNKNOWN", "CONTRACT_CREATE", "ADD_LIQ",
                           "REMOVE_LIQ", "BUY", "SELL", "OWNER_CHANGE", "APPROVAL"};
    for (int i = 0; i < 8; ++i) {
        uint64_t c = event_counts_[i].load(std::memory_order_relaxed);
        if (c > 0) std::fprintf(stderr, "  %s: %lu\n", names[i], c);
    }

    std::fprintf(stderr, "\nLatency histogram (parse -> decision):\n");
    for (int i = 0; i < MAX_BUCKETS; ++i) {
        uint64_t c = latency_hist_[i].load(std::memory_order_relaxed);
        if (c > 0) {
            uint64_t lower = (i == 0) ? 0 : (1ULL << i);
            uint64_t upper = (1ULL << (i + 1));
            std::fprintf(stderr, "  %5lu - %5lu us: %lu\n", lower, upper, c);
        }
    }
    std::fprintf(stderr, "===============================\n\n");
}

void Logger::reset_stats() {
    total_events_ = 0;
    peak_latency_us_ = 0;
    for (auto& c : event_counts_) c = 0;
    for (auto& c : decision_counts_) c = 0;
    for (auto& c : latency_hist_) c = 0;
}

} // namespace lumina
