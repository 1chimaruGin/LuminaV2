// ============================================================
// Lumina BSC Tier 1 — Configuration
// ============================================================
// Runtime-tunable parameters for the pipeline:
//   - BSC endpoint URLs (WebSocket, Router, Factory, Lockers)
//   - SPSC queue capacity
//   - Scoring weights (deployer, authority, LP lock, bytecode)
//   - Decision thresholds (hard reject, fast pass)
//   - Minimum liquidity requirements
// ============================================================
#pragma once
#include <string>
#include <cstdint>

namespace lumina {

struct Config {
    std::string bsc_ws_url       = "wss://bsc-dataseed.binance.org/";
    std::string pancake_router_v2= "0x10ED43C718714eb63d5aA57B78B54704E256024E";
    std::string pancake_factory_v2="0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73";
    std::string pinklock_v2      = "0x407993575c91ce7643a4d4ccacc9a98c36ee1bbe";
    std::string uncx_locker      = "0xc765bddb93b0d1c1a88282ba0fa6b2d00e3e0c83";

    static constexpr size_t QUEUE_SIZE = 4096;

    float weight_deployer_reputation = 0.35f;
    float weight_authority_flags     = 0.25f;
    float weight_lp_lock             = 0.20f;
    float weight_bytecode_safety     = 0.15f;
    float weight_context_signals     = 0.05f;

    float threshold_hard_reject = 0.15f;
    float threshold_fast_pass   = 0.90f;

    float fast_pass_position_pct = 0.25f;
    float tier2_borderline_pct   = 0.50f;
    float unknown_deployer_score = 0.50f;

    uint64_t min_liquidity_wei = 500000000000000000ULL; // 0.5 BNB

    uint32_t log_stats_interval_sec = 60;
};

} // namespace lumina
