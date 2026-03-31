#include "lumina/data/live_writer.h"

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <sys/stat.h>

namespace lumina {

// ── Column definitions (must match scripts/kol_dataset_schema.py exactly) ────

const char* const LiveDatasetWriter::DATASET_HEADER[] = {
    // DATASET_CSV_COLUMNS_90D (69)
    "row", "token_address", "name", "create_block", "create_time",
    "create_hour_utc", "create_dow", "creator",
    "deployer_prior_launches", "deployer_prior_grads", "deployer_grad_rate",
    "dev_buy_usd", "dev_sell_usd", "dev_sell_pct_supply", "dev_net_usd",
    "kol_count_final", "kol_count_at_entry",
    "combo_k1k2", "combo_k1k2k3", "combined_notional_k1k2_usd",
    "kol1_7d_win_rate", "kol2_7d_win_rate",
    "kol1_name", "kol1_buy_block", "kol1_buy_usd", "kol1_sell_usd",
    "kol1_pnl_usd", "kol1_held_at_entry", "kol1_holder_count",
    "kol2_name", "kol2_buy_block", "kol2_buy_usd", "kol2_sell_usd",
    "kol2_pnl_usd", "kol2_held_at_entry", "kol2_holder_count",
    "kol1_kol2_delta_blocks",
    "kol3_name", "kol3_buy_block", "kol3_buy_usd", "kol3_sell_usd",
    "kol3_pnl_usd", "kol3_holder_count", "kol2_kol3_delta_blocks",
    "kol4_name", "kol4_buy_block", "kol4_buy_usd", "kol4_sell_usd",
    "kol4_pnl_usd", "kol4_holder_count",
    "kol5_name", "kol5_buy_block", "kol5_buy_usd", "kol5_sell_usd",
    "kol5_pnl_usd", "kol5_holder_count",
    "holder_count_at_entry", "holder_growth_kol1_to_kol2",
    "holder_growth_kol2_to_entry",
    "entry_mcap_usd", "bonding_curve_pct", "age_blocks_at_entry",
    "peak_mcap_usd", "low_mcap_usd", "graduated", "peak_mult_vs_slot2_entry",
    "bnb_price_usd", "btc_4h_change_pct", "bnb_4h_change_pct",
    // LIVE_DATASET_EXTRA_COLUMNS (12)
    "ml_score", "current_mcap_usd", "signal_mode", "signal_mode_label",
    "position_bnb", "sl_x", "signal_block", "signal_tx",
    "deployer_score_signal", "deployer_success_rate_signal",
    "deployer_successful_signal", "deployer_total_tokens_signal",
};

const char* const LiveDatasetWriter::PAPER_HEADER[] = {
    "paper_ts_utc", "token", "mode", "mode_label", "ml_score",
    "kol_count", "create_block", "create_block_known", "shadow",
    "age_blocks", "entry_mcap_usd", "current_mcap_usd",
    "signal_block", "signal_tx", "position_bnb", "sl_x",
};

// ── Helpers ──────────────────────────────────────────────────────────────────

std::string LiveDatasetWriter::csv_escape(const std::string& s) {
    bool needs_quote = false;
    for (char c : s) {
        if (c == ',' || c == '"' || c == '\n' || c == '\r') {
            needs_quote = true;
            break;
        }
    }
    if (!needs_quote) return s;
    std::string out;
    out.reserve(s.size() + 4);
    out += '"';
    for (char c : s) {
        if (c == '"') out += '"';
        out += c;
    }
    out += '"';
    return out;
}

std::string LiveDatasetWriter::json_str(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 4);
    out += '"';
    for (unsigned char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);
                }
                break;
        }
    }
    out += '"';
    return out;
}

std::string LiveDatasetWriter::fmt_double(double v, int prec) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*f", prec, v);
    return buf;
}

static std::string iso_now_utc() {
    auto now = std::chrono::system_clock::now();
    auto tt = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                  now.time_since_epoch()) % 1000;
    struct tm tm{};
    gmtime_r(&tt, &tm);
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%03d+00:00",
                  tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                  tm.tm_hour, tm.tm_min, tm.tm_sec, static_cast<int>(ms.count()));
    return buf;
}

