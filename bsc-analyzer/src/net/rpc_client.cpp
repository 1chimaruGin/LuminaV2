#include "lumina/net/rpc_client.h"
#include "lumina/fourmeme/constants.h"
#include "lumina/net/json_minimal.h"
#include "lumina/tracking/logger.h"
#include <curl/curl.h>
#include <algorithm>
#include <sstream>
#include <cctype>
#include <thread>

namespace lumina {

static size_t curl_write_cb(char* ptr, size_t size, size_t nmemb, void* userdata) {
    auto* s = static_cast<std::string*>(userdata);
    s->append(ptr, size * nmemb);
    return size * nmemb;
}

BscRpcClient::BscRpcClient(std::string primary_http_rpc, std::string fallback_http_rpc)
    : primary_(std::move(primary_http_rpc)), fallback_(std::move(fallback_http_rpc)) {}

bool BscRpcClient::post_json(const std::string& body, std::string& response_out) {
    std::lock_guard<std::mutex> lock(mutex_);
    CURL* curl = curl_easy_init();
    if (!curl) return false;

    auto try_url = [&](const std::string& url) -> bool {
        response_out.clear();
        struct curl_slist* hdr = nullptr;
        hdr = curl_slist_append(hdr, "Content-Type: application/json");
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdr);
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response_out);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);
        curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
        CURLcode res = curl_easy_perform(curl);
        curl_slist_free_all(hdr);
        return res == CURLE_OK && !response_out.empty();
    };

    bool ok = try_url(primary_);
    if (!ok && !fallback_.empty()) ok = try_url(fallback_);
    curl_easy_cleanup(curl);
    return ok;
}

bool BscRpcClient::eth_block_number(uint64_t& out_block) {
    std::string body = R"({"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]})";
    std::string resp;
    if (!post_json(body, resp)) return false;
    return json_minimal::extract_hex_u64(resp, "result", out_block);
}

static std::string addr_to_json_hex(const Address& a) {
    return address_to_hex(a);
}

bool BscRpcClient::eth_get_logs_manager(const std::string& manager_address_lower,
                                        const std::string& topic0_hex_lower,
                                        const std::string& from_block_hex,
                                        const std::string& to_block_hex,
                                        std::vector<RpcLogEntry>& out) {
    out.clear();
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{)"
        << R"("address":")" << manager_address_lower << R"(",)"
        << R"("topics":[")" << topic0_hex_lower << R"("],)"
        << R"("fromBlock":")" << from_block_hex << R"(",)"
        << R"("toBlock":")" << to_block_hex << R"(")"
        << R"(}]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    if (resp.find("\"error\"") != std::string::npos) {
        LOG_WRN("eth_getLogs error: %s", resp.substr(0, 200).c_str());
        return false;
    }
    return parse_logs_result(resp, out);
}

bool BscRpcClient::eth_get_logs_manager(const std::string& manager_address_lower,
                                        const std::vector<std::string>& topic0_or,
                                        const std::string& from_block_hex,
                                        const std::string& to_block_hex,
                                        std::vector<RpcLogEntry>& out) {
    if (topic0_or.size() == 1) return eth_get_logs_manager(manager_address_lower, topic0_or[0], from_block_hex, to_block_hex, out);
    out.clear();
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{)"
        << R"("address":")" << manager_address_lower << R"(",)"
        << R"("topics":[[)";
    for (size_t i = 0; i < topic0_or.size(); ++i) {
        if (i) oss << ',';
        oss << '"' << topic0_or[i] << '"';
    }
    oss << R"(]],)"
        << R"("fromBlock":")" << from_block_hex << R"(",)"
        << R"("toBlock":")" << to_block_hex << R"(")"
        << R"(}]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    if (resp.find("\"error\"") != std::string::npos) {
        LOG_WRN("eth_getLogs error: %s", resp.substr(0, 200).c_str());
        return false;
    }
    return parse_logs_result(resp, out);
}

