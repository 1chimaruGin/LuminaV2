// KOL buy monitor for Four.meme tokens on BSC.
//
// Two modes:
//   1. Live (default): WSS eth_subscribe for sub-second KOL buy detection
//   2. Replay: --yesterday / --recent N / FROM TO scans historical blocks
//
// Detection: ERC20 Transfer events where recipient is a KOL wallet and the
// token address ends in 0x...4444 (Four.meme deterministic deploy pattern).
//
// Replay output: deduplicated numbered token list with mcap at entry.
// Live output: streaming JSONL per KOL buy + IPC to hotpath.
//
// Env: QUICK_NODE_BSC_RPC, KOL_FILE (top.json), BSC_WS_URL (optional)

#include "lumina/core/types.h"
#include "lumina/data/clickhouse_writer.h"
#include "lumina/data/live_writer.h"
#include "lumina/fourmeme/constants.h"
#include "lumina/fourmeme/token_create_abi.h"
#include "lumina/net/binance_klines.h"
#include "lumina/net/bsc_ws_client.h"
#include "lumina/net/ipc_bridge.h"
#include "lumina/net/rpc_client.h"
#include "lumina/tracking/logger.h"
#include "lumina/ml/kol_scorer.h"
#include "lumina/data/deployer_db.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <functional>
#include <map>
#include <mutex>
#include <tuple>
#include <signal.h>
#include <string>
#include <thread>
#include <cstdint>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace lumina;

namespace {
DeployerDB g_deployer_db;
LiveDatasetWriter* g_writer = nullptr;
BinanceKlines g_klines;
} // namespace

static std::atomic<bool> g_running{true};
static FILE* g_log_fp = nullptr; // log file mirror (set by --log-file)

// ── Session stats for structured logging ─────────────────────────────────────
struct SessionStats {
    std::atomic<uint64_t> tokens_seen{0};
    std::atomic<uint64_t> signals_emitted{0};
    std::atomic<uint64_t> rows_written{0};
    std::atomic<uint64_t> paper_hits{0};
    std::atomic<uint64_t> mode_probe{0};
    std::atomic<uint64_t> mode_confirmed{0};
    std::atomic<uint64_t> mode_strong{0};
    std::chrono::steady_clock::time_point start_time;
};
static SessionStats g_session;

// ANSI color codes
#define CLR_RESET    "\033[0m"
#define CLR_DIM      "\033[2m"
#define CLR_CYAN     "\033[36m"
#define CLR_YELLOW   "\033[33m"
#define CLR_GREEN    "\033[32;1m"
#define CLR_RED      "\033[31m"
#define CLR_MAGENTA  "\033[35m"
#define CLR_BOLD     "\033[1m"
#define CLR_RED_BOLD "\033[31;1m"
#define CLR_YLW_DIM  "\033[33;2m"

// Write message to stderr and, if open, to the log file simultaneously
static void tee_stderr(const std::string& msg) {
    std::fputs(msg.c_str(), stderr);
    if (g_log_fp) {
        std::fputs(msg.c_str(), g_log_fp);
        std::fflush(g_log_fp);
    }
}

static void print_session_summary() {
    auto elapsed = std::chrono::steady_clock::now() - g_session.start_time;
    auto mins = std::chrono::duration_cast<std::chrono::minutes>(elapsed).count();
    char buf[512];
    std::snprintf(buf, sizeof(buf),
        "\n" CLR_GREEN "── Session Summary ──" CLR_RESET "\n"
        "  Runtime:    %lldm\n"
        "  Tokens:     %llu\n"
        "  Signals:    %llu\n"
        "  Rows:       %llu\n"
        "  Paper hits: %llu\n"
        "  Modes:      PROBE=%llu  CONFIRMED=%llu  STRONG=%llu\n",
        static_cast<long long>(mins),
        static_cast<unsigned long long>(g_session.tokens_seen.load()),
        static_cast<unsigned long long>(g_session.signals_emitted.load()),
        static_cast<unsigned long long>(g_session.rows_written.load()),
        static_cast<unsigned long long>(g_session.paper_hits.load()),
        static_cast<unsigned long long>(g_session.mode_probe.load()),
        static_cast<unsigned long long>(g_session.mode_confirmed.load()),
        static_cast<unsigned long long>(g_session.mode_strong.load()));
    tee_stderr(buf);
    if (g_writer) {
        std::snprintf(buf, sizeof(buf), "  Writer:     %d CSV rows, %d paper hits\n",
                      g_writer->rows_written(), g_writer->paper_hits());
        tee_stderr(buf);
    }
}

static void on_signal(int) {
    if (!g_running.load()) {
        // Second signal: force exit
        std::_Exit(1);
    }
    g_running.store(false);
    print_session_summary();
}

// ── Types / helpers ─────────────────────────────────────────────────────────

struct TokenMeta {
    Address creator;
    uint64_t create_block = 0;
    std::string name;
    std::string symbol;
};

// One ERC20 Transfer to a KOL (raw, before dedupe by KOL)
struct KolBuyEvent {
    Address kol{};
    uint64_t block = 0;
    uint64_t log_index = 0;
    std::string tx_hash;
    // ERC20 Transfer `data`: uint256 value (token wei, usually 18 decimals)
    std::string amount_raw; // decimal string, empty if unparsed
    uint64_t holder_count = 0; // unique recipients up to this buy block
};

// Per-slot, per-delay-profile outcome (3 slots x 3 delays: +1 block, +2 blocks, +2s)
struct SlotDelayStats {
    uint64_t our_entry_block = 0;
    double our_entry_mcap_usd = 0.0;
    double peak_mcap_usd = 0.0;
    double low_mcap_usd = 0.0;
};

struct TokenSummary {
    std::string name;
    std::string token_addr;
    Address first_buyer;
    uint64_t first_buy_block = 0;
    uint64_t create_block = 0;
    uint64_t age_blocks = 0;
    size_t kol_count = 0;
    double mcap_bnb = 0.0;
    double max_funds_bnb = 18.0;
    // Distinct KOLs in chronological order (Transfer receipt, first occurrence per wallet)
    std::vector<KolBuyEvent> kol_order;
    // Backtest enrichment fields (USD)
    double entry_mcap_usd = 0.0;
    double peak_mcap_usd = 0.0;
    double low_mcap_usd = 0.0;
    double current_mcap_usd = 0.0;
    bool graduated = false;
    uint64_t create_timestamp = 0;
    // Mcap at each KOL's buy block (slots 0..2)
    double slot_entry_mcap_usd[3] = {0.0, 0.0, 0.0};
    SlotDelayStats slot_delay[3][3]{};
    Address creator{};
    // Sum of ERC20 Transfer amounts (token units) with from == creator (excludes mint from 0x0).
    double dev_sell_tokens = 0.0;
    // Enrichment v2: bonding curve progress, BNB price, holder count
    double bonding_curve_pct = 0.0;  // funds_bnb / max_funds_bnb  [0..1]
    double bnb_price_usd = 0.0;
    uint64_t holder_count_at_entry = 0;
};

// Four.meme bonding curve mcap: constant virtual reserve V=4.34 BNB regardless of max_funds.
// At 0 funds: mcap ≈ V * bnb_price ≈ $2800. At 18 BNB graduation: ≈ $74K.
static constexpr double VIRTUAL_BNB = 4.34;

static double bonding_curve_mcap_usd(double funds_bnb, double /*max_funds_bnb*/, double bnb_price) {
    double mcap_bnb = (VIRTUAL_BNB + funds_bnb) * (VIRTUAL_BNB + funds_bnb) / VIRTUAL_BNB;
    return mcap_bnb * bnb_price;
}

// PancakeSwap V3 price for graduated tokens
static const char* PANCAKE_V3_FACTORY = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865";
static const char* WBNB_ADDR          = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c";
static constexpr double TOTAL_SUPPLY  = 1000000000.0; // 1B tokens (Four.meme standard)

static std::string pad_address(const std::string& addr) {
    std::string a = addr;
    if (a.size() > 2 && a[0] == '0' && a[1] == 'x') a = a.substr(2);
    while (a.size() < 64) a = "0" + a;
    return a;
}

static std::string pad_uint24(uint32_t val) {
    char buf[65];
    std::snprintf(buf, sizeof(buf), "%064x", val);
    return buf;
}

static double hex_word_to_double(const std::string& hex, size_t word_offset) {
    if (hex.size() < (word_offset + 1) * 64) return 0.0;
    std::string_view w(hex.data() + word_offset * 64, 64);
    auto hn = [](char x) -> int {
        if (x >= '0' && x <= '9') return x - '0';
        if (x >= 'a' && x <= 'f') return 10 + x - 'a';
        if (x >= 'A' && x <= 'F') return 10 + x - 'A';
        return 0;
    };
    double v = 0.0;
    for (size_t i = 0; i < 64; ++i) v = v * 16.0 + hn(w[i]);
    return v;
}

static bool is_zero_result(const std::string& hex) {
    for (char c : hex) if (c != '0') return false;
    return true;
}

static const char* PANCAKE_V2_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73";

struct DexPool {
    std::string address;
    bool is_v3 = false;
};

struct DexPools {
    DexPool v2;
    DexPool v3;
    bool has_v2 = false;
    bool has_v3 = false;
};

