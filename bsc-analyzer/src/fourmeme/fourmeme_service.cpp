#include "lumina/fourmeme/fourmeme_service.h"
#include "lumina/fourmeme/constants.h"
#include "lumina/fourmeme/token_create_abi.h"
#include "lumina/tracking/logger.h"
#include <cctype>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <sstream>

namespace lumina::fourmeme {

static std::string json_escape(std::string_view s) {
    std::string o;
    for (char c : s) {
        if (c == '"' || c == '\\') o.push_back('\\');
        o.push_back(c);
    }
    return o;
}

static bool extract_brace_object(std::string_view in, size_t start, std::string_view& out_obj) {
    size_t i = in.find('{', start);
    if (i == std::string_view::npos) return false;
    int d = 0;
    for (size_t j = i; j < in.size(); ++j) {
        if (in[j] == '{') ++d;
        else if (in[j] == '}') {
            --d;
            if (d == 0) {
                out_obj = in.substr(i, j - i + 1);
                return true;
            }
        }
    }
    return false;
}

static bool ws_message_to_rpc_log(std::string_view msg, RpcLogEntry& e) {
    if (msg.find("eth_subscription") == std::string_view::npos) return false;
    auto r = msg.find("\"result\":");
    if (r == std::string_view::npos) return false;
    r += 9;
    std::string_view obj;
    if (!extract_brace_object(msg, r, obj)) return false;
    std::string fake = "{\"result\":[";
    fake.append(obj.data(), obj.size());
    fake += "]}";
    std::vector<RpcLogEntry> vec;
    if (!lumina::BscRpcClient::parse_logs_result(fake, vec)) return false;
    if (vec.empty()) return false;
    e = std::move(vec[0]);
    return true;
}

FourMemeService::FourMemeService(std::string http_rpc_primary, std::string http_rpc_fallback,
                                 std::string wss_url, DeployerDB& deployers,
                                 BloomFilter<2097152>& smart_money)
    : wss_(std::move(wss_url)),
      deployers_(deployers),
      smart_money_(smart_money),
      rpc_(std::move(http_rpc_primary), std::move(http_rpc_fallback)),
      registry_(&deployers_, &smart_money_),
      goplus_("") {}

std::string FourMemeService::block_to_hex(uint64_t bn) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "0x%lx", static_cast<unsigned long>(bn));
    return buf;
}

void FourMemeService::emit_intel_json(const Address& token, const TokenIntelSnapshot& snap,
                                      const FourMemeScoreResult& score) {
    std::lock_guard<std::mutex> lock(io_mu_);
    std::ostringstream j;
    j << "{\"type\":\"fourmeme_intel\""
      << ",\"token\":\"" << address_to_hex(token) << "\""
      << ",\"creator\":\"" << address_to_hex(snap.creator) << "\""
      << ",\"launch_block\":" << snap.launch_block
      << ",\"advise_min_entry_block\":" << snap.advise_min_entry_block
      << ",\"hhi_approx\":" << snap.hhi
      << ",\"transfer_count\":" << snap.transfer_count
      << ",\"unique_recipients_launch_window\":" << snap.unique_recipients_launch_window
      << ",\"bundle_heavy\":" << (snap.bundle_heavy ? "true" : "false")
      << ",\"wash_ratio\":" << snap.wash_ratio
      << ",\"curve_funds_wei\":" << snap.curve.funds_wei
      << ",\"curve_max_wei\":" << snap.curve.max_funds_wei
      << ",\"liquidity_added\":" << (snap.curve.liquidity_added ? "true" : "false")
      << ",\"goplus_honeypot\":" << (snap.goplus_honeypot ? "true" : "false")
      << ",\"kol_buy_count\":" << static_cast<int>(snap.kol_buy_count)
      << ",\"score\":" << score.score
      << ",\"hard_veto\":" << (score.hard_veto ? "true" : "false")
      << ",\"veto_reason\":\"" << json_escape(score.veto_reason) << "\""
      << ",\"decision\":\"";
    j << (score.decision == ::lumina::Decision::HARD_REJECT     ? "HARD_REJECT"
          : score.decision == ::lumina::Decision::FAST_PASS     ? "FAST_PASS"
                                                                  : "FORWARD_TIER2");
    j << "\"}";
    std::printf("%s\n", j.str().c_str());
    std::fflush(stdout);
}

