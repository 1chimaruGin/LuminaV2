// Minimal JSON string extraction (no allocations on hot path for fixed keys).
#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace lumina::json_minimal {

std::optional<std::string_view> extract_string_value(std::string_view json, std::string_view key);
std::optional<std::string_view> extract_array_body(std::string_view json, std::string_view key);
bool extract_hex_u64(std::string_view json, std::string_view key, uint64_t& out);

} // namespace lumina::json_minimal
