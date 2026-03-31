#pragma once
#include "lumina/fourmeme/token_registry.h"
#include "lumina/net/bsc_ws_client.h"
#include "lumina/net/rpc_client.h"
#include "lumina/net/honeypot_checker.h"
#include "lumina/net/ipc_bridge.h"
#include "lumina/data/bloom_filter.h"
#include "lumina/data/deployer_db.h"
#include <atomic>
#include <memory>
#include <queue>
#include <string>
#include <thread>

namespace lumina::fourmeme {

class FourMemeService {
public:
    FourMemeService(std::string http_rpc_primary, std::string http_rpc_fallback, std::string wss_url,
                    DeployerDB& deployers, BloomFilter<2097152>& smart_money);

    void start();
    void stop();

private:
    void thread_ws();
    void thread_poll_blocks();
    void thread_goplus();
    void handle_log_entry(const RpcLogEntry& log);
    void handle_ipc_message(const std::string& json_line);
    static std::string block_to_hex(uint64_t bn);
    void emit_intel_json(const Address& token, const TokenIntelSnapshot& snap, const FourMemeScoreResult& score);

    std::string wss_;
    DeployerDB& deployers_;
    BloomFilter<2097152>& smart_money_;

    BscRpcClient rpc_;
    std::atomic<bool> running_{false};
    std::thread th_ws_;
    std::thread th_poll_;
    std::thread th_go_;

    TokenRegistry registry_;
    uint64_t last_block_ = 0;

    HoneypotChecker goplus_;
    std::mutex goq_mu_;
    std::queue<Address> goq_;
    std::mutex io_mu_;

    std::unique_ptr<IPCBridge> ipc_;
};

} // namespace lumina::fourmeme
