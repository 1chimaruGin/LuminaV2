#include "lumina/fourmeme/token_registry.h"
#include "lumina/fourmeme/constants.h"
#include <algorithm>
#include <cmath>
#include <cstdio>

namespace lumina::fourmeme {

static uint64_t parse_hex_u64_tail(std::string_view hex) {
    std::string_view h = hex;
    if (h.size() >= 2 && h[0] == '0' && (h[1] == 'x' || h[1] == 'X')) h.remove_prefix(2);
    if (h.size() > 16) h = h.substr(h.size() - 16);
    uint64_t v = 0;
    for (char c : h) {
        v <<= 4;
        if (c >= '0' && c <= '9') v |= static_cast<uint64_t>(c - '0');
        else if (c >= 'a' && c <= 'f') v |= static_cast<uint64_t>(10 + c - 'a');
        else if (c >= 'A' && c <= 'F') v |= static_cast<uint64_t>(10 + c - 'A');
    }
    return v;
}

double TokenRegistry::wei_to_tokens(double wei) { return wei / 1e18; }

void TokenRegistry::recompute_hhi(Session& s) {
    double sum_sq = 0.0;
    for (const auto& [addr, wei_est] : s.balance_wei_est) {
        (void)addr;
        double t = wei_to_tokens(wei_est);
        sum_sq += t * t;
    }
    s.sum_sq_bal = sum_sq;
}

TokenRegistry::TokenRegistry(const DeployerDB* deployers, const BloomFilter<2097152>* smart_money)
    : deployers_(deployers), smart_money_(smart_money) {}

void TokenRegistry::evict_if_needed() {
    while (sessions_.size() > max_tracked_ && !insert_order_.empty()) {
        Address old = insert_order_.front();
        insert_order_.pop_front();
        sessions_.erase(old);
    }
}

void TokenRegistry::on_token_create(const Address& creator, const Address& token, uint64_t block_number) {
    std::lock_guard<std::mutex> lock(mu_);
    if (sessions_.count(token)) return;
    evict_if_needed();
    Session s{};
    s.token = token;
    s.creator = creator;
    s.launch_block = block_number;
    sessions_[token] = std::move(s);
    insert_order_.push_back(token);
}

void TokenRegistry::on_transfer(const Address& token, const Address& from, const Address& to,
                                std::string_view value_hex, uint64_t block_number) {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = sessions_.find(token);
    if (it == sessions_.end()) return;
    Session& s = it->second;
    double amt = static_cast<double>(parse_hex_u64_tail(value_hex));
    if (amt <= 0) return;

    auto upd_bal = [&](const Address& a, double delta) {
        if (lumina::is_zero(a)) return;
        double& b = s.balance_wei_est[a];
        b += delta;
        if (std::abs(b) < 1e-6) s.balance_wei_est.erase(a);
    };

    if (!lumina::is_zero(from)) upd_bal(from, -amt);
    if (!lumina::is_zero(to)) upd_bal(to, amt);

    if (!lumina::is_zero(from) && !lumina::is_zero(to)) {
        s.flows[from].sell += amt;
        s.flows[to].buy += amt;
    } else if (lumina::is_zero(from) && !lumina::is_zero(to)) {
        s.flows[to].buy += amt;
    } else if (!lumina::is_zero(from) && lumina::is_zero(to)) {
        s.flows[from].sell += amt;
    }

    s.transfer_count++;
    if (block_number <= s.launch_block + 2) {
        if (!lumina::is_zero(to)) s.recv_by_block[block_number].insert(to);
    }

    recompute_hhi(s);
}

std::vector<Address> TokenRegistry::active_tokens_snapshot() const {
    std::lock_guard<std::mutex> lock(mu_);
    std::vector<Address> v;
    v.reserve(sessions_.size());
    for (const auto& [t, _] : sessions_) {
        (void)_;
        v.push_back(t);
    }
    return v;
}

void TokenRegistry::set_curve_info(const Address& token, const TokenManagerCurveInfo& c) {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = sessions_.find(token);
    if (it == sessions_.end()) return;
    it->second.curve = c;
}

void TokenRegistry::set_goplus(const Address& token, bool is_honeypot) {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = sessions_.find(token);
    if (it == sessions_.end()) return;
    it->second.goplus_honeypot = is_honeypot;
    it->second.goplus_checked = true;
}

void TokenRegistry::set_kol_buy_count(const Address& token, uint8_t count) {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = sessions_.find(token);
    if (it == sessions_.end()) return;
    if (count > it->second.kol_buy_count)
        it->second.kol_buy_count = count;
}

bool TokenRegistry::snapshot_for(const Address& token, TokenIntelSnapshot& out) const {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = sessions_.find(token);
    if (it == sessions_.end()) return false;
    const Session& s = it->second;
    out.token = s.token;
    out.creator = s.creator;
    out.launch_block = s.launch_block;
    out.advise_min_entry_block = s.launch_block + XMODE_MIN_BLOCK_OFFSET;
    constexpr double supply_sq = 1e9 * 1e9;
    out.hhi = (supply_sq > 0) ? (s.sum_sq_bal / supply_sq) : 0.0;
    out.transfer_count = s.transfer_count;
    std::unordered_set<Address, AddressHash> uni;
    for (uint64_t b = s.launch_block; b <= s.launch_block + 2; ++b) {
        auto j = s.recv_by_block.find(b);
        if (j != s.recv_by_block.end()) {
            for (const auto& a : j->second) uni.insert(a);
        }
    }
    out.unique_recipients_launch_window = static_cast<uint32_t>(uni.size());
    out.bundle_heavy = out.unique_recipients_launch_window >= bundle_threshold_;
    uint32_t wash = 0;
    uint32_t active_traders = 0;
    for (const auto& [addr, f] : s.flows) {
        (void)addr;
        if (f.buy <= 0 || f.sell <= 0) continue;
        active_traders++;
        double mx = std::max(f.buy, f.sell);
        if (mx > 0 && std::abs(f.buy - f.sell) / mx <= 0.02) ++wash;
    }
    out.wash_like_wallet_count = wash;
    out.wash_ratio = active_traders ? (static_cast<double>(wash) / active_traders) : 0.0;
    out.curve = s.curve;
    out.goplus_honeypot = s.goplus_honeypot;
    out.goplus_checked = s.goplus_checked;
    out.smart_money_touch = false;
    if (smart_money_) {
        if (smart_money_->maybe_contains(s.creator.data(), 20)) out.smart_money_touch = true;
    }
    out.deployer_known = false;
    out.deployer_score = 0.5f;
    if (deployers_) {
        auto rep = deployers_->lookup(s.creator);
        if (rep.has_value()) {
            out.deployer_known = true;
            out.deployer_score = rep->score;
            if (rep->is_scammer()) out.deployer_score = 0.0f;
        }
    }
    out.kol_buy_count = s.kol_buy_count;
    return true;
}

FourMemeScoreResult TokenRegistry::score(const TokenIntelSnapshot& snap, float hard_reject,
                                           float fast_pass) const {
    FourMemeScoreResult r{};
    if (snap.goplus_checked && snap.goplus_honeypot) {
        r.hard_veto = true;
        r.veto_reason = "goplus_honeypot";
        r.score = 0.0f;
        r.decision = ::lumina::Decision::HARD_REJECT;
        return r;
    }
    if (snap.bundle_heavy) {
        r.hard_veto = true;
        r.veto_reason = "bundle_heavy";
        r.score = 0.0f;
        r.decision = ::lumina::Decision::HARD_REJECT;
        return r;
    }
    if (snap.hhi > hhi_veto_) {
        r.hard_veto = true;
        r.veto_reason = "hhi_concentration";
        r.score = 0.0f;
        r.decision = ::lumina::Decision::HARD_REJECT;
        return r;
    }
    if (snap.deployer_known && snap.deployer_score <= 0.01f) {
        r.hard_veto = true;
        r.veto_reason = "deployer_scammer";
        r.score = 0.0f;
        r.decision = ::lumina::Decision::HARD_REJECT;
        return r;
    }
    if (snap.wash_ratio > 0.2) {
        r.hard_veto = true;
        r.veto_reason = "wash_ratio";
        r.score = 0.0f;
        r.decision = ::lumina::Decision::HARD_REJECT;
        return r;
    }

    // KOL buys are the strongest signal for Four.meme tokens.
    // 2+ KOL buyers → FAST_PASS, 1 KOL buyer → strong FORWARD_TIER2.
    if (snap.kol_buy_count >= 2) {
        r.score = 0.92f;
        r.decision = ::lumina::Decision::FAST_PASS;
        r.position_pct = 0.25f;
        return r;
    }
    if (snap.kol_buy_count == 1) {
        r.score = 0.75f;
        r.decision = ::lumina::Decision::FORWARD_TIER2;
        r.position_pct = 0.20f;
        return r;
    }

    float s = 0.35f;
    if (snap.deployer_known) s += 0.25f * snap.deployer_score;
    else s += 0.12f;
    if (snap.curve.valid && snap.curve.max_funds_wei > 0) {
        float prog = static_cast<float>(snap.curve.funds_wei) / static_cast<float>(snap.curve.max_funds_wei);
        s += 0.15f * std::min(prog, 1.0f);
    }
    if (snap.smart_money_touch) s += 0.15f;
    if (snap.transfer_count >= 60) s += 0.1f;
    r.score = std::min(s, 1.0f);
    if (r.score < hard_reject) {
        r.decision = ::lumina::Decision::HARD_REJECT;
        r.position_pct = 0.0f;
    } else if (r.score >= fast_pass) {
        r.decision = ::lumina::Decision::FAST_PASS;
        r.position_pct = 0.25f;
    } else {
        r.decision = ::lumina::Decision::FORWARD_TIER2;
        r.position_pct = 0.15f;
    }
    return r;
}

} // namespace lumina::fourmeme
