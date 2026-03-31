#pragma once
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <unordered_set>
#include <vector>

namespace lumina {

struct SignalRow {
    std::string token_address;
    std::string name;
    std::string creator;
    uint64_t create_block = 0;
    bool create_block_known = false;

    int create_hour_utc = 12;
    int create_dow = 3;
    std::string create_time_iso;

    int deployer_prior_launches = 0;
    int deployer_prior_grads = 0;
    double deployer_grad_rate = 0.0;

    double dev_buy_usd = 0.0;
    double dev_sell_usd = 0.0;
    double dev_sell_pct_supply = 0.0;

    int kol_count = 0;
    struct KolSlot {
        std::string name;
        int64_t buy_block = -1;
        double buy_usd = 0.0;
        uint64_t holder_count = 0; // unique holders at this KOL's buy block
    };
    KolSlot kol[5];
    std::string combo_k1k2;
    std::string combo_k1k2k3;
    double combined_notional_k1k2_usd = 0.0;
    double kol1_7d_win_rate = -1.0;
    double kol2_7d_win_rate = -1.0;
    int64_t kol1_kol2_delta_blocks = -1;
    int64_t kol2_kol3_delta_blocks = -1;

    double entry_mcap_usd = 0.0;
    double current_mcap_usd = 0.0;
    double bonding_curve_pct = 0.0;
    double bnb_price_usd = 0.0;
    uint64_t age_blocks = 0;
    uint64_t holder_count = 0;
    double holder_growth_k1_to_k2 = 0.0;
    double holder_growth_k2_to_entry = 0.0;

    double ml_score = 0.0;
    int mode = 0;
    std::string mode_label;
    double position_bnb = 0.0;
    double sl_x = 0.0;

    std::string signal_block;
    std::string signal_tx;

    double deployer_score = 0.0;
    double deployer_success_rate = 0.0;
    int deployer_successful = 0;
    int deployer_total_tokens = 0;

    double btc_4h_change_pct = 0.0;
    double bnb_4h_change_pct = 0.0;
    bool macro_available = false;

    bool shadow = false;
};

struct LiveWriterConfig {
    std::string csv_path;
    std::string jsonl_path;
    std::string paper_csv_path;
    bool fresh_output = false;
    int first_signal_min_kol_count = 0;
    bool tokens_newer_than_session = false;
    uint64_t session_start_block = 0;
    int paper_min_mode = 2;
    double paper_min_ml_score = 0.5;
    int paper_min_kol_count = 2;
    bool require_create_block_known = true;
};

class LiveDatasetWriter {
public:
    explicit LiveDatasetWriter(const LiveWriterConfig& cfg);
    ~LiveDatasetWriter();

    bool init();

    // Returns true if dataset row was written (passed filters + dedup).
    bool write_signal(const SignalRow& row);

    // Paper gate: check thresholds and write paper CSV if passed.
    bool check_paper_gate(const SignalRow& row);

    int rows_written() const { return row_count_; }
    int paper_hits() const { return paper_count_; }

    // Column counts
    static constexpr int DATASET_COLS = 81;
    static constexpr int PAPER_COLS = 16;
    static const char* const DATASET_HEADER[];
    static const char* const PAPER_HEADER[];

private:
    void write_csv_row(const SignalRow& row);
    void write_jsonl_row(const SignalRow& row);
    void write_paper_row(const SignalRow& row);
    void hydrate_emitted_tokens();
    bool should_emit(const SignalRow& row) const;

    static std::string csv_escape(const std::string& s);
    static std::string json_str(const std::string& s);
    static std::string fmt_double(double v, int prec = 4);

    LiveWriterConfig cfg_;
    FILE* csv_fp_ = nullptr;
    FILE* jsonl_fp_ = nullptr;
    FILE* paper_fp_ = nullptr;
    int row_count_ = 0;
    int paper_count_ = 0;
    std::unordered_set<std::string> emitted_tokens_;
};

} // namespace lumina
