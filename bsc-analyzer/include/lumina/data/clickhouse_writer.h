#pragma once
#include <string>
#include <vector>

namespace lumina {

// Lightweight ClickHouse HTTP writer.
// Posts tab-separated rows to ClickHouse's HTTP interface at 8123.
class ClickHouseWriter {
public:
    explicit ClickHouseWriter(const std::string& host = "localhost", int port = 8123,
                               const std::string& database = "lumina");

    // Insert a single row of tab-separated values into the given table.
    bool insert_row(const std::string& table, const std::string& tsv_row);

    // Insert multiple rows of tab-separated values.
    bool insert_rows(const std::string& table, const std::vector<std::string>& tsv_rows);

    // Check connection
    bool ping();

private:
    bool http_post(const std::string& url, const std::string& body);
    std::string base_url_;
    std::string database_;
};

} // namespace lumina