static bool file_exists_nonempty(const char* path) {
    struct stat st{};
    return (stat(path, &st) == 0 && st.st_size > 0);
}

// ── LiveDatasetWriter ────────────────────────────────────────────────────────

LiveDatasetWriter::LiveDatasetWriter(const LiveWriterConfig& cfg) : cfg_(cfg) {}

LiveDatasetWriter::~LiveDatasetWriter() {
    if (csv_fp_) std::fclose(csv_fp_);
    if (jsonl_fp_) std::fclose(jsonl_fp_);
    if (paper_fp_) std::fclose(paper_fp_);
}

bool LiveDatasetWriter::init() {
    // Hydrate emitted tokens from existing JSONL (before truncation check)
    if (!cfg_.fresh_output && cfg_.first_signal_min_kol_count > 0 && !cfg_.jsonl_path.empty()) {
        hydrate_emitted_tokens();
    }

    const char* mode = cfg_.fresh_output ? "w" : "a";

    if (!cfg_.csv_path.empty()) {
        bool need_header = cfg_.fresh_output || !file_exists_nonempty(cfg_.csv_path.c_str());
        csv_fp_ = std::fopen(cfg_.csv_path.c_str(), mode);
        if (!csv_fp_) {
            std::fprintf(stderr, "[writer] Cannot open CSV %s: %s\n", cfg_.csv_path.c_str(), std::strerror(errno));
            return false;
        }
        if (need_header) {
            for (int i = 0; i < DATASET_COLS; ++i) {
                if (i) std::fputc(',', csv_fp_);
                std::fputs(DATASET_HEADER[i], csv_fp_);
            }
            std::fputc('\n', csv_fp_);
            std::fflush(csv_fp_);
        }
    }

    if (!cfg_.jsonl_path.empty()) {
        jsonl_fp_ = std::fopen(cfg_.jsonl_path.c_str(), mode);
        if (!jsonl_fp_) {
            std::fprintf(stderr, "[writer] Cannot open JSONL %s: %s\n", cfg_.jsonl_path.c_str(), std::strerror(errno));
            return false;
        }
    }

    if (!cfg_.paper_csv_path.empty()) {
        bool need_header = cfg_.fresh_output || !file_exists_nonempty(cfg_.paper_csv_path.c_str());
        paper_fp_ = std::fopen(cfg_.paper_csv_path.c_str(), mode);
        if (!paper_fp_) {
            std::fprintf(stderr, "[writer] Cannot open paper CSV %s: %s\n",
                          cfg_.paper_csv_path.c_str(), std::strerror(errno));
            return false;
        }
        if (need_header) {
            for (int i = 0; i < PAPER_COLS; ++i) {
                if (i) std::fputc(',', paper_fp_);
                std::fputs(PAPER_HEADER[i], paper_fp_);
            }
            std::fputc('\n', paper_fp_);
            std::fflush(paper_fp_);
        }
    }

    std::fprintf(stderr, "[writer] CSV: %s | JSONL: %s | Paper: %s | %d cols\n",
                 cfg_.csv_path.empty() ? "(none)" : cfg_.csv_path.c_str(),
                 cfg_.jsonl_path.empty() ? "(none)" : cfg_.jsonl_path.c_str(),
                 cfg_.paper_csv_path.empty() ? "(none)" : cfg_.paper_csv_path.c_str(),
                 DATASET_COLS);
    if (cfg_.first_signal_min_kol_count > 0)
        std::fprintf(stderr, "[writer] One row per token at kol_count >= %d\n",
                     cfg_.first_signal_min_kol_count);
    if (cfg_.tokens_newer_than_session)
        std::fprintf(stderr, "[writer] Session floor: create_block >= %llu\n",
                     static_cast<unsigned long long>(cfg_.session_start_block));
    if (!emitted_tokens_.empty())
        std::fprintf(stderr, "[writer] Hydrated %zu previously emitted tokens\n", emitted_tokens_.size());

    return true;
}