static DexPools find_all_dex_pools(BscRpcClient& client, const std::string& token_addr) {
    DexPools pools;
    std::string token_low = token_addr;
    std::transform(token_low.begin(), token_low.end(), token_low.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    // V2: getPair(address,address) = 0xe6a43905
    {
        std::string calldata = "0xe6a43905" + pad_address(token_low) + pad_address(WBNB_ADDR);
        std::string result;
        if (client.eth_call_raw(PANCAKE_V2_FACTORY, calldata, "latest", result) &&
            !is_zero_result(result) && result.size() >= 40) {
            pools.v2 = {"0x" + result.substr(result.size() - 40), false};
            pools.has_v2 = true;
        }
    }

    // V3: try multiple fee tiers, take first found
    static const uint32_t fees[] = {2500, 10000, 500, 100};
    for (uint32_t fee : fees) {
        std::string calldata = "0x1698ee82" + pad_address(token_low) + pad_address(WBNB_ADDR) + pad_uint24(fee);
        std::string result;
        if (client.eth_call_raw(PANCAKE_V3_FACTORY, calldata, "latest", result) &&
            !is_zero_result(result) && result.size() >= 40) {
            pools.v3 = {"0x" + result.substr(result.size() - 40), true};
            pools.has_v3 = true;
            break;
        }
    }
    return pools;
}

// Legacy API for backward compat
static DexPool find_dex_pool(BscRpcClient& client, const std::string& token_addr) {
    auto pools = find_all_dex_pools(client, token_addr);
    if (pools.has_v2) return pools.v2;
    if (pools.has_v3) return pools.v3;
    return {};
}

// Query PancakeSwap V3 slot0 at a specific block, compute mcap in USD
static double v3_mcap_usd(BscRpcClient& client, const std::string& pool_addr,
                           const std::string& token_addr, const std::string& block_hex,
                           double bnb_price) {
    // slot0() selector = 0x3850c7bd
    std::string result;
    if (!client.eth_call_raw(pool_addr, "0x3850c7bd", block_hex, result) || result.size() < 64)
        return 0.0;

    // First word is sqrtPriceX96 (uint160, stored in a 256-bit word)
    double sqrtPriceX96 = hex_word_to_double(result, 0);
    if (sqrtPriceX96 < 1.0) return 0.0;

    // price = (sqrtPriceX96 / 2^96)^2 = sqrtPriceX96^2 / 2^192
    static const double TWO_192 = std::pow(2.0, 192);
    double price_ratio = (sqrtPriceX96 * sqrtPriceX96) / TWO_192;

    // Determine token ordering: lower address = token0
    std::string tok_low = token_addr, wbnb_low = WBNB_ADDR;
    std::transform(tok_low.begin(), tok_low.end(), tok_low.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::transform(wbnb_low.begin(), wbnb_low.end(), wbnb_low.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    double price_bnb_per_token;
    if (tok_low < wbnb_low) {
        // token is token0: price_ratio = token1/token0 = WBNB/token
        price_bnb_per_token = price_ratio;
    } else {
        // token is token1: price_ratio = token0/token1 = WBNB/token... wait, opposite
        // price_ratio = token0/token1 where token0=WBNB, so price = WBNB_per_token = 1/price_ratio
        if (price_ratio > 1e-30)
            price_bnb_per_token = 1.0 / price_ratio;
        else
            return 0.0;
    }

    return price_bnb_per_token * TOTAL_SUPPLY * bnb_price;
}

// PancakeSwap V2: getReserves() = 0x0902f1ac → (uint112 reserve0, uint112 reserve1, uint32 ts)
static double v2_mcap_usd(BscRpcClient& client, const std::string& pair_addr,
                           const std::string& token_addr, const std::string& block_hex,
                           double bnb_price) {
    std::string result;
    if (!client.eth_call_raw(pair_addr, "0x0902f1ac", block_hex, result) || result.size() < 192)
        return 0.0;

    double reserve0 = hex_word_to_double(result, 0) / 1e18;
    double reserve1 = hex_word_to_double(result, 1) / 1e18;
    if (reserve0 < 1e-12 || reserve1 < 1e-12) return 0.0;

    std::string tok_low = token_addr, wbnb_low = WBNB_ADDR;
    std::transform(tok_low.begin(), tok_low.end(), tok_low.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::transform(wbnb_low.begin(), wbnb_low.end(), wbnb_low.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    double bnb_reserve, token_reserve;
    if (tok_low < wbnb_low) {
        token_reserve = reserve0;
        bnb_reserve = reserve1;
    } else {
        bnb_reserve = reserve0;
        token_reserve = reserve1;
    }

    double price_bnb_per_token = bnb_reserve / token_reserve;
    return price_bnb_per_token * TOTAL_SUPPLY * bnb_price;
}

// Unified DEX mcap query: tries V3 slot0, falls back to V2 reserves
static double dex_mcap_usd(BscRpcClient& client, const DexPool& pool,
                            const std::string& token_addr, const std::string& block_hex,
                            double bnb_price) {
    if (pool.is_v3)
        return v3_mcap_usd(client, pool.address, token_addr, block_hex, bnb_price);
    else
        return v2_mcap_usd(client, pool.address, token_addr, block_hex, bnb_price);
}

// Best-effort DEX mcap: try both V2 and V3, prefer V2 when both available
static double best_dex_mcap_usd(BscRpcClient& client, const DexPools& pools,
                                 const std::string& token_addr, const std::string& block_hex,
                                 double bnb_price) {
    double mc_v2 = 0.0, mc_v3 = 0.0;
    if (pools.has_v2)
        mc_v2 = v2_mcap_usd(client, pools.v2.address, token_addr, block_hex, bnb_price);
    if (pools.has_v3)
        mc_v3 = v3_mcap_usd(client, pools.v3.address, token_addr, block_hex, bnb_price);
    if (mc_v2 > 100) return mc_v2;
    if (mc_v3 > 100) return mc_v3;
    return 0.0;
}

enum class OutFmt { Json, Tsv };

static std::string addr_lower(const Address& a) {
    std::string h = address_to_hex(a);
    std::transform(h.begin(), h.end(), h.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return h;
}

static std::string to_lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

static std::string json_escape(std::string_view s) {
    std::string o;
    o.reserve(s.size() + 8);
    for (char c : s) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default: o += c;
        }
    }
    return o;
}

static double decimal_string_to_tokens_double(const std::string& dec);

// Maps KOL address → short name (A, B, C, ...) from top.json — declared early for use in append_kol_buys_json
static std::unordered_map<Address, std::string, AddressHash> g_kol_name_map;

static void append_kol_buys_json(std::string& out, const TokenSummary& ts) {
    out += "\"kol_buys\":[";
    for (size_t i = 0; i < ts.kol_order.size(); ++i) {
        if (i) out += ',';
        const auto& k = ts.kol_order[i];
        int si = static_cast<int>(i);
        double em = (si < 3) ? ts.slot_entry_mcap_usd[si] : 0.0;
        out += "{\"kol\":\"";
        out += addr_lower(k.kol);
        out += "\",\"kol_name\":\"";
        {
            auto nit = g_kol_name_map.find(k.kol);
            out += json_escape((nit != g_kol_name_map.end()) ? nit->second : "");
        }
        out += "\",\"buy_block\":";
        out += std::to_string(k.block);
        out += ",\"log_index\":";
        out += std::to_string(k.log_index);
        out += ",\"tx\":\"";
        out += json_escape(k.tx_hash);
        out += "\",\"entry_mcap_usd\":";
        out += std::to_string(static_cast<long long>(em + 0.5));
        out += ",\"amount_raw\":\"";
        out += json_escape(k.amount_raw.empty() ? "0" : k.amount_raw);
        out += "\",\"buy_notional_usd_approx\":";
        {
            double buy_usd = 0.0;
            if (em > 1.0 && !k.amount_raw.empty() && k.amount_raw != "0") {
                double nt = decimal_string_to_tokens_double(k.amount_raw);
                buy_usd = nt * (em / TOTAL_SUPPLY);
            }
            out += std::to_string(static_cast<long long>(buy_usd + 0.5));
        }
        out += '}';
    }
    out += ']';
}

static void append_slot_delay_json(std::string& out, const TokenSummary& ts) {
    static const char* dk[3] = {"plus_1_block", "plus_2_block", "plus_2s"};
    out += "\"slot_delay\":{";
    bool first_slot = true;
    for (int s = 0; s < 3; ++s) {
        if (s >= static_cast<int>(ts.kol_order.size())) break;
        if (!first_slot) out += ',';
        first_slot = false;
        out += "\"slot_";
        out += char('1' + s);
        out += "\":{";
        for (int d = 0; d < 3; ++d) {
            if (d) out += ',';
            const auto& sd = ts.slot_delay[s][d];
            out += '"';
            out += dk[d];
            out += "\":{\"our_entry_block\":";
            out += std::to_string(sd.our_entry_block);
            out += ",\"our_entry_mcap_usd\":";
            out += std::to_string(static_cast<long long>(sd.our_entry_mcap_usd + 0.5));
            out += ",\"peak_mcap_usd\":";
            out += std::to_string(static_cast<long long>(sd.peak_mcap_usd + 0.5));
            out += ",\"low_mcap_usd\":";
            out += std::to_string(static_cast<long long>(sd.low_mcap_usd + 0.5));
            out += "}";
        }
        out += '}';
    }
    out += '}';
}

static void tsv_sanitize(std::string& s) {
    for (char& c : s) {
        if (c == '\t' || c == '\n' || c == '\r') c = ' ';
    }
}

static size_t load_kol_file(const char* path,
                            std::unordered_set<Address, AddressHash>& out,
                            std::vector<std::string>& padded_out) {
    std::ifstream in(path);
    if (!in) return 0;
    std::string full;
    { std::string line; while (std::getline(in, line)) full += line + "\n"; }
    in.close();

    // Parse JSON array entries: find each {"address":"0x...", "name":"X", ...}
    size_t n = 0;
    size_t pos = 0;
    while (pos < full.size()) {
        auto obj_start = full.find('{', pos);
        if (obj_start == std::string::npos) break;
        auto obj_end = full.find('}', obj_start);
        if (obj_end == std::string::npos) break;
        std::string obj = full.substr(obj_start, obj_end - obj_start + 1);
        pos = obj_end + 1;

        // Extract address
        auto addr_pos = obj.find("\"address\"");
        if (addr_pos == std::string::npos) continue;
        auto q1 = obj.find("\"0x", addr_pos);
        if (q1 == std::string::npos) continue;
        auto q2 = obj.find('"', q1 + 1);
        if (q2 == std::string::npos) continue;
        std::string addr_str = obj.substr(q1 + 1, q2 - q1 - 1);
        if (addr_str.size() < 42) continue;

        // Extract name
        std::string kol_name;
        auto name_pos = obj.find("\"name\"");
        if (name_pos != std::string::npos) {
            auto nq1 = obj.find('"', name_pos + 6);
            if (nq1 != std::string::npos) {
                auto nq2 = obj.find('"', nq1 + 1);
                if (nq2 != std::string::npos)
                    kol_name = obj.substr(nq1 + 1, nq2 - nq1 - 1);
            }
        }

        auto a = hex_to_address(addr_str);
        bool all_zero = true;
        for (int i = 0; i < 20; ++i) { if (a[i]) { all_zero = false; break; } }
        if (all_zero) continue;
        out.insert(a);
        if (!kol_name.empty()) g_kol_name_map[a] = kol_name;
        std::string lower = to_lower(addr_str);
        std::string padded = "0x000000000000000000000000" + lower.substr(2, 40);
        padded_out.push_back(padded);
        ++n;
    }
    return n;
}

static std::string kol_display_name(const Address& a) {
    auto it = g_kol_name_map.find(a);
    return (it != g_kol_name_map.end()) ? it->second : addr_lower(a).substr(0, 10);
}

static std::string block_to_hex(uint64_t bn) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "0x%lx", static_cast<unsigned long>(bn));
    return buf;
}

// Transfer `data` last 64 hex → token amount (18 decimals) as double
static double transfer_amount_tokens_from_data(std::string_view data) {
    std::string_view d = data;
    if (d.size() >= 2 && d[0] == '0' && (d[1] == 'x' || d[1] == 'X')) d = d.substr(2);
    if (d.size() < 64) return 0.0;
    d = d.substr(d.size() - 64);
    double v = 0.0;
    for (int i = 0; i < 64; ++i) {
        char c = d[static_cast<size_t>(i)];
        uint8_t n = 0;
        if (c >= '0' && c <= '9') n = static_cast<uint8_t>(c - '0');
        else if (c >= 'a' && c <= 'f') n = static_cast<uint8_t>(10 + c - 'a');
        else if (c >= 'A' && c <= 'F') n = static_cast<uint8_t>(10 + c - 'A');
        else return 0.0;
        v = v * 16.0 + static_cast<double>(n);
    }
    return v / 1e18;
}

// `amount_raw` decimal string (wei) → human token units
static double decimal_string_to_tokens_double(const std::string& dec) {
    if (dec.empty() || dec == "0") return 0.0;
    double x = 0.0;
    for (char c : dec) {
        if (c < '0' || c > '9') return 0.0;
        x = x * 10.0 + static_cast<double>(c - '0');
        if (x > 1e24) break;
    }
    return x / 1e18;
}

static double sum_dev_transfer_out_tokens(BscRpcClient& client, const std::string& token_lower,
                                          const Address& creator, uint64_t from_block, uint64_t to_block,
                                          const std::string& xfer_topic_lower) {
    if (to_block < from_block || is_zero(creator)) return 0.0;
    double sum = 0.0;
    uint64_t cur = from_block;
    constexpr uint64_t K_CHUNK = 4000;
    std::vector<RpcLogEntry> logs;
    while (cur <= to_block) {
        uint64_t end = std::min(cur + K_CHUNK - 1, to_block);
        logs.clear();
        if (!client.eth_get_logs_token_transfers_all(token_lower, xfer_topic_lower, block_to_hex(cur),
                                                     block_to_hex(end), logs))
            return sum;
        for (const auto& log : logs) {
            if (log.topics.size() < 3 || log.topics[1].size() < 42) continue;
            std::string af = "0x" + log.topics[1].substr(log.topics[1].size() - 40);
            Address from = hex_to_address(af);
            if (is_zero(from) || from != creator) continue;
            sum += transfer_amount_tokens_from_data(log.data);
        }
        cur = end + 1;
    }
    return sum;
}

static double fetch_bnb_price() {
    if (const char* env = std::getenv("BNB_USD"); env && *env) {
        double p = std::atof(env);
        if (p > 0) return p;
    }
    // Try CoinGecko API
    FILE* fp = popen("curl -s 'https://api.coingecko.com/api/v3/simple/price?ids=binancecoin&vs_currencies=usd' 2>/dev/null", "r");
    if (fp) {
        char buf[512];
        std::string resp;
        while (fgets(buf, sizeof(buf), fp)) resp += buf;
        pclose(fp);
        auto pos = resp.find("\"usd\":");
        if (pos != std::string::npos) {
            double p = std::atof(resp.c_str() + pos + 6);
            if (p > 10) return p;
        }
    }
    return 600.0;
}

// Chainlink BNB/USD price feed on BSC — latestAnswer() returns int256 with 8 decimals
static const char* CHAINLINK_BNB_USD = "0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE";
static std::unordered_map<uint64_t, double> g_bnb_price_cache;
static std::mutex g_bnb_price_cache_mu;

static double fetch_bnb_price_at_block(BscRpcClient& client, uint64_t block_num, double fallback) {
    uint64_t cache_key = (block_num / 500) * 500;
    {
        std::lock_guard<std::mutex> lk(g_bnb_price_cache_mu);
        auto it = g_bnb_price_cache.find(cache_key);
        if (it != g_bnb_price_cache.end()) return it->second;
    }

    std::string result;
    std::string bh = block_to_hex(cache_key > 0 ? cache_key : block_num);
    if (client.eth_call_raw(CHAINLINK_BNB_USD, "0x50d25bcd", bh, result) && result.size() >= 64) {
        double raw = hex_word_to_double(result, 0);
        double price = raw / 1e8;
        if (price > 10.0 && price < 100000.0) {
            std::lock_guard<std::mutex> lk(g_bnb_price_cache_mu);
            g_bnb_price_cache[cache_key] = price;
            return price;
        }
    }
    return fallback;
}

// Mcap (USD) at a specific block (curve + DEX); fills all_dex_pools on first DEX hit
static double entry_mcap_usd_at_buy_block(BscRpcClient& client, const std::string& token_addr, Address token,
                                          uint64_t buy_block, double bnb_fallback,
                                          std::unordered_map<std::string, DexPools>& all_dex_pools) {
    TokenManagerCurveInfo curve{};
    std::string bh = block_to_hex(buy_block);
    double hist_bnb = fetch_bnb_price_at_block(client, buy_block, bnb_fallback);
    if (!client.eth_get_token_info_curve_at_block(token, bh, curve) || !curve.valid) return 0.0;
    double quote_price = curve.is_bnb_quote ? hist_bnb : 1.0;
    if (curve.liquidity_added) {
        DexPools pools{};
        auto it = all_dex_pools.find(token_addr);
        if (it != all_dex_pools.end())
            pools = it->second;
        else {
            pools = find_all_dex_pools(client, token_addr);
            if (pools.has_v2 || pools.has_v3) all_dex_pools[token_addr] = pools;
        }
        if (pools.has_v2 || pools.has_v3) {
            double mc = 0.0;
            for (uint64_t off : {0ULL, 1ULL, 3ULL, 10ULL}) {
                mc = best_dex_mcap_usd(client, pools, token_addr, block_to_hex(buy_block + off), hist_bnb);
                if (mc > 100) break;
            }
            if (mc > 100) return mc;
        }
        return curve.last_price_raw / 1e9 * quote_price;
    }
    return curve.last_price_raw / 1e9 * quote_price;
}

// Env: KOL_PEAK_OFFSETS="0,1,2,5,..." or KOL_PEAK_FAST=1 for fewer checkpoints (faster backtest).
static const uint64_t k_default_peak_offsets[] = {0, 1, 2, 3, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 4000, 10000,
                                                  30000, 60000, 130000};
static const uint64_t k_fast_peak_offsets[] = {0, 1, 2, 5, 10, 20, 50, 100, 500, 1000, 2000, 5000, 10000, 30000, 60000,
                                               130000};

static std::vector<uint64_t> load_peak_offsets() {
    if (const char* e = std::getenv("KOL_PEAK_OFFSETS")) {
        if (e[0] != '\0') {
            std::vector<uint64_t> v;
            std::string s(e);
            size_t p = 0;
            while (p < s.size()) {
                while (p < s.size() && (s[p] == ' ' || s[p] == '\t')) ++p;
                if (p >= s.size()) break;
                size_t q = s.find(',', p);
                std::string tok = (q == std::string::npos) ? s.substr(p) : s.substr(p, q - p);
                while (!tok.empty() && (tok.back() == ' ' || tok.back() == '\t')) tok.pop_back();
                if (!tok.empty()) v.push_back(std::strtoull(tok.c_str(), nullptr, 0));
                if (q == std::string::npos) break;
                p = q + 1;
            }
            if (!v.empty()) return v;
        }
    }
    if (const char* f = std::getenv("KOL_PEAK_FAST")) {
        if (f[0] != '\0' && std::strcmp(f, "0") != 0) {
            return std::vector<uint64_t>(k_fast_peak_offsets,
                                         k_fast_peak_offsets + sizeof(k_fast_peak_offsets) / sizeof(k_fast_peak_offsets[0]));
        }
    }
    return std::vector<uint64_t>(k_default_peak_offsets,
                                 k_default_peak_offsets + sizeof(k_default_peak_offsets) / sizeof(k_default_peak_offsets[0]));
}

static const std::vector<uint64_t>& peak_offsets_vec() {
    static std::vector<uint64_t> v = load_peak_offsets();
    return v;
}

// Batched peak/low scan: pre-fetches all curve checkpoints in one HTTP round-trip,
// then falls back to DEX queries only for graduated tokens.
static void scan_peak_low_window(BscRpcClient& client, TokenSummary& ts, Address token, uint64_t our_entry_block,
                                 double seed_peak_low, uint64_t to_b, double bnb_price,
                                 std::unordered_map<std::string, DexPools>& all_dex_pools, double& peak_usd,
                                 double& low_usd, double& current_usd) {
    peak_usd = seed_peak_low;
    low_usd = seed_peak_low;
    bool has_dex = (all_dex_pools.count(ts.token_addr) > 0);
    DexPools pools = has_dex ? all_dex_pools[ts.token_addr] : DexPools{};

    // Collect all target blocks for batching
    std::vector<uint64_t> target_blocks;
    for (uint64_t off : peak_offsets_vec()) {
        uint64_t target = our_entry_block + off;
        if (target > to_b) break;
        target_blocks.push_back(target);
    }

    if (!target_blocks.empty()) {
        // Batch-fetch curve info for all checkpoints + BNB prices
        std::vector<std::pair<Address, std::string>> curve_queries;
        curve_queries.reserve(target_blocks.size());
        for (uint64_t blk : target_blocks)
            curve_queries.push_back({token, block_to_hex(blk)});

        std::vector<TokenManagerCurveInfo> curve_results;
        client.batch_get_token_info_curve(curve_queries, curve_results);

        bool grad_discovered = false;
        for (size_t i = 0; i < target_blocks.size(); ++i) {
            double hist_bnb = fetch_bnb_price_at_block(client, target_blocks[i], bnb_price);
            double mc = 0.0;

            if (has_dex && (pools.has_v2 || pools.has_v3)) {
                mc = best_dex_mcap_usd(client, pools, ts.token_addr, block_to_hex(target_blocks[i]), hist_bnb);
            }
            if (mc < 1.0 && curve_results[i].valid) {
                double qp = curve_results[i].is_bnb_quote ? hist_bnb : 1.0;
                mc = curve_results[i].last_price_raw / 1e9 * qp;
                if (curve_results[i].liquidity_added && !has_dex && !grad_discovered) {
                    grad_discovered = true;
                    DexPools p = find_all_dex_pools(client, ts.token_addr);
                    if (p.has_v2 || p.has_v3) {
                        all_dex_pools[ts.token_addr] = p;
                        pools = p;
                        has_dex = true;
                        double mc2 = best_dex_mcap_usd(client, p, ts.token_addr, block_to_hex(target_blocks[i]), hist_bnb);
                        if (mc2 > 100) mc = mc2;
                    }
                }
            }
            if (mc > peak_usd) peak_usd = mc;
            if (mc > 0 && mc < low_usd) low_usd = mc;
        }
    }

    current_usd = 0.0;
    if (has_dex && (pools.has_v2 || pools.has_v3)) {
        current_usd = best_dex_mcap_usd(client, pools, ts.token_addr, "latest", bnb_price);
    }
    if (current_usd < 1.0) {
        TokenManagerCurveInfo latest_curve{};
        if (client.eth_get_token_info_curve(token, latest_curve) && latest_curve.valid) {
            double qp = latest_curve.is_bnb_quote ? bnb_price : 1.0;
            current_usd = latest_curve.last_price_raw / 1e9 * qp;
            if (latest_curve.liquidity_added) ts.graduated = true;
        }
    }
    if (current_usd > peak_usd) peak_usd = current_usd;
    if (current_usd > 0 && current_usd < low_usd) low_usd = current_usd;
}

static bool is_fourmeme_token(const std::string& addr_lower_str) {
    return addr_lower_str.size() >= 4 &&
           addr_lower_str.substr(addr_lower_str.size() - 4) == "4444";
}

// Measured once per replay for +2s delay → blocks
static double g_replay_block_time_sec = 3.0;

// Sort raw transfers, dedupe by KOL (first occurrence), build TokenSummary map
static void finalize_token_summaries_from_raw(
    std::unordered_map<std::string, std::vector<KolBuyEvent>>& raw_buys,
    const std::unordered_map<Address, TokenMeta, AddressHash>& recent_creates,
    std::map<std::string, TokenSummary>& token_summaries)
{
    token_summaries.clear();
    for (auto& [token_addr_lower, events] : raw_buys) {
        std::sort(events.begin(), events.end(),
                  [](const KolBuyEvent& a, const KolBuyEvent& b) {
                      if (a.block != b.block) return a.block < b.block;
                      if (a.log_index != b.log_index) return a.log_index < b.log_index;
                      return addr_lower(a.kol) < addr_lower(b.kol);
                  });
        std::unordered_set<std::string> seen_kol;
        std::vector<KolBuyEvent> distinct;
        distinct.reserve(events.size());
        for (const auto& ev : events) {
            std::string k = addr_lower(ev.kol);
            if (seen_kol.count(k)) continue;
            seen_kol.insert(k);
            distinct.push_back(ev);
        }
        if (distinct.empty()) continue;

        TokenSummary ts;
        ts.token_addr = token_addr_lower;
        ts.kol_order = std::move(distinct);
        ts.first_buyer = ts.kol_order[0].kol;
        ts.first_buy_block = ts.kol_order[0].block;
        ts.kol_count = ts.kol_order.size();

        auto cit = recent_creates.find(hex_to_address(token_addr_lower));
        if (cit != recent_creates.end()) {
            ts.name = cit->second.name;
            ts.create_block = cit->second.create_block;
            ts.creator = cit->second.creator;
            if (ts.first_buy_block >= cit->second.create_block)
                ts.age_blocks = ts.first_buy_block - cit->second.create_block;
        }
        token_summaries[token_addr_lower] = std::move(ts);
    }
}

// Last 64 hex chars of Transfer data -> decimal string (full uint256, no /1e18)
static std::string hex_u256_to_decimal(std::string_view hex64) {
    if (hex64.size() < 64) return {};
    hex64 = hex64.substr(hex64.size() - 64);
    auto hex_digit = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return 10 + c - 'a';
        if (c >= 'A' && c <= 'F') return 10 + c - 'A';
        return -1;
    };
    std::string dec = "0";
    auto mul_add = [](std::string& s, int mul, int add) {
        int carry = add;
        for (int i = static_cast<int>(s.size()) - 1; i >= 0; --i) {
            int x = (s[static_cast<size_t>(i)] - '0') * mul + carry;
            s[static_cast<size_t>(i)] = static_cast<char>('0' + (x % 10));
            carry = x / 10;
        }
        while (carry > 0) {
            s.insert(s.begin(), static_cast<char>('0' + (carry % 10)));
            carry /= 10;
        }
        while (s.size() > 1 && s[0] == '0') s.erase(s.begin());
    };
    for (char c : hex64) {
        int v = hex_digit(c);
        if (v < 0) return {};
        mul_add(dec, 16, v);
    }
    return dec.empty() ? std::string{"0"} : dec;
}

static std::string u256_hex_to_decimal_tokens(std::string_view hex64) {
    if (hex64.size() < 64) return "0";
    double v = 0;
    for (int i = 0; i < 64; ++i) {
        char c = hex64[i];
        uint8_t n = 0;
        if (c >= '0' && c <= '9') n = c - '0';
        else if (c >= 'a' && c <= 'f') n = 10 + c - 'a';
        else if (c >= 'A' && c <= 'F') n = 10 + c - 'A';
        v = v * 16.0 + n;
    }
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.0f", v / 1e18);
    return buf;
}

// ── Stats ───────────────────────────────────────────────────────────────────

struct KolStats {
    uint64_t n_proxy_events = 0;
    uint64_t n_transfer_events = 0;
    uint64_t n_kol_buys = 0;
    uint64_t n_creates = 0;
};

// ── Process proxy logs (TokenCreate — for name/symbol enrichment) ───────────

static void process_proxy_logs(
    const std::vector<RpcLogEntry>& logs,
    std::unordered_map<Address, TokenMeta, AddressHash>& recent_creates,
    const std::string& topic_create, const std::string& topic_create_legacy,
    KolStats& stats)
{
    for (const auto& log : logs) {
        if (log.topics.empty()) continue;
        std::string t0 = to_lower(log.topics[0]);
        ++stats.n_proxy_events;

        if (t0 == topic_create) {
            Address creator{}, token{};
            std::string name, symbol;
            if (fourmeme::decode_token_create_data_v2(log.data, creator, token, name, symbol)) {
                TokenMeta meta;
                meta.creator = creator;
                meta.create_block = log.block_number;
                meta.name = name;
                meta.symbol = symbol;
                recent_creates[token] = meta;
                ++stats.n_creates;
            }
        }
        else if (t0 == topic_create_legacy && log.topics.size() >= 3) {
            Address creator{}, token{};
            if (fourmeme::topic_to_address(log.topics[1], creator) &&
                fourmeme::topic_to_address(log.topics[2], token)) {
                TokenMeta meta;
                meta.creator = creator;
                meta.create_block = log.block_number;
                std::string name, symbol;
                fourmeme::decode_token_create_data_legacy(log.data, name, symbol);
                meta.name = name;
                meta.symbol = symbol;
                recent_creates[token] = meta;
                ++stats.n_creates;
            }
        }
    }
}

// ── Process Transfer logs — collect into token_summaries for replay ──────────

static void collect_transfer_logs(
    const std::vector<RpcLogEntry>& logs,
    const std::unordered_set<Address, AddressHash>& kol_set,
    const std::unordered_map<Address, TokenMeta, AddressHash>& /*recent_creates*/,
    std::unordered_map<std::string, std::vector<KolBuyEvent>>& raw_buys,
    KolStats& stats)
{
    static const std::string TRANSFER_TOPIC = to_lower("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef");

    for (const auto& log : logs) {
        if (log.topics.size() < 3) continue;
        std::string t0 = to_lower(log.topics[0]);
        if (t0 != TRANSFER_TOPIC) continue;

        ++stats.n_transfer_events;

        std::string token_addr_lower = log.address_lower;
        if (!is_fourmeme_token(token_addr_lower)) continue;

        Address to_addr{};
        if (log.topics[2].size() >= 42) {
            std::string addr_hex = "0x" + log.topics[2].substr(log.topics[2].size() - 40);
            to_addr = hex_to_address(addr_hex);
        } else continue;

        if (!kol_set.count(to_addr)) continue;
        ++stats.n_kol_buys;

        std::string kol_addr = addr_lower(to_addr);
        KolBuyEvent ev;
        ev.kol = to_addr;
        ev.block = log.block_number;
        ev.log_index = log.log_index;
        ev.tx_hash = log.tx_hash;
        {
            std::string_view d = log.data;
            if (d.size() >= 2 && d[0] == '0' && (d[1] == 'x' || d[1] == 'X')) d = d.substr(2);
            if (d.size() >= 64)
                ev.amount_raw = hex_u256_to_decimal(d);
        }
        raw_buys[token_addr_lower].push_back(std::move(ev));

        std::fprintf(stderr, "[kol_monitor] KOL BUY #%llu %s → %s (block %s)\n",
                     static_cast<unsigned long long>(stats.n_kol_buys),
                     kol_addr.c_str(), token_addr_lower.c_str(), log.block_hex.c_str());
    }
}

// ── 3-Mode Scoring System (Probe / Confirmed / Strong) ──────────────────────

/** When true: emit same JSON signals but force position_bnb=0 (no sizing intent); IPC disabled by default usage. */
static bool g_shadow_mode = false;
/** Max blocks to scan backward via HTTP eth_getLogs when TokenCreate was not seen on WSS (0 = disable). */
static uint64_t g_live_create_backfill_max_blocks = 500000;
/** If true, allow mode sizing when create_block is still unknown after backfill (not recommended). */
static bool g_allow_unknown_create_for_modes = false;

struct TpLevel {
    double x;
    int sell_pct;
};

struct ModeSignal {
    int mode;                    // 0=no signal, 1=probe, 2=confirmed, 3=strong
    const char* label;           // "PROBE", "CONFIRMED", "STRONG"
    double position_bnb;
    double sl_x;
    std::vector<TpLevel> tp_levels;
    std::string reason;          // human-readable accept/reject reason for logging
};

static const ModeSignal MODE_NONE     = {0, "NONE", 0.0, 0.0, {}};
static const ModeSignal MODE_1_PROBE  = {1, "PROBE",     0.02, 0.65, {{1.5, 40}, {3.0, 60}}};
static const ModeSignal MODE_2_CONF   = {2, "CONFIRMED", 0.03, 0.65, {{2.0, 35}, {4.0, 35}, {8.0, 30}}};
static const ModeSignal MODE_3_STRONG = {3, "STRONG",    0.05, 0.70, {{2.0, 25}, {5.0, 25}, {10.0, 25}, {20.0, 25}}};

// Live per-token state tracking
struct LiveTokenState {
    std::string token_addr;
    Address creator{};
    uint64_t create_block = 0;
    std::string name;
    std::string symbol;
    std::vector<KolBuyEvent> kol_buys;
    std::vector<std::string> kol_names;
    std::unordered_set<Address, AddressHash> unique_kols;
    size_t kol_count = 0;
    double entry_mcap_usd = 0.0;     // at 1st KOL buy
    double current_mcap_usd = 0.0;
    double dev_sell_usd_approx = 0.0;
    uint64_t holder_proxy = 0;
    uint64_t kol_buy_speed_blocks = 0;
    double latest_buy_notional_usd = 0.0;
    uint64_t age_blocks = 0;
    ModeSignal current_mode = MODE_NONE;
    double bonding_curve_pct = 0.0;
    double bnb_price_usd = 0.0;
    // ML scorer enrichment (populated per KOL buy)
    double kol1_buy_usd = 0.0;
    double kol2_buy_usd = 0.0;
    double combined_notional_usd = 0.0;
    double kol1_kol2_delta_blocks = 0.0;
    double holder_growth_k1_to_k2 = 0.0;
    double holder_growth_k2_to_entry = 0.0;
    uint64_t holder_at_kol[5] = {};   // holder_proxy snapshot at each KOL buy block
    double dev_sell_pct_supply = 0.0;
    double create_hour_utc = 12.0;
    double create_dow = 3.0;
    double ml_score = 0.0;
    /** False when Four.meme create_block is unknown (WSS cache miss and RPC backfill failed). */
    bool create_block_known = false;
    // Deployer reputation (from data/deployers_fourmeme.csv via DeployerDB)
    double deployer_prior_grads_ml = 0.0;
    double deployer_grad_rate_ml = 0.0;
    float deployer_score = 0.0f;
    /** Prior avg peak mult from labeled history (CSV / PIT); 0 if unknown — matches training feature 53. */
    float deployer_prior_avg_peak_ml = 0.0f;
    uint32_t deployer_total_tokens = 0;
    // Mcap at each KOL buy (slots 0..4) — used for live kol_buys[] JSON
    double slot_entry_mcap_usd[5] = {0, 0, 0, 0, 0};
};

// ── Combo classification from 90d analysis ──
// Weak combos (avg_mult < 1.5x): hard reject regardless of other signals
static bool is_weak_combo(const std::string& a, const std::string& b) {
    // A→B removed: historically weak but ML should score per-token, not hard-skip
    return (a == "E" && b == "C")
        || (a == "G" && b == "A");
}

// KOL letter → feature index for ML model
static int kol_letter_idx(const std::string& name) {
    if (name.size() == 1 && name[0] >= 'A' && name[0] <= 'K')
        return name[0] - 'A';
    return -1;
}

// Top combo one-hot mapping: combo string → feature index offset (0-based within combo block).
// Matches TOP_COMBOS in ml/train_kol_scorer_v2.py exactly.
// All other combos fall through to combo_other (feature index 26).
static int combo_feature_idx(const std::string& a, const std::string& b) {
    // 24 combos → feature indices 2..25 (0=kol1_idx, 1=kol2_idx, 26=combo_other)
    static const std::pair<const char*, const char*> MAP[] = {
        {"B","A"}, {"D","A"}, {"C","A"}, {"K","A"},
        {"D","C"}, {"C","D"}, {"B","C"}, {"A","C"},
        {"D","E"}, {"B","E"}, {"C","E"},
        {"D","B"}, {"C","B"}, {"E","B"},
        {"A","G"}, {"D","K"}, {"A","K"}, {"C","K"}, {"K","C"},
        {"A","D"}, {"B","D"}, {"B","H"}, {"K","B"}, {"K","D"},
    };
    for (int i = 0; i < 24; ++i)
        if (a == MAP[i].first && b == MAP[i].second) return i;
    return -1; // "other" combo → feature index 26
}

// Count CJK characters (U+4E00–U+9FFF, U+3000–U+303F, U+FF00–U+FFEF) as a ratio of total chars
static float cjk_char_ratio(const std::string& s) {
    if (s.empty()) return 0.0f;
    int cjk = 0, total = 0;
    for (size_t i = 0; i < s.size(); ) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        uint32_t cp = 0;
        size_t bytes = 1;
        if      ((c & 0x80) == 0x00) { cp = c;        bytes = 1; }
        else if ((c & 0xE0) == 0xC0) { cp = c & 0x1F; bytes = 2; }
        else if ((c & 0xF0) == 0xE0) { cp = c & 0x0F; bytes = 3; }
        else if ((c & 0xF8) == 0xF0) { cp = c & 0x07; bytes = 4; }
        for (size_t j = 1; j < bytes && i + j < s.size(); ++j)
            cp = (cp << 6) | (static_cast<unsigned char>(s[i + j]) & 0x3F);
        i += bytes;
        ++total;
        if ((cp >= 0x4E00 && cp <= 0x9FFF) ||
            (cp >= 0x3000 && cp <= 0x303F) ||
            (cp >= 0xFF00 && cp <= 0xFFEF))
            ++cjk;
    }
    return total > 0 ? static_cast<float>(cjk) / total : 0.0f;
}

