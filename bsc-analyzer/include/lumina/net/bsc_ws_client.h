#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace lumina {

// Minimal client WebSocket over TLS (BSC JSON-RPC eth_subscribe).
class BscWsClient {
public:
    using OnText = std::function<void(std::string_view)>;

    BscWsClient();
    ~BscWsClient();

    BscWsClient(const BscWsClient&) = delete;
    BscWsClient& operator=(const BscWsClient&) = delete;

    // Full URL e.g. wss://host.example/path (path must include trailing slash if provider requires)
    bool connect(std::string_view wss_url);
    void close();

    bool send_json(std::string_view json_utf8);

    // Blocks until one complete text frame or error. Returns false on disconnect / parse error.
    bool recv_text(std::string& out);

    int last_error() const { return last_errno_; }

private:
    bool do_tls_handshake();
    bool send_frame(uint8_t opcode, const uint8_t* payload, size_t len, bool mask);
    bool read_full(void* buf, size_t n);
    bool parse_http_upgrade_response();
    static bool parse_wss_url(std::string_view url, std::string& host, std::string& path, int& port);

    int sock_ = -1;
    void* ssl_ = nullptr;   // SSL*
    void* ssl_ctx_ = nullptr; // SSL_CTX*
    std::string host_;
    std::string path_;
    int port_ = 443;
    int last_errno_ = 0;
};

} // namespace lumina