bool LiveDatasetWriter::should_emit(const SignalRow& row) const {
    if (row.token_address.empty()) return false;

    if (cfg_.require_create_block_known && !row.create_block_known) return false;

    if (cfg_.tokens_newer_than_session && cfg_.session_start_block > 0) {
        if (row.create_block < cfg_.session_start_block) return false;
    }

    if (cfg_.first_signal_min_kol_count > 0) {
        if (row.kol_count < cfg_.first_signal_min_kol_count) return false;
        if (row.create_block == 0) return false;
        if (emitted_tokens_.count(row.token_address)) return false;
    }

    return true;
}

bool LiveDatasetWriter::write_signal(const SignalRow& row) {
    if (!should_emit(row)) return false;

    ++row_count_;

    if (cfg_.first_signal_min_kol_count > 0)
        emitted_tokens_.insert(row.token_address);

    if (csv_fp_) write_csv_row(row);
    if (jsonl_fp_) write_jsonl_row(row);

    return true;
}

bool LiveDatasetWriter::check_paper_gate(const SignalRow& row) {
    if (!paper_fp_) return false;
    if (row.mode < cfg_.paper_min_mode) return false;
    if (row.ml_score < cfg_.paper_min_ml_score) return false;
    if (row.kol_count < cfg_.paper_min_kol_count) return false;
    if (cfg_.require_create_block_known && !row.create_block_known) return false;

    ++paper_count_;
    write_paper_row(row);
    return true;
}

// ── CSV row (81 columns, matching DATASET_HEADER order) ─────────────────────