// Build the 31-element feature vector for ML scorer v3 from LiveTokenState.
// Feature order must match KOL_SCORER_FEATURE_NAMES[] in include/lumina/ml/kol_scorer.h exactly.
//
// v3 change: replaced 24 combo one-hot features with 2 continuous features:
//   combo_2x_rate_smoothed — Bayesian-smoothed per-combo 2x win rate (pseudo-count=20)
//   combo_log_n            — log1p(training sample count for this combo)
// This fixes the overfitting bug where C→I (N=1, one 100% win) scored 0.795 live.
static void build_ml_features(const LiveTokenState& st, float* f) {
    std::memset(f, 0, sizeof(float) * KOL_SCORER_N_FEATURES);

    // f[0] = kol1_idx, f[1] = kol2_idx (A=0, B=1, ..., K=10)
    if (st.kol_names.size() >= 1) f[0] = static_cast<float>(kol_letter_idx(st.kol_names[0]));
    if (st.kol_names.size() >= 2) f[1] = static_cast<float>(kol_letter_idx(st.kol_names[1]));

    // f[2] = kol1_tier_rank, f[3] = kol2_tier_rank (same as idx, kept separate for clarity)
    f[2] = f[0];
    f[3] = f[1];

    // f[4] = combo_2x_rate_smoothed, f[5] = combo_log_n
    if (st.kol_names.size() >= 2) {
        std::string combo = st.kol_names[0] + "\xe2\x86\x92" + st.kol_names[1]; // UTF-8 "→"
        f[4] = static_cast<float>(combo_smoothed_rate(combo));
        f[5] = static_cast<float>(combo_log_n(combo));
    }

    // f[6] = kol_count_at_entry
    f[6] = static_cast<float>(st.kol_count);
    // f[7] = kol1_buy_usd, f[8] = kol2_buy_usd, f[9] = combined_notional
    f[7] = static_cast<float>(st.kol1_buy_usd);
    f[8] = static_cast<float>(st.kol2_buy_usd);
    f[9] = static_cast<float>(st.combined_notional_usd);
    // f[10] = delta_blocks (kol1→kol2)
    f[10] = static_cast<float>(st.kol1_kol2_delta_blocks);
    // f[11] = entry_mcap
    f[11] = static_cast<float>(st.current_mcap_usd);
    // f[12] = bonding_curve_pct, f[13] = age_blocks
    f[12] = static_cast<float>(st.bonding_curve_pct);
    f[13] = static_cast<float>(st.age_blocks);
    // f[14] = dev_sell_usd, f[15] = dev_sell_pct
    f[14] = static_cast<float>(st.dev_sell_usd_approx);
    f[15] = static_cast<float>(st.dev_sell_pct_supply);
    // f[16] = holder_count
    f[16] = static_cast<float>(st.holder_proxy);
    // f[17] = deployer_grads, f[18] = deployer_grad_rate
    f[17] = static_cast<float>(st.deployer_prior_grads_ml);
    f[18] = static_cast<float>(st.deployer_grad_rate_ml);
    // f[19] = hour_utc, f[20] = dow
    f[19] = static_cast<float>(st.create_hour_utc);
    f[20] = static_cast<float>(st.create_dow);
    // f[21] = bnb_price
    f[21] = static_cast<float>(st.bnb_price_usd);
    // f[22] = btc_4h_chg, f[23] = bnb_4h_chg
    {
        auto macro = g_klines.get();
        f[22] = macro.available ? static_cast<float>(macro.btc_4h_pct) : 0.0f;
        f[23] = macro.available ? static_cast<float>(macro.bnb_4h_pct) : 0.0f;
    }
    // f[24] = k1k2_ratio, f[25] = dev_sell_rate
    f[24] = (st.kol2_buy_usd > 0) ? static_cast<float>(st.kol1_buy_usd / st.kol2_buy_usd) : 0.0f;
    f[25] = (st.age_blocks > 0) ? static_cast<float>(st.dev_sell_usd_approx / st.age_blocks) : 0.0f;
    // f[26] = deployer_reputation_score
    f[26] = st.deployer_score;
    // f[27] = name_len, f[28] = name_cjk_ratio
    f[27] = static_cast<float>(st.name.size());
    f[28] = cjk_char_ratio(st.name);
    // f[29] = kol1_buy_pct_mcap
    f[29] = (st.entry_mcap_usd > 0) ? static_cast<float>(st.kol1_buy_usd / st.entry_mcap_usd * 100.0) : 0.0f;
    // f[30] = deployer_launches
    f[30] = static_cast<float>(st.deployer_total_tokens);
}

