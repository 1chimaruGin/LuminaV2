// Four.meme TokenCreate replay via HTTP eth_getLogs (chunked ranges for performance).
#include "lumina/fourmeme/constants.h"
#include "lumina/fourmeme/token_create_abi.h"
#include "lumina/fourmeme/token_registry.h"
#include "lumina/net/rpc_client.h"
#include "lumina/data/deployer_db.h"
#include "lumina/data/bloom_filter.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using namespace lumina;

enum class OutFmt { Json, Tsv };

static std::string block_hex(uint64_t b) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "0x%lx", static_cast<unsigned long>(b));
    return buf;
}

static std::string json_escape(std::string_view s) {
    std::string o;
    o.reserve(s.size() + 8);
    for (char c : s) {
        switch (c) {
            case '"':
                o += "\\\"";
                break;
            case '\\':
                o += "\\\\";
                break;
            case '\n':
                o += "\\n";
                break;
            case '\r':
                o += "\\r";
                break;
            case '\t':
                o += "\\t";
                break;
            default:
                o += c;
        }
    }
    return o;
}

static void tsv_sanitize(std::string& s) {
    for (char& c : s) {
        if (c == '\t' || c == '\n' || c == '\r') c = ' ';
    }
}

static void process_logs(fourmeme::TokenRegistry& reg, BscRpcClient& client,
                         const std::vector<RpcLogEntry>& logs,
                         const std::string& topic_create_lower,
                         const std::string& topic_create_legacy_lower,
                         uint64_t& n_creates, double& score_sum, uint32_t& n_hard_reject, uint32_t& n_fast_pass,
                         uint64_t& n_passed_decision, uint64_t& n_lines_out, bool passed_only, OutFmt fmt) {
    for (const auto& lg : logs) {
        if (lg.topics.empty()) continue;
        std::string t0 = lg.topics[0];
        std::transform(t0.begin(), t0.end(), t0.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

        Address creator{}, token{};
        std::string name, symbol;

        if (t0 == topic_create_lower) {
            // Current ABI: all params in data (no indexed topics)
            if (!fourmeme::decode_token_create_data_v2(lg.data, creator, token, name, symbol)) continue;
        } else if (t0 == topic_create_legacy_lower && lg.topics.size() >= 3) {
            // Legacy ABI: creator+token indexed in topics
            if (!fourmeme::topic_to_address(lg.topics[1], creator)) continue;
            if (!fourmeme::topic_to_address(lg.topics[2], token)) continue;
            (void)fourmeme::decode_token_create_data_legacy(lg.data, name, symbol);
        } else {
            continue;
        }

        reg.on_token_create(creator, token, lg.block_number);
        TokenManagerCurveInfo c{};
        (void)client.eth_get_token_info_curve(token, c);
        reg.set_curve_info(token, c);
        fourmeme::TokenIntelSnapshot snap{};
        if (!reg.snapshot_for(token, snap)) continue;
        auto sc = reg.score(snap, 0.15f, 0.90f);
        n_creates++;
        score_sum += static_cast<double>(sc.score);
        if (sc.decision == lumina::Decision::HARD_REJECT) ++n_hard_reject;
        if (sc.decision == lumina::Decision::FAST_PASS) ++n_fast_pass;
        if (sc.decision != lumina::Decision::HARD_REJECT) ++n_passed_decision;

        if (passed_only && sc.decision == lumina::Decision::HARD_REJECT) continue;

        ++n_lines_out;
        if (fmt == OutFmt::Tsv) {
            tsv_sanitize(name);
            tsv_sanitize(symbol);
            std::printf("%s\t%s\t%s\t%.4f\n", name.c_str(), symbol.c_str(), address_to_hex(token).c_str(),
                        static_cast<double>(sc.score));
        } else {
            std::printf(
                "{\"block\":%lu,\"name\":\"%s\",\"symbol\":\"%s\",\"token\":\"%s\",\"creator\":\"%s\","
                "\"score\":%.4f,\"decision\":\"%s\",\"veto\":\"%s\"}\n",
                static_cast<unsigned long>(lg.block_number), json_escape(name).c_str(),
                json_escape(symbol).c_str(), address_to_hex(token).c_str(), address_to_hex(creator).c_str(),
                static_cast<double>(sc.score),
                sc.decision == lumina::Decision::HARD_REJECT       ? "HARD_REJECT"
                    : sc.decision == lumina::Decision::FAST_PASS   ? "FAST_PASS"
                                                                   : "FORWARD_TIER2",
                json_escape(sc.veto_reason).c_str());
        }
        std::fflush(stdout);
    }
}

static void print_usage() {
    std::fprintf(stderr,
                 "Usage:\n"
                 "  lumina_replay_fourmeme [--yesterday] [--passed-only] [--format json|tsv]\n"
                 "                         [--recent <N> | <from_block> <to_block>]\n"
                 "  --yesterday     Last REPLAY_YESTERDAY_BLOCKS (default 28800 ≈ ~24h @ 3s blocks)\n"
                 "  --passed-only   Only print tokens with decision != HARD_REJECT\n"
                 "  --format tsv    Columns: name symbol address score (default: json with name/symbol)\n"
                 "Stdout: one line per TokenCreate (after filters). Stderr: [replay] progress + summary.\n"
                 "Env: QUICK_NODE_BSC_RPC, ALCHEMY_BSC_RPC, DEPLOYER_CSV,\n"
                 "     REPLAY_CHUNK_BLOCKS (default 1 — see README; 80 often returns ZERO logs on Four.meme),\n"
                 "     REPLAY_PROGRESS_CHUNKS (default 200), REPLAY_YESTERDAY_BLOCKS (default 28800)\n");
}

int main(int argc, char** argv) {
    const char* rpc = std::getenv("QUICK_NODE_BSC_RPC");
    const char* rpc2 = std::getenv("ALCHEMY_BSC_RPC");
    if (!rpc) {
        std::fprintf(stderr, "Set QUICK_NODE_BSC_RPC\n");
        print_usage();
        return 1;
    }

    bool yesterday = false;
    bool passed_only = false;
    OutFmt fmt = OutFmt::Json;
    std::vector<char*> pos;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--yesterday") == 0) {
            yesterday = true;
            continue;
        }
        if (std::strcmp(argv[i], "--passed-only") == 0) {
            passed_only = true;
            continue;
        }
        if (std::strcmp(argv[i], "--format") == 0 && i + 1 < argc) {
            ++i;
            if (std::strcmp(argv[i], "tsv") == 0) fmt = OutFmt::Tsv;
            else if (std::strcmp(argv[i], "json") == 0) fmt = OutFmt::Json;
            else {
                std::fprintf(stderr, "Unknown --format %s (use json or tsv)\n", argv[i]);
                return 1;
            }
            continue;
        }
        if (std::strcmp(argv[i], "--help") == 0 || std::strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        }
        pos.push_back(argv[i]);
    }

    uint64_t yesterday_blocks = 28800;
    if (const char* yb = std::getenv("REPLAY_YESTERDAY_BLOCKS"); yb && *yb)
        yesterday_blocks = std::max<uint64_t>(1, std::strtoull(yb, nullptr, 0));

    // Four.meme proxy emits huge log volume; multi-block eth_getLogs often hits provider limits and
    // returns an empty "result" (you see 0 TokenCreates forever). Default 1 block per request.
    uint64_t chunk = 1;
    if (const char* cs = std::getenv("REPLAY_CHUNK_BLOCKS"); cs && *cs)
        chunk = std::max<uint64_t>(1, std::strtoull(cs, nullptr, 0));

    uint64_t progress_every = 200;
    if (const char* pe = std::getenv("REPLAY_PROGRESS_CHUNKS"); pe && *pe)
        progress_every = std::strtoull(pe, nullptr, 0);

    BscRpcClient client(rpc, rpc2 ? rpc2 : "");
    uint64_t from_b = 0, to_b = 0;
    enum class RangeMode { Yesterday, Recent, Explicit } range_mode = RangeMode::Explicit;

    if (yesterday) {
        if (!pos.empty()) {
            std::fprintf(stderr, "--yesterday does not take block arguments (use --recent or from to without "
                                 "--yesterday)\n");
            return 1;
        }
        uint64_t latest = 0;
        if (!client.eth_block_number(latest)) {
            std::fprintf(stderr, "eth_blockNumber failed\n");
            return 1;
        }
        if (latest > yesterday_blocks)
            from_b = latest - yesterday_blocks;
        else
            from_b = 0;
        to_b = latest;
        range_mode = RangeMode::Yesterday;
    } else if (pos.size() >= 2 && std::strcmp(pos[0], "--recent") == 0) {
        uint64_t n = std::strtoull(pos[1], nullptr, 0);
        uint64_t latest = 0;
        if (!client.eth_block_number(latest)) {
            std::fprintf(stderr, "eth_blockNumber failed\n");
            return 1;
        }
        if (latest > n)
            from_b = latest - n;
        else
            from_b = 0;
        to_b = latest;
        range_mode = RangeMode::Recent;
    } else if (pos.size() >= 2) {
        from_b = std::strtoull(pos[0], nullptr, 0);
        to_b = std::strtoull(pos[1], nullptr, 0);
    } else {
        print_usage();
        return 1;
    }

    if (to_b < from_b) {
        std::fprintf(stderr, "invalid range\n");
        return 1;
    }

    if (fmt == OutFmt::Tsv && !passed_only)
        std::fprintf(stderr, "note: tsv is usually paired with --passed-only for a clean name/address/score list\n");

    DeployerDB deployers;
    const char* csv = std::getenv("DEPLOYER_CSV");
    if (csv) deployers.load_csv(csv);

    BloomFilter<2097152> smart;
    fourmeme::TokenRegistry reg(&deployers, &smart);

    std::string mgr = fourmeme::PROXY_MANAGER;
    std::transform(mgr.begin(), mgr.end(), mgr.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::string tpc = fourmeme::TOPIC_TOKEN_CREATE;
    std::transform(tpc.begin(), tpc.end(), tpc.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    std::string tpc_legacy = fourmeme::TOPIC_TOKEN_CREATE_LEGACY;
    std::transform(tpc_legacy.begin(), tpc_legacy.end(), tpc_legacy.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    const auto t0 = std::chrono::steady_clock::now();
    uint64_t n_creates = 0;
    double score_sum = 0.0;
    uint32_t n_hard_reject = 0, n_fast_pass = 0;
    uint64_t n_passed_decision = 0;
    uint64_t n_lines_out = 0;

    const uint64_t total_blocks = (to_b >= from_b) ? (to_b - from_b + 1) : 0;
    uint64_t chunk_i = 0;
    for (uint64_t b = from_b; b <= to_b;) {
        uint64_t end = std::min(b + chunk - 1, to_b);
        std::vector<RpcLogEntry> logs;
        std::vector<std::string> topics_or = {tpc, tpc_legacy};
        if (!client.eth_get_logs_manager(mgr, topics_or, block_hex(b), block_hex(end), logs)) {
            std::fprintf(stderr, "getLogs failed blocks %lu..%lu (try smaller REPLAY_CHUNK_BLOCKS)\n",
                         static_cast<unsigned long>(b), static_cast<unsigned long>(end));
            b = end + 1;
            ++chunk_i;
            continue;
        }
        process_logs(reg, client, logs, tpc, tpc_legacy, n_creates, score_sum, n_hard_reject, n_fast_pass,
                     n_passed_decision, n_lines_out, passed_only, fmt);
        ++chunk_i;
        if (progress_every > 0 && (chunk_i % progress_every == 0)) {
            const auto now = std::chrono::steady_clock::now();
            auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - t0).count();
            uint64_t done_blocks = end - from_b + 1;
            std::fprintf(stderr,
                         "[replay] chunk %llu blocks %lu..%lu (%llu / %llu blocks, %llu TokenCreates, %lld ms)\n",
                         static_cast<unsigned long long>(chunk_i), static_cast<unsigned long>(b),
                         static_cast<unsigned long>(end),
                         static_cast<unsigned long long>(done_blocks),
                         static_cast<unsigned long long>(total_blocks),
                         static_cast<unsigned long long>(n_creates), static_cast<long long>(elapsed_ms));
            std::fflush(stderr);
        }
        b = end + 1;
    }

    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::steady_clock::now() - t0)
                        .count();
    double avg = (n_creates > 0) ? (score_sum / static_cast<double>(n_creates)) : 0.0;
    if (n_creates == 0 && total_blocks > 100) {
        std::fprintf(stderr,
                     "[replay] WARNING: zero TokenCreate logs over %llu blocks — RPC likely dropped "
                     "eth_getLogs (Four.meme proxy is log-heavy). Use REPLAY_CHUNK_BLOCKS=1 (default), "
                     "ALCHEMY_BSC_RPC, or another archive. Not a filter issue: nothing was ingested.\n",
                     static_cast<unsigned long long>(total_blocks));
    }
    const char* mode = range_mode == RangeMode::Yesterday   ? "yesterday"
                       : range_mode == RangeMode::Recent ? "recent"
                                                         : "explicit";
    std::fprintf(stderr,
                 "{\"summary\":{\"mode\":\"%s\",\"from_block\":%lu,\"to_block\":%lu,\"chunk\":%lu,"
                 "\"token_creates_scored\":%lu,\"passed_decision\":%lu,\"lines_emitted\":%lu,"
                 "\"avg_score\":%.4f,\"hard_reject\":%u,\"fast_pass\":%u,\"elapsed_ms\":%lld,"
                 "\"yesterday_span_blocks\":%lu,\"passed_only\":%s,\"format\":\"%s\"}}\n",
                 mode, static_cast<unsigned long>(from_b), static_cast<unsigned long>(to_b),
                 static_cast<unsigned long>(chunk), static_cast<unsigned long>(n_creates),
                 static_cast<unsigned long>(n_passed_decision), static_cast<unsigned long>(n_lines_out), avg,
                 n_hard_reject, n_fast_pass, static_cast<long long>(ms),
                 static_cast<unsigned long>(range_mode == RangeMode::Yesterday ? yesterday_blocks : 0ULL),
                 passed_only ? "true" : "false",
                 fmt == OutFmt::Tsv ? "tsv" : "json");
    return 0;
}