bool BscRpcClient::eth_get_logs_manager_topic0_or_and_topic2(
    const std::string& manager_address_lower,
    const std::vector<std::string>& topic0_hex_lower_or,
    const std::string& topic2_hex_lower,
    const std::string& from_block_hex,
    const std::string& to_block_hex,
    std::vector<RpcLogEntry>& out) {
    out.clear();
    if (topic0_hex_lower_or.empty()) return true;
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{)"
        << R"("address":")" << manager_address_lower << R"(",)"
        << R"("topics":[[)";
    for (size_t i = 0; i < topic0_hex_lower_or.size(); ++i) {
        if (i) oss << ',';
        oss << '"' << topic0_hex_lower_or[i] << '"';
    }
    oss << R"(],null,")" << topic2_hex_lower << R"("],)"
        << R"("fromBlock":")" << from_block_hex << R"(",)"
        << R"("toBlock":")" << to_block_hex << R"(")"
        << R"(}]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    if (resp.find("\"error\"") != std::string::npos) {
        LOG_WRN("eth_getLogs topic2 error: %s", resp.substr(0, 200).c_str());
        return false;
    }
    return parse_logs_result(resp, out);
}

bool BscRpcClient::eth_get_logs_transfer_to(const std::string& topic0_hex,
                                            const std::vector<std::string>& to_addresses_padded,
                                            const std::string& from_block_hex,
                                            const std::string& to_block_hex,
                                            std::vector<RpcLogEntry>& out) {
    out.clear();
    if (to_addresses_padded.empty()) return true;
    // topics: [topic0, null, [addr1, addr2, ...]]
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{)"
        << R"("topics":[")" << topic0_hex << R"(",null,[)";
    for (size_t i = 0; i < to_addresses_padded.size(); ++i) {
        if (i) oss << ',';
        oss << '"' << to_addresses_padded[i] << '"';
    }
    oss << R"(]],)"
        << R"("fromBlock":")" << from_block_hex << R"(",)"
        << R"("toBlock":")" << to_block_hex << R"(")"
        << R"(}]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    if (resp.find("\"error\"") != std::string::npos) {
        LOG_WRN("eth_getLogs transfer_to error: %s", resp.substr(0, 200).c_str());
        return false;
    }
    return parse_logs_result(resp, out);
}

bool BscRpcClient::eth_get_logs_token_transfer_to(const std::string& token_address_lower,
                                                  const std::string& topic0_hex,
                                                  const std::vector<std::string>& to_addresses_padded,
                                                  const std::string& from_block_hex,
                                                  const std::string& to_block_hex,
                                                  std::vector<RpcLogEntry>& out) {
    out.clear();
    if (to_addresses_padded.empty()) return true;
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{)"
        << R"("address":")" << token_address_lower << R"(",)"
        << R"("topics":[")" << topic0_hex << R"(",null,[)";
    for (size_t i = 0; i < to_addresses_padded.size(); ++i) {
        if (i) oss << ',';
        oss << '"' << to_addresses_padded[i] << '"';
    }
    oss << R"(]],)"
        << R"("fromBlock":")" << from_block_hex << R"(",)"
        << R"("toBlock":")" << to_block_hex << R"(")"
        << R"(}]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    if (resp.find("\"error\"") != std::string::npos) {
        LOG_WRN("eth_getLogs token_transfer_to error: %s", resp.substr(0, 200).c_str());
        return false;
    }
    return parse_logs_result(resp, out);
}

