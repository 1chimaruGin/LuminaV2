// ============================================================
// Lumina BSC Tier 1 — Honeypot Checker
// ============================================================
// Detects honeypot tokens by checking:
//   - Buy/sell tax via contract calls
//   - Transfer restrictions
//   - Ownership renouncement status
// Uses external APIs (GoPlus) for comprehensive checks.
// ============================================================
#pragma once
#include "lumina/core/types.h"
#include <string>
#include <optional>

namespace lumina {

struct HoneypotResult {
    bool is_honeypot;
    double buy_tax;
    double sell_tax;
    bool can_buy;
    bool can_sell;
    bool owner_renounced;
    std::string error;
};

class HoneypotChecker {
public:
    explicit HoneypotChecker(const std::string& api_key = "");
    
    std::optional<HoneypotResult> check_token(const Address& token_addr) const;
    
private:
    std::string api_key_;
    std::string call_api(const std::string& url) const;
    HoneypotResult parse_response(const std::string& json) const;
};

} // namespace lumina
