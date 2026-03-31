// ============================================================
// Lumina BSC Tier 1 — Transaction Parser
// ============================================================
// Zero-copy JSON parser for BSC pending transactions.
// Extracts from/to/value/input and classifies event type:
//   ADD_LIQUIDITY, REMOVE_LIQUIDITY, BUY, SELL,
//   CONTRACT_CREATION, OWNERSHIP_CHANGE, UNKNOWN.
//
// Identifies PancakeSwap Router V2 method selectors.
// ~400 ns/parse, 2.4M parses/sec.
// ============================================================
#pragma once
#include "lumina/core/types.h"

namespace lumina {

class TxParser {
public:
    bool parse(const RawEvent& raw, ParsedTx& out) const noexcept;

private:
    EventType classify(const ParsedTx& tx) const noexcept;

    static std::string_view extract(std::string_view json, std::string_view key) noexcept;
    static uint8_t  hb(char hi, char lo) noexcept;
    static uint64_t hex_to_u64(std::string_view h) noexcept;
};

} // namespace lumina
