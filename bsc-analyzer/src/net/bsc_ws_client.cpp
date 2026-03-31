#include "lumina/net/bsc_ws_client.h"
#include "lumina/tracking/logger.h"
#include <arpa/inet.h>
#include <cstring>
#include <netdb.h>
#include <netinet/tcp.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/sha.h>
#include <openssl/ssl.h>
#include <random>
#include <sstream>
#include <sys/socket.h>
#include <unistd.h>

namespace lumina {

static void base64_encode_sha1(const uint8_t* in, size_t len, std::string& out) {
    static const char* tbl =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    out.clear();
    for (size_t i = 0; i < len; i += 3) {
        uint32_t v = static_cast<uint32_t>(in[i]) << 16;
        if (i + 1 < len) v |= static_cast<uint32_t>(in[i + 1]) << 8;
        if (i + 2 < len) v |= static_cast<uint32_t>(in[i + 2]);
        out.push_back(tbl[(v >> 18) & 63]);
        out.push_back(tbl[(v >> 12) & 63]);
        if (i + 1 < len) out.push_back(tbl[(v >> 6) & 63]);
        else out.push_back('=');
        if (i + 2 < len) out.push_back(tbl[v & 63]);
        else out.push_back('=');
    }
}

static bool random_key_16(std::string& key_b64) {
    uint8_t buf[16];
    if (RAND_bytes(buf, sizeof(buf)) != 1) {
        std::random_device rd;
        for (auto& b : buf) b = static_cast<uint8_t>(rd());
    }
    unsigned char enc[32];
    int el = EVP_EncodeBlock(enc, buf, 16);
    if (el <= 0) return false;
    key_b64.assign(reinterpret_cast<char*>(enc), static_cast<size_t>(el));
    while (!key_b64.empty() && key_b64.back() == '\n') key_b64.pop_back();
    return true;
}

static bool verify_accept(std::string_view accept_hdr, std::string_view sec_key) {
    static const char magic[] = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
    std::string concat;
    concat.append(sec_key.data(), sec_key.size());
    concat.append(magic, sizeof(magic) - 1);
    unsigned char hash[20];
    SHA1(reinterpret_cast<const unsigned char*>(concat.data()), concat.size(), hash);
    std::string expected;
    base64_encode_sha1(hash, 20, expected);
    return accept_hdr == expected;
}

bool BscWsClient::parse_wss_url(std::string_view url, std::string& host, std::string& path, int& port) {
    host.clear();
    path = "/";
    port = 443;
    if (url.size() < 8) return false;
    if (url.substr(0, 6) != "wss://" && url.substr(0, 5) != "ws://") return false;
    bool tls = url[2] == 's';
    size_t start = tls ? 6 : 5;
    size_t slash = url.find('/', start);
    if (slash == std::string_view::npos) {
        host = std::string(url.substr(start));
        path = "/";
    } else {
        host = std::string(url.substr(start, slash - start));
        path = std::string(url.substr(slash));
    }
    port = tls ? 443 : 80;
    auto colon = host.rfind(':');
    if (colon != std::string::npos && colon + 1 < host.size()) {
        bool all_digit = true;
        for (size_t i = colon + 1; i < host.size(); ++i) {
            if (!std::isdigit(static_cast<unsigned char>(host[i]))) all_digit = false;
        }
        if (all_digit) {
            port = std::stoi(host.substr(colon + 1));
            host = host.substr(0, colon);
        }
    }
    return !host.empty();
}

BscWsClient::BscWsClient() = default;

BscWsClient::~BscWsClient() { close(); }

void BscWsClient::close() {
    if (ssl_) {
        SSL_shutdown(static_cast<SSL*>(ssl_));
        SSL_free(static_cast<SSL*>(ssl_));
        ssl_ = nullptr;
    }
    if (ssl_ctx_) {
        SSL_CTX_free(static_cast<SSL_CTX*>(ssl_ctx_));
        ssl_ctx_ = nullptr;
    }
    if (sock_ >= 0) {
        ::close(sock_);
        sock_ = -1;
    }
}

bool BscWsClient::read_full(void* buf, size_t n) {
    auto* p = static_cast<uint8_t*>(buf);
    size_t got = 0;
    while (got < n) {
        int r = SSL_read(static_cast<SSL*>(ssl_), p + got, static_cast<int>(n - got));
        if (r <= 0) return false;
        got += static_cast<size_t>(r);
    }
    return true;
}

bool BscWsClient::connect(std::string_view wss_url) {
    close();
    if (!parse_wss_url(wss_url, host_, path_, port_)) return false;

    struct addrinfo hints{};
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_family = AF_UNSPEC;
    struct addrinfo* res = nullptr;
    std::string port_str = std::to_string(port_);
    if (getaddrinfo(host_.c_str(), port_str.c_str(), &hints, &res) != 0 || !res) return false;

    sock_ = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (sock_ < 0) {
        freeaddrinfo(res);
        return false;
    }
    int one = 1;
    setsockopt(sock_, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    if (::connect(sock_, res->ai_addr, static_cast<socklen_t>(res->ai_addrlen)) < 0) {
        last_errno_ = errno;
        freeaddrinfo(res);
        ::close(sock_);
        sock_ = -1;
        return false;
    }
    freeaddrinfo(res);

    ssl_ctx_ = SSL_CTX_new(TLS_client_method());
    if (!ssl_ctx_) return false;
    ssl_ = SSL_new(static_cast<SSL_CTX*>(ssl_ctx_));
    if (!ssl_) return false;
    SSL_set_fd(static_cast<SSL*>(ssl_), sock_);
    SSL_set_tlsext_host_name(static_cast<SSL*>(ssl_), host_.c_str());
    if (SSL_connect(static_cast<SSL*>(ssl_)) != 1) {
        last_errno_ = static_cast<int>(ERR_get_error());
        close();
        return false;
    }

    std::string ws_key;
    random_key_16(ws_key);
    std::ostringstream req;
    req << "GET " << path_ << " HTTP/1.1\r\n"
        << "Host: " << host_ << "\r\n"
        << "Upgrade: websocket\r\n"
        << "Connection: Upgrade\r\n"
        << "Sec-WebSocket-Key: " << ws_key << "\r\n"
        << "Sec-WebSocket-Version: 13\r\n"
        << "\r\n";
    std::string rq = req.str();
    if (SSL_write(static_cast<SSL*>(ssl_), rq.data(), static_cast<int>(rq.size())) != static_cast<int>(rq.size()))
        return false;

    char buf[4096];
    size_t total = 0;
    while (total < sizeof(buf) - 1) {
        int r = SSL_read(static_cast<SSL*>(ssl_), buf + total, 1);
        if (r <= 0) return false;
        ++total;
        if (total >= 4 && std::memcmp(buf + total - 4, "\r\n\r\n", 4) == 0) break;
    }
    buf[total] = '\0';
    std::string_view resp(buf, total);
    if (resp.find(" 101 ") == std::string_view::npos) {
        LOG_ERR("WS upgrade failed: %s", buf);
        close();
        return false;
    }
    auto ak = resp.find("Sec-WebSocket-Accept:");
    if (ak != std::string_view::npos) {
        ak += 23;
        while (ak < resp.size() && (resp[ak] == ' ' || resp[ak] == '\t')) ++ak;
        auto e = resp.find("\r\n", ak);
        if (e != std::string_view::npos) {
            std::string_view acc = resp.substr(ak, e - ak);
            while (!acc.empty() && (acc.front() == ' ' || acc.front() == '\t')) acc.remove_prefix(1);
            while (!acc.empty() &&
                   (acc.back() == ' ' || acc.back() == '\t' || acc.back() == '\r')) acc.remove_suffix(1);
            if (!verify_accept(acc, ws_key)) {
                LOG_WRN("WS Sec-WebSocket-Accept mismatch (continuing anyway)");
            }
        }
    }

    {
        std::string url_owned(wss_url);
        LOG_INF("WebSocket connected: %s", url_owned.c_str());
    }
    return true;
}

bool BscWsClient::send_frame(uint8_t opcode, const uint8_t* payload, size_t len, bool mask) {
    uint8_t hdr[14];
    size_t hlen = 0;
    hdr[0] = static_cast<uint8_t>(0x80 | opcode);
    const uint8_t mask_bit = mask ? 0x80 : 0;
    if (len < 126) {
        hdr[1] = static_cast<uint8_t>(len | mask_bit);
        hlen = 2;
    } else if (len < 65536) {
        hdr[1] = static_cast<uint8_t>(126 | mask_bit);
        hdr[2] = static_cast<uint8_t>((len >> 8) & 0xff);
        hdr[3] = static_cast<uint8_t>(len & 0xff);
        hlen = 4;
    } else {
        return false;
    }
    if (mask) {
        uint8_t mk[4];
        std::random_device rd;
        for (auto& b : mk) b = static_cast<uint8_t>(rd());
        std::memcpy(hdr + hlen, mk, 4);
        hlen += 4;
        std::vector<uint8_t> masked(len);
        for (size_t i = 0; i < len; ++i) masked[i] = payload[i] ^ mk[i % 4];
        if (SSL_write(static_cast<SSL*>(ssl_), hdr, static_cast<int>(hlen)) != static_cast<int>(hlen))
            return false;
        return SSL_write(static_cast<SSL*>(ssl_), masked.data(), static_cast<int>(len)) == static_cast<int>(len);
    }
    if (SSL_write(static_cast<SSL*>(ssl_), hdr, static_cast<int>(hlen)) != static_cast<int>(hlen)) return false;
    if (len && SSL_write(static_cast<SSL*>(ssl_), payload, static_cast<int>(len)) != static_cast<int>(len))
        return false;
    return true;
}

bool BscWsClient::send_json(std::string_view json_utf8) {
    return send_frame(0x01, reinterpret_cast<const uint8_t*>(json_utf8.data()), json_utf8.size(), true);
}

bool BscWsClient::recv_text(std::string& out) {
    out.clear();
    for (;;) {
        uint8_t b0, b1;
        if (!read_full(&b0, 1) || !read_full(&b1, 1)) return false;
        bool fin = (b0 & 0x80) != 0;
        (void)fin;
        uint8_t opcode = b0 & 0x0f;
        bool masked = (b1 & 0x80) != 0;
        uint64_t plen = b1 & 0x7f;
        if (plen == 126) {
            uint8_t e[2];
            if (!read_full(e, 2)) return false;
            plen = (static_cast<uint64_t>(e[0]) << 8) | e[1];
        } else if (plen == 127) {
            uint8_t e[8];
            if (!read_full(e, 8)) return false;
            plen = 0;
            for (int i = 0; i < 8; ++i) plen = (plen << 8) | e[i];
        }
        uint8_t mask[4]{};
        if (masked && !read_full(mask, 4)) return false;
        std::vector<uint8_t> payload(plen);
        if (plen && !read_full(payload.data(), plen)) return false;
        if (masked) {
            for (uint64_t i = 0; i < plen; ++i) payload[i] ^= mask[i % 4];
        }
        if (opcode == 0x8) return false;
        if (opcode == 0x9) {
            send_frame(0x0a, payload.data(), static_cast<size_t>(plen), true);
            continue;
        }
        if (opcode == 0x1 || opcode == 0x0) {
            out.append(reinterpret_cast<char*>(payload.data()), payload.size());
            if (fin) return true;
            continue;
        }
        if (fin && opcode != 0x9 && opcode != 0x8) continue;
    }
}

} // namespace lumina
