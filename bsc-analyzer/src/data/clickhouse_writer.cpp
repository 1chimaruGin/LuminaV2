#include "lumina/data/clickhouse_writer.h"
#include <curl/curl.h>
#include <cstdio>
#include <sstream>

namespace lumina {

static size_t discard_cb(char*, size_t size, size_t nmemb, void*) {
    return size * nmemb;
}

ClickHouseWriter::ClickHouseWriter(const std::string& host, int port, const std::string& database)
    : database_(database) {
    std::ostringstream oss;
    oss << "http://" << host << ":" << port;
    base_url_ = oss.str();
}

bool ClickHouseWriter::http_post(const std::string& url, const std::string& body) {
    CURL* curl = curl_easy_init();
    if (!curl) return false;

    std::string response;
    auto write_cb = [](char* ptr, size_t size, size_t nmemb, void* ud) -> size_t {
        auto* s = static_cast<std::string*>(ud);
        s->append(ptr, size * nmemb);
        return size * nmemb;
    };

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, +write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);

    CURLcode res = curl_easy_perform(curl);
    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK || http_code != 200) {
        std::fprintf(stderr, "[clickhouse] POST failed: curl=%d http=%ld resp=%.200s\n",
                     static_cast<int>(res), http_code, response.c_str());
        return false;
    }
    return true;
}

bool ClickHouseWriter::ping() {
    CURL* curl = curl_easy_init();
    if (!curl) return false;
    std::string url = base_url_ + "/ping";
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, discard_cb);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 3L);
    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    return res == CURLE_OK;
}

bool ClickHouseWriter::insert_row(const std::string& table, const std::string& tsv_row) {
    std::string url = base_url_ + "/?database=" + database_ +
                      "&query=" + "INSERT%20INTO%20" + table + "%20FORMAT%20TabSeparated";
    return http_post(url, tsv_row + "\n");
}

bool ClickHouseWriter::insert_rows(const std::string& table, const std::vector<std::string>& tsv_rows) {
    if (tsv_rows.empty()) return true;
    std::string body;
    for (const auto& r : tsv_rows) {
        body += r;
        body += '\n';
    }
    std::string url = base_url_ + "/?database=" + database_ +
                      "&query=" + "INSERT%20INTO%20" + table + "%20FORMAT%20TabSeparated";
    return http_post(url, body);
}

} // namespace lumina