bool BscRpcClient::eth_get_logs_token_transfers_all(const std::string& token_address_lower,
                                                    const std::string& topic0_hex_lower,
                                                    const std::string& from_block_hex,
                                                    const std::string& to_block_hex,
                                                    std::vector<RpcLogEntry>& out) {
    out.clear();
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{)"
        << R"("address":")" << token_address_lower << R"(",)"
        << R"("topics":[")" << topic0_hex_lower << R"("],)"
        << R"("fromBlock":")" << from_block_hex << R"(",)"
        << R"("toBlock":")" << to_block_hex << R"(")"
        << R"(}]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    if (resp.find("\"error\"") != std::string::npos) {
        LOG_WRN("eth_getLogs token_transfers_all error: %s", resp.substr(0, 200).c_str());
        return false;
    }
    return parse_logs_result(resp, out);
}

bool BscRpcClient::eth_get_logs_transfers_block(const std::vector<Address>& tokens,
                                                const std::string& block_hex,
                                                std::vector<RpcLogEntry>& out) {
    out.clear();
    if (tokens.empty()) return true;
    std::ostringstream addr_arr;
    addr_arr << "[";
    for (size_t i = 0; i < tokens.size(); ++i) {
        if (i) addr_arr << ',';
        std::string h = addr_to_json_hex(tokens[i]);
        std::transform(h.begin(), h.end(), h.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        addr_arr << '"' << h << '"';
    }
    addr_arr << "]";
    std::ostringstream oss;
    std::string xfer = fourmeme::TOPIC_ERC20_TRANSFER;
    std::transform(xfer.begin(), xfer.end(), xfer.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getLogs","params":[{)"
        << R"("address":)" << addr_arr.str() << ','
        << R"("topics":[")" << xfer << R"("],)"
        << R"("fromBlock":")" << block_hex << R"(",)"
        << R"("toBlock":")" << block_hex << R"(")"
        << R"(}]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    if (resp.find("\"error\"") != std::string::npos) return false;
    return parse_logs_result(resp, out);
}

bool BscRpcClient::eth_call_raw(const std::string& to_address, const std::string& calldata,
                                const std::string& block_hex, std::string& result_hex_out) {
    result_hex_out.clear();
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{"to":")"
        << to_address << R"(","data":")" << calldata << R"("},")" << block_hex << R"("]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    auto pos = resp.find("\"result\":\"0x");
    if (pos == std::string::npos) return false;
    pos += 12; // skip past "result":"0x
    auto end = resp.find('"', pos);
    if (end == std::string::npos) return false;
    result_hex_out = resp.substr(pos, end - pos);
    return !result_hex_out.empty();
}

bool BscRpcClient::eth_get_block_timestamp(const std::string& block_hex, uint64_t& out_timestamp) {
    out_timestamp = 0;
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":[")"
        << block_hex << R"(", false]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    return json_minimal::extract_hex_u64(resp, "timestamp", out_timestamp);
}