void LiveDatasetWriter::write_csv_row(const SignalRow& r) {
    auto d = [](double v) { return fmt_double(v, 4); };
    auto d0 = [](double v) { return fmt_double(v, 0); };
    auto d2 = [](double v) { return fmt_double(v, 2); };
    auto null_d = [](double v) -> std::string {
        return (v < -900.0) ? "" : fmt_double(v, 4);
    };

    auto kol_block = [](int64_t b) -> std::string {
        return (b < 0) ? "" : std::to_string(b);
    };

    std::string create_time = r.create_time_iso.empty() ? iso_now_utc() : r.create_time_iso;
    double dev_net = -(r.dev_sell_usd);

    // Build fields array (order must match DATASET_HEADER exactly)
    std::string fields[DATASET_COLS];
    int i = 0;
    fields[i++] = std::to_string(row_count_);                              // row
    fields[i++] = r.token_address;                                          // token_address
    fields[i++] = csv_escape(r.name);                                       // name
    fields[i++] = std::to_string(r.create_block);                           // create_block
    fields[i++] = create_time;                                              // create_time
    fields[i++] = std::to_string(r.create_hour_utc);                        // create_hour_utc
    fields[i++] = std::to_string(r.create_dow);                             // create_dow
    fields[i++] = r.creator;                                                // creator
    fields[i++] = std::to_string(r.deployer_prior_launches);                // deployer_prior_launches
    fields[i++] = std::to_string(r.deployer_prior_grads);                   // deployer_prior_grads
    fields[i++] = d(r.deployer_grad_rate);                                  // deployer_grad_rate
    fields[i++] = d0(r.dev_buy_usd);                                        // dev_buy_usd
    fields[i++] = d0(r.dev_sell_usd);                                       // dev_sell_usd
    fields[i++] = d(r.dev_sell_pct_supply);                                  // dev_sell_pct_supply
    fields[i++] = d0(dev_net);                                               // dev_net_usd
    fields[i++] = std::to_string(r.kol_count);                              // kol_count_final
    fields[i++] = std::to_string(r.kol_count);                              // kol_count_at_entry
    fields[i++] = csv_escape(r.combo_k1k2);                                 // combo_k1k2
    fields[i++] = csv_escape(r.combo_k1k2k3);                               // combo_k1k2k3
    fields[i++] = d(r.combined_notional_k1k2_usd);                          // combined_notional_k1k2_usd
    fields[i++] = (r.kol1_7d_win_rate >= 0) ? d(r.kol1_7d_win_rate) : "";  // kol1_7d_win_rate
    fields[i++] = (r.kol2_7d_win_rate >= 0) ? d(r.kol2_7d_win_rate) : "";  // kol2_7d_win_rate

    // KOL slots 1-5 (each: name, buy_block, buy_usd, sell_usd, pnl_usd, held_at_entry|holder_count)
    // Slot 1 + 2: 7 fields each (name, block, buy_usd, sell_usd, pnl_usd, held, holder_count)
    for (int k = 0; k < 2; ++k) {
        fields[i++] = csv_escape(r.kol[k].name);                            // kolN_name
        fields[i++] = kol_block(r.kol[k].buy_block);                        // kolN_buy_block
        fields[i++] = (r.kol[k].buy_block >= 0) ? d(r.kol[k].buy_usd) : "";// kolN_buy_usd
        fields[i++] = "";                                                    // kolN_sell_usd (null live)
        fields[i++] = "";                                                    // kolN_pnl_usd (null)
        fields[i++] = "";                                                    // kolN_held_at_entry (null)
        fields[i++] = (r.kol[k].holder_count > 0)                           // kolN_holder_count
                      ? std::to_string(r.kol[k].holder_count) : "";
    }

    // kol1_kol2_delta_blocks
    fields[i++] = (r.kol1_kol2_delta_blocks >= 0) ?
                  std::to_string(r.kol1_kol2_delta_blocks) : "";

    // Slots 3-5: 6 fields each (name, block, buy_usd, sell_usd, pnl_usd, holder_count) + delta after slot 3
    for (int k = 2; k < 5; ++k) {
        fields[i++] = csv_escape(r.kol[k].name);
        fields[i++] = kol_block(r.kol[k].buy_block);
        fields[i++] = (r.kol[k].buy_block >= 0) ? d(r.kol[k].buy_usd) : "";
        fields[i++] = "";  // sell_usd
        fields[i++] = "";  // pnl_usd
        fields[i++] = (r.kol[k].holder_count > 0)
                      ? std::to_string(r.kol[k].holder_count) : "";  // holder_count
        if (k == 2) {
            fields[i++] = (r.kol2_kol3_delta_blocks >= 0) ?
                          std::to_string(r.kol2_kol3_delta_blocks) : "";
        }
    }

    fields[i++] = std::to_string(r.holder_count);                           // holder_count_at_entry
    fields[i++] = (r.holder_growth_k1_to_k2 != 0.0)                        // holder_growth_kol1_to_kol2
                  ? d(r.holder_growth_k1_to_k2) : "";
    fields[i++] = (r.holder_growth_k2_to_entry != 0.0)                      // holder_growth_kol2_to_entry
                  ? d(r.holder_growth_k2_to_entry) : "";
    fields[i++] = d0(r.entry_mcap_usd);                                     // entry_mcap_usd
    fields[i++] = d(r.bonding_curve_pct);                                    // bonding_curve_pct
    fields[i++] = std::to_string(r.age_blocks);                             // age_blocks_at_entry
    fields[i++] = "";                                                        // peak_mcap_usd (null live)
    fields[i++] = "";                                                        // low_mcap_usd (null)
    fields[i++] = "";                                                        // graduated (null)
    fields[i++] = "";                                                        // peak_mult_vs_slot2_entry (null)
    fields[i++] = d2(r.bnb_price_usd);                                      // bnb_price_usd
    fields[i++] = r.macro_available ? d(r.btc_4h_change_pct) : "";          // btc_4h_change_pct
    fields[i++] = r.macro_available ? d(r.bnb_4h_change_pct) : "";          // bnb_4h_change_pct

    // LIVE_DATASET_EXTRA_COLUMNS (12)
    fields[i++] = d(r.ml_score);                                             // ml_score
    fields[i++] = d0(r.current_mcap_usd);                                   // current_mcap_usd
    fields[i++] = std::to_string(r.mode);                                    // signal_mode
    fields[i++] = r.mode_label;                                              // signal_mode_label
    fields[i++] = d(r.position_bnb);                                         // position_bnb
    fields[i++] = d(r.sl_x);                                                 // sl_x
    fields[i++] = r.signal_block;                                            // signal_block
    fields[i++] = r.signal_tx;                                               // signal_tx
    fields[i++] = d2(r.deployer_score);                                      // deployer_score_signal
    fields[i++] = d(r.deployer_success_rate);                                // deployer_success_rate_signal
    fields[i++] = std::to_string(r.deployer_successful);                     // deployer_successful_signal
    fields[i++] = std::to_string(r.deployer_total_tokens);                   // deployer_total_tokens_signal

    for (int j = 0; j < i; ++j) {
        if (j) std::fputc(',', csv_fp_);
        std::fputs(fields[j].c_str(), csv_fp_);
    }
    std::fputc('\n', csv_fp_);
    std::fflush(csv_fp_);
}

