// ============================================================
// Lumina BSC Tier 1 — Deployer & Blacklist Databases
// ============================================================
// DeployerDB  – Lock-free double-buffered wallet reputation map.
//               Readers never block; writers swap buffers atomically.
// BlacklistDB – Bloom filter + confirmed set for O(1) blacklist.
// BytecodeDB  – Bloom filter + hash map for known scam bytecode.
// ============================================================
#pragma once
#include "lumina/core/types.h"
#include "lumina/data/bloom_filter.h"
#include <mutex>
#include <optional>
#include <unordered_map>
#include <string>

namespace lumina {

class DeployerDB {
public:
    DeployerDB();
    std::optional<DeployerReputation> lookup(const Address& addr) const noexcept;
    void   upsert(const Address& addr, const DeployerReputation& rep);
    void   publish();
    size_t load_csv(const std::string& path);
    size_t size() const;
private:
    using Map = std::unordered_map<Address, DeployerReputation, AddressHash>;
    Map buf_a_, buf_b_;
    std::atomic<Map*> active_;
    std::atomic<Map*> shadow_;
    std::mutex write_mutex_;
};

class BlacklistDB {
public:
    void   add(const Address& a);
    bool   maybe_blacklisted(const Address& a) const noexcept;
    bool   is_blacklisted(const Address& a) const;
    size_t load_file(const std::string& path);
    size_t size() const;
private:
    BloomFilter<> bloom_;
    std::unordered_map<Address, bool, AddressHash> confirmed_;
    mutable std::mutex m_;
};

struct BytecodeInfo {
    std::string label;
    float risk_score;
};

class BytecodeDB {
public:
    void add_scam_hash(const Hash32& h, const std::string& label, float risk = 1.0f);
    bool maybe_scam(const Hash32& h) const noexcept;
    std::optional<BytecodeInfo> check(const Hash32& h) const;
    size_t size() const;
private:
    BloomFilter<> bloom_;
    std::unordered_map<Hash32, BytecodeInfo, Hash32Hash> confirmed_;
};

} // namespace lumina
