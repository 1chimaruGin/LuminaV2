# Train vs live feature parity (`kol_scorer`)

Training uses [`ml/train_kol_scorer.py`](train_kol_scorer.py) `build_features()`. Live inference uses [`bench/kol_monitor.cpp`](../bench/kol_monitor.cpp) `build_ml_features()`. Indices must match `include/lumina/ml/kol_scorer.h` (`KOL_SCORER_N_FEATURES`).

## Index map (54 features)

| Idx | Name | Python CSV column(s) | C++ `LiveTokenState` source |
|-----|------|----------------------|-----------------------------|
| 0–1 | kol1_idx, kol2_idx | kol1_name, kol2_name | kol_names[0], kol_names[1] |
| 2–26 | combo one-hot | combo_k1k2 vs TOP_COMBOS | combo_feature_idx |
| 27 | kol_count_at_entry | kol_count_at_entry | kol_count |
| 28–30 | kol buys / notional | kol1_buy_usd, kol2_buy_usd, combined_notional_k1k2_usd | kol1_buy_usd, kol2_buy_usd, combined_notional_usd |
| 31–32 | KOL 7d WR | kol1_7d_win_rate, kol2_7d_win_rate | **0 live** (not wired) |
| 33 | delta_blocks | kol1_kol2_delta_blocks | kol1_kol2_delta_blocks |
| 34–39 | mcap, bc, age, dev, holders | entry_mcap_usd, bonding_curve_pct, age_blocks_at_entry, dev_sell_*, holder_* | current_mcap_usd, bonding_curve_pct, age_blocks, dev_sell_*, holder_proxy, holder_growth_k1_to_k2 |
| 40–41 | deployer grads | deployer_prior_grads, deployer_grad_rate | deployer_prior_grads_ml, deployer_grad_rate_ml |
| 42–44 | time / BNB | create_hour_utc, create_dow, bnb_price_usd | create_hour_utc, create_dow, bnb_price_usd |
| 45–46 | macro 4h | btc_4h_change_pct, bnb_4h_change_pct | **0 live** (not wired) |
| 47–49 | ratios | k1k2_ratio, dev_sell_rate | computed from live fields |
| 50–51 | held flags | kol1_held_at_entry, kol2_held_at_entry | **0 live** (not tracked) |
| 52 | deployer_reputation_score | deployer_reputation_score (CSV / PIT) | deployer_score (static CSV lookup) |
| 53 | deployer_prior_avg_peak_mult | deployer_prior_avg_peak_mult | **0** unless you wire rolling PIT avg peak |

## Known gaps (calibration drift risk)

- **31–32, 45–46, 50–51**: Often **0 in C++** while CSV may have non-zero history — model may rely on missing signal live.
- **52 vs 53**: Training may use **PIT** reputation + prior avg peak from labeled history; live uses **static** deployer score and **0** for avg peak unless extended.

## Ablation / tightening

- Compare OOF AUC with and without deployer extras: retrain after zeroing CSV columns `deployer_reputation_score` and `deployer_prior_avg_peak_mult`, or drop those columns in a forked CSV.
- Prefer **time CV** (`--cv time`) and **holdout** (`--holdout-pct`) before trusting metrics when regimes shift.

See also [`ml/DATASET_LABEL_SPEC.md`](DATASET_LABEL_SPEC.md).
