// ============================================================
// Lumina BSC Tier 1 — Heuristic Detector Implementation
// ============================================================
#include "lumina/pipeline/detector.h"
#include <cmath>

namespace lumina {

Detector::Detector(const Config& cfg, const DeployerDB& deployers,
                   const BlacklistDB& blacklist, const BytecodeDB& bytecodes)
    : cfg_(cfg), deployers_(deployers), blacklist_(blacklist), bytecodes_(bytecodes) {}

DetectionResult Detector::detect(const ParsedTx& tx) const noexcept {
    DetectionResult result{};
    result.tx = tx;
    result.deployer_score = std::nanf("");
    result.bytecode_is_scam = false;
    result.deployer_blacklisted = false;
    result.has_mint_authority = false;
    result.has_dangerous_funcs = false;
    result.lp_locked = false;
    result.lp_lock_percent = 0.0f;
    result.lp_lock_duration_days = 0;
    result.checks_performed = 0;

    run_deployer_check(tx, result);
    run_blacklist_check(tx, result);
    if (tx.is_contract_creation) run_bytecode_check(tx, result);
    run_context_check(tx, result);
    if (tx.event_type == EventType::ADD_LIQUIDITY ||
        tx.event_type == EventType::REMOVE_LIQUIDITY) {
        run_liquidity_check(tx, result);
    }

    result.detect_time = now_ns();
    return result;
}

void Detector::run_deployer_check(const ParsedTx& tx, DetectionResult& r) const noexcept {
    r.checks_performed |= (1 << 0);
    const Address& deployer = tx.from;
    auto rep = deployers_.lookup(deployer);
    if (rep.has_value()) {
        r.deployer_score = rep->score;
        if (rep->is_scammer()) r.deployer_score = 0.0f;
        if (rep->is_serial() && rep->rug_count > 0) r.deployer_score *= 0.3f;
    }
}

void Detector::run_blacklist_check(const ParsedTx& tx, DetectionResult& r) const noexcept {
    r.checks_performed |= (1 << 1);
    if (blacklist_.maybe_blacklisted(tx.from)) r.deployer_blacklisted = true;
    if (!is_zero(tx.to) && blacklist_.maybe_blacklisted(tx.to)) r.deployer_blacklisted = true;
    if (tx.event_type == EventType::ADD_LIQUIDITY && !is_zero(tx.token_address)) {
        if (blacklist_.maybe_blacklisted(tx.token_address)) r.deployer_blacklisted = true;
    }
}

void Detector::run_bytecode_check(const ParsedTx& tx, DetectionResult& r) const noexcept {
    r.checks_performed |= (1 << 2);
    if (tx.input_length < 100) r.has_dangerous_funcs = true;
}

void Detector::run_context_check(const ParsedTx& tx, DetectionResult& r) const noexcept {
    r.checks_performed |= (1 << 3);
    switch (tx.event_type) {
        case EventType::ADD_LIQUIDITY:
            if (tx.value_wei < cfg_.min_liquidity_wei) r.has_dangerous_funcs = true;
            break;
        case EventType::REMOVE_LIQUIDITY:
            r.has_dangerous_funcs = true;
            break;
        default:
            break;
    }
}

void Detector::run_liquidity_check(const ParsedTx& tx, DetectionResult& r) const noexcept {
    r.checks_performed |= (1 << 4);
    Address pinklock = hex_to_address(cfg_.pinklock_v2);
    Address uncx = hex_to_address(cfg_.uncx_locker);

    if (tx.lp_recipient == pinklock || tx.lp_recipient == uncx) {
        r.lp_locked = true;
        r.lp_lock_percent = 1.0f;
        r.lp_lock_duration_days = 30;
    } else if (tx.lp_recipient == DEAD_ADDRESS) {
        r.lp_locked = true;
        r.lp_lock_percent = 1.0f;
        r.lp_lock_duration_days = 9999;
    }
}

} // namespace lumina