// Helper: return MODE_NONE with a rejection reason for logging
static ModeSignal none_r(std::string reason) {
    ModeSignal m = MODE_NONE;
    m.reason = std::move(reason);
    return m;
}

// Score-adjusted position sizing from ML model output.
// floored=true: use 0.5x floor so kol_count>=3 signals are never fully suppressed by low ML.
static ModeSignal make_mode(int mode, const char* label, double ml_score,
                            double base_bnb, double sl,
                            std::vector<TpLevel> tp, std::string reason = "",
                            bool floored = false) {
    double scale = (ml_score >= 0.7) ? 1.5
                 : (ml_score >= 0.5) ? 1.0
                 : (ml_score >= 0.3) ? 0.7
                 : floored            ? 0.5   // floor for count-triggered modes: never full-zero
                 :                     0.0;
    double pos_bnb = base_bnb * scale;
    if (g_shadow_mode) pos_bnb = 0.0;
    ModeSignal m{mode, label, pos_bnb, sl, std::move(tp)};
    m.reason = reason.empty() ? std::string(label) : std::move(reason);
    return m;
}

static ModeSignal evaluate_mode(LiveTokenState& st) {
    // Compute ML score (sub-100ns)
    float features[KOL_SCORER_N_FEATURES];
    build_ml_features(st, features);
    st.ml_score = predict_kol_score(features);

    // Feature debug: log key inputs whenever score is noteworthy (>=0.3)
    if (st.ml_score >= 0.3) {
        fprintf(stderr,
            "[ml_feat] %.4f  kc=%d combo=%s  "
            "combo_rate=%.3f combo_logn=%.2f  "
            "k1_usd=%.0f k2_usd=%.0f notional=%.0f delta_blk=%d  "
            "mcap=%.0f bc=%.3f age=%llu  "
            "dev_sell=%.0f holders=%d  "
            "k1_pct_mcap=%.2f  "
            "deployer_score=%.2f dep_grads=%d dep_rate=%.2f dep_total=%d  "
            "btc4h=%.4f bnb4h=%.4f  "
            "name_len=%d cjk=%.2f  token=%s\n",
            st.ml_score, st.kol_count,
            (st.kol_names.size() >= 2 ? (st.kol_names[0] + "\xe2\x86\x92" + st.kol_names[1]).c_str() : "?"),
            features[4], features[5],
            features[7], features[8], features[9], (int)features[10],
            features[11], features[12], (unsigned long long)features[13],
            features[14], (int)features[16],
            features[29],
            features[26], (int)features[17], features[18], (int)features[30],
            features[22], features[23],
            (int)features[27], features[28],
            st.token_addr.c_str());
    }

    if (!g_allow_unknown_create_for_modes && !st.create_block_known)
        return none_r("create_block unknown");

    // Hard reject: weak combos
    if (st.kol_names.size() >= 2 && is_weak_combo(st.kol_names[0], st.kol_names[1])) {
        return none_r("weak combo (" + st.kol_names[0] + "→" + st.kol_names[1] + " avg_mult<1.5x)");
    }

    // Block delta sanity: ultra-fast follows (<5 blocks) are likely coordinated, not independent
    if (st.kol_count == 2 && st.kol1_kol2_delta_blocks > 0 && st.kol1_kol2_delta_blocks < 5) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "coordinated buy (delta=%d blks)",
                      static_cast<int>(st.kol1_kol2_delta_blocks));
        return none_r(buf);
    }

    // H wallet = instant Mode 3 (60% hit 2x on 90d data, N=15).
    // ML is bypassed (score forced to 0.8) because H-wallet history predates the
    // training CSV — the model only has N=2 H→E examples, both under 2x, so it
    // scores H combos near 0. The hardcoded rule already encodes the real base rate.
    for (const auto& n : st.kol_names)
        if (n == "H") return make_mode(3, "STRONG", /*ml_score=*/0.8, 0.05, 0.70,
                                        {{2.0, 25}, {5.0, 25}, {10.0, 25}, {20.0, 25}},
                                        "H-wallet detected", /*floored=*/false);

    // kc >= 5: MODE_3_STRONG (7.96x avg on 90d, 52% hit 2x)
    if (st.kol_count >= 5)
        return make_mode(3, "STRONG", st.ml_score, 0.07, 0.70,
                         {{2.0, 25}, {5.0, 25}, {10.0, 25}, {20.0, 25}},
                         "kol_count=" + std::to_string(st.kol_count), /*floored=*/true);

    // kc == 4: MODE_3_STRONG (5.37x avg, 60% hit 2x)
    if (st.kol_count == 4)
        return make_mode(3, "STRONG", st.ml_score, 0.05, 0.65,
                         {{2.0, 30}, {5.0, 30}, {10.0, 40}},
                         "kol_count=4", /*floored=*/true);

    // kc == 3: MODE_2_CONF if entry conditions met (2.69x avg, 32% hit 2x)
    if (st.kol_count == 3) {
        if (st.current_mcap_usd < 50000.0 && st.dev_sell_usd_approx < 5000.0)
            return make_mode(2, "CONFIRMED", st.ml_score, 0.03, 0.65,
                             {{2.0, 35}, {4.0, 35}, {8.0, 30}},
                             "kol_count=3", /*floored=*/true);
        char buf[128];
        if (st.current_mcap_usd >= 50000.0)
            std::snprintf(buf, sizeof(buf), "kol_count=3 mcap=$%.0fk > $50k limit",
                          st.current_mcap_usd / 1000.0);
        else
            std::snprintf(buf, sizeof(buf), "kol_count=3 dev_sell=$%.0f > $5k limit",
                          st.dev_sell_usd_approx);
        return none_r(buf);
    }

    // kc == 2: MODE_1_PROBE only if ML score is high enough (requires known create + age cap)
    if (st.kol_count == 2 && st.kol_names.size() >= 2) {
        if (st.create_block_known && st.ml_score >= 0.5 && st.age_blocks < 2000)
            return make_mode(1, "PROBE", st.ml_score, 0.02, 0.60,
                             {{2.0, 50}, {4.0, 50}},
                             "kol_count=2");
        // Build specific reason for the miss
        char buf[128];
        if (st.age_blocks >= 2000)
            std::snprintf(buf, sizeof(buf), "kol_count=2 age=%llu >= 2000 blks limit",
                          static_cast<unsigned long long>(st.age_blocks));
        else
            std::snprintf(buf, sizeof(buf), "kol_count=2 ml=%.2f < 0.50 required for PROBE",
                          st.ml_score);
        return none_r(buf);
    }

    return none_r("kol_count=" + std::to_string(st.kol_count) + " no rule matched");
}

// Count unique Transfer recipients (holder proxy) for a token up to a block
static uint64_t count_holders_proxy(BscRpcClient& client, const std::string& token_lower,
                                     uint64_t from_block, uint64_t to_block) {
    if (to_block < from_block) return 0;
    static const std::string XFER_T =
        to_lower("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef");
    std::unordered_set<std::string> recipients;
    uint64_t cur = from_block;
    constexpr uint64_t K = 2000;
    std::vector<RpcLogEntry> logs;
    while (cur <= to_block) {
        uint64_t end = std::min(cur + K - 1, to_block);
        logs.clear();
        if (!client.eth_get_logs_token_transfers_all(token_lower, XFER_T, block_to_hex(cur), block_to_hex(end), logs))
            break;
        for (const auto& log : logs) {
            if (log.topics.size() >= 3 && log.topics[2].size() >= 42)
                recipients.insert(log.topics[2].substr(log.topics[2].size() - 40));
        }
        cur = end + 1;
    }
    return static_cast<uint64_t>(recipients.size());
}

static void append_live_kol_buys_json(std::string& out, const LiveTokenState& st) {
    out += ",\"kol_buys\":[";
    for (size_t i = 0; i < st.kol_buys.size(); ++i) {
        if (i) out += ',';
        const auto& k = st.kol_buys[i];
        double em = (i < 5) ? st.slot_entry_mcap_usd[i] : 0.0;
        out += "{\"kol\":\"";
        out += addr_lower(k.kol);
        out += "\",\"kol_name\":\"";
        if (i < st.kol_names.size())
            out += json_escape(st.kol_names[i]);
        out += "\",\"buy_block\":";
        out += std::to_string(k.block);
        out += ",\"log_index\":";
        out += std::to_string(k.log_index);
        out += ",\"tx\":\"";
        out += json_escape(k.tx_hash);
        out += "\",\"entry_mcap_usd\":";
        out += std::to_string(static_cast<long long>(em + 0.5));
        out += ",\"amount_raw\":\"";
        out += json_escape(k.amount_raw.empty() ? "0" : k.amount_raw);
        out += "\",\"buy_notional_usd_approx\":";
        {
            double buy_usd = 0.0;
            if (em > 1.0 && !k.amount_raw.empty() && k.amount_raw != "0") {
                double nt = decimal_string_to_tokens_double(k.amount_raw);
                buy_usd = nt * (em / TOTAL_SUPPLY);
            }
            out += std::to_string(static_cast<long long>(buy_usd + 0.5));
        }
        out += '}';
    }
    out += ']';
}

// Emit rich JSON signal for live mode
static void emit_live_signal(const LiveTokenState& st, const RpcLogEntry& trigger_log,
                             bool ipc_enabled, const char* ipc_path) {
    const ModeSignal& m = st.current_mode;

    // Build kol_combo string
    std::string combo;
    for (size_t i = 0; i < st.kol_names.size(); ++i) {
        if (i) combo += "\xe2\x86\x92"; // UTF-8 →
        combo += st.kol_names[i];
    }

    // Build TP levels JSON array
    std::string tp_json = "[";
    for (size_t i = 0; i < m.tp_levels.size(); ++i) {
        if (i) tp_json += ',';
        tp_json += "{\"x\":";
        tp_json += std::to_string(m.tp_levels[i].x);
        tp_json += ",\"sell_pct\":";
        tp_json += std::to_string(m.tp_levels[i].sell_pct);
        tp_json += '}';
    }
    tp_json += ']';

    // Build kol_names array
    std::string names_json = "[";
    for (size_t i = 0; i < st.kol_names.size(); ++i) {
        if (i) names_json += ',';
        names_json += "\"" + json_escape(st.kol_names[i]) + "\"";
    }
    names_json += ']';

    std::string out;
    out.reserve(1024);
    out += "{\"event\":\"kol_signal\"";
    out += ",\"shadow\":";
    out += g_shadow_mode ? "true" : "false";
    out += ",\"token\":\"" + st.token_addr + "\"";
    out += ",\"name\":\"" + json_escape(st.name) + "\"";
    out += ",\"symbol\":\"" + json_escape(st.symbol) + "\"";
    out += ",\"mode\":" + std::to_string(m.mode);
    out += ",\"mode_label\":\"" + std::string(m.label) + "\"";
    out += ",\"kol_count\":" + std::to_string(st.kol_count);
    out += ",\"kol_names\":" + names_json;
    append_live_kol_buys_json(out, st);
    out += ",\"kol_combo\":\"" + json_escape(combo) + "\"";
    out += ",\"entry_mcap_usd\":" + std::to_string(static_cast<long long>(st.entry_mcap_usd + 0.5));
    out += ",\"current_mcap_usd\":" + std::to_string(static_cast<long long>(st.current_mcap_usd + 0.5));
    out += ",\"holder_proxy\":" + std::to_string(st.holder_proxy);
    out += ",\"dev_sell_usd\":" + std::to_string(static_cast<long long>(st.dev_sell_usd_approx + 0.5));
    out += ",\"kol_buy_speed_blocks\":" + std::to_string(st.kol_buy_speed_blocks);
    out += ",\"latest_buy_notional_usd\":" + std::to_string(static_cast<long long>(st.latest_buy_notional_usd + 0.5));
    if (st.create_block_known)
        out += ",\"age_blocks\":" + std::to_string(st.age_blocks);
    else
        out += ",\"age_blocks\":null";
    out += ",\"create_block_known\":";
    out += st.create_block_known ? "true" : "false";
    {
        char bc_buf[32]; std::snprintf(bc_buf, sizeof(bc_buf), "%.4f", st.bonding_curve_pct);
        out += ",\"bonding_curve_pct\":"; out += bc_buf;
        char bp_buf[32]; std::snprintf(bp_buf, sizeof(bp_buf), "%.2f", st.bnb_price_usd);
        out += ",\"bnb_price_usd\":"; out += bp_buf;
    }
    out += ",\"position_bnb\":" + std::to_string(m.position_bnb);
    out += ",\"tp_levels\":" + tp_json;
    out += ",\"sl_x\":" + std::to_string(m.sl_x);
    {
        char ml_buf[32]; std::snprintf(ml_buf, sizeof(ml_buf), "%.4f", st.ml_score);
        out += ",\"ml_score\":"; out += ml_buf;
    }
    {
        char ds_buf[32]; std::snprintf(ds_buf, sizeof(ds_buf), "%.2f", st.deployer_score);
        out += ",\"deployer_score\":"; out += ds_buf;
        char sr_buf[32]; std::snprintf(sr_buf, sizeof(sr_buf), "%.4f", st.deployer_grad_rate_ml);
        out += ",\"deployer_success_rate\":"; out += sr_buf;
        out += ",\"deployer_successful\":" + std::to_string(static_cast<unsigned long long>(st.deployer_prior_grads_ml + 0.5));
        out += ",\"deployer_total_tokens\":" + std::to_string(st.deployer_total_tokens);
    }
    out += ",\"create_block\":" + std::to_string(st.create_block);
    out += ",\"creator\":\"" + addr_lower(st.creator) + "\"";
    out += ",\"block\":\"" + trigger_log.block_hex + "\"";
    out += ",\"tx\":\"" + json_escape(trigger_log.tx_hash) + "\"";
    out += "}\n";

    std::printf("%s", out.c_str());
    std::fflush(stdout);

    if (ipc_enabled) {
        if (!IPCBridge::send_line(ipc_path, out.c_str())) {
            std::fprintf(stderr, "[kol_monitor] IPC send failed\n");
        }
    }
}

// ── Build SignalRow from LiveTokenState for dataset writer ───────────────────

static void estimate_block_time(uint64_t block, uint64_t ref_block, uint64_t ref_ts,
                                int& hour_utc, int& dow) {
    if (ref_block == 0 || ref_ts == 0 || block == 0) {
        hour_utc = 12; dow = 3;
        return;
    }
    int64_t delta_blocks = static_cast<int64_t>(block) - static_cast<int64_t>(ref_block);
    int64_t delta_sec = delta_blocks * 3; // BSC ~3s/block
    time_t ts = static_cast<time_t>(ref_ts) + delta_sec;
    struct tm tm{};
    gmtime_r(&ts, &tm);
    hour_utc = tm.tm_hour;
    dow = tm.tm_wday == 0 ? 6 : tm.tm_wday - 1; // Python weekday: Mon=0
}

