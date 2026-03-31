// ============================================================
// Lumina BSC Tier 1 — Scorer Implementation
// ============================================================
// Four.meme launchpad scoring lives in fourmeme::TokenRegistry::score (JSONL via lumina_hotpath).
// ============================================================
#include "lumina/pipeline/scorer.h"
#include <algorithm>
#include <cmath>

namespace lumina {

Scorer::Scorer(const Config& cfg) : cfg_(cfg) {}

ScoredEvent Scorer::score(const DetectionResult& det) const noexcept {
    ScoredEvent result{};
    result.detection = det;

    // ---- Instant kill conditions ----
    if (det.deployer_blacklisted)
        return make_reject(result, 0.0f, "blacklisted");
    if (det.bytecode_is_scam)
        return make_reject(result, 0.0f, "scam_bytecode");
    if (!std::isnan(det.deployer_score) && det.deployer_score == 0.0f)
        return make_reject(result, 0.0f, "known_scammer");

    // ---- Weighted scoring ----
    float s = 0.0f;
    float total_weight = 0.0f;

    // Component 1: Deployer reputation
    if (!std::isnan(det.deployer_score)) {
        s += det.deployer_score * cfg_.weight_deployer_reputation;
        total_weight += cfg_.weight_deployer_reputation;
    } else {
        s += cfg_.unknown_deployer_score * cfg_.weight_deployer_reputation * 0.5f;
        total_weight += cfg_.weight_deployer_reputation * 0.5f;
    }

    // Component 2: Authority / dangerous function flags
    if (det.has_mint_authority) {
        s += 0.0f;
    } else if (!det.has_dangerous_funcs) {
        s += cfg_.weight_authority_flags;
    } else {
        s += cfg_.weight_authority_flags * 0.3f;
    }
    total_weight += cfg_.weight_authority_flags;

    // Component 3: LP lock status
    if (det.lp_locked) {
        float lock_quality = det.lp_lock_percent;
        if (det.lp_lock_duration_days >= 180)     lock_quality *= 1.0f;
        else if (det.lp_lock_duration_days >= 30)  lock_quality *= 0.8f;
        else                                        lock_quality *= 0.5f;
        s += lock_quality * cfg_.weight_lp_lock;
    }
    total_weight += cfg_.weight_lp_lock;

    // Component 4: Bytecode safety
    if (!det.bytecode_is_scam) s += cfg_.weight_bytecode_safety;
    total_weight += cfg_.weight_bytecode_safety;

    // Component 5: Context signals
    float context = 0.0f;
    if (det.tx.event_type == EventType::ADD_LIQUIDITY) {
        double bnb = double(det.tx.value_wei) / 1e18;
        if (bnb >= 5.0)      context = 1.0f;
        else if (bnb >= 1.0) context = 0.7f;
        else if (bnb >= 0.5) context = 0.4f;
        else                  context = 0.1f;
    }
    s += context * cfg_.weight_context_signals;
    total_weight += cfg_.weight_context_signals;

    // Normalize
    float final_score = (total_weight > 0.0f) ? (s / total_weight) : 0.5f;
    final_score = std::clamp(final_score, 0.0f, 1.0f);

    // ---- Decision ----
    result.final_score = final_score;
    result.decision_time = now_ns();

    if (final_score < cfg_.threshold_hard_reject) {
        result.decision = Decision::HARD_REJECT;
        result.position_pct = 0.0f;
    } else if (final_score >= cfg_.threshold_fast_pass) {
        result.decision = Decision::FAST_PASS;
        result.position_pct = cfg_.fast_pass_position_pct;
    } else {
        result.decision = Decision::FORWARD_TIER2;
        float t = (final_score - cfg_.threshold_hard_reject) /
                  (cfg_.threshold_fast_pass - cfg_.threshold_hard_reject);
        result.position_pct = t * cfg_.tier2_borderline_pct;
    }

    return result;
}

ScoredEvent Scorer::make_reject(ScoredEvent& result, float score,
                                 [[maybe_unused]] const char* reason) const noexcept {
    result.final_score = score;
    result.decision = Decision::HARD_REJECT;
    result.position_pct = 0.0f;
    result.decision_time = now_ns();
    return result;
}

} // namespace lumina
