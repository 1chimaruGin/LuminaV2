// ============================================================
// Lumina BSC Tier 1 — Heuristic Detector
// ============================================================
// Runs 5 non-blocking security checks on each parsed transaction:
//   1. Deployer reputation lookup (double-buffered map)
//   2. Blacklist bloom filter check (from + to + token)
//   3. Bytecode pattern matching (contract creation only)
//   4. Context signals (low liq, remove liq = rug)
//   5. LP lock analysis (PinkLock / UNCX / burn address)
//
// All checks are read-only against pre-built data stores.
// No allocations, no locks on the hot path.
// ============================================================
#pragma once
#include "lumina/core/types.h"
#include "lumina/core/config.h"
#include "lumina/data/deployer_db.h"

namespace lumina {

class Detector {
public:
    Detector(const Config& cfg, const DeployerDB& deployers,
             const BlacklistDB& blacklist, const BytecodeDB& bytecodes);

    DetectionResult detect(const ParsedTx& tx) const noexcept;

private:
    void run_deployer_check(const ParsedTx& tx, DetectionResult& r) const noexcept;
    void run_blacklist_check(const ParsedTx& tx, DetectionResult& r) const noexcept;
    void run_bytecode_check(const ParsedTx& tx, DetectionResult& r) const noexcept;
    void run_context_check(const ParsedTx& tx, DetectionResult& r) const noexcept;
    void run_liquidity_check(const ParsedTx& tx, DetectionResult& r) const noexcept;

    const Config& cfg_;
    const DeployerDB& deployers_;
    const BlacklistDB& blacklist_;
    const BytecodeDB& bytecodes_;
};

} // namespace lumina