// Heuristic decode: many helper ABIs end with (…, uint256 funds, uint256 maxFunds, bool liquidityAdded).
bool BscRpcClient::decode_get_token_info_return(std::string_view hex, TokenManagerCurveInfo& out) {
    out = {};
    std::string_view h = hex;
    if (h.size() >= 2 && h[0] == '0' && (h[1] == 'x' || h[1] == 'X')) h.remove_prefix(2);
    if (h.size() < 64 * 3) return false;

    auto hn = [](char x) -> int {
        if (x >= '0' && x <= '9') return x - '0';
        if (x >= 'a' && x <= 'f') return 10 + x - 'a';
        if (x >= 'A' && x <= 'F') return 10 + x - 'A';
        return 0;
    };

    size_t total_words = h.size() / 64;

    // Read low 8 bytes of a word as uint64_t
    auto word64_from_end = [&](size_t word_idx_from_end) -> uint64_t {
        if (word_idx_from_end >= total_words) return 0;
        size_t wi = total_words - 1 - word_idx_from_end;
        std::string_view w = h.substr(wi * 64, 64);
        uint64_t v = 0;
        for (size_t i = 0; i < 8; ++i) {
            char c = w[48 + i * 2];
            char d = w[48 + i * 2 + 1];
            v = (v << 8) | static_cast<uint64_t>((hn(c) << 4) | hn(d));
        }
        return v;
    };

    // Read full 32 bytes as double (handles values > uint64 max, e.g. 5000 BNB)
    auto word_double_from_end = [&](size_t word_idx_from_end) -> double {
        if (word_idx_from_end >= total_words) return 0.0;
        size_t wi = total_words - 1 - word_idx_from_end;
        std::string_view w = h.substr(wi * 64, 64);
        double v = 0.0;
        for (size_t i = 0; i < 64; ++i) {
            v = v * 16.0 + hn(w[i]);
        }
        return v;
    };

    uint64_t liq_word = word64_from_end(0);
    out.liquidity_added = (liq_word != 0);
    out.funds_wei = word64_from_end(2);
    out.max_funds_wei = word64_from_end(1);
    out.funds_bnb = word_double_from_end(2) / 1e18;
    out.max_funds_bnb = word_double_from_end(1) / 1e18;

    // Parse lastPrice (word[3]) and quote (word[2]) for FDV calculation
    // getTokenInfo returns: version, tokenManager, quote, lastPrice, ...
    // lastPrice is at absolute word index 3, quote at index 2
    if (total_words >= 12) {
        // Read absolute word indices (forward from start)
        auto word_double_abs = [&](size_t wi) -> double {
            if (wi >= total_words) return 0.0;
            std::string_view w = h.substr(wi * 64, 64);
            double v = 0.0;
            for (size_t i = 0; i < 64; ++i)
                v = v * 16.0 + hn(w[i]);
            return v;
        };
        out.last_price_raw = word_double_abs(3);
        // quote = word[2]; check if all zeros (BNB) or non-zero (BEP20)
        std::string_view quote_word = h.substr(2 * 64, 64);
        bool all_zero = true;
        for (size_t i = 0; i < 64 && all_zero; ++i)
            if (quote_word[i] != '0') all_zero = false;
        out.is_bnb_quote = all_zero;
    }

    out.valid = true;
    return true;
}

