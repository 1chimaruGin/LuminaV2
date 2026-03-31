// ============================================================
// Lumina BSC Tier 1 — Deployer & Blacklist DB Implementation
// ============================================================
#include "lumina/data/deployer_db.h"
#include <fstream>
#include <sstream>

namespace lumina {

// --- DeployerDB ---

DeployerDB::DeployerDB() : active_(&buf_a_), shadow_(&buf_b_) {}

std::optional<DeployerReputation> DeployerDB::lookup(const Address& addr) const noexcept {
    const auto* map = active_.load(std::memory_order_acquire);
    auto it = map->find(addr);
    if (it != map->end()) return it->second;
    return std::nullopt;
}

void DeployerDB::upsert(const Address& addr, const DeployerReputation& rep) {
    std::lock_guard<std::mutex> lock(write_mutex_);
    (*shadow_.load())[addr] = rep;
}

void DeployerDB::publish() {
    std::lock_guard<std::mutex> lock(write_mutex_);
    auto* a = active_.load(std::memory_order_relaxed);
    auto* s = shadow_.load(std::memory_order_relaxed);
    active_.store(s, std::memory_order_release);
    shadow_.store(a, std::memory_order_relaxed);
}

size_t DeployerDB::load_csv(const std::string& path) {
    // CSV format from build_deployer_db.py:
    // deployer,total_tokens,rugged,honeypots,successful,avg_lifespan_hours,success_rate,rug_rate,score,first_seen_block,last_seen_block
    std::ifstream file(path);
    if (!file) return 0;
    std::string line;
    size_t count = 0;
    std::getline(file, line); // skip header
    while (std::getline(file, line)) {
        std::istringstream ss(line);
        std::string addr_hex, total_s, rugged_s, honeypots_s, successful_s;
        std::string lifespan_s, success_rate_s, rug_rate_s, score_s;
        std::string first_block_s, last_block_s;
        
        if (!std::getline(ss, addr_hex, ',')) continue;
        std::getline(ss, total_s, ',');
        std::getline(ss, rugged_s, ',');
        std::getline(ss, honeypots_s, ',');
        std::getline(ss, successful_s, ',');
        std::getline(ss, lifespan_s, ',');
        std::getline(ss, success_rate_s, ',');
        std::getline(ss, rug_rate_s, ',');
        std::getline(ss, score_s, ',');
        std::getline(ss, first_block_s, ',');
        std::getline(ss, last_block_s, ',');
        
        Address addr = hex_to_address(addr_hex);
        DeployerReputation rep{};
        rep.total_deploys = static_cast<uint16_t>(std::stoi(total_s));
        rep.rug_count = static_cast<uint16_t>(std::stoi(rugged_s));
        rep.honeypot_count = static_cast<uint16_t>(std::stoi(honeypots_s));
        rep.success_count = static_cast<uint16_t>(std::stoi(successful_s));
        rep.avg_lifespan_hours = std::stof(lifespan_s);
        rep.success_rate = std::stof(success_rate_s);
        rep.rug_rate = std::stof(rug_rate_s);
        rep.score = std::stof(score_s);
        rep.first_seen_block = static_cast<uint32_t>(std::stoul(first_block_s));
        rep.last_seen_block = static_cast<uint32_t>(std::stoul(last_block_s));
        
        // Set flags based on score
        if (rep.score < DeployerReputation::SCORE_SKIP) {
            rep.flags = DeployerReputation::KNOWN_SCAMMER;
        } else if (rep.score >= DeployerReputation::SCORE_AUTO_SNIPE) {
            rep.flags = DeployerReputation::KNOWN_LEGIT;
        } else {
            rep.flags = DeployerReputation::NONE;
        }
        if (rep.total_deploys >= 10) {
            rep.flags |= DeployerReputation::SERIAL_DEPLOYER;
        }
        
        (*shadow_.load())[addr] = rep;
        count++;
    }
    publish();
    return count;
}

size_t DeployerDB::size() const {
    return active_.load(std::memory_order_acquire)->size();
}

// --- BlacklistDB ---

void BlacklistDB::add(const Address& a) {
    bloom_.insert(a);
    std::lock_guard<std::mutex> l(m_);
    confirmed_[a] = true;
}

bool BlacklistDB::maybe_blacklisted(const Address& a) const noexcept {
    return bloom_.maybe_contains(a);
}

bool BlacklistDB::is_blacklisted(const Address& a) const {
    if (!bloom_.maybe_contains(a)) return false;
    std::lock_guard<std::mutex> l(m_);
    return confirmed_.count(a) > 0;
}

size_t BlacklistDB::load_file(const std::string& path) {
    std::ifstream f(path);
    if (!f) return 0;
    std::string line;
    size_t c = 0;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        add(hex_to_address(line));
        c++;
    }
    return c;
}

size_t BlacklistDB::size() const { return bloom_.count(); }

// --- BytecodeDB ---

void BytecodeDB::add_scam_hash(const Hash32& h, const std::string& label, float risk) {
    bloom_.insert(h);
    confirmed_[h] = {label, risk};
}

bool BytecodeDB::maybe_scam(const Hash32& h) const noexcept {
    return bloom_.maybe_contains(h);
}

std::optional<BytecodeInfo> BytecodeDB::check(const Hash32& h) const {
    if (!bloom_.maybe_contains(h)) return std::nullopt;
    auto it = confirmed_.find(h);
    if (it != confirmed_.end()) return it->second;
    return std::nullopt;
}

size_t BytecodeDB::size() const { return confirmed_.size(); }

} // namespace lumina
