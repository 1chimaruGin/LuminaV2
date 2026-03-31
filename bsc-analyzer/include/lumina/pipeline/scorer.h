// ============================================================
// Lumina BSC Tier 1 — Weighted Scorer & Decision Engine
// ============================================================
// Converts DetectionResult flags into a single 0.0–1.0 score
// using configurable weights, then maps to a decision:
//   HARD_REJECT   – score < 0.15
//   FAST_PASS     – score >= 0.90
//   FORWARD_TIER2 – everything else
//
// Pure computation — no I/O, no locks, no allocations.
// ============================================================
#pragma once
#include "lumina/core/types.h"
#include "lumina/core/config.h"

namespace lumina {

class Scorer {
public:
    explicit Scorer(const Config& cfg);
    ScoredEvent score(const DetectionResult& det) const noexcept;

private:
    ScoredEvent make_reject(ScoredEvent& result, float score, const char* reason) const noexcept;
    const Config& cfg_;
};

} // namespace lumina