// ── JSONL row ────────────────────────────────────────────────────────────────

void LiveDatasetWriter::write_jsonl_row(const SignalRow& r) {
    std::string o;
    o.reserve(2048);

    auto add_str = [&](const char* key, const std::string& val) {
        o += ",\""; o += key; o += "\":"; o += json_str(val);
    };
    auto add_int = [&](const char* key, int64_t val) {
        o += ",\""; o += key; o += "\":"; o += std::to_string(val);
    };
    auto add_uint = [&](const char* key, uint64_t val) {
        o += ",\""; o += key; o += "\":"; o += std::to_string(val);
    };
    auto add_dbl = [&](const char* key, double val) {
        o += ",\""; o += key; o += "\":"; o += fmt_double(val, 4);
    };
    auto add_null = [&](const char* key) {
        o += ",\""; o += key; o += "\":null";
    };
    auto add_bool = [&](const char* key, bool val) {
        o += ",\""; o += key; o += "\":"; o += val ? "true" : "false";
    };

    std::string create_time = r.create_time_iso.empty() ? iso_now_utc() : r.create_time_iso;

    o += "{\"token_address\":"; o += json_str(r.token_address);
    add_str("name", r.name);
    add_str("creator", r.creator);
    add_uint("create_block", r.create_block);
    add_str("create_time", create_time);
    add_int("create_hour_utc", r.create_hour_utc);
    add_int("create_dow", r.create_dow);
    add_int("deployer_prior_launches", r.deployer_prior_launches);
    add_int("deployer_prior_grads", r.deployer_prior_grads);
    add_dbl("deployer_grad_rate", r.deployer_grad_rate);
    add_dbl("dev_buy_usd", r.dev_buy_usd);
    add_dbl("dev_sell_usd", r.dev_sell_usd);
    add_dbl("dev_sell_pct_supply", r.dev_sell_pct_supply);
    add_dbl("dev_net_usd", -(r.dev_sell_usd));
    add_int("kol_count_final", r.kol_count);
    add_int("kol_count_at_entry", r.kol_count);
    add_str("combo_k1k2", r.combo_k1k2);
    add_str("combo_k1k2k3", r.combo_k1k2k3);
    add_dbl("combined_notional_k1k2_usd", r.combined_notional_k1k2_usd);

    if (r.kol1_7d_win_rate >= 0) add_dbl("kol1_7d_win_rate", r.kol1_7d_win_rate);
    else add_null("kol1_7d_win_rate");
    if (r.kol2_7d_win_rate >= 0) add_dbl("kol2_7d_win_rate", r.kol2_7d_win_rate);
    else add_null("kol2_7d_win_rate");

    for (int k = 0; k < 5; ++k) {
        char pfx[16];
        std::snprintf(pfx, sizeof(pfx), "kol%d_", k + 1);
        std::string p(pfx);
        if (!r.kol[k].name.empty()) add_str((p + "name").c_str(), r.kol[k].name);
        else add_null((p + "name").c_str());
        if (r.kol[k].buy_block >= 0) add_int((p + "buy_block").c_str(), r.kol[k].buy_block);
        else add_null((p + "buy_block").c_str());
        if (r.kol[k].buy_block >= 0) add_dbl((p + "buy_usd").c_str(), r.kol[k].buy_usd);
        else add_null((p + "buy_usd").c_str());
        add_null((p + "sell_usd").c_str());
        add_null((p + "pnl_usd").c_str());
        if (k < 2) {
            add_null((p + "held_at_entry").c_str());
        }
        add_null((p + "holder_count").c_str());
    }

    if (r.kol1_kol2_delta_blocks >= 0)
        add_int("kol1_kol2_delta_blocks", r.kol1_kol2_delta_blocks);
    else
        add_null("kol1_kol2_delta_blocks");
    if (r.kol2_kol3_delta_blocks >= 0)
        add_int("kol2_kol3_delta_blocks", r.kol2_kol3_delta_blocks);
    else
        add_null("kol2_kol3_delta_blocks");

    add_uint("holder_count_at_entry", r.holder_count);
    add_null("holder_growth_kol1_to_kol2");
    add_null("holder_growth_kol2_to_entry");
    add_dbl("entry_mcap_usd", r.entry_mcap_usd);
    add_dbl("bonding_curve_pct", r.bonding_curve_pct);
    add_uint("age_blocks_at_entry", r.age_blocks);
    add_null("peak_mcap_usd");
    add_null("low_mcap_usd");
    add_null("graduated");
    add_null("peak_mult_vs_slot2_entry");
    add_dbl("bnb_price_usd", r.bnb_price_usd);
    if (r.macro_available) {
        add_dbl("btc_4h_change_pct", r.btc_4h_change_pct);
        add_dbl("bnb_4h_change_pct", r.bnb_4h_change_pct);
    } else {
        add_null("btc_4h_change_pct");
        add_null("bnb_4h_change_pct");
    }

    add_dbl("ml_score", r.ml_score);
    add_dbl("current_mcap_usd", r.current_mcap_usd);
    add_int("signal_mode", r.mode);
    add_str("signal_mode_label", r.mode_label);
    add_dbl("position_bnb", r.position_bnb);
    add_dbl("sl_x", r.sl_x);
    add_str("signal_block", r.signal_block);
    add_str("signal_tx", r.signal_tx);
    add_dbl("deployer_score_signal", r.deployer_score);
    add_dbl("deployer_success_rate_signal", r.deployer_success_rate);
    add_int("deployer_successful_signal", r.deployer_successful);
    add_int("deployer_total_tokens_signal", r.deployer_total_tokens);
    add_bool("shadow", r.shadow);
    add_bool("create_block_known", r.create_block_known);
    add_int("row", row_count_);

    o += "}\n";

    std::fputs(o.c_str(), jsonl_fp_);
    std::fflush(jsonl_fp_);
}

