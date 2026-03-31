#pragma once
#include <atomic>
#include <cstdint>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <thread>
#include <vector>

namespace lumina {

struct MacroChange {
    double btc_4h_pct = 0.0;
    double bnb_4h_pct = 0.0;
    bool available = false;
};

// Fetches BTC/BNB 4h klines from Binance in a background thread.
// Thread-safe reads via shared_mutex.
class BinanceKlines {
public:
    BinanceKlines();
    ~BinanceKlines();

    // Start background refresh thread (call once from main).
    void start(const std::string& base_url = "");

    // Stop background thread.
    void stop();

    // Thread-safe read of latest 4h change.
    MacroChange get() const;

    // Force an immediate refresh (blocks until done).
    void refresh_now();

private:
    void worker();
    bool fetch_and_update();
    double fetch_4h_change(const std::string& symbol);

    std::string base_url_;
    mutable std::shared_mutex mtx_;
    MacroChange latest_;
    std::atomic<bool> running_{false};
    std::thread thread_;
    static constexpr int REFRESH_SECONDS = 14400; // 4 hours
};

} // namespace lumina
