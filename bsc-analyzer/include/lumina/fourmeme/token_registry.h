#pragma once
#include "lumina/core/types.h"
#include "lumina/data/bloom_filter.h"
#include "lumina/data/deployer_db.h"
#include "lumina/net/rpc_client.h"
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace lumina::fourmeme {

struct TokenIntelSnapshot {
    Address token{};
    Address creator{};
    uint64_t launch_block = 0;
    uint64_t advise_min_entry_block = 0;
    double hhi = 0.0; // 0..1 approximate
    uint32_t transfer_count = 0;
    uint32_t unique_recipients_launch_window = 0;
    bool bundle_heavy = false;
    uint32_t wash_like_wallet_count = 0;
    double wash_ratio = 0.0;
    bool smart_money_touch = false;
    TokenManagerCurveInfo curve{};
    bool goplus_honeypot = false;
    bool goplus_checked = false;
    float deployer_score = 0.5f;
    bool deployer_known = false;
    uint8_t kol_buy_count = 0;
};

struct FourMemeScoreResult {
    float score = 0.5f;
    bool hard_veto = false;
    std::string veto_reason;
    ::lumina::Decision decision = ::lumina::Decision::FORWARD_TIER2;
    float position_pct = 0.25f;
};

class TokenRegistry {
public:
    explicit TokenRegistry(const DeployerDB* deployers, const BloomFilter<2097152>* smart_money_bloom);

    void set_max_tracked(size_t n) { max_tracked_ = n; }
    void set_bundle_unique_threshold(uint32_t n) { bundle_threshold_ = n; }
    void set_hhi_veto_threshold(double t) { hhi_veto_ = t; }

    void on_token_create(const Address& creator, const Address& token, uint64_t block_number);
    void on_transfer(const Address& token, const Address& from, const Address& to, std::string_view value_hex,
                     uint64_t block_number);

    std::vector<Address> active_tokens_snapshot() const;
    void set_curve_info(const Address& token, const TokenManagerCurveInfo& c);
    void set_goplus(const Address& token, bool is_honeypot);
    void set_kol_buy_count(const Address& token, uint8_t count);

    bool snapshot_for(const Address& token, TokenIntelSnapshot& out) const;
    FourMemeScoreResult score(const TokenIntelSnapshot& snap, float hard_reject, float fast_pass) const;

private:
    struct WalletFlow {
        double buy = 0.0;
        double sell = 0.0;
    };

    struct Session {
        Address token{};
        Address creator{};
        uint64_t launch_block = 0;
        std::unordered_map<Address, double, AddressHash> balance_wei_est;
        double sum_sq_bal = 0.0;
        uint32_t transfer_count = 0;
        std::unordered_map<uint64_t, std::unordered_set<Address, AddressHash>> recv_by_block;
        std::unordered_map<Address, WalletFlow, AddressHash> flows;
        TokenManagerCurveInfo curve{};
        bool goplus_honeypot = false;
        bool goplus_checked = false;
        uint8_t kol_buy_count = 0;
    };

    void evict_if_needed();
    void recompute_hhi(Session& s);
    static double wei_to_tokens(double wei);

    const DeployerDB* deployers_;
    const BloomFilter<2097152>* smart_money_;

    mutable std::mutex mu_;
    std::unordered_map<Address, Session, AddressHash> sessions_;
    std::deque<Address> insert_order_;
    size_t max_tracked_ = 256;
    uint32_t bundle_threshold_ = 4;
    double hhi_veto_ = 0.25; // sum (s_i)^2 above this => concentrated
};

} // namespace lumina::fourmeme
