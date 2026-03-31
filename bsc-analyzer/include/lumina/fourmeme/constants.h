// Four.meme BSC — verified event topics (eth_hash keccak256) and contract addresses.
// TokenCreate signature: TokenCreate(address,address,string,string,uint256,uint256,uint256,uint256)
// topic1 = creator, topic2 = token (both indexed). Data holds name, symbol, uint256×4 (ABI-encoded).
#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <string_view>

namespace lumina::fourmeme {

inline constexpr const char* PROXY_MANAGER = "0x5c952063c7fc8610FFDB798152D69F0B9550762b";
inline constexpr const char* TOKEN_MANAGER_HELPER3 = "0xF251F83e40a78868FcfA3FA4599Dad6494E46034";

// keccak256("TokenCreate(address,address,uint256,string,string,uint256,uint256,uint256)")
// Current ABI (2025-Q4+): creator/token NOT indexed, requestId added before strings.
inline constexpr const char* TOPIC_TOKEN_CREATE =
    "0x396d5e902b675b032348d3d2e9517ee8f0c4a926603fbc075d3d282ff00cad20";

// Legacy ABI: TokenCreate(address indexed creator, address indexed token, string, string, uint256×4)
inline constexpr const char* TOPIC_TOKEN_CREATE_LEGACY =
    "0x589f95642efe902cf4021543f39840e7f9cecd61430e908f946dda4ffef3a29f";

// Legacy / alternate factory event (very old)
inline constexpr const char* TOPIC_TOKEN_CREATED_ALT =
    "0xb7d8fd3c9d56d12c15c8e139bc4e6febd6ad2349b3ebe6a1a91c0a9e7797710d";

// TokenPurchase(address token, address buyer, uint256 requestId, uint256 tokensOut,
//               uint256 bnbIn, uint256 fee, uint256 tokenReserve, uint256 totalFunds)
inline constexpr const char* TOPIC_TOKEN_PURCHASE =
    "0x7db52723a3b2cdd6164364b3b766e65e540d7be48ffa89582956d8eaebe62942";

// TokenSale(address token, address seller, uint256 requestId, uint256 tokensIn,
//           uint256 bnbOut, uint256 fee, uint256 tokenReserve, uint256 totalFunds)
inline constexpr const char* TOPIC_TOKEN_SALE =
    "0x0a5575b3648bae2210cee56bf33254cc1ddfbc7bf637c0af2ac18b14fb1bae19";

// Transfer(address,address,uint256)
inline constexpr const char* TOPIC_ERC20_TRANSFER =
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";

// getTokenInfo(address) selector
inline constexpr const char* SELECTOR_GET_TOKEN_INFO = "0x1f69565f";

// X Mode: avoid entries before this block offset from launch (plan default)
inline constexpr uint32_t XMODE_MIN_BLOCK_OFFSET = 6;

bool hex_to_bytes_32(std::string_view hex, std::array<uint8_t, 32>& out);
bool topic_to_address(std::string_view topic_hex, std::array<uint8_t, 20>& out);

// https://.../path → wss://host/path (QuickNode / Alchemy)
std::string http_rpc_to_ws_url(std::string_view http_url);

} // namespace lumina::fourmeme
