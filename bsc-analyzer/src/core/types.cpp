// ============================================================
// Lumina BSC Tier 1 — Core Types Implementation
// ============================================================
#include "lumina/core/types.h"

namespace lumina {

Timestamp now_ns() {
    return static_cast<Timestamp>(
        std::chrono::steady_clock::now().time_since_epoch().count());
}

bool is_zero(const Address& a) {
    return a == ZERO_ADDRESS;
}

Address hex_to_address(std::string_view hex) {
    Address addr{};
    if (hex.size() >= 2 && hex[0] == '0' && hex[1] == 'x') hex.remove_prefix(2);
    auto nib = [](char c) -> uint8_t {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return 10 + c - 'a';
        if (c >= 'A' && c <= 'F') return 10 + c - 'A';
        return 0;
    };
    for (size_t i = 0; i < 20 && i * 2 + 1 < hex.size(); ++i)
        addr[i] = (nib(hex[i * 2]) << 4) | nib(hex[i * 2 + 1]);
    return addr;
}

std::string address_to_hex(const Address& a) {
    static const char hx[] = "0123456789abcdef";
    std::string r = "0x";
    r.reserve(42);
    for (uint8_t b : a) { r += hx[b >> 4]; r += hx[b & 0xf]; }
    return r;
}

const char* event_type_str(EventType t) {
    switch (t) {
        case EventType::UNKNOWN:            return "UNKNOWN";
        case EventType::CONTRACT_CREATION:  return "CONTRACT_CREATION";
        case EventType::ADD_LIQUIDITY:      return "ADD_LIQUIDITY";
        case EventType::REMOVE_LIQUIDITY:   return "REMOVE_LIQUIDITY";
        case EventType::BUY:                return "BUY";
        case EventType::SELL:               return "SELL";
        case EventType::OWNERSHIP_CHANGE:   return "OWNERSHIP_CHANGE";
        case EventType::APPROVAL:           return "APPROVAL";
    }
    return "UNKNOWN";
}

void RawEvent::set(const char* src, uint32_t len) {
    length = std::min(len, uint32_t(sizeof(data) - 1));
    std::memcpy(data, src, length);
    data[length] = '\0';
    recv_time = now_ns();
}

bool  DeployerReputation::is_scammer() const { return flags & KNOWN_SCAMMER; }
bool  DeployerReputation::is_legit()   const { return flags & KNOWN_LEGIT; }
bool  DeployerReputation::is_serial()  const { return flags & SERIAL_DEPLOYER; }

float DeployerReputation::compute_score() const {
    // Score from -100 to +100, matching Python builder formula
    if (total_deploys == 0) return 0.0f;
    
    float s = 0.0f;
    
    // Base score from success rate (0 to 50 points)
    s += success_rate * 50.0f;
    
    // Penalty for rugs (-100 points max)
    s -= rug_rate * 100.0f;
    
    // Penalty for honeypots (-50 points max)
    float honeypot_rate = float(honeypot_count) / float(total_deploys);
    s -= honeypot_rate * 50.0f;
    
    // Experience bonus (+10 if deployed 5+ tokens)
    if (total_deploys >= 5) s += 10.0f;
    
    // Longevity bonus (+10 if avg lifespan > 24h)
    if (avg_lifespan_hours > 24.0f) s += 10.0f;
    
    return std::clamp(s, -100.0f, 100.0f);
}

const char* decision_str(Decision d) {
    switch (d) {
        case Decision::HARD_REJECT:   return "HARD_REJECT";
        case Decision::FORWARD_TIER2: return "FORWARD_TIER2";
        case Decision::FAST_PASS:     return "FAST_PASS";
    }
    return "UNKNOWN";
}

uint64_t ScoredEvent::latency_ns() const {
    return decision_time - detection.tx.recv_time;
}

size_t AddressHash::operator()(const Address& a) const noexcept {
    size_t h = 14695981039346656037ULL;
    for (uint8_t b : a) { h ^= b; h *= 1099511628211ULL; }
    return h;
}

size_t Hash32Hash::operator()(const Hash32& h) const noexcept {
    size_t r;
    std::memcpy(&r, h.data(), sizeof(r));
    return r;
}

} // namespace lumina
