// ============================================================
// Lumina BSC Tier 1 — Core Types & Data Structures
// ============================================================
// Defines all shared types used across the pipeline:
//   Address, Hash32, Selector   – Fixed-size byte arrays
//   RawEvent                    – Raw JSON from WebSocket
//   ParsedTx                    – Parsed transaction fields
//   DetectionResult             – Heuristic check output
//   ScoredEvent                 – Final score + decision
//   DeployerReputation          – Wallet reputation data
//
// All structs are cache-line aligned for performance.
// ============================================================
#pragma once
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <string>
#include <string_view>
#include <algorithm>

namespace lumina {

// --- Primitive aliases ---
using Address   = std::array<uint8_t, 20>;
using Hash32    = std::array<uint8_t, 32>;
using Selector  = std::array<uint8_t, 4>;
using Timestamp = uint64_t;

// --- Time ---
Timestamp now_ns();

// --- Constants ---
static constexpr Address ZERO_ADDRESS = {};
static constexpr Address DEAD_ADDRESS = {0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0xdE,0xaD};

// --- Address utilities ---
bool      is_zero(const Address& a);
Address   hex_to_address(std::string_view hex);
std::string address_to_hex(const Address& a);

// --- PancakeSwap Router V2 method selectors ---
namespace selectors {
    static constexpr uint32_t ADD_LIQUIDITY_ETH = 0xf305d719;
    static constexpr uint32_t ADD_LIQUIDITY     = 0xe8e33700;
    static constexpr uint32_t REMOVE_LIQ_ETH    = 0x02751cec;
    static constexpr uint32_t REMOVE_LIQ        = 0xbaa2abde;
    static constexpr uint32_t REMOVE_LIQ_ETH_FEE= 0xaf2979eb;
    static constexpr uint32_t SWAP_EXACT_ETH_FOR_TOKENS    = 0x7ff36ab5;
    static constexpr uint32_t SWAP_EXACT_TOKENS_FOR_ETH    = 0x18cbafe5;
    static constexpr uint32_t SWAP_EXACT_TOKENS_FOR_TOKENS = 0x38ed1739;
    static constexpr uint32_t SWAP_ETH_FOR_EXACT_TOKENS    = 0xfb3bdb41;
    static constexpr uint32_t SWAP_TOKENS_FOR_EXACT_ETH    = 0x4a25d94a;
    static constexpr uint32_t SWAP_TOKENS_FOR_EXACT_TOKENS = 0x8803dbee;
    static constexpr uint32_t SWAP_EXACT_TOKENS_FOR_ETH_FEE= 0x791ac947;
    static constexpr uint32_t SWAP_EXACT_TOKENS_FOR_TOKENS_FEE=0x5c11d795;
    static constexpr uint32_t RENOUNCE_OWNERSHIP = 0x715018a6;
    static constexpr uint32_t TRANSFER_OWNERSHIP = 0xf2fde38b;
}

// --- Event classification ---
enum class EventType : uint8_t {
    UNKNOWN=0, CONTRACT_CREATION, ADD_LIQUIDITY, REMOVE_LIQUIDITY,
    BUY, SELL, OWNERSHIP_CHANGE, APPROVAL
};
const char* event_type_str(EventType t);

// --- Core data structures (cache-line aligned) ---

struct alignas(64) RawEvent {
    char data[4096];
    uint32_t length;
    Timestamp recv_time;

    void set(const char* src, uint32_t len);
};

struct alignas(64) ParsedTx {
    Address from, to;
    Selector selector;
    uint64_t value_wei, gas_price;
    uint32_t input_length;
    EventType event_type;
    bool is_contract_creation;
    Timestamp recv_time;
    Address token_address;
    uint64_t token_amount, min_bnb;
    Address lp_recipient;
    Hash32 tx_hash;
};

struct alignas(64) DeployerReputation {
    float score;
    uint16_t total_deploys, rug_count, honeypot_count, success_count;
    float success_rate, rug_rate, avg_lifespan_hours;
    uint32_t last_seen_block, first_seen_block;
    enum Flags : uint8_t {
        NONE=0, KNOWN_SCAMMER=1, KNOWN_LEGIT=2,
        CEX_FUNDED=4, MIXER_FUNDED=8, SERIAL_DEPLOYER=16
    };
    uint8_t flags;

    bool  is_scammer() const;
    bool  is_legit()   const;
    bool  is_serial()  const;
    float compute_score() const;
    
    // Score thresholds for decision making
    static constexpr float SCORE_AUTO_SNIPE = 30.0f;   // High confidence
    static constexpr float SCORE_FORWARD = 0.0f;       // Needs more analysis
    static constexpr float SCORE_SKIP = -50.0f;        // Likely scammer
};

struct alignas(64) DetectionResult {
    ParsedTx tx;
    float deployer_score;
    bool bytecode_is_scam, deployer_blacklisted;
    bool has_mint_authority, has_dangerous_funcs, lp_locked;
    float lp_lock_percent;
    uint32_t lp_lock_duration_days;
    uint8_t checks_performed;
    Timestamp detect_time;
};

enum class Decision : uint8_t { HARD_REJECT=0, FORWARD_TIER2=1, FAST_PASS=2 };
const char* decision_str(Decision d);

struct alignas(64) ScoredEvent {
    DetectionResult detection;
    float final_score;
    Decision decision;
    float position_pct;
    Timestamp decision_time;

    uint64_t latency_ns() const;
};

// --- Hash functors for Address / Hash32 ---
struct AddressHash {
    size_t operator()(const Address& a) const noexcept;
};
struct Hash32Hash {
    size_t operator()(const Hash32& h) const noexcept;
};

} // namespace lumina
