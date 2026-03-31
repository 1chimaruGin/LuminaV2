#include "lumina/net/binance_klines.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <curl/curl.h>
#include <string>

namespace lumina {

static size_t curl_write_cb(void* data, size_t size, size_t nmemb, void* userp) {
    auto* buf = static_cast<std::string*>(userp);
    buf->append(static_cast<char*>(data), size * nmemb);
    return size * nmemb;
}

BinanceKlines::BinanceKlines() = default;

BinanceKlines::~BinanceKlines() { stop(); }

void BinanceKlines::start(const std::string& base_url) {
    if (running_.load()) return;
    base_url_ = base_url.empty() ? "https://api.binance.com" : base_url;
    if (const char* env = std::getenv("BINANCE_SPOT_API_BASE"); env && *env)
        base_url_ = env;
    running_.store(true);
    thread_ = std::thread(&BinanceKlines::worker, this);
}

void BinanceKlines::stop() {
    running_.store(false);
    if (thread_.joinable()) thread_.join();
}

MacroChange BinanceKlines::get() const {
    std::shared_lock lock(mtx_);
    return latest_;
}

void BinanceKlines::refresh_now() {
    fetch_and_update();
}

void BinanceKlines::worker() {
    fetch_and_update();
    auto last = std::chrono::steady_clock::now();
    while (running_.load()) {
        std::this_thread::sleep_for(std::chrono::seconds(5));
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - last).count();
        if (elapsed >= REFRESH_SECONDS) {
            fetch_and_update();
            last = now;
        }
    }
}

bool BinanceKlines::fetch_and_update() {
    double btc = fetch_4h_change("BTCUSDT");
    double bnb = fetch_4h_change("BNBUSDT");

    bool ok = (btc != 0.0 || bnb != 0.0);
    {
        std::unique_lock lock(mtx_);
        latest_.btc_4h_pct = btc;
        latest_.bnb_4h_pct = bnb;
        latest_.available = ok;
    }

    if (ok)
        std::fprintf(stderr, "[klines] BTC 4h: %+.2f%%  BNB 4h: %+.2f%%\n", btc * 100.0, bnb * 100.0);
    else
        std::fprintf(stderr, "[klines] Failed to fetch klines (network/geo-block?)\n");

    return ok;
}

double BinanceKlines::fetch_4h_change(const std::string& symbol) {
    std::string url = base_url_ + "/api/v3/klines?symbol=" + symbol +
                      "&interval=4h&limit=2";

    CURL* curl = curl_easy_init();
    if (!curl) return 0.0;

    std::string body;
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 15L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "lumina/1.0");
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);

    CURLcode rc = curl_easy_perform(curl);
    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK || http_code != 200) {
        std::fprintf(stderr, "[klines] %s: HTTP %ld curl=%d\n", symbol.c_str(), http_code, rc);
        return 0.0;
    }

    // Minimal JSON parsing: klines is [[open_time, open, high, low, close, ...], ...]
    // We want the second-to-last candle (completed) open and close.
    // Find the FIRST "[" after the outer "[" — that's the first candle.
    // We need the open (index 1) and close (index 4) of the first completed candle.
    auto find_field = [](const std::string& s, size_t start, int field_idx) -> double {
        size_t pos = start;
        int commas = 0;
        // Skip to the right field (comma-separated within the inner array)
        while (pos < s.size() && commas < field_idx) {
            if (s[pos] == ',') ++commas;
            ++pos;
        }
        if (pos >= s.size()) return 0.0;
        // Skip quote if present
        if (s[pos] == '"') ++pos;
        return std::strtod(s.c_str() + pos, nullptr);
    };

    // Find first inner array
    size_t arr_start = body.find('[');
    if (arr_start == std::string::npos) return 0.0;
    size_t inner_start = body.find('[', arr_start + 1);
    if (inner_start == std::string::npos) return 0.0;
    inner_start++; // skip [

    double open_price = find_field(body, inner_start, 1);
    double close_price = find_field(body, inner_start, 4);

    if (open_price > 0.0)
        return (close_price - open_price) / open_price;
    return 0.0;
}

} // namespace lumina