// ── Paper CSV row ────────────────────────────────────────────────────────────

void LiveDatasetWriter::write_paper_row(const SignalRow& r) {
    std::string ts = iso_now_utc();
    std::fprintf(paper_fp_,
        "%s,%s,%d,%s,%s,%d,%llu,%s,%s,%llu,%s,%s,%s,%s,%s,%s\n",
        ts.c_str(),
        r.token_address.c_str(),
        r.mode,
        r.mode_label.c_str(),
        fmt_double(r.ml_score, 4).c_str(),
        r.kol_count,
        static_cast<unsigned long long>(r.create_block),
        r.create_block_known ? "true" : "false",
        r.shadow ? "true" : "false",
        static_cast<unsigned long long>(r.age_blocks),
        fmt_double(r.entry_mcap_usd, 0).c_str(),
        fmt_double(r.current_mcap_usd, 0).c_str(),
        r.signal_block.c_str(),
        r.signal_tx.c_str(),
        fmt_double(r.position_bnb, 4).c_str(),
        fmt_double(r.sl_x, 2).c_str());
    std::fflush(paper_fp_);
}

// ── Hydrate emitted tokens from existing JSONL ──────────────────────────────

void LiveDatasetWriter::hydrate_emitted_tokens() {
    FILE* fp = std::fopen(cfg_.jsonl_path.c_str(), "r");
    if (!fp) return;

    char buf[8192];
    int count = 0;
    while (std::fgets(buf, sizeof(buf), fp)) {
        // Quick extraction of token_address and kol_count_final
        const char* ta = std::strstr(buf, "\"token_address\":\"");
        const char* kc = std::strstr(buf, "\"kol_count_final\":");
        if (!ta || !kc) continue;

        ta += 17; // skip "token_address":"
        const char* ta_end = std::strchr(ta, '"');
        if (!ta_end) continue;
        std::string token(ta, ta_end);

        kc += 18; // skip "kol_count_final":
        int kol_count = std::atoi(kc);
        if (kol_count >= cfg_.first_signal_min_kol_count) {
            emitted_tokens_.insert(token);
            ++count;
        }
    }
    std::fclose(fp);
}

} // namespace lumina