bool BscRpcClient::eth_get_token_info_curve(const Address& token, TokenManagerCurveInfo& out) {
    out = {};
    auto now = std::chrono::steady_clock::now();
    if (now - last_ti_ < min_ti_) {
        std::this_thread::sleep_until(last_ti_ + min_ti_);
    }
    last_ti_ = std::chrono::steady_clock::now();

    std::string tok = addr_to_json_hex(token);
    std::transform(tok.begin(), tok.end(), tok.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    tok.erase(0, 2); // strip 0x (40 hex)
    std::string input = std::string(fourmeme::SELECTOR_GET_TOKEN_INFO);
    input.append(24, '0'); // 12-byte ABI address padding (12 bytes = 24 hex chars)
    input.append(tok);

    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{)"
        << R"("to":")" << fourmeme::TOKEN_MANAGER_HELPER3 << R"(",)"
        << R"("data":")" << input << R"("}, "latest"]})";
    std::string resp;
    if (!post_json(oss.str(), resp)) return false;
    auto res = json_minimal::extract_string_value(resp, "result");
    if (!res) return false;
    return decode_get_token_info_return(*res, out);
}

bool BscRpcClient::eth_get_token_info_curve_at_block(const Address& token, const std::string& block_hex,
                                                      TokenManagerCurveInfo& out) {
    out = {};
    auto now = std::chrono::steady_clock::now();
    if (now - last_ti_ < min_ti_) {
        std::this_thread::sleep_until(last_ti_ + min_ti_);
    }
    last_ti_ = std::chrono::steady_clock::now();

    std::string tok = addr_to_json_hex(token);
    std::transform(tok.begin(), tok.end(), tok.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    tok.erase(0, 2);
    std::string input = std::string(fourmeme::SELECTOR_GET_TOKEN_INFO);
    input.append(24, '0');
    input.append(tok);

    // Try at specific block first (requires archive node)
    std::ostringstream oss;
    oss << R"({"jsonrpc":"2.0","id":1,"method":"eth_call","params":[{)"
        << R"("to":")" << fourmeme::TOKEN_MANAGER_HELPER3 << R"(",)"
        << R"("data":")" << input << R"("}, ")" << block_hex << R"("]})";
    std::string resp;
    if (post_json(oss.str(), resp)) {
        if (resp.find("\"error\"") == std::string::npos) {
            auto res = json_minimal::extract_string_value(resp, "result");
            if (res && decode_get_token_info_return(*res, out)) return true;
        }
    }
    // Fallback to "latest"
    return eth_get_token_info_curve(token, out);
}

// ---- JSON-RPC batch support ----

// Split a JSON-RPC batch response array "[{...},{...},...]" into individual response objects.
// Responses may arrive out of order; we re-order by "id" field.
std::vector<std::string> BscRpcClient::split_batch_response(const std::string& response, size_t expected) {
    std::vector<std::string> ordered(expected);
    size_t pos = response.find('[');
    if (pos == std::string::npos) return ordered;
    ++pos;

    while (pos < response.size()) {
        auto o = response.find('{', pos);
        if (o == std::string::npos) break;
        int depth = 0;
        size_t i = o;
        for (; i < response.size(); ++i) {
            if (response[i] == '{') ++depth;
            else if (response[i] == '}') {
                --depth;
                if (depth == 0) break;
            }
        }
        if (depth != 0) break;
        std::string obj = response.substr(o, i - o + 1);

        // Extract "id":N
        auto id_pos = obj.find("\"id\":");
        if (id_pos != std::string::npos) {
            size_t num_start = id_pos + 5;
            while (num_start < obj.size() && (obj[num_start] == ' ' || obj[num_start] == '\t')) ++num_start;
            size_t id_val = 0;
            for (size_t k = num_start; k < obj.size() && obj[k] >= '0' && obj[k] <= '9'; ++k)
                id_val = id_val * 10 + static_cast<size_t>(obj[k] - '0');
            if (id_val < expected) ordered[id_val] = std::move(obj);
        }
        pos = i + 1;
    }
    return ordered;
}

bool BscRpcClient::batch_eth_call(const std::vector<BatchEthCallItem>& items,
                                   std::vector<BatchEthCallResult>& results) {
    results.resize(items.size());
    if (items.empty()) return true;

    constexpr size_t MAX_BATCH = 50;
    for (size_t base = 0; base < items.size(); base += MAX_BATCH) {
        size_t count = std::min(MAX_BATCH, items.size() - base);

        std::string body = "[";
        for (size_t i = 0; i < count; ++i) {
            if (i) body += ',';
            const auto& it = items[base + i];
            body += R"({"jsonrpc":"2.0","id":)";
            body += std::to_string(i);
            body += R"(,"method":"eth_call","params":[{"to":")" + it.to_address +
                    R"(","data":")" + it.calldata + R"("},")" + it.block_hex + R"("]})";
        }
        body += ']';

        std::string resp;
        if (!post_json(body, resp)) return false;

        auto parts = split_batch_response(resp, count);
        for (size_t i = 0; i < count; ++i) {
            auto& r = results[base + i];
            const auto& p = parts[i];
            if (p.empty() || p.find("\"error\"") != std::string::npos) continue;
            auto rpos = p.find("\"result\":\"0x");
            if (rpos == std::string::npos) continue;
            rpos += 12;
            auto rend = p.find('"', rpos);
            if (rend == std::string::npos) continue;
            r.result_hex = p.substr(rpos, rend - rpos);
            r.ok = !r.result_hex.empty();
        }
    }
    return true;
}

