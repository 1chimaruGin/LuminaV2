#include "lumina/fourmeme/token_create_abi.h"
#include <cctype>
#include <cstdint>
#include <cstring>
#include <vector>

namespace lumina::fourmeme {

static bool hex_nibble(char c, uint8_t& out) {
    if (c >= '0' && c <= '9') { out = static_cast<uint8_t>(c - '0'); return true; }
    if (c >= 'a' && c <= 'f') { out = static_cast<uint8_t>(10 + c - 'a'); return true; }
    if (c >= 'A' && c <= 'F') { out = static_cast<uint8_t>(10 + c - 'A'); return true; }
    return false;
}

static bool hex_to_bytes(std::string_view hex, std::vector<uint8_t>& out) {
    out.clear();
    if (hex.size() >= 2 && hex[0] == '0' && (hex[1] == 'x' || hex[1] == 'X')) hex.remove_prefix(2);
    if (hex.size() % 2) return false;
    out.reserve(hex.size() / 2);
    for (size_t i = 0; i < hex.size(); i += 2) {
        uint8_t hi{}, lo{};
        if (!hex_nibble(hex[i], hi) || !hex_nibble(hex[i + 1], lo)) return false;
        out.push_back(static_cast<uint8_t>((hi << 4) | lo));
    }
    return true;
}

static size_t read_u256_be32(const uint8_t* p) {
    size_t v = 0;
    for (int i = 0; i < 32; ++i) v = (v << 8) | p[i];
    return v;
}

static bool read_abi_string(const std::vector<uint8_t>& buf, size_t offset,
                            std::string& s, size_t max_len = 8192) {
    s.clear();
    if (offset + 32 > buf.size()) return false;
    size_t len = read_u256_be32(buf.data() + offset);
    if (len > max_len || offset + 32 + len > buf.size()) return false;
    s.assign(reinterpret_cast<const char*>(buf.data() + offset + 32), len);
    return true;
}

static void extract_address(const uint8_t* word32, Address& out) {
    std::memcpy(out.data(), word32 + 12, 20);
}

// Current ABI — all fields in data, no indexed topics.
// Layout: creator(addr) | token(addr) | requestId(u256) | off_name | off_symbol | totalSupply | launchTime | launchFee
bool decode_token_create_data_v2(std::string_view data_hex,
                                 Address& creator_out, Address& token_out,
                                 std::string& name_out, std::string& symbol_out) {
    name_out.clear();
    symbol_out.clear();
    std::vector<uint8_t> raw;
    if (!hex_to_bytes(data_hex, raw)) return false;
    if (raw.size() < 32 * 8) return false;
    extract_address(raw.data(), creator_out);
    extract_address(raw.data() + 32, token_out);
    // word[3] = offset to name, word[4] = offset to symbol
    size_t off_name = read_u256_be32(raw.data() + 3 * 32);
    size_t off_sym  = read_u256_be32(raw.data() + 4 * 32);
    if (off_name >= raw.size() || off_sym >= raw.size()) return false;
    if (!read_abi_string(raw, off_name, name_out)) return false;
    if (!read_abi_string(raw, off_sym, symbol_out)) return false;
    return true;
}

// Legacy ABI — creator+token were indexed topics; data starts with string offsets.
bool decode_token_create_data_legacy(std::string_view data_hex,
                                     std::string& name_out, std::string& symbol_out) {
    name_out.clear();
    symbol_out.clear();
    std::vector<uint8_t> raw;
    if (!hex_to_bytes(data_hex, raw)) return false;
    if (raw.size() < 32 * 6) return false;
    size_t off_name = read_u256_be32(raw.data());
    size_t off_sym  = read_u256_be32(raw.data() + 32);
    if (off_name >= raw.size() || off_sym >= raw.size()) return false;
    if (!read_abi_string(raw, off_name, name_out)) return false;
    if (!read_abi_string(raw, off_sym, symbol_out)) return false;
    return true;
}

} // namespace lumina::fourmeme