void FourMemeService::handle_log_entry(const RpcLogEntry& log) {
    std::string mgr = fourmeme::PROXY_MANAGER;
    std::transform(mgr.begin(), mgr.end(), mgr.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::string addr = log.address_lower;
    std::transform(addr.begin(), addr.end(), addr.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (addr != mgr) return;
    if (log.topics.empty()) return;
    std::string t0 = log.topics[0];
    std::transform(t0.begin(), t0.end(), t0.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    static const std::string tc = [] {
        std::string s(TOPIC_TOKEN_CREATE);
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return s;
    }();
    static const std::string tc_legacy = [] {
        std::string s(TOPIC_TOKEN_CREATE_LEGACY);
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return s;
    }();

    Address creator{}, token{};
    if (t0 == tc) {
        std::string name, symbol;
        if (!decode_token_create_data_v2(log.data, creator, token, name, symbol)) return;
    } else if ((t0 == tc_legacy) && log.topics.size() >= 3) {
        if (!topic_to_address(log.topics[1], creator)) return;
        if (!topic_to_address(log.topics[2], token)) return;
    } else {
        return;
    }

    registry_.on_token_create(creator, token, log.block_number);
    {
        std::lock_guard<std::mutex> g(goq_mu_);
        goq_.push(token);
    }

    TokenManagerCurveInfo curve{};
    if (rpc_.eth_get_token_info_curve(token, curve)) registry_.set_curve_info(token, curve);

    TokenIntelSnapshot snap{};
    if (registry_.snapshot_for(token, snap)) {
        FourMemeScoreResult sc = registry_.score(snap, 0.15f, 0.90f);
        emit_intel_json(token, snap, sc);
    }
}

void FourMemeService::thread_ws() {
    BscWsClient ws;
    while (running_.load()) {
        if (!ws.connect(wss_)) {
            LOG_ERR("FourMeme WS connect failed, retry 5s");
            std::this_thread::sleep_for(std::chrono::seconds(5));
            continue;
        }
        const char* sub =
            R"({"jsonrpc":"2.0","id":1,"method":"eth_subscribe","params":["logs",{"address":"0x5c952063c7fc8610ffdb798152d69f0b9550762b","topics":[["0x396d5e902b675b032348d3d2e9517ee8f0c4a926603fbc075d3d282ff00cad20","0x589f95642efe902cf4021543f39840e7f9cecd61430e908f946dda4ffef3a29f","0xb7d8fd3c9d56d12c15c8e139bc4e6febd6ad2349b3ebe6a1a91c0a9e7797710d"]]}}]})";
        if (!ws.send_json(sub)) {
            ws.close();
            continue;
        }
        LOG_INF("Four.meme WS subscribed; blocking until log events (stdout stays quiet if chain is idle)");
        while (running_.load()) {
            std::string msg;
            if (!ws.recv_text(msg)) {
                LOG_WRN("FourMeme WS recv ended, reconnecting");
                ws.close();
                break;
            }
            RpcLogEntry e;
            if (ws_message_to_rpc_log(msg, e)) handle_log_entry(e);
        }
    }
}

void FourMemeService::thread_poll_blocks() {
    while (running_.load()) {
        uint64_t bn = 0;
        if (!rpc_.eth_block_number(bn)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            continue;
        }
        if (last_block_ == 0) {
            last_block_ = bn;
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            continue;
        }
        if (bn > last_block_) {
            uint64_t end = std::min(bn, last_block_ + 4);
            for (uint64_t b = last_block_ + 1; b <= end; ++b) {
                std::vector<Address> tokens = registry_.active_tokens_snapshot();
                std::vector<RpcLogEntry> logs;
                if (!tokens.empty() &&
                    rpc_.eth_get_logs_transfers_block(tokens, block_to_hex(b), logs)) {
                    for (const auto& lg : logs) {
                        if (lg.topics.size() < 3) continue;
                        Address from{}, to{}, tok = hex_to_address(lg.address_lower);
                        if (!fourmeme::topic_to_address(lg.topics[1], from)) continue;
                        if (!fourmeme::topic_to_address(lg.topics[2], to)) continue;
                        registry_.on_transfer(tok, from, to, lg.data, b);
                    }
                }
            }
            last_block_ = end;
        }
        std::vector<Address> tokens = registry_.active_tokens_snapshot();
        size_t ncurve = 0;
        for (const auto& t : tokens) {
            if (++ncurve > 12) break;
            TokenManagerCurveInfo c{};
            if (rpc_.eth_get_token_info_curve(t, c)) registry_.set_curve_info(t, c);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(750));
    }
}

void FourMemeService::thread_goplus() {
    while (running_.load()) {
        Address tok{};
        bool has = false;
        {
            std::lock_guard<std::mutex> g(goq_mu_);
            if (!goq_.empty()) {
                tok = goq_.front();
                goq_.pop();
                has = true;
            }
        }
        if (!has) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            continue;
        }
        auto r = goplus_.check_token(tok);
        if (r.has_value()) {
            registry_.set_goplus(tok, r->is_honeypot);
            TokenIntelSnapshot snap{};
            if (registry_.snapshot_for(tok, snap)) {
                FourMemeScoreResult sc = registry_.score(snap, 0.15f, 0.90f);
                emit_intel_json(tok, snap, sc);
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(400));
    }
}

void FourMemeService::handle_ipc_message(const std::string& json_line) {
    // Parse {"event":"kol_buy","token":"0x...","kol_count":N,...}
    auto find_str = [&](const char* key) -> std::string {
        auto pos = json_line.find(key);
        if (pos == std::string::npos) return {};
        pos = json_line.find('"', pos + std::strlen(key));
        if (pos == std::string::npos) return {};
        auto end = json_line.find('"', pos + 1);
        if (end == std::string::npos) return {};
        return json_line.substr(pos + 1, end - pos - 1);
    };
    auto find_int = [&](const char* key) -> int {
        auto pos = json_line.find(key);
        if (pos == std::string::npos) return 0;
        pos += std::strlen(key);
        return std::atoi(json_line.c_str() + pos);
    };

    std::string event = find_str("\"event\":\"");
    if (event != "kol_buy") return;

    std::string token_hex = find_str("\"token\":\"");
    int kol_count = find_int("\"kol_count\":");
    if (token_hex.empty() || kol_count <= 0) return;

    Address token = hex_to_address(token_hex);
    registry_.set_kol_buy_count(token, static_cast<uint8_t>(std::min(kol_count, 255)));

    TokenIntelSnapshot snap{};
    if (registry_.snapshot_for(token, snap)) {
        FourMemeScoreResult sc = registry_.score(snap, 0.15f, 0.90f);
        if (sc.score >= 0.70f) {
            emit_intel_json(token, snap, sc);
        }
    }
    LOG_INF("IPC: KOL buy signal for %s (kol_count=%d)", token_hex.c_str(), kol_count);
}

void FourMemeService::start() {
    if (running_.exchange(true)) return;
    if (!rpc_.eth_block_number(last_block_)) last_block_ = 0;

    const char* ipc_path = std::getenv("LUMINA_IPC_SOCKET");
    if (!ipc_path) ipc_path = "/tmp/lumina_ipc.sock";
    ipc_ = std::make_unique<IPCBridge>(ipc_path);
    ipc_->on_message([this](const std::string& msg) {
        handle_ipc_message(msg);
    });
    ipc_->start_server();

    th_ws_ = std::thread(&FourMemeService::thread_ws, this);
    th_poll_ = std::thread(&FourMemeService::thread_poll_blocks, this);
    th_go_ = std::thread(&FourMemeService::thread_goplus, this);
    LOG_INF("FourMemeService started");
}

void FourMemeService::stop() {
    running_ = false;
    if (ipc_) ipc_->stop();
    if (th_ws_.joinable()) th_ws_.join();
    if (th_poll_.joinable()) th_poll_.join();
    if (th_go_.joinable()) th_go_.join();
}

} // namespace lumina::fourmeme
