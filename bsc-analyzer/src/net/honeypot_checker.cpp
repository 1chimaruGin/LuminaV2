#include "lumina/net/honeypot_checker.h"
#include "lumina/tracking/logger.h"
#include <algorithm>
#include <curl/curl.h>
#include <sstream>

namespace lumina {

static size_t curl_write_cb(char* ptr, size_t size, size_t nmemb, void* userdata) {
    auto* s = static_cast<std::string*>(userdata);
    s->append(ptr, size * nmemb);
    return size * nmemb;
}

HoneypotChecker::HoneypotChecker(const std::string& api_key) : api_key_(api_key) {}

std::string HoneypotChecker::call_api(const std::string& url) const {
    std::string response;
    CURL* curl = curl_easy_init();
    if (!curl) return response;
    struct curl_slist* hdr = nullptr;
    hdr = curl_slist_append(hdr, "Accept: application/json");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdr);
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "lumina-bsc-analyzer/1.0");
    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(hdr);
    curl_easy_cleanup(curl);
    if (res != CURLE_OK) {
        LOG_WRN("GoPlus HTTP error: %s", curl_easy_strerror(res));
        response.clear();
    }
    return response;
}

static bool json_get_boolish(std::string_view json, std::string_view key, bool& out) {
    std::string needle;
    needle.push_back('"');
    needle.append(key);
    needle += "\":";
    auto p = json.find(needle);
    if (p == std::string_view::npos) return false;
    p += needle.size();
    while (p < json.size() && (json[p] == ' ' || json[p] == '\t')) ++p;
    if (p < json.size() && json[p] == '"') {
        ++p;
        if (p < json.size() && json[p] == '1') {
            out = true;
            return true;
        }
        if (p < json.size() && json[p] == '0') {
            out = false;
            return true;
        }
    }
    if (p + 4 <= json.size() && json.substr(p, 4) == "true") {
        out = true;
        return true;
    }
    if (p + 5 <= json.size() && json.substr(p, 5) == "false") {
        out = false;
        return true;
    }
    return false;
}

static bool json_get_doubleish(std::string_view json, std::string_view key, double& out) {
    std::string needle;
    needle.push_back('"');
    needle.append(key);
    needle += "\":";
    auto p = json.find(needle);
    if (p == std::string_view::npos) return false;
    p += needle.size();
    while (p < json.size() && (json[p] == ' ' || json[p] == '\t')) ++p;
    if (p < json.size() && json[p] == '"') {
        ++p;
        auto e = json.find('"', p);
        if (e == std::string_view::npos) return false;
        try {
            out = std::stod(std::string(json.substr(p, e - p)));
        } catch (...) {
            return false;
        }
        return true;
    }
    return false;
}

HoneypotResult HoneypotChecker::parse_response(const std::string& json) const {
    HoneypotResult result{};
    result.is_honeypot = false;
    result.buy_tax = 0.0;
    result.sell_tax = 0.0;
    result.can_buy = true;
    result.can_sell = true;
    result.owner_renounced = false;

    if (json.find("\"result\"") == std::string::npos) {
        result.error = "no_result";
        return result;
    }
    std::string_view tokjson(json);

    bool hp = false;
    if (json_get_boolish(tokjson, "is_honeypot", hp)) result.is_honeypot = hp;
    double bt = 0, st = 0;
    if (json_get_doubleish(tokjson, "buy_tax", bt)) result.buy_tax = bt;
    if (json_get_doubleish(tokjson, "sell_tax", st)) result.sell_tax = st;
    bool cb = false, cs_all = false;
    if (json_get_boolish(tokjson, "cannot_buy", cb)) result.can_buy = !cb;
    if (json_get_boolish(tokjson, "cannot_sell_all", cs_all)) result.can_sell = !cs_all;

    return result;
}

std::optional<HoneypotResult> HoneypotChecker::check_token(const Address& token_addr) const {
    std::string token_hex = address_to_hex(token_addr);
    std::transform(token_hex.begin(), token_hex.end(), token_hex.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    std::ostringstream url;
    url << "https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses=" << token_hex;
    (void)api_key_;

    try {
        std::string response = call_api(url.str());
        if (response.empty()) return std::nullopt;
        if (response.find("\"code\":1") == std::string::npos && response.find("\"code\": 1") == std::string::npos) {
            if (response.find("message") != std::string::npos) LOG_WRN("GoPlus: %s", response.substr(0, 300).c_str());
        }
        return parse_response(response);
    } catch (const std::exception& e) {
        LOG_ERR("Honeypot check failed: %s", e.what());
        return std::nullopt;
    }
}

} // namespace lumina
