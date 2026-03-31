#pragma once
#include "lumina/core/types.h"
#include <string>
#include <string_view>

namespace lumina::fourmeme {

// Current ABI: TokenCreate(address creator, address token, uint256 requestId,
//                           string name, string symbol, uint256 totalSupply,
//                           uint256 launchTime, uint256 launchFee)
// All params in `data` (none indexed).
bool decode_token_create_data_v2(std::string_view data_hex,
                                 Address& creator_out, Address& token_out,
                                 std::string& name_out, std::string& symbol_out);

// Legacy ABI: creator and token were indexed in topics[1..2]; data held only strings + 4 uint256.
bool decode_token_create_data_legacy(std::string_view data_hex,
                                     std::string& name_out, std::string& symbol_out);

} // namespace lumina::fourmeme