static SignalRow build_signal_row(const LiveTokenState& st, const RpcLogEntry& trigger_log,
                                  uint64_t ref_block, uint64_t ref_ts) {
    SignalRow r;
    r.token_address = st.token_addr;
    r.name = st.name;
    r.creator = addr_lower(st.creator);
    r.create_block = st.create_block;
    r.create_block_known = st.create_block_known;

    estimate_block_time(st.create_block, ref_block, ref_ts,
                        r.create_hour_utc, r.create_dow);

    r.deployer_prior_grads = static_cast<int>(st.deployer_prior_grads_ml + 0.5);
    r.deployer_grad_rate = st.deployer_grad_rate_ml;
    r.deployer_prior_launches = static_cast<int>(st.deployer_total_tokens);

    r.dev_sell_usd = st.dev_sell_usd_approx;
    r.dev_sell_pct_supply = st.dev_sell_pct_supply;

    r.kol_count = static_cast<int>(st.kol_count);

    // Populate KOL slots
    for (int k = 0; k < 5 && k < static_cast<int>(st.kol_names.size()); ++k) {
        r.kol[k].name = st.kol_names[k];
        if (k < static_cast<int>(st.kol_buys.size())) {
            r.kol[k].buy_block = static_cast<int64_t>(st.kol_buys[k].block);
            double notional = 0.0;
            if (k == 0) notional = st.kol1_buy_usd;
            else if (k == 1) notional = st.kol2_buy_usd;
            r.kol[k].buy_usd = notional;
            r.kol[k].holder_count = st.kol_buys[k].holder_count;
        }
    }

    // Combos
    if (st.kol_names.size() >= 2)
        r.combo_k1k2 = st.kol_names[0] + "\xe2\x86\x92" + st.kol_names[1]; // UTF-8 →
    if (st.kol_names.size() >= 3)
        r.combo_k1k2k3 = st.kol_names[0] + "\xe2\x86\x92" + st.kol_names[1] +
                          "\xe2\x86\x92" + st.kol_names[2];

    r.combined_notional_k1k2_usd = st.combined_notional_usd;
    r.kol1_kol2_delta_blocks = (st.kol1_kol2_delta_blocks > 0)
        ? static_cast<int64_t>(st.kol1_kol2_delta_blocks) : -1;
    if (st.kol_buys.size() >= 3) {
        r.kol2_kol3_delta_blocks = static_cast<int64_t>(
            st.kol_buys[2].block - st.kol_buys[1].block);
    }

    r.entry_mcap_usd = st.entry_mcap_usd;
    r.current_mcap_usd = st.current_mcap_usd;
    r.bonding_curve_pct = st.bonding_curve_pct;
    r.bnb_price_usd = st.bnb_price_usd;
    r.age_blocks = st.age_blocks;
    r.holder_count = st.holder_proxy;
    r.holder_growth_k1_to_k2 = st.holder_growth_k1_to_k2;
    // holder_growth_k2_to_entry: from kol2 buy block to signal block
    // At signal time, holder_proxy == holder_at_kol[kol_count-1], so for kol_count>=3 this is non-zero
    if (st.kol_count >= 2 && st.holder_at_kol[1] > 0)
        r.holder_growth_k2_to_entry = static_cast<double>(st.holder_proxy)
                                     - static_cast<double>(st.holder_at_kol[1]);
    else
        r.holder_growth_k2_to_entry = 0.0;

    r.ml_score = st.ml_score;
    r.mode = st.current_mode.mode;
    r.mode_label = st.current_mode.label;
    r.position_bnb = st.current_mode.position_bnb;
    r.sl_x = st.current_mode.sl_x;

    r.signal_block = trigger_log.block_hex;
    r.signal_tx = trigger_log.tx_hash;

    r.deployer_score = st.deployer_score;
    r.deployer_success_rate = st.deployer_grad_rate_ml;
    r.deployer_successful = static_cast<int>(st.deployer_prior_grads_ml + 0.5);
    r.deployer_total_tokens = static_cast<int>(st.deployer_total_tokens);

    // Macro from BinanceKlines
    auto macro = g_klines.get();
    r.btc_4h_change_pct = macro.btc_4h_pct;
    r.bnb_4h_change_pct = macro.bnb_4h_pct;
    r.macro_available = macro.available;

    r.shadow = g_shadow_mode;

    return r;
}

// ── Structured log for signal ────────────────────────────────────────────────

static void log_signal(const LiveTokenState& st) {
    auto now = std::chrono::system_clock::now();
    auto tt = std::chrono::system_clock::to_time_t(now);
    struct tm tm{};
    gmtime_r(&tt, &tm);

    // Mode color + label
    const char* mode_color = CLR_DIM;
    if      (st.current_mode.mode >= 3) mode_color = CLR_GREEN;
    else if (st.current_mode.mode == 2) mode_color = CLR_YELLOW;
    else if (st.current_mode.mode == 1) mode_color = CLR_CYAN;

    // ML score color + directional indicator
    const char* ml_color = CLR_DIM;
    const char* ml_arrow = " ";
    if      (st.ml_score >= 0.7) { ml_color = CLR_GREEN;    ml_arrow = "↑"; }
    else if (st.ml_score >= 0.5) { ml_color = CLR_CYAN;     ml_arrow = "↗"; }
    else if (st.ml_score >= 0.35){ ml_color = CLR_YLW_DIM;  ml_arrow = "→"; }
    else                         { ml_color = CLR_DIM;       ml_arrow = "↓"; }

    // Rejection reason color
    const char* reason_color = CLR_DIM;
    if (st.current_mode.mode == 0) {
        const std::string& r = st.current_mode.reason;
        if (r.find("weak combo") != std::string::npos ||
            r.find("coordinated") != std::string::npos ||
            r.find("create_block") != std::string::npos)
            reason_color = CLR_RED_BOLD;
        else if (st.ml_score >= 0.35)
            reason_color = CLR_YLW_DIM;
    }

    // Build combo string (k1→k2)
    std::string combo;
    if (st.kol_names.size() >= 2)
        combo = st.kol_names[0] + "\xe2\x86\x92" + st.kol_names[1]; // UTF-8 →
    else if (!st.kol_names.empty())
        combo = st.kol_names[0];

    // Truncate token address for display: 0x + first 6 chars
    std::string addr_short = st.token_addr.size() > 8
        ? st.token_addr.substr(0, 8) + "\xe2\x80\xa6"  // 0x123456…
        : st.token_addr;

    // Build main log line into string for tee
    char line1[1024];
    std::snprintf(line1, sizeof(line1),
        "%s[%02d:%02d:%02d]" CLR_RESET
        " KOL %s (#%zu) %s%-8s" CLR_RESET
        "  %s%-9s" CLR_RESET
        "  %sml=%.2f%s" CLR_RESET
        "  mcap=$%.0f  age=%llu  h=%llu"
        "  %s%s" CLR_RESET
        "  %s\n",
        CLR_DIM, tm.tm_hour, tm.tm_min, tm.tm_sec,
        st.kol_names.empty() ? "?" : st.kol_names.back().c_str(),
        st.kol_count,
        mode_color, combo.c_str(),
        mode_color, st.current_mode.label,
        ml_color, st.ml_score, ml_arrow,
        st.current_mcap_usd,
        static_cast<unsigned long long>(st.age_blocks),
        static_cast<unsigned long long>(st.holder_proxy),
        CLR_DIM, addr_short.c_str(),
        json_escape(st.name).c_str());
    tee_stderr(line1);

    // Rejection / accept reason on second line (only when informative)
    if (!st.current_mode.reason.empty() &&
        (st.current_mode.mode == 0 || st.current_mode.mode >= 2)) {
        const char* pfx = (st.current_mode.mode == 0) ? "  \xe2\x94\x94\xe2\x94\x80 " : "  \xe2\x86\x92 ";
        char line2[512];
        std::snprintf(line2, sizeof(line2), "%s%s%s" CLR_RESET "\n",
                      reason_color, pfx, st.current_mode.reason.c_str());
        tee_stderr(line2);
    }

    ++g_session.signals_emitted;
    if (st.current_mode.mode == 1) ++g_session.mode_probe;
    else if (st.current_mode.mode == 2) ++g_session.mode_confirmed;
    else if (st.current_mode.mode >= 3) ++g_session.mode_strong;
}

static void log_periodic_stats() {
    static auto last_log = std::chrono::steady_clock::now();
    auto now = std::chrono::steady_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - last_log).count();
    if (elapsed < 60) return;
    last_log = now;

    auto total_min = std::chrono::duration_cast<std::chrono::minutes>(
        now - g_session.start_time).count();

    char stats_buf[256];
    std::snprintf(stats_buf, sizeof(stats_buf),
        CLR_DIM "[STATS %lldm]" CLR_RESET
        " tokens=%llu signals=%llu rows=%llu paper=%llu"
        " P/C/S=%llu/%llu/%llu\n",
        static_cast<long long>(total_min),
        static_cast<unsigned long long>(g_session.tokens_seen.load()),
        static_cast<unsigned long long>(g_session.signals_emitted.load()),
        static_cast<unsigned long long>(g_session.rows_written.load()),
        static_cast<unsigned long long>(g_session.paper_hits.load()),
        static_cast<unsigned long long>(g_session.mode_probe.load()),
        static_cast<unsigned long long>(g_session.mode_confirmed.load()),
        static_cast<unsigned long long>(g_session.mode_strong.load()));
    tee_stderr(stats_buf);
}

// ── Live: RPC backfill when TokenCreate was not in WSS cache ─────────────────

