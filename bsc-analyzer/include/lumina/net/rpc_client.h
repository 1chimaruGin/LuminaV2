#pragma once
#include "lumina/core/types.h"
#include <chrono>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace lumina {

struct RpcLogEntry {
    std::string address_lower;
    std::vector<std::string> topics;
    std::string data;
    uint64_t block_number = 0;
    std::string block_hex;
    std::string tx_hash;
    uint64_t log_index = 0;
    uint64_t transaction_index = 0;
};

struct TokenManagerCurveInfo {
    uint64_t funds_wei = 0;
    uint64_t max_funds_wei = 0;
    double funds_bnb = 0.0;
    double max_funds_bnb = 0.0;
    double last_price_raw = 0.0;  // raw lastPrice from contract
    bool is_bnb_quote = true;     // false if BEP20 stablecoin quote
    bool liquidity_added = false;
    bool valid = false;
};

// One item in a JSON-RPC batch request: {to, calldata, block_hex}
struct BatchEthCallItem {
    std::string to_address;
    std::string calldata;
    std::string block_hex;
};

// Result for one item in the batch — either raw hex or failure
struct BatchEthCallResult {
    bool ok = false;
    std::string result_hex; // without 0x prefix
};

// Thread-safe HTTP JSON-RPC (libcurl). Uses primary URL with optional failover.
class BscRpcClient {
public:
    BscRpcClient(std::string primary_http_rpc, std::string fallback_http_rpc = {});

    const std::string& primary_url() const { return primary_; }
    const std::string& fallback_url() const { return fallback_; }

    bool eth_block_number(uint64_t& out_block);

    // eth_getLogs with topic0 filter on manager; block range inclusive hex strings e.g. "0x123"
    bool eth_get_logs_manager(const std::string& manager_address_lower,
                              const std::string& topic0_hex_lower,
                              const std::string& from_block_hex,
                              const std::string& to_block_hex,
                              std::vector<RpcLogEntry>& out);

    // OR of multiple topic0 values (for current + legacy event signatures)
    bool eth_get_logs_manager(const std::string& manager_address_lower,
                              const std::vector<std::string>& topic0_or,
                              const std::string& from_block_hex,
                              const std::string& to_block_hex,
                              std::vector<RpcLogEntry>& out);

    // TokenCreate (legacy indexed layout): topic0 OR-set, topic1=null, topic2=indexed token (32-byte hex).
    bool eth_get_logs_manager_topic0_or_and_topic2(
        const std::string& manager_address_lower,
        const std::vector<std::string>& topic0_hex_lower_or,
        const std::string& topic2_hex_lower,
        const std::string& from_block_hex,
        const std::string& to_block_hex,
        std::vector<RpcLogEntry>& out);

    // Transfers for many token contracts in one block (address list JSON array)
    bool eth_get_logs_transfers_block(const std::vector<Address>& tokens,
                                      const std::string& block_hex,
                                      std::vector<RpcLogEntry>& out);

    // Generic eth_getLogs: topic0 fixed, topic1 null, topic2 = OR of addresses.
    // No address filter (searches all contracts). For detecting ERC20 Transfers to wallets.
    bool eth_get_logs_transfer_to(const std::string& topic0_hex,
                                  const std::vector<std::string>& to_addresses_padded,
                                  const std::string& from_block_hex,
                                  const std::string& to_block_hex,
                                  std::vector<RpcLogEntry>& out);

    // Get block timestamp (unix seconds) via eth_getBlockByNumber
    bool eth_get_block_timestamp(const std::string& block_hex, uint64_t& out_timestamp);

    bool eth_get_token_info_curve(const Address& token, TokenManagerCurveInfo& out);

    // Same as above but at a specific block (hex string, e.g. "0x123"). Falls back to "latest" on failure.
    bool eth_get_token_info_curve_at_block(const Address& token, const std::string& block_hex,
                                           TokenManagerCurveInfo& out);

    // Transfer logs for a SPECIFIC token contract to KOL wallets. For finding first KOL buy per token.
    bool eth_get_logs_token_transfer_to(const std::string& token_address_lower,
                                        const std::string& topic0_hex,
                                        const std::vector<std::string>& to_addresses_padded,
                                        const std::string& from_block_hex,
                                        const std::string& to_block_hex,
                                        std::vector<RpcLogEntry>& out);

    // All ERC20 Transfer logs for one token in [from_block, to_block] (topic0 only).
    bool eth_get_logs_token_transfers_all(const std::string& token_address_lower,
                                          const std::string& topic0_hex_lower,
                                          const std::string& from_block_hex,
                                          const std::string& to_block_hex,
                                          std::vector<RpcLogEntry>& out);

    // Generic eth_call returning raw hex result (no 0x prefix). block_hex = "latest" or "0x123".
    bool eth_call_raw(const std::string& to_address, const std::string& calldata,
                      const std::string& block_hex, std::string& result_hex_out);

    // Batched eth_call: send N calls in a single HTTP round-trip.
    // Returns results in same order as items. Max batch size capped at 50.
    bool batch_eth_call(const std::vector<BatchEthCallItem>& items,
                        std::vector<BatchEthCallResult>& results);

    // Batched getTokenInfo: N tokens at N (possibly different) blocks in one HTTP request.
    // Returns decoded curve info for each, in order. Invalid entries have .valid = false.
    bool batch_get_token_info_curve(const std::vector<std::pair<Address, std::string>>& token_block_pairs,
                                    std::vector<TokenManagerCurveInfo>& results);

    // Rate limit: minimum interval between getTokenInfo calls (default 250ms)
    void set_min_token_info_interval(std::chrono::milliseconds ms) { min_ti_ = ms; }

    static bool parse_logs_result(std::string_view json, std::vector<RpcLogEntry>& out);

private:
    bool post_json(const std::string& body, std::string& response_out);
    static bool decode_get_token_info_return(std::string_view result_hex, TokenManagerCurveInfo& out);
    static std::vector<std::string> split_batch_response(const std::string& response, size_t expected);

    std::string primary_;
    std::string fallback_;
    std::mutex mutex_;
    std::chrono::steady_clock::time_point last_ti_{};
    std::chrono::milliseconds min_ti_{250};
};

} // namespace lumina
