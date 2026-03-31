// ============================================================
// Lumina BSC — Four.meme intelligence (intel-only, filter_1 / filter_2 alignment)
// ============================================================
#include "lumina/core/types.h"
#include "lumina/data/deployer_db.h"
#include "lumina/fourmeme/constants.h"
#include "lumina/fourmeme/fourmeme_service.h"
#include "lumina/tracking/logger.h"
#include "lumina/data/bloom_filter.h"

#include <atomic>
#include <chrono>
#include <cctype>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <thread>

static std::atomic<bool> g_running{true};

static void signal_handler(int) { g_running.store(false); }

static void load_smart_money_file(const char* path, lumina::BloomFilter<2097152>& bf) {
    if (!path || !*path) return;
    std::ifstream in(path);
    std::string line;
    size_t n = 0;
    while (std::getline(in, line)) {
        while (!line.empty() && std::isspace(static_cast<unsigned char>(line.back()))) line.pop_back();
        if (line.empty() || line[0] == '#') continue;
        auto a = lumina::hex_to_address(line);
        bf.insert(a.data(), 20);
        ++n;
    }
    LOG_INF("Loaded %zu smart-money addresses from %s", n, path);
}

int main(int, char**) {
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    const char* rpc = std::getenv("QUICK_NODE_BSC_RPC");
    if (!rpc || !*rpc) {
        LOG_ERR("QUICK_NODE_BSC_RPC is required");
        return 1;
    }
    const char* rpc_fb = std::getenv("ALCHEMY_BSC_RPC");
    std::string wss = lumina::fourmeme::http_rpc_to_ws_url(rpc);
    const char* wss_env = std::getenv("BSC_WS_URL");
    if (wss_env && *wss_env) wss = wss_env;

    lumina::DeployerDB deployers;
    const char* deployer_csv = std::getenv("DEPLOYER_CSV");
    if (deployer_csv) {
        size_t n = deployers.load_csv(deployer_csv);
        LOG_INF("Loaded %zu deployer records from %s", n, deployer_csv);
    }

    lumina::BloomFilter<2097152> smart_money;
    const char* smf = std::getenv("SMART_MONEY_FILE");
    load_smart_money_file(smf, smart_money);

    LOG_INF("=== Lumina Four.meme BSC intelligence (v1) ===");
    lumina::fourmeme::FourMemeService svc(rpc, rpc_fb ? rpc_fb : "", std::move(wss), deployers, smart_money);
    svc.start();
    LOG_INF("JSONL on stdout. Progress on stderr. Ctrl+C to stop.");
    while (g_running.load()) std::this_thread::sleep_for(std::chrono::seconds(1));
    svc.stop();
    return 0;
}
