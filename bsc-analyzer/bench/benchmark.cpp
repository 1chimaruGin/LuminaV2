// ============================================================
// Lumina BSC Tier 1 — Pipeline Benchmark
// ============================================================
// Measures throughput and latency of the full pipeline:
//   Parser → Detector → Scorer → Decision
// Uses synthetic transactions to stress-test all stages.
// ============================================================
#include "lumina/core/config.h"
#include "lumina/core/types.h"
#include "lumina/pipeline/tx_parser.h"
#include "lumina/pipeline/detector.h"
#include "lumina/pipeline/scorer.h"
#include "lumina/data/deployer_db.h"
#include "lumina/tracking/logger.h"

#include <chrono>
#include <cstdio>
#include <cstring>
#include <vector>

using namespace lumina;

// --- Synthetic transaction generators ---

static RawEvent make_add_liquidity_event(uint64_t value_bnb_wei) {
    char json[4096];
    int len = std::snprintf(json, sizeof(json),
        R"({"hash":"0x%064x","from":"0x%040x","to":"0x10ED43C718714eb63d5aA57B78B54704E256024E",)"
        R"("value":"0x%lx","gasPrice":"0x12a05f200",)"
        R"("input":"0xf305d71900000000000000000000000042069abcdef12345678901234567890abcdef1234")"
        R"(,"nonce":"0x1","blockNumber":null})",
        rand(), rand(), value_bnb_wei);
    RawEvent ev;
    ev.set(json, len);
    return ev;
}

static RawEvent make_swap_event() {
    char json[4096];
    int len = std::snprintf(json, sizeof(json),
        R"({"hash":"0x%064x","from":"0x%040x","to":"0x10ED43C718714eb63d5aA57B78B54704E256024E",)"
        R"("value":"0x2386f26fc10000","gasPrice":"0x12a05f200",)"
        R"("input":"0x7ff36ab5000000000000000000000000000000000000000000000000000000000000002000000000000000000000000042069abc")"
        R"(,"nonce":"0x5","blockNumber":null})",
        rand(), rand());
    RawEvent ev;
    ev.set(json, len);
    return ev;
}

static RawEvent make_contract_creation_event() {
    char json[4096];
    int len = std::snprintf(json, sizeof(json),
        R"({"hash":"0x%064x","from":"0x%040x","to":null,)"
        R"("value":"0x0","gasPrice":"0x12a05f200",)"
        R"("input":"0x608060405234801561001057600080fd5b506040516105d83803806105d88339818101604052810190610036919061013")"
        R"(,"nonce":"0x0","blockNumber":null})",
        rand(), rand());
    RawEvent ev;
    ev.set(json, len);
    return ev;
}

// --- Benchmark functions ---

static void bench_parser(size_t iterations) {
    TxParser parser;
    std::vector<RawEvent> events;
    events.reserve(iterations);
    for (size_t i = 0; i < iterations; ++i) {
        switch (i % 3) {
            case 0: events.push_back(make_add_liquidity_event(1000000000000000000ULL)); break;
            case 1: events.push_back(make_swap_event()); break;
            case 2: events.push_back(make_contract_creation_event()); break;
        }
    }

    auto start = std::chrono::high_resolution_clock::now();
    ParsedTx out;
    for (size_t i = 0; i < iterations; ++i) {
        parser.parse(events[i], out);
    }
    auto end = std::chrono::high_resolution_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

    std::printf("  Parser:   %zu ops in %ld ms  (%.0f ns/op, %.1fM ops/sec)\n",
                iterations, ns / 1000000,
                double(ns) / iterations,
                double(iterations) / ns * 1e9 / 1e6);
}

static void bench_detector(size_t iterations) {
    Config cfg;
    DeployerDB deployers;
    BlacklistDB blacklist;
    BytecodeDB bytecodes;
    Detector detector(cfg, deployers, blacklist, bytecodes);
    TxParser parser;

    std::vector<ParsedTx> txns;
    txns.reserve(iterations);
    for (size_t i = 0; i < iterations; ++i) {
        RawEvent ev = make_add_liquidity_event(1000000000000000000ULL);
        ParsedTx out;
        parser.parse(ev, out);
        txns.push_back(out);
    }

    auto start = std::chrono::high_resolution_clock::now();
    for (size_t i = 0; i < iterations; ++i) {
        detector.detect(txns[i]);
    }
    auto end = std::chrono::high_resolution_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

    std::printf("  Detector: %zu ops in %ld ms  (%.0f ns/op, %.1fM ops/sec)\n",
                iterations, ns / 1000000,
                double(ns) / iterations,
                double(iterations) / ns * 1e9 / 1e6);
}

static void bench_scorer(size_t iterations) {
    Config cfg;
    Scorer scorer(cfg);

    DetectionResult det{};
    det.deployer_score = 0.7f;
    det.bytecode_is_scam = false;
    det.deployer_blacklisted = false;
    det.has_mint_authority = false;
    det.has_dangerous_funcs = false;
    det.lp_locked = true;
    det.lp_lock_percent = 1.0f;
    det.lp_lock_duration_days = 180;
    det.tx.event_type = EventType::ADD_LIQUIDITY;
    det.tx.value_wei = 2000000000000000000ULL;
    det.tx.recv_time = now_ns();

    auto start = std::chrono::high_resolution_clock::now();
    for (size_t i = 0; i < iterations; ++i) {
        scorer.score(det);
    }
    auto end = std::chrono::high_resolution_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

    std::printf("  Scorer:   %zu ops in %ld ms  (%.0f ns/op, %.1fM ops/sec)\n",
                iterations, ns / 1000000,
                double(ns) / iterations,
                double(iterations) / ns * 1e9 / 1e6);
}

static void bench_end_to_end(size_t iterations) {
    Config cfg;
    DeployerDB deployers;
    BlacklistDB blacklist;
    BytecodeDB bytecodes;
    TxParser parser;
    Detector detector(cfg, deployers, blacklist, bytecodes);
    Scorer scorer(cfg);

    std::vector<RawEvent> events;
    events.reserve(iterations);
    for (size_t i = 0; i < iterations; ++i) {
        events.push_back(make_add_liquidity_event(1000000000000000000ULL));
    }

    auto start = std::chrono::high_resolution_clock::now();
    for (size_t i = 0; i < iterations; ++i) {
        ParsedTx parsed;
        parser.parse(events[i], parsed);
        DetectionResult det = detector.detect(parsed);
        scorer.score(det);
    }
    auto end = std::chrono::high_resolution_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

    std::printf("  E2E:      %zu ops in %ld ms  (%.0f ns/op, %.1fM ops/sec)\n",
                iterations, ns / 1000000,
                double(ns) / iterations,
                double(iterations) / ns * 1e9 / 1e6);
}

int main() {
    std::printf("=== Lumina Tier 1 Pipeline Benchmark ===\n\n");

    constexpr size_t N = 1000000;
    std::printf("Running %zu iterations per benchmark...\n\n", N);

    bench_parser(N);
    bench_detector(N);
    bench_scorer(N);
    bench_end_to_end(N);

    std::printf("\nDone.\n");
    return 0;
}
