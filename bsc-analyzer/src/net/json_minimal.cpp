#include "lumina/net/json_minimal.h"

namespace lumina::json_minimal {

std::optional<std::string_view> extract_string_value(std::string_view json, std::string_view key) {
    std::string needle;
    needle.push_back('"');
    needle.append(key);
    needle += "\":";
    auto pos = json.find(needle);
    if (pos == std::string_view::npos) return std::nullopt;
    pos += needle.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
    if (pos >= json.size()) return std::nullopt;
    if (json[pos] == '"') {
        ++pos;
        auto end = json.find('"', pos);
        if (end == std::string_view::npos) return std::nullopt;
        return json.substr(pos, end - pos);
    }
    auto end = json.find_first_of(",}]\n\r", pos);
    if (end == std::string_view::npos) end = json.size();
    return json.substr(pos, end - pos);
}

std::optional<std::string_view> extract_array_body(std::string_view json, std::string_view key) {
    std::string needle;
    needle.push_back('"');
    needle.append(key);
    needle += "\":";
    auto pos = json.find(needle);
    if (pos == std::string_view::npos) return std::nullopt;
    pos += needle.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
    if (pos >= json.size() || json[pos] != '[') return std::nullopt;
    ++pos;
    int depth = 1;
    size_t start = pos;
    for (; pos < json.size(); ++pos) {
        if (json[pos] == '[') ++depth;
        else if (json[pos] == ']') {
            --depth;
            if (depth == 0) return json.substr(start, pos - start);
        }
    }
    return std::nullopt;
}

static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + c - 'a';
    if (c >= 'A' && c <= 'F') return 10 + c - 'A';
    return -1;
}

bool extract_hex_u64(std::string_view json, std::string_view key, uint64_t& out) {
    auto v = extract_string_value(json, key);
    if (!v) return false;
    std::string_view h = *v;
    if (h.size() >= 2 && h[0] == '0' && (h[1] == 'x' || h[1] == 'X')) h.remove_prefix(2);
    uint64_t r = 0;
    for (char c : h) {
        int d = hex_digit(c);
        if (d < 0) return false;
        r = (r << 4) | static_cast<uint64_t>(d);
    }
    out = r;
    return true;
}

} // namespace lumina::json_minimal
