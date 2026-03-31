#include "lumina/fourmeme/constants.h"
#include "lumina/core/types.h"
#include <algorithm>
#include <cctype>

namespace lumina::fourmeme {

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + c - 'a';
    if (c >= 'A' && c <= 'F') return 10 + c - 'A';
    return -1;
}

bool hex_to_bytes_32(std::string_view hex, std::array<uint8_t, 32>& out) {
    std::string_view h = hex;
    if (h.size() >= 2 && h[0] == '0' && (h[1] == 'x' || h[1] == 'X')) h.remove_prefix(2);
    if (h.size() < 64) return false;
    for (size_t i = 0; i < 32; ++i) {
        int hi = hex_nibble(h[i * 2]);
        int lo = hex_nibble(h[i * 2 + 1]);
        if (hi < 0 || lo < 0) return false;
        out[i] = static_cast<uint8_t>((hi << 4) | lo);
    }
    return true;
}

bool topic_to_address(std::string_view topic_hex, std::array<uint8_t, 20>& out) {
    std::array<uint8_t, 32> w{};
    if (!hex_to_bytes_32(topic_hex, w)) return false;
    // Last 20 bytes of 32-byte topic word
    for (size_t i = 0; i < 20; ++i) out[i] = w[12 + i];
    return true;
}

std::string http_rpc_to_ws_url(std::string_view http_url) {
    std::string u(http_url);
    auto pos = u.find("://");
    if (pos == std::string::npos) return u;
    std::string scheme = u.substr(0, pos);
    std::transform(scheme.begin(), scheme.end(), scheme.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::string rest = u.substr(pos + 3);
    if (scheme == "https")
        return "wss://" + rest;
    if (scheme == "http")
        return "ws://" + rest;
    return u;
}

} // namespace lumina::fourmeme