bool BscRpcClient::batch_get_token_info_curve(
    const std::vector<std::pair<Address, std::string>>& token_block_pairs,
    std::vector<TokenManagerCurveInfo>& results) {
    results.resize(token_block_pairs.size());
    if (token_block_pairs.empty()) return true;

    std::vector<BatchEthCallItem> items;
    items.reserve(token_block_pairs.size());

    for (const auto& [token, block_hex] : token_block_pairs) {
        std::string tok = address_to_hex(token);
        std::transform(tok.begin(), tok.end(), tok.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        tok.erase(0, 2);
        std::string input = std::string(fourmeme::SELECTOR_GET_TOKEN_INFO);
        input.append(24, '0');
        input.append(tok);
        items.push_back({std::string(fourmeme::TOKEN_MANAGER_HELPER3), input, block_hex});
    }

    std::vector<BatchEthCallResult> raw_results;
    if (!batch_eth_call(items, raw_results)) return false;

    for (size_t i = 0; i < token_block_pairs.size(); ++i) {
        if (raw_results[i].ok) {
            decode_get_token_info_return(raw_results[i].result_hex, results[i]);
        }
    }
    return true;
}

// ---- parse logs array from full JSON-RPC response ----
bool BscRpcClient::parse_logs_result(std::string_view json, std::vector<RpcLogEntry>& out) {
    out.clear();
    if (json.find("\"result\":null") != std::string_view::npos) return true;
    auto arr = json_minimal::extract_array_body(json, "result");
    if (!arr) return false;
    std::string_view body = *arr;
    size_t pos = 0;
    while (pos < body.size()) {
        auto o = body.find('{', pos);
        if (o == std::string_view::npos) break;
        int depth = 0;
        size_t i = o;
        for (; i < body.size(); ++i) {
            if (body[i] == '{') ++depth;
            else if (body[i] == '}') {
                --depth;
                if (depth == 0) {
                    std::string_view obj = body.substr(o, i - o + 1);
                    RpcLogEntry e;
                    auto ad = json_minimal::extract_string_value(obj, "address");
                    auto blk = json_minimal::extract_string_value(obj, "blockNumber");
                    auto txh = json_minimal::extract_string_value(obj, "transactionHash");
                    auto dat = json_minimal::extract_string_value(obj, "data");
                    auto top_body = json_minimal::extract_array_body(obj, "topics");
                    if (ad && blk && dat) {
                        e.address_lower = std::string(*ad);
                        e.block_hex = std::string(*blk);
                        e.block_number = 0;
                        std::string_view bh = *blk;
                        if (bh.size() >= 2 && bh[0] == '0' && bh[1] == 'x') {
                            for (size_t k = 2; k < bh.size(); ++k) {
                                char c = bh[k];
                                int d = (c >= '0' && c <= '9') ? c - '0'
                                        : (c >= 'a' && c <= 'f') ? 10 + c - 'a'
                                        : (c >= 'A' && c <= 'F') ? 10 + c - 'A' : 0;
                                e.block_number = (e.block_number << 4) | static_cast<uint64_t>(d);
                            }
                        }
                        e.data = std::string(*dat);
                        if (txh) e.tx_hash = std::string(*txh);
                        (void)json_minimal::extract_hex_u64(obj, "logIndex", e.log_index);
                        (void)json_minimal::extract_hex_u64(obj, "transactionIndex", e.transaction_index);
                        if (top_body) {
                            std::string_view tb = *top_body;
                            size_t p = 0;
                            while (p < tb.size()) {
                                auto q = tb.find('"', p);
                                if (q == std::string_view::npos) break;
                                ++q;
                                auto r = tb.find('"', q);
                                if (r == std::string_view::npos) break;
                                e.topics.emplace_back(tb.substr(q, r - q));
                                p = r + 1;
                                p = tb.find(',', p);
                                if (p == std::string_view::npos) break;
                                ++p;
                            }
                        }
                        out.push_back(std::move(e));
                    }
                    pos = i + 1;
                    break;
                }
            }
        }
        if (i >= body.size()) break;
    }
    return true;
}

} // namespace lumina