static std::string create_topic2_padded(const std::string& token_addr_lower) {
    std::string a = token_addr_lower;
    if (a.size() >= 2 && a[0] == '0' && (a[1] == 'x' || a[1] == 'X')) a = a.substr(2);
    std::transform(a.begin(), a.end(), a.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    while (a.size() < 40) a = "0" + a;
    if (a.size() > 40) a = a.substr(a.size() - 40);
    return "0x" + std::string(24, '0') + a;
}

static bool token_meta_from_create_log(const RpcLogEntry& log, const std::string& want_token_lower,
                                       TokenMeta& meta_out) {
    if (log.topics.empty()) return false;
    std::string t0 = to_lower(log.topics[0]);
    const std::string leg = to_lower(fourmeme::TOPIC_TOKEN_CREATE_LEGACY);
    if (t0 == leg && log.topics.size() >= 3) {
        Address creator{}, token{};
        if (!fourmeme::topic_to_address(log.topics[1], creator) ||
            !fourmeme::topic_to_address(log.topics[2], token))
            return false;
        if (addr_lower(token) != want_token_lower) return false;
        meta_out.creator = creator;
        meta_out.create_block = log.block_number;
        fourmeme::decode_token_create_data_legacy(log.data, meta_out.name, meta_out.symbol);
        return true;
    }
    const std::string v2 = to_lower(fourmeme::TOPIC_TOKEN_CREATE);
    if (t0 == v2) {
        Address creator{}, token{};
        std::string n, s;
        if (!fourmeme::decode_token_create_data_v2(log.data, creator, token, n, s)) return false;
        if (addr_lower(token) != want_token_lower) return false;
        meta_out.creator = creator;
        meta_out.create_block = log.block_number;
        meta_out.name = std::move(n);
        meta_out.symbol = std::move(s);
        return true;
    }
    return false;
}

static bool backfill_token_create_meta(BscRpcClient& client, const std::string& token_addr_lower,
                                       Address /*token*/, uint64_t signal_block, TokenMeta& meta_out) {
    if (g_live_create_backfill_max_blocks == 0) return false;
    meta_out = TokenMeta{};
    const std::string proxy = to_lower(fourmeme::PROXY_MANAGER);
    const uint64_t min_b = (signal_block > g_live_create_backfill_max_blocks)
                               ? signal_block - g_live_create_backfill_max_blocks
                               : 0;
    constexpr uint64_t CHUNK = 4999;
    const std::string t2 = create_topic2_padded(token_addr_lower);
    const std::vector<std::string> leg_t0 = {to_lower(fourmeme::TOPIC_TOKEN_CREATE_LEGACY)};

    uint64_t to_blk = signal_block;
    while (to_blk >= min_b && to_blk > 0) {
        const uint64_t span = std::min<uint64_t>(CHUNK, to_blk - min_b + 1);
        const uint64_t from_blk = to_blk + 1 - span;
        std::vector<RpcLogEntry> chunk_logs;
        if (client.eth_get_logs_manager_topic0_or_and_topic2(proxy, leg_t0, t2, block_to_hex(from_blk),
                                                             block_to_hex(to_blk), chunk_logs)) {
            const RpcLogEntry* best = nullptr;
            for (const auto& L : chunk_logs) {
                TokenMeta m{};
                if (token_meta_from_create_log(L, token_addr_lower, m) && m.create_block > 0) {
                    if (!best || L.block_number < best->block_number) best = &L;
                }
            }
            if (best) {
                token_meta_from_create_log(*best, token_addr_lower, meta_out);
                return meta_out.create_block > 0;
            }
        }
        if (from_blk == min_b) break;
        to_blk = from_blk - 1;
    }

    const std::string v2t = to_lower(fourmeme::TOPIC_TOKEN_CREATE);
    to_blk = signal_block;
    while (to_blk >= min_b && to_blk > 0) {
        const uint64_t span = std::min<uint64_t>(CHUNK, to_blk - min_b + 1);
        const uint64_t from_blk = to_blk + 1 - span;
        std::vector<RpcLogEntry> chunk_logs;
        if (client.eth_get_logs_manager(proxy, v2t, block_to_hex(from_blk), block_to_hex(to_blk),
                                        chunk_logs)) {
            const RpcLogEntry* best = nullptr;
            for (const auto& L : chunk_logs) {
                TokenMeta m{};
                if (token_meta_from_create_log(L, token_addr_lower, m) && m.create_block > 0) {
                    if (!best || L.block_number < best->block_number) best = &L;
                }
            }
            if (best) {
                token_meta_from_create_log(*best, token_addr_lower, meta_out);
                return meta_out.create_block > 0;
            }
        }
        if (from_blk == min_b) break;
        to_blk = from_blk - 1;
    }
    return false;
}

// ── Process Transfer logs — streaming for live mode (with enrichment + scoring) ──

static std::unordered_map<std::string, LiveTokenState> g_live_state;

static void process_transfer_logs_live(
    const std::vector<RpcLogEntry>& logs,
    BscRpcClient& client,
    const std::unordered_set<Address, AddressHash>& kol_set,
    std::unordered_map<Address, TokenMeta, AddressHash>& recent_creates,
    std::unordered_map<Address, std::unordered_set<Address, AddressHash>, AddressHash>& kol_buys_per_token,
    KolStats& stats,
    bool ipc_enabled, const char* ipc_path,
    double bnb_price,
    uint64_t ref_block = 0, uint64_t ref_ts = 0)
{
    static const std::string TRANSFER_TOPIC = to_lower("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef");

    for (const auto& log : logs) {
        if (log.topics.size() < 3) continue;
        std::string t0 = to_lower(log.topics[0]);
        if (t0 != TRANSFER_TOPIC) continue;
        ++stats.n_transfer_events;

        std::string token_addr_lower = log.address_lower;
        if (!is_fourmeme_token(token_addr_lower)) continue;

        Address to_addr{};
        if (log.topics[2].size() >= 42) {
            std::string addr_hex = "0x" + log.topics[2].substr(log.topics[2].size() - 40);
            to_addr = hex_to_address(addr_hex);
        } else continue;

        if (!kol_set.count(to_addr)) continue;

        Address token = hex_to_address(token_addr_lower);
        bool new_kol = kol_buys_per_token[token].insert(to_addr).second;
        if (!new_kol) continue; // duplicate buy from same KOL, skip

        ++stats.n_kol_buys;

        // Parse amount
        std::string_view dv(log.data);
        if (dv.size() >= 2 && dv[0] == '0' && (dv[1] == 'x' || dv[1] == 'X')) dv.remove_prefix(2);
        std::string amount_dec;
        if (dv.size() >= 64) amount_dec = hex_u256_to_decimal(dv);

        // Get or create LiveTokenState
        LiveTokenState& st = g_live_state[token_addr_lower];
        if (st.token_addr.empty()) {
            st.token_addr = token_addr_lower;
            auto it = recent_creates.find(token);
            if (it != recent_creates.end()) {
                st.creator = it->second.creator;
                st.create_block = it->second.create_block;
                st.name = it->second.name;
                st.symbol = it->second.symbol;
            }
            if (st.create_block == 0 && g_live_create_backfill_max_blocks > 0) {
                TokenMeta bf{};
                if (backfill_token_create_meta(client, token_addr_lower, token, log.block_number, bf) &&
                    bf.create_block > 0) {
                    st.creator = bf.creator;
                    st.create_block = bf.create_block;
                    if (!bf.name.empty()) st.name = bf.name;
                    if (!bf.symbol.empty()) st.symbol = bf.symbol;
                    recent_creates[token] = bf;
                }
            }
        }

        // Record KOL buy
        KolBuyEvent ev;
        ev.kol = to_addr;
        ev.block = log.block_number;
        ev.log_index = log.log_index;
        ev.tx_hash = log.tx_hash;
        ev.amount_raw = amount_dec;
        st.kol_buys.push_back(ev);
        st.unique_kols.insert(to_addr);
        st.kol_names.push_back(kol_display_name(to_addr));
        st.kol_count = st.unique_kols.size();

        // Calculate age (meaningful only when create_block_known)
        st.age_blocks = (log.block_number > st.create_block && st.create_block > 0)
                            ? log.block_number - st.create_block : 0;
        st.create_block_known = (st.create_block > 0);

        // Estimate create time for ML features
        if (st.create_block_known && ref_block > 0 && ref_ts > 0) {
            int h, d;
            estimate_block_time(st.create_block, ref_block, ref_ts, h, d);
            st.create_hour_utc = static_cast<double>(h);
            st.create_dow = static_cast<double>(d);
        }

        // KOL buy speed (delta between consecutive KOLs)
        if (st.kol_buys.size() >= 2) {
            st.kol_buy_speed_blocks = st.kol_buys.back().block -
                                       st.kol_buys[st.kol_buys.size() - 2].block;
        }

        // ── Live enrichment ──
        // 1. Current mcap via curve info
        TokenManagerCurveInfo curve{};
        if (client.eth_get_token_info_curve(token, curve) && curve.valid) {
            double qp = curve.is_bnb_quote ? bnb_price : 1.0;
            st.current_mcap_usd = curve.last_price_raw / 1e9 * qp;
            if (st.kol_count == 1)
                st.entry_mcap_usd = st.current_mcap_usd;
            st.bonding_curve_pct = (curve.max_funds_bnb > 0.0)
                ? std::min(1.0, curve.funds_bnb / curve.max_funds_bnb)
                : 0.0;
            if (st.kol_count >= 1 && st.kol_count <= 5)
                st.slot_entry_mcap_usd[st.kol_count - 1] = st.current_mcap_usd;
        }
        st.bnb_price_usd = bnb_price;

        // 2. Buy notional USD + ML enrichment
        if (st.current_mcap_usd > 1.0 && !amount_dec.empty() && amount_dec != "0") {
            double tokens = decimal_string_to_tokens_double(amount_dec);
            st.latest_buy_notional_usd = tokens * (st.current_mcap_usd / TOTAL_SUPPLY);
        }
        if (st.kol_count == 1) {
            st.kol1_buy_usd = st.latest_buy_notional_usd;
        } else if (st.kol_count == 2) {
            st.kol2_buy_usd = st.latest_buy_notional_usd;
            st.combined_notional_usd = st.kol1_buy_usd + st.kol2_buy_usd;
            st.kol1_kol2_delta_blocks = static_cast<double>(st.kol_buy_speed_blocks);
        }

        // 3. Holder proxy (unique recipients) — only for small age to keep latency low
        if (st.create_block > 0 && st.age_blocks < 2000) {
            st.holder_proxy = count_holders_proxy(client, token_addr_lower, st.create_block, log.block_number);
            // Snapshot holder count at this KOL's buy block
            if (!st.kol_buys.empty())
                st.kol_buys.back().holder_count = st.holder_proxy;
            size_t slot = st.kol_count - 1;
            if (slot < 5) st.holder_at_kol[slot] = st.holder_proxy;
            if (st.kol_count == 2) {
                st.holder_growth_k1_to_k2 = static_cast<double>(st.holder_at_kol[1])
                                           - static_cast<double>(st.holder_at_kol[0]);
            }
        }

        // 4. Dev sell estimate
        if (!is_zero(st.creator) && st.create_block > 0 && st.age_blocks < 2000) {
            static const std::string XFER_T_LOWER =
                to_lower("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef");
            double dev_tokens = sum_dev_transfer_out_tokens(
                client, token_addr_lower, st.creator, st.create_block, log.block_number, XFER_T_LOWER);
            if (st.current_mcap_usd > 1.0)
                st.dev_sell_usd_approx = dev_tokens * (st.current_mcap_usd / TOTAL_SUPPLY);
        }

        // Deployer reputation (static CSV; matches training f[41]/f[42] semantics)
        st.deployer_prior_grads_ml = 0.0;
        st.deployer_grad_rate_ml = 0.0;
        st.deployer_score = 0.0f;
        st.deployer_prior_avg_peak_ml = 0.0f;
        st.deployer_total_tokens = 0;
        if (!is_zero(st.creator)) {
            if (auto rep = g_deployer_db.lookup(st.creator)) {
                st.deployer_prior_grads_ml = static_cast<double>(rep->success_count);
                st.deployer_grad_rate_ml = static_cast<double>(rep->success_rate);
                st.deployer_score = rep->score;
                st.deployer_total_tokens = rep->total_deploys;
            }
        }

        // ── 3-Mode scoring ──
        st.current_mode = evaluate_mode(st);

        // ── Structured log ──
        log_signal(st);
        ++g_session.tokens_seen;

        // ── Emit JSON to stdout + IPC ──
        emit_live_signal(st, log, ipc_enabled, ipc_path);

        // ── Dataset writer + paper gate ──
        if (g_writer) {
            SignalRow row = build_signal_row(st, log, ref_block, ref_ts);
            if (g_writer->write_signal(row))
                ++g_session.rows_written;
            if (g_writer->check_paper_gate(row))
                ++g_session.paper_hits;
        }

        log_periodic_stats();
    }
}

// ── Main ────────────────────────────────────────────────────────────────────

static void print_usage() {
    std::fprintf(stderr,
        "Usage:\n"
        "  lumina_kol_monitor [--yesterday] [--recent HOURS] [FROM TO] [options]\n"
        "\n"
        "Modes:\n"
        "  (no range args)       Live WSS stream from chain head\n"
        "  --yesterday           Replay last 24 hours\n"
        "  --recent HOURS        Replay last N hours\n"
        "  FROM TO               Replay explicit block range\n"
        "\n"
        "Live output:\n"
        "  --csv PATH            Write dataset CSV (81 columns, training-compatible)\n"
        "  --jsonl PATH          Write dataset JSONL\n"
        "  --paper-csv PATH      Write paper trading hits CSV\n"
        "  --fresh-output        Truncate output files on startup\n"
        "  --first-signal-min-kol-count N   One row per token at kol_count >= N\n"
        "  --tokens-newer-than-session-start   Skip tokens older than session start\n"
        "  --paper-min-mode N    Paper gate minimum mode (default 2)\n"
        "  --paper-min-ml N      Paper gate minimum ml_score (default 0.5)\n"
        "  --log-file PATH       Tee stderr to file\n"
        "\n"
        "Options:\n"
        "  --format tsv|json     Stdout format (default: json)\n"
        "  --backtest            Replay with outcome enrichment\n"
        "  --no-ipc              Don't send signals to hotpath IPC\n"
        "  --shadow              Shadow mode (position_bnb=0)\n"
        "  --create-backfill-blocks N   TokenCreate backfill depth (default 500000; 0=off)\n"
        "  --allow-unknown-create       Allow modes without create_block\n"
        "  --poll-ms N           HTTP poll interval (default 1000)\n"
        "  --deployers PATH      Deployer reputation CSV\n"
        "\n"
        "Env: QUICK_NODE_BSC_RPC, ALCHEMY_BSC_RPC, BSC_WS_URL, KOL_FILE,\n"
        "     DEPLOYER_CSV, BINANCE_SPOT_API_BASE, LUMINA_IPC_SOCKET\n");
}

int main(int argc, char** argv) {
    ::signal(SIGINT, on_signal);
    ::signal(SIGTERM, on_signal);

    const char* rpc = std::getenv("QUICK_NODE_BSC_RPC");
    if (!rpc || !*rpc) {
        std::fprintf(stderr, "Set QUICK_NODE_BSC_RPC\n");
        print_usage();
        return 1;
    }
    const char* rpc_fb = std::getenv("ALCHEMY_BSC_RPC");
    BscRpcClient client(rpc, rpc_fb ? rpc_fb : "");

    const char* kol_path = std::getenv("KOL_FILE");
    if (!kol_path || !*kol_path) kol_path = "top.json";
    std::unordered_set<Address, AddressHash> kol_set;
    std::vector<std::string> kol_padded;
    size_t nk = load_kol_file(kol_path, kol_set, kol_padded);
    if (nk == 0) {
        std::fprintf(stderr, "No KOL wallets loaded from %s\n", kol_path);
        return 1;
    }
    std::fprintf(stderr, "[kol_monitor] Loaded %zu KOL wallets from %s\n", nk, kol_path);

    const char* ipc_path = std::getenv("LUMINA_IPC_SOCKET");
    if (!ipc_path) ipc_path = "/tmp/lumina_ipc.sock";
    bool ipc_enabled = true;
    int poll_ms = 1000;
    OutFmt fmt = OutFmt::Json;
    bool yesterday = false;
    bool backtest_mode = false;
    const char* deployers_path = nullptr;
    std::vector<char*> pos_args;

    // Live writer config
    LiveWriterConfig writer_cfg;
    const char* log_file_path = nullptr;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--deployers") == 0 && i + 1 < argc) {
            deployers_path = argv[++i]; continue;
        }
        if (std::strcmp(argv[i], "--no-ipc") == 0) { ipc_enabled = false; continue; }
        if (std::strcmp(argv[i], "--create-backfill-blocks") == 0 && i + 1 < argc) {
            g_live_create_backfill_max_blocks = std::strtoull(argv[++i], nullptr, 10); continue;
        }
        if (std::strcmp(argv[i], "--allow-unknown-create") == 0) {
            g_allow_unknown_create_for_modes = true; continue;
        }
        if (std::strcmp(argv[i], "--shadow") == 0) {
            g_shadow_mode = true; ipc_enabled = false; continue;
        }
        if (std::strcmp(argv[i], "--yesterday") == 0) { yesterday = true; continue; }
        if (std::strcmp(argv[i], "--backtest") == 0) { backtest_mode = true; continue; }
        if (std::strcmp(argv[i], "--poll-ms") == 0 && i + 1 < argc) {
            poll_ms = std::atoi(argv[++i]); continue;
        }
        if (std::strcmp(argv[i], "--format") == 0 && i + 1 < argc) {
            ++i;
            if (std::strcmp(argv[i], "tsv") == 0) fmt = OutFmt::Tsv;
            else if (std::strcmp(argv[i], "json") == 0) fmt = OutFmt::Json;
            else { std::fprintf(stderr, "Unknown --format %s\n", argv[i]); return 1; }
            continue;
        }
        // Live writer args
        if (std::strcmp(argv[i], "--csv") == 0 && i + 1 < argc) {
            writer_cfg.csv_path = argv[++i]; continue;
        }
        if (std::strcmp(argv[i], "--jsonl") == 0 && i + 1 < argc) {
            writer_cfg.jsonl_path = argv[++i]; continue;
        }
        if (std::strcmp(argv[i], "--paper-csv") == 0 && i + 1 < argc) {
            writer_cfg.paper_csv_path = argv[++i]; continue;
        }
        if (std::strcmp(argv[i], "--fresh-output") == 0) {
            writer_cfg.fresh_output = true; continue;
        }
        if (std::strcmp(argv[i], "--first-signal-min-kol-count") == 0 && i + 1 < argc) {
            writer_cfg.first_signal_min_kol_count = std::atoi(argv[++i]); continue;
        }
        if (std::strcmp(argv[i], "--tokens-newer-than-session-start") == 0) {
            writer_cfg.tokens_newer_than_session = true; continue;
        }
        if (std::strcmp(argv[i], "--paper-min-mode") == 0 && i + 1 < argc) {
            writer_cfg.paper_min_mode = std::atoi(argv[++i]); continue;
        }
        if (std::strcmp(argv[i], "--paper-min-ml") == 0 && i + 1 < argc) {
            writer_cfg.paper_min_ml_score = std::strtod(argv[++i], nullptr); continue;
        }
        if (std::strcmp(argv[i], "--log-file") == 0 && i + 1 < argc) {
            log_file_path = argv[++i]; continue;
        }
        if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            print_usage(); return 0;
        }
        pos_args.push_back(argv[i]);
    }

    // Tee stderr to log file if requested
    if (log_file_path) {
        g_log_fp = std::fopen(log_file_path, "a");
        if (!g_log_fp)
            std::fprintf(stderr, "[kol_monitor] Cannot open log file %s\n", log_file_path);
        else
            std::fprintf(stderr, "[kol_monitor] Logging signals to %s\n", log_file_path);
    }

    if (!deployers_path || !*deployers_path)
        deployers_path = std::getenv("DEPLOYER_CSV");
    if (deployers_path && *deployers_path) {
        size_t nd = g_deployer_db.load_csv(deployers_path);
        std::fprintf(stderr, "[kol_monitor] Loaded %zu deployer rows from %s\n", nd, deployers_path);
    }

    // Shared state
    std::unordered_map<Address, TokenMeta, AddressHash> recent_creates;

    std::string proxy_lower = to_lower(fourmeme::PROXY_MANAGER);
    std::string topic_create = to_lower(fourmeme::TOPIC_TOKEN_CREATE);
    std::string topic_create_legacy = to_lower(fourmeme::TOPIC_TOKEN_CREATE_LEGACY);

    std::vector<std::string> create_topics = {
        fourmeme::TOPIC_TOKEN_CREATE,
        fourmeme::TOPIC_TOKEN_CREATE_LEGACY,
    };

    static const std::string TRANSFER_TOPIC =
        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";

    // Determine mode
    bool replay_mode = false;
    uint64_t from_b = 0, to_b = 0;

    // Auto-detect BSC block time to compute correct time-based ranges
    auto blocks_for_seconds = [&](uint64_t latest_block, uint64_t seconds) -> uint64_t {
        uint64_t sample_block = (latest_block > 2000) ? latest_block - 2000 : 0;
        uint64_t ts_latest = 0, ts_sample = 0;
        client.eth_get_block_timestamp(block_to_hex(latest_block), ts_latest);
        client.eth_get_block_timestamp(block_to_hex(sample_block), ts_sample);
        if (ts_latest > ts_sample && ts_latest - ts_sample > 0) {
            double block_time = static_cast<double>(ts_latest - ts_sample) /
                                static_cast<double>(latest_block - sample_block);
            // BSC mainnet is ~3s/block; bad RPC timestamps can imply absurd rates (e.g. 0.45s)
            // and blow up --recent ranges into millions of blocks.
            constexpr double kBscMinSec = 2.0;
            constexpr double kBscMaxSec = 6.0;
            constexpr double kBscDefaultSec = 3.0;
            if (block_time < kBscMinSec || block_time > kBscMaxSec) {
                std::fprintf(stderr,
                             "[kol_monitor] measured block_time %.3fs out of range [%.1f, %.1f]; using %.1fs\n",
                             block_time, kBscMinSec, kBscMaxSec, kBscDefaultSec);
                block_time = kBscDefaultSec;
            }
            uint64_t blocks = static_cast<uint64_t>(seconds / block_time + 0.5);
            std::fprintf(stderr, "[kol_monitor] BSC block time: %.3fs → %llu blocks for %llus (%lluh)\n",
                         block_time, static_cast<unsigned long long>(blocks),
                         static_cast<unsigned long long>(seconds),
                         static_cast<unsigned long long>(seconds / 3600));
            return blocks;
        }
        return seconds; // fallback: assume 1s/block
    };

    if (yesterday) {
        replay_mode = true;
        uint64_t latest = 0;
        if (!client.eth_block_number(latest)) { std::fprintf(stderr, "eth_blockNumber failed\n"); return 1; }
        uint64_t yesterday_blocks = blocks_for_seconds(latest, 86400);
        from_b = (latest > yesterday_blocks) ? latest - yesterday_blocks : 0;
        to_b = latest;
    } else if (pos_args.size() >= 2 && std::strcmp(pos_args[0], "--recent") == 0) {
        replay_mode = true;
        uint64_t hours = std::strtoull(pos_args[1], nullptr, 0);
        uint64_t latest = 0;
        if (!client.eth_block_number(latest)) { std::fprintf(stderr, "eth_blockNumber failed\n"); return 1; }
        uint64_t n = blocks_for_seconds(latest, hours * 3600);
        from_b = (latest > n) ? latest - n : 0;
        to_b = latest;
    } else if (pos_args.size() >= 2) {
        replay_mode = true;
        from_b = std::strtoull(pos_args[0], nullptr, 0);
        to_b = std::strtoull(pos_args[1], nullptr, 0);
        if (to_b < from_b) { std::fprintf(stderr, "invalid range\n"); return 1; }
    }

    KolStats stats{};

    // ── REPLAY MODE ─────────────────────────────────────────────────────
    if (replay_mode) {
        uint64_t chunk = 2000;
        if (const char* cs = std::getenv("REPLAY_CHUNK_BLOCKS"); cs && *cs)
            chunk = std::max<uint64_t>(1, std::strtoull(cs, nullptr, 0));
        uint64_t progress_every = 200;
        if (const char* pe = std::getenv("REPLAY_PROGRESS_CHUNKS"); pe && *pe)
            progress_every = std::strtoull(pe, nullptr, 0);

        const uint64_t total_blocks = (to_b >= from_b) ? (to_b - from_b + 1) : 0;
        std::fprintf(stderr, "[kol_monitor] REPLAY %llu..%llu (%llu blocks, chunk=%llu)\n",
                     static_cast<unsigned long long>(from_b), static_cast<unsigned long long>(to_b),
                     static_cast<unsigned long long>(total_blocks), static_cast<unsigned long long>(chunk));

        if (to_b > from_b) {
            uint64_t ts_lo = 0, ts_hi = 0;
            if (client.eth_get_block_timestamp(block_to_hex(from_b), ts_lo) &&
                client.eth_get_block_timestamp(block_to_hex(to_b), ts_hi) && ts_hi > ts_lo) {
                double bt = static_cast<double>(ts_hi - ts_lo) / static_cast<double>(to_b - from_b);
                // Match blocks_for_seconds: BSC ~3s; bad timestamp deltas skew +2s delay rounding.
                if (bt >= 2.0 && bt <= 6.0) g_replay_block_time_sec = bt;
                else if (bt >= 0.05 && bt <= 30.0) {
                    std::fprintf(stderr,
                                 "[kol_monitor] replay block_time %.4fs implausible for BSC; using 3.0s for +2s\n",
                                 bt);
                    g_replay_block_time_sec = 3.0;
                }
            }
            std::fprintf(stderr, "[kol_monitor] block_time_sec=%.4f (for +2s → blocks)\n", g_replay_block_time_sec);
        }

        const auto t0 = std::chrono::steady_clock::now();
        uint64_t chunk_i = 0;

        double bnb_price = fetch_bnb_price();
        std::fprintf(stderr, "[kol_monitor] BNB/USD price: $%.2f\n", bnb_price);

        std::unordered_map<std::string, std::vector<KolBuyEvent>> raw_kol_buys;

        // ── Phase 1: bulk scan for TokenCreate + Transfer-to-KOL in range ──
        std::fprintf(stderr, "[kol_monitor] Phase 1: bulk scanning TokenCreate + Transfer events...\n");
        for (uint64_t b = from_b; b <= to_b && g_running.load();) {
            uint64_t end = std::min(b + chunk - 1, to_b);
            std::string from_hex = block_to_hex(b);
            std::string to_hex = block_to_hex(end);

            std::vector<RpcLogEntry> proxy_logs;
            client.eth_get_logs_manager(proxy_lower, create_topics, from_hex, to_hex, proxy_logs);
            process_proxy_logs(proxy_logs, recent_creates, topic_create, topic_create_legacy, stats);

            std::vector<RpcLogEntry> transfer_logs;
            if (client.eth_get_logs_transfer_to(TRANSFER_TOPIC, kol_padded, from_hex, to_hex, transfer_logs)) {
                collect_transfer_logs(transfer_logs, kol_set, recent_creates, raw_kol_buys, stats);
            }

            ++chunk_i;
            if (progress_every > 0 && (chunk_i % progress_every == 0)) {
                auto now = std::chrono::steady_clock::now();
                auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
                uint64_t done = end - from_b + 1;
                std::fprintf(stderr,
                             "[kol_monitor] chunk %llu  %llu/%llu blocks  creates=%llu  kol_buys=%llu  %lldms\n",
                             static_cast<unsigned long long>(chunk_i),
                             static_cast<unsigned long long>(done),
                             static_cast<unsigned long long>(total_blocks),
                             static_cast<unsigned long long>(stats.n_creates),
                             static_cast<unsigned long long>(stats.n_kol_buys),
                             static_cast<long long>(ms));
                std::fflush(stderr);
            }
            b = end + 1;
        }

        auto scan_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                            std::chrono::steady_clock::now() - t0).count();
        std::map<std::string, TokenSummary> token_summaries;
        finalize_token_summaries_from_raw(raw_kol_buys, recent_creates, token_summaries);

        std::fprintf(stderr, "[kol_monitor] Phase 1 done: %llu creates, %llu kol_buys, %zu unique tokens (%lldms)\n",
                     static_cast<unsigned long long>(stats.n_creates),
                     static_cast<unsigned long long>(stats.n_kol_buys),
                     token_summaries.size(), static_cast<long long>(scan_ms));

        // ── Phase 2: filter — only tokens CREATED in range (has create_block) ──
        std::vector<TokenSummary> filtered;
        for (auto& [addr, ts] : token_summaries) {
            if (ts.create_block > 0 && ts.create_block >= from_b) {
                filtered.push_back(ts);
            }
        }
        std::sort(filtered.begin(), filtered.end(),
                  [](const TokenSummary& a, const TokenSummary& b) {
                      return a.first_buy_block < b.first_buy_block;
                  });

        std::fprintf(stderr, "[kol_monitor] Phase 2: %zu tokens created in range with KOL buys (filtered from %zu)\n",
                     filtered.size(), token_summaries.size());

        // ── Phase 3: entry mcap at each KOL buy block (slots 0..2) ───────
        // Uses batched RPC: pre-fetch curve info for all tokens' first-buy blocks in one pass,
        // then per-slot entry mcap with batching.
        std::fprintf(stderr, "[kol_monitor] Phase 3: querying entry mcap for %zu tokens (batched)...\n", filtered.size());
        std::unordered_map<std::string, DexPools> all_dex_pools;

        // Pre-batch: fetch curve info at first_buy_block for all tokens
        {
            std::vector<std::pair<Address, std::string>> batch_queries;
            batch_queries.reserve(filtered.size());
            for (const auto& ts : filtered)
                batch_queries.push_back({hex_to_address(ts.token_addr), block_to_hex(ts.first_buy_block)});

            std::vector<TokenManagerCurveInfo> batch_results;
            client.batch_get_token_info_curve(batch_queries, batch_results);

            for (size_t i = 0; i < filtered.size(); ++i) {
                auto& ts = filtered[i];
                if (batch_results[i].valid) {
                    ts.max_funds_bnb = batch_results[i].max_funds_bnb;
                    ts.mcap_bnb = batch_results[i].funds_bnb;
                    ts.graduated = batch_results[i].liquidity_added;
                    ts.bonding_curve_pct = (ts.max_funds_bnb > 0.0)
                        ? std::min(1.0, ts.mcap_bnb / ts.max_funds_bnb)
                        : 0.0;
                }
            }
        }

        // ── Phase 3+3b+4: parallel token enrichment via thread pool ─────
        // Each thread gets its own BscRpcClient to avoid mutex contention.
        // Env: KOL_THREADS (default 4)
        int n_threads = 4;
        if (const char* e = std::getenv("KOL_THREADS"); e && *e)
            n_threads = std::max(1, std::min(32, std::atoi(e)));
        std::fprintf(stderr, "[kol_monitor] Phase 3+3b+4: parallel enrichment with %d threads for %zu tokens...\n",
                     n_threads, filtered.size());

        const std::string XFER_TOPIC_LOWER =
            to_lower("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef");
        uint64_t dev_span_cap = 100000;
        if (const char* e = std::getenv("KOL_DEV_SELL_MAX_SPAN_BLOCKS"); e && *e)
            dev_span_cap = std::max<uint64_t>(1ULL, std::strtoull(e, nullptr, 0));
        const uint64_t delay_2s_blocks =
            std::max<uint64_t>(1ULL, static_cast<uint64_t>(2.0 / g_replay_block_time_sec + 0.5));
        const uint64_t delay_blocks_arr[3] = {1, 2, delay_2s_blocks};

        std::atomic<size_t> progress_counter{0};

        // Worker function: process a range [begin, end) of the filtered array
        auto worker_fn = [&](size_t begin, size_t end_idx, BscRpcClient& w_client) {
            std::unordered_map<std::string, DexPools> local_dex_pools;
            // Seed from pre-existing dex pools
            {
                std::lock_guard<std::mutex> lk(g_bnb_price_cache_mu); // reuse mutex for dex_pools
                local_dex_pools = all_dex_pools;
            }

            for (size_t i = begin; i < end_idx && g_running.load(); ++i) {
                auto& ts = filtered[i];
                Address token = hex_to_address(ts.token_addr);

                // Phase 3 per-token: slot entry mcap + create timestamp
                for (int s = 0; s < 3 && s < static_cast<int>(ts.kol_order.size()); ++s) {
                    uint64_t eb = ts.kol_order[static_cast<size_t>(s)].block;
                    ts.slot_entry_mcap_usd[s] =
                        entry_mcap_usd_at_buy_block(w_client, ts.token_addr, token, eb, bnb_price, local_dex_pools);
                }
                ts.entry_mcap_usd = ts.slot_entry_mcap_usd[0];
                if (ts.create_block > 0)
                    w_client.eth_get_block_timestamp(block_to_hex(ts.create_block), ts.create_timestamp);

                // BNB price at first buy
                if (ts.first_buy_block > 0)
                    ts.bnb_price_usd = fetch_bnb_price_at_block(w_client, ts.first_buy_block, bnb_price);

                // Holder count at entry (first KOL buy block)
                if (backtest_mode && ts.create_block > 0 && ts.first_buy_block > 0) {
                    std::string tok_lower = to_lower(ts.token_addr);
                    ts.holder_count_at_entry = count_holders_proxy(w_client, tok_lower, ts.create_block, ts.first_buy_block);
                }

                // Phase 3b: dev sells
                if (backtest_mode) {
                    ts.dev_sell_tokens = 0.0;
                    if (!is_zero(ts.creator) && ts.create_block > 0) {
                        uint64_t last_kol = ts.create_block;
                        for (const auto& k : ts.kol_order) last_kol = std::max(last_kol, k.block);
                        uint64_t dev_end = std::min({to_b, last_kol, ts.create_block + dev_span_cap});
                        if (dev_end >= ts.create_block) {
                            ts.dev_sell_tokens = sum_dev_transfer_out_tokens(
                                w_client, ts.token_addr, ts.creator, ts.create_block, dev_end, XFER_TOPIC_LOWER);
                        }
                    }
                }

                // Phase 4: peak/low outcome enrichment
                if (backtest_mode) {
                    std::unordered_map<uint64_t, std::tuple<double, double, double>> peak_by_entry_block;
                    double legacy_current = 0.0;
                    for (int s = 0; s < 3 && s < static_cast<int>(ts.kol_order.size()); ++s) {
                        uint64_t buy_b = ts.kol_order[static_cast<size_t>(s)].block;
                        for (int d = 0; d < 3; ++d) {
                            uint64_t our_b = buy_b + delay_blocks_arr[d];
                            if (our_b > to_b) continue;
                            double our_m = entry_mcap_usd_at_buy_block(
                                w_client, ts.token_addr, token, our_b, bnb_price, local_dex_pools);
                            double peak_s = our_m, low_s = our_m, cur_s = 0.0;
                            auto pit = peak_by_entry_block.find(our_b);
                            if (pit == peak_by_entry_block.end()) {
                                scan_peak_low_window(w_client, ts, token, our_b, our_m, to_b, bnb_price,
                                                     local_dex_pools, peak_s, low_s, cur_s);
                                peak_by_entry_block[our_b] = std::make_tuple(peak_s, low_s, cur_s);
                            } else {
                                peak_s = std::get<0>(pit->second);
                                low_s = std::get<1>(pit->second);
                                cur_s = std::get<2>(pit->second);
                            }
                            ts.slot_delay[s][d].our_entry_block = our_b;
                            ts.slot_delay[s][d].our_entry_mcap_usd = our_m;
                            ts.slot_delay[s][d].peak_mcap_usd = peak_s;
                            ts.slot_delay[s][d].low_mcap_usd = low_s;
                            if (s == 0 && d == 0) legacy_current = cur_s;
                        }
                    }
                    ts.peak_mcap_usd = ts.slot_delay[0][0].peak_mcap_usd;
                    ts.low_mcap_usd = ts.slot_delay[0][0].low_mcap_usd;
                    ts.current_mcap_usd = legacy_current;
                    if (ts.slot_delay[0][0].our_entry_block == 0) {
                        ts.peak_mcap_usd = ts.entry_mcap_usd;
                        ts.low_mcap_usd = ts.entry_mcap_usd;
                    }
                    if (ts.current_mcap_usd < 1.0) ts.current_mcap_usd = ts.entry_mcap_usd;
                }

                size_t done = progress_counter.fetch_add(1) + 1;
                if (done % 50 == 0 || done == filtered.size()) {
                    std::fprintf(stderr, "[parallel] %zu/%zu tokens enriched\n", done, filtered.size());
                }
            }

            // Merge local DEX pools back (non-critical, best-effort for Phase 5 output tags)
            {
                std::lock_guard<std::mutex> lk(g_bnb_price_cache_mu);
                for (auto& [k, v] : local_dex_pools)
                    all_dex_pools.emplace(k, v);
            }
        };

        // Dispatch threads
        if (n_threads <= 1 || filtered.size() <= 4) {
            worker_fn(0, filtered.size(), client);
        } else {
            std::vector<std::thread> threads;
            std::vector<std::unique_ptr<BscRpcClient>> thread_clients;
            size_t per_thread = (filtered.size() + static_cast<size_t>(n_threads) - 1)
                                / static_cast<size_t>(n_threads);
            for (int t = 0; t < n_threads; ++t) {
                size_t begin = static_cast<size_t>(t) * per_thread;
                size_t end_idx = std::min(begin + per_thread, filtered.size());
                if (begin >= filtered.size()) break;
                auto tc = std::make_unique<BscRpcClient>(client.primary_url(), client.fallback_url());
                tc->set_min_token_info_interval(std::chrono::milliseconds(0));
                BscRpcClient* tc_ptr = tc.get();
                thread_clients.push_back(std::move(tc));
                threads.emplace_back([&worker_fn, begin, end_idx, tc_ptr]() {
                    worker_fn(begin, end_idx, *tc_ptr);
                });
            }
            for (auto& th : threads) th.join();
        }

        std::fprintf(stderr, "[kol_monitor] Phase 3+3b+4 complete.\n");

        // Phase 5: output
        if (backtest_mode) {
            // Full JSONL with outcome data in USD
            int row = 0;
            for (const auto& ts : filtered) {
                ++row;
                std::string name = ts.name.empty() ? "(no name)" : ts.name;
                double peak_x = (ts.entry_mcap_usd > 1.0) ? ts.peak_mcap_usd / ts.entry_mcap_usd : 0.0;
                double low_x = (ts.entry_mcap_usd > 1.0) ? ts.low_mcap_usd / ts.entry_mcap_usd : 0.0;
                double dev_sell_usd_approx = 0.0;
                if (ts.entry_mcap_usd > 1.0 && ts.dev_sell_tokens > 0.0)
                    dev_sell_usd_approx = ts.dev_sell_tokens * (ts.entry_mcap_usd / TOTAL_SUPPLY);

                // Format create_time as ISO8601
                char time_buf[32] = "unknown";
                if (ts.create_timestamp > 0) {
                    time_t t = static_cast<time_t>(ts.create_timestamp);
                    struct tm tm{};
                    gmtime_r(&t, &tm);
                    std::strftime(time_buf, sizeof(time_buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
                }

                std::printf(
                    "{\"row\":%d,\"name\":\"%s\",\"token\":\"%s\","
                    "\"first_buyer\":\"%s\",\"kol_count\":%zu,\"age_blocks\":%llu,"
                    "\"create_block\":%llu,\"create_time\":\"%s\","
                    "\"creator\":\"%s\","
                    "\"entry_mcap_usd\":%.0f,\"peak_mcap_usd\":%.0f,"
                    "\"low_mcap_usd\":%.0f,\"current_mcap_usd\":%.0f,"
                    "\"graduated\":%s,\"peak_x\":%.2f,\"low_x\":%.2f,"
                    "\"dev_sell_tokens\":%.9g,\"dev_sell_usd_approx\":%.0f,"
                    "\"bonding_curve_pct\":%.4f,\"bnb_price_usd\":%.2f,"
                    "\"holder_count_at_entry\":%llu",
                    row, json_escape(name).c_str(), ts.token_addr.c_str(),
                    addr_lower(ts.first_buyer).c_str(), ts.kol_count,
                    static_cast<unsigned long long>(ts.age_blocks),
                    static_cast<unsigned long long>(ts.create_block), time_buf,
                    addr_lower(ts.creator).c_str(),
                    ts.entry_mcap_usd, ts.peak_mcap_usd,
                    ts.low_mcap_usd, ts.current_mcap_usd,
                    ts.graduated ? "true" : "false", peak_x, low_x, ts.dev_sell_tokens,
                    dev_sell_usd_approx,
                    ts.bonding_curve_pct, ts.bnb_price_usd,
                    static_cast<unsigned long long>(ts.holder_count_at_entry));
                std::string kb_json;
                append_kol_buys_json(kb_json, ts);
                std::printf(",%s", kb_json.c_str());
                std::string sd_json;
                append_slot_delay_json(sd_json, ts);
                std::printf(",%s,\"block_time_sec\":%.6f}\n", sd_json.c_str(), g_replay_block_time_sec);
            }
        } else if (fmt == OutFmt::Tsv) {
            std::printf("#\tname\ttoken\tfirst_buyer\tmcap_bnb\tkol_count\tage_blocks\n");
            int row = 0;
            for (const auto& ts : filtered) {
                ++row;
                std::string name = ts.name;
                tsv_sanitize(name);
                if (name.empty()) name = "(no name)";

                std::printf("%d\t%s\t%s\t%s\t%.4f\t%zu\t%llu\n",
                            row, name.c_str(), ts.token_addr.c_str(),
                            addr_lower(ts.first_buyer).c_str(),
                            ts.mcap_bnb, ts.kol_count,
                            static_cast<unsigned long long>(ts.age_blocks));
            }
        } else {
            int row = 0;
            for (const auto& ts : filtered) {
                ++row;
                std::string name = ts.name.empty() ? "(no name)" : ts.name;
                std::printf(
                    "{\"row\":%d,\"name\":\"%s\",\"token\":\"%s\","
                    "\"first_buyer\":\"%s\",\"mcap_bnb\":%.4f,"
                    "\"kol_count\":%zu,\"age_blocks\":%llu}\n",
                    row, json_escape(name).c_str(), ts.token_addr.c_str(),
                    addr_lower(ts.first_buyer).c_str(), ts.mcap_bnb,
                    ts.kol_count, static_cast<unsigned long long>(ts.age_blocks));
            }
        }
        std::fflush(stdout);

        // ── ClickHouse write (optional, controlled by CLICKHOUSE_HOST env) ──
        if (backtest_mode) {
            const char* ch_host = std::getenv("CLICKHOUSE_HOST");
            if (ch_host && *ch_host) {
                int ch_port = 8123;
                if (const char* p = std::getenv("CLICKHOUSE_PORT"); p && *p)
                    ch_port = std::atoi(p);
                ClickHouseWriter ch(ch_host, ch_port, "lumina");
                if (ch.ping()) {
                    std::fprintf(stderr, "[kol_monitor] Writing %zu rows to ClickHouse kol_signals...\n", filtered.size());
                    std::vector<std::string> rows;
                    rows.reserve(filtered.size());
                    for (const auto& ts : filtered) {
                        double peak_x = (ts.entry_mcap_usd > 1.0) ? ts.peak_mcap_usd / ts.entry_mcap_usd : 0.0;
                        double low_x = (ts.entry_mcap_usd > 1.0) ? ts.low_mcap_usd / ts.entry_mcap_usd : 0.0;
                        double dsell_usd = (ts.entry_mcap_usd > 1.0 && ts.dev_sell_tokens > 0.0)
                                               ? ts.dev_sell_tokens * (ts.entry_mcap_usd / TOTAL_SUPPLY) : 0.0;
                        // Build KOL names from kol_order
                        std::string kol_names_arr = "[";
                        std::string combo;
                        for (size_t k = 0; k < ts.kol_order.size(); ++k) {
                            std::string n = kol_display_name(ts.kol_order[k].kol);
                            if (k) { kol_names_arr += ","; combo += "\xe2\x86\x92"; }
                            kol_names_arr += "'" + n + "'";
                            combo += n;
                        }
                        kol_names_arr += "]";
                        // Tab-separated row matching kol_signals schema
                        std::ostringstream r;
                        r << ts.token_addr << '\t'
                          << ts.name << '\t'
                          << "" << '\t' // symbol (not stored in TokenSummary)
                          << ts.kol_count << '\t'
                          << kol_names_arr << '\t'
                          << combo << '\t'
                          << 0 << '\t' // mode (backtest doesn't score)
                          << ts.entry_mcap_usd << '\t'
                          << ts.peak_mcap_usd << '\t'
                          << ts.low_mcap_usd << '\t'
                          << ts.current_mcap_usd << '\t'
                          << 0 << '\t' // holder_proxy (needs enrichment)
                          << dsell_usd << '\t'
                          << ts.dev_sell_tokens << '\t'
                          << addr_lower(ts.creator) << '\t'
                          << ts.create_block << '\t'
                          << ts.age_blocks << '\t'
                          << (ts.graduated ? 1 : 0) << '\t'
                          << peak_x << '\t'
                          << low_x << '\t'
                          << 0 << '\t' // kol_buy_speed_blocks
                          << addr_lower(ts.first_buyer) << '\t'
                          << "backtest" << '\t'
                          << "0000-00-00 00:00:00"; // will use default
                        rows.push_back(r.str());
                    }
                    if (ch.insert_rows("kol_signals", rows)) {
                        std::fprintf(stderr, "[kol_monitor] ClickHouse: %zu rows written\n", rows.size());
                    }
                } else {
                    std::fprintf(stderr, "[kol_monitor] ClickHouse ping failed at %s:%d, skipping write\n",
                                 ch_host, ch_port);
                }
            }
        }

        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::steady_clock::now() - t0).count();

        std::fprintf(stderr,
                     "{\"summary\":{\"mode\":\"%s\","
                     "\"from_block\":%llu,\"to_block\":%llu,"
                     "\"blocks_scanned\":%llu,"
                     "\"token_creates\":%llu,\"tokens_with_kol\":%zu,"
                     "\"elapsed_ms\":%lld}}\n",
                     backtest_mode ? "backtest" : "replay",
                     static_cast<unsigned long long>(from_b),
                     static_cast<unsigned long long>(to_b),
                     static_cast<unsigned long long>(to_b - from_b + 1),
                     static_cast<unsigned long long>(stats.n_creates),
                     filtered.size(),
                     static_cast<long long>(elapsed_ms));
        return 0;
    }

    // ── LIVE MODE (WSS with HTTP fallback) ──────────────────────────────
    g_session.start_time = std::chrono::steady_clock::now();

    double live_bnb_price = fetch_bnb_price();
    std::fprintf(stderr, "[kol_monitor] Live BNB/USD: $%.2f\n", live_bnb_price);

    // Get chain tip for session floor and block-time reference
    uint64_t live_tip_block = 0;
    uint64_t live_tip_ts = 0;
    if (client.eth_block_number(live_tip_block)) {
        client.eth_get_block_timestamp(block_to_hex(live_tip_block), live_tip_ts);
    }

    // Initialize dataset writer
    if (!writer_cfg.csv_path.empty() || !writer_cfg.jsonl_path.empty() ||
        !writer_cfg.paper_csv_path.empty()) {
        if (writer_cfg.tokens_newer_than_session)
            writer_cfg.session_start_block = live_tip_block;
        static LiveDatasetWriter writer(writer_cfg);
        if (!writer.init()) {
            std::fprintf(stderr, "[kol_monitor] Writer init failed\n");
            return 1;
        }
        g_writer = &writer;
    }

    // Start Binance klines background thread
    g_klines.start();

    const char* ws_url_env = std::getenv("BSC_WS_URL");
    std::string ws_url;
    if (ws_url_env && *ws_url_env) {
        ws_url = ws_url_env;
    } else {
        ws_url = fourmeme::http_rpc_to_ws_url(rpc);
    }

    std::unordered_map<Address, std::unordered_set<Address, AddressHash>, AddressHash> kol_buys_per_token;

    // Build WSS subscription JSON for Transfer events to KOL wallets
    // topics: [Transfer, null, [kol1_padded, kol2_padded, ...]]
    std::string sub_topics_arr = "[";
    for (size_t i = 0; i < kol_padded.size(); ++i) {
        if (i) sub_topics_arr += ",";
        sub_topics_arr += "\"" + kol_padded[i] + "\"";
    }
    sub_topics_arr += "]";

    std::string sub_json =
        R"({"jsonrpc":"2.0","id":1,"method":"eth_subscribe","params":["logs",{"topics":[")" +
        TRANSFER_TOPIC + R"(",null,)" + sub_topics_arr + R"(]}]})";

    // Also subscribe to TokenCreate on the proxy for name/symbol enrichment
    std::string sub_create_json =
        R"({"jsonrpc":"2.0","id":2,"method":"eth_subscribe","params":["logs",{"address":")" +
        proxy_lower + R"(","topics":[[)" +
        "\"" + to_lower(fourmeme::TOPIC_TOKEN_CREATE) + "\"," +
        "\"" + to_lower(fourmeme::TOPIC_TOKEN_CREATE_LEGACY) + "\"" +
        R"(]]}]})";

    bool wss_connected = false;
    BscWsClient ws;

    auto try_wss = [&]() -> bool {
        if (ws_url.empty()) return false;
        std::fprintf(stderr, "[kol_monitor] Connecting WSS %s...\n", ws_url.substr(0, 50).c_str());
        if (!ws.connect(ws_url)) {
            std::fprintf(stderr, "[kol_monitor] WSS connect failed\n");
            return false;
        }
        // Subscribe to Transfer events
        if (!ws.send_json(sub_json)) { ws.close(); return false; }
        std::string ack;
        if (!ws.recv_text(ack)) { ws.close(); return false; }
        std::fprintf(stderr, "[kol_monitor] WSS sub Transfer ack: %.100s\n", ack.c_str());
        // Subscribe to TokenCreate
        if (!ws.send_json(sub_create_json)) { ws.close(); return false; }
        if (!ws.recv_text(ack)) { ws.close(); return false; }
        std::fprintf(stderr, "[kol_monitor] WSS sub TokenCreate ack: %.100s\n", ack.c_str());
        return true;
    };

    wss_connected = try_wss();
    if (!wss_connected) {
        std::fprintf(stderr, "[kol_monitor] WSS unavailable, falling back to HTTP polling\n");
    }

    if (wss_connected) {
        std::fprintf(stderr, "[kol_monitor] Live WSS mode — sub-second KOL detection\n");
        std::fprintf(stderr, "[kol_monitor] TokenCreate HTTP backfill: max %llu blocks (%s); unknown-create modes %s\n",
                     static_cast<unsigned long long>(g_live_create_backfill_max_blocks),
                     g_live_create_backfill_max_blocks > 0 ? "on" : "off",
                     g_allow_unknown_create_for_modes ? "allowed" : "blocked");
        // WSS event loop
        while (g_running.load()) {
            std::string msg;
            if (!ws.recv_text(msg)) {
                std::fprintf(stderr, "[kol_monitor] WSS disconnected, reconnecting...\n");
                ws.close();
                std::this_thread::sleep_for(std::chrono::seconds(2));
                wss_connected = try_wss();
                if (!wss_connected) {
                    std::fprintf(stderr, "[kol_monitor] WSS reconnect failed, switching to HTTP poll\n");
                    break;
                }
                continue;
            }

            // Parse the incoming log message — minimal JSON extraction
            // {"params":{"result":{"address":"0x...","topics":[...],"data":"0x...","blockNumber":"0x...",
            //   "transactionHash":"0x..."}}}
            auto extract = [](const std::string& json, const char* key) -> std::string {
                std::string search = std::string("\"") + key + "\":\"";
                auto pos = json.find(search);
                if (pos == std::string::npos) return {};
                pos += search.size();
                auto end = json.find('"', pos);
                if (end == std::string::npos) return {};
                return json.substr(pos, end - pos);
            };

            // Extract topics array manually
            auto extract_topics = [](const std::string& json) -> std::vector<std::string> {
                std::vector<std::string> result;
                auto pos = json.find("\"topics\":[");
                if (pos == std::string::npos) return result;
                pos += 10; // skip "topics":[
                auto end = json.find(']', pos);
                if (end == std::string::npos) return result;
                std::string arr = json.substr(pos, end - pos);
                size_t p = 0;
                while (p < arr.size()) {
                    auto q1 = arr.find('"', p);
                    if (q1 == std::string::npos) break;
                    auto q2 = arr.find('"', q1 + 1);
                    if (q2 == std::string::npos) break;
                    result.push_back(arr.substr(q1 + 1, q2 - q1 - 1));
                    p = q2 + 1;
                }
                return result;
            };

            std::string address = to_lower(extract(msg, "address"));
            std::string data = extract(msg, "data");
            std::string block_hex = extract(msg, "blockNumber");
            std::string tx_hash = extract(msg, "transactionHash");
            auto topics = extract_topics(msg);

            if (topics.empty() || address.empty()) continue;
            std::string t0 = to_lower(topics[0]);

            static const std::string TRANSFER_T = to_lower("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef");
            uint64_t block_num = 0;
            if (block_hex.size() > 2) block_num = std::strtoull(block_hex.c_str() + 2, nullptr, 16);

            // TokenCreate enrichment
            if (t0 == topic_create || t0 == topic_create_legacy) {
                RpcLogEntry log_entry;
                log_entry.address_lower = address;
                log_entry.topics = topics;
                log_entry.data = data;
                log_entry.block_number = block_num;
                log_entry.block_hex = block_hex;
                std::vector<RpcLogEntry> logs = {log_entry};
                process_proxy_logs(logs, recent_creates, topic_create, topic_create_legacy, stats);
                continue;
            }

            // Transfer event → KOL buy detection
            if (t0 == TRANSFER_T && is_fourmeme_token(address) && topics.size() >= 3) {
                RpcLogEntry log_entry;
                log_entry.address_lower = address;
                log_entry.topics = topics;
                log_entry.data = data;
                log_entry.block_number = block_num;
                log_entry.block_hex = block_hex;
                log_entry.tx_hash = tx_hash;
                std::vector<RpcLogEntry> logs = {log_entry};
                process_transfer_logs_live(logs, client, kol_set, recent_creates, kol_buys_per_token,
                                           stats, ipc_enabled, ipc_path, live_bnb_price,
                                           live_tip_block, live_tip_ts);
            }
        }
    }

    // HTTP polling fallback (if WSS failed or after WSS disconnect)
    if (!wss_connected && g_running.load()) {
        uint64_t last_block = 0;
        client.eth_block_number(last_block);
        if (last_block > 5) last_block -= 5;

        std::fprintf(stderr, "[kol_monitor] HTTP poll fallback from block %llu (poll=%dms)\n",
                     static_cast<unsigned long long>(last_block), poll_ms);

        uint64_t n_polls = 0;
        while (g_running.load()) {
            uint64_t head = 0;
            if (!client.eth_block_number(head) || head <= last_block) {
                std::this_thread::sleep_for(std::chrono::milliseconds(poll_ms));
                continue;
            }

            uint64_t from = last_block + 1;
            uint64_t to = std::min(head, from + 9);
            std::string from_hex = block_to_hex(from);
            std::string to_hex = block_to_hex(to);

            std::vector<RpcLogEntry> proxy_logs;
            client.eth_get_logs_manager(proxy_lower, create_topics, from_hex, to_hex, proxy_logs);
            process_proxy_logs(proxy_logs, recent_creates, topic_create, topic_create_legacy, stats);

            std::vector<RpcLogEntry> transfer_logs;
            if (client.eth_get_logs_transfer_to(TRANSFER_TOPIC, kol_padded, from_hex, to_hex, transfer_logs)) {
                process_transfer_logs_live(transfer_logs, client, kol_set, recent_creates, kol_buys_per_token,
                                           stats, ipc_enabled, ipc_path, live_bnb_price,
                                           live_tip_block, live_tip_ts);
            }

            last_block = to;
            ++n_polls;

            if (n_polls % 30 == 0) {
                std::fprintf(stderr, "[kol_monitor] poll=%llu block=%llu creates=%llu kol_buys=%llu\n",
                             static_cast<unsigned long long>(n_polls),
                             static_cast<unsigned long long>(last_block),
                             static_cast<unsigned long long>(stats.n_creates),
                             static_cast<unsigned long long>(stats.n_kol_buys));
            }

            if (recent_creates.size() > 5000 && last_block > 1200) {
                uint64_t cutoff = last_block - 1200;
                for (auto it = recent_creates.begin(); it != recent_creates.end(); ) {
                    if (it->second.create_block < cutoff) it = recent_creates.erase(it);
                    else ++it;
                }
            }

            std::this_thread::sleep_for(std::chrono::milliseconds(poll_ms));
        }
    }

    g_klines.stop();
    print_session_summary();
    g_writer = nullptr;
    return 0;
}
