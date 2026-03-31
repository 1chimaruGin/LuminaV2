// ============================================================
// Lumina BSC Tier 1 — Transaction Parser Implementation
// ============================================================
#include "lumina/pipeline/tx_parser.h"
#include <cstring>

namespace lumina {

bool TxParser::parse(const RawEvent& raw, ParsedTx& out) const noexcept {
    std::string_view json(raw.data, raw.length);
    out = {};
    out.recv_time = raw.recv_time;

    auto from_hex = extract(json, "\"from\"");
    if (!from_hex.empty()) out.from = hex_to_address(from_hex);

    auto to_hex = extract(json, "\"to\"");
    if (to_hex.empty() || to_hex == "null" || to_hex == "0x") {
        out.is_contract_creation = true;
        out.to = ZERO_ADDRESS;
    } else {
        out.to = hex_to_address(to_hex);
    }

    auto val = extract(json, "\"value\"");
    if (!val.empty()) out.value_wei = hex_to_u64(val);

    auto gas = extract(json, "\"gasPrice\"");
    if (!gas.empty()) out.gas_price = hex_to_u64(gas);

    auto input = extract(json, "\"input\"");
    if (input.size() >= 10) {
        std::string_view s = input;
        if (s.substr(0, 2) == "0x") s.remove_prefix(2);
        if (s.size() >= 8) {
            for (int i = 0; i < 4; ++i)
                out.selector[i] = hb(s[i * 2], s[i * 2 + 1]);
        }
        out.input_length = uint32_t((input.size() - 2) / 2);
    }

    auto hash = extract(json, "\"hash\"");
    if (hash.size() >= 66) {
        std::string_view h = hash;
        if (h.substr(0, 2) == "0x") h.remove_prefix(2);
        for (size_t i = 0; i < 32 && i * 2 + 1 < h.size(); ++i)
            out.tx_hash[i] = hb(h[i * 2], h[i * 2 + 1]);
    }

    out.event_type = classify(out);

    if (out.event_type == EventType::ADD_LIQUIDITY && input.size() >= 74) {
        std::string_view p = input;
        if (p.substr(0, 2) == "0x") p.remove_prefix(2);
        p.remove_prefix(8);
        if (p.size() >= 64) {
            std::string_view ah = p.substr(24, 40);
            Address a{};
            for (size_t i = 0; i < 20 && i * 2 + 1 < ah.size(); ++i)
                a[i] = hb(ah[i * 2], ah[i * 2 + 1]);
            out.token_address = a;
        }
    }
    return true;
}

EventType TxParser::classify(const ParsedTx& tx) const noexcept {
    if (tx.is_contract_creation) return EventType::CONTRACT_CREATION;
    uint32_t s = (uint32_t(tx.selector[0]) << 24) | (uint32_t(tx.selector[1]) << 16) |
                 (uint32_t(tx.selector[2]) << 8)  |  uint32_t(tx.selector[3]);
    switch (s) {
        case selectors::ADD_LIQUIDITY_ETH:
        case selectors::ADD_LIQUIDITY:
            return EventType::ADD_LIQUIDITY;
        case selectors::REMOVE_LIQ_ETH:
        case selectors::REMOVE_LIQ:
        case selectors::REMOVE_LIQ_ETH_FEE:
            return EventType::REMOVE_LIQUIDITY;
        case selectors::SWAP_EXACT_ETH_FOR_TOKENS:
        case selectors::SWAP_ETH_FOR_EXACT_TOKENS:
            return EventType::BUY;
        case selectors::SWAP_EXACT_TOKENS_FOR_ETH:
        case selectors::SWAP_TOKENS_FOR_EXACT_ETH:
        case selectors::SWAP_EXACT_TOKENS_FOR_ETH_FEE:
        case selectors::SWAP_EXACT_TOKENS_FOR_TOKENS:
        case selectors::SWAP_TOKENS_FOR_EXACT_TOKENS:
        case selectors::SWAP_EXACT_TOKENS_FOR_TOKENS_FEE:
            return EventType::SELL;
        case selectors::RENOUNCE_OWNERSHIP:
        case selectors::TRANSFER_OWNERSHIP:
            return EventType::OWNERSHIP_CHANGE;
        default:
            return EventType::UNKNOWN;
    }
}

std::string_view TxParser::extract(std::string_view json, std::string_view key) noexcept {
    auto pos = json.find(key);
    if (pos == std::string_view::npos) return {};
    pos += key.size();
    while (pos < json.size() && (json[pos] == ':' || json[pos] == ' ' || json[pos] == '\t')) ++pos;
    if (pos >= json.size()) return {};
    if (json.substr(pos, 4) == "null") return "null";
    if (json[pos] == '"') {
        ++pos;
        auto e = json.find('"', pos);
        if (e == std::string_view::npos) return {};
        return json.substr(pos, e - pos);
    }
    auto e = json.find_first_of(",}] \t\n", pos);
    if (e == std::string_view::npos) e = json.size();
    return json.substr(pos, e - pos);
}

uint8_t TxParser::hb(char hi, char lo) noexcept {
    auto n = [](char c) -> uint8_t {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return 10 + c - 'a';
        if (c >= 'A' && c <= 'F') return 10 + c - 'A';
        return 0;
    };
    return (n(hi) << 4) | n(lo);
}

uint64_t TxParser::hex_to_u64(std::string_view h) noexcept {
    if (h.substr(0, 2) == "0x") h.remove_prefix(2);
    uint64_t r = 0;
    for (char c : h) {
        r <<= 4;
        if (c >= '0' && c <= '9')      r |= (c - '0');
        else if (c >= 'a' && c <= 'f') r |= (10 + c - 'a');
        else if (c >= 'A' && c <= 'F') r |= (10 + c - 'A');
    }
    return r;
}

} // namespace lumina
