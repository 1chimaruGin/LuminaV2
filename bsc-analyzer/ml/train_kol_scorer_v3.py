#!/usr/bin/env python3
"""
KOL scorer v3 — fixes combo one-hot overfitting.

Key change vs v2:
  - REMOVED: 24 combo one-hot features (C→I N=1, B→G N=2 were memorized, scored 0.775+ live)
  - ADDED: combo_2x_rate_smoothed  — Bayesian-smoothed win rate (blends toward base rate for N<20)
  - ADDED: combo_train_n           — log1p(N) so model knows how reliable the rate is
  - ADDED: kol1_tier_rank, kol2_tier_rank  — ordinal rank of KOL tier (A=top, K=bottom)
  - All other features identical to v2

Root cause diagnosed 2026-04-01:
  The model memorized rare combos in training. C→I appeared once and 3.75x'd → model gives
  all C→I tokens ml=0.795. B→G appeared twice → ml=0.775 live, but both lost.
  Meanwhile B→A (N=30, 47% 2x) gets ml=0.09 because the combo feature is noisy.
  Replacing one-hots with smoothed rates forces generalization.

Usage:
    python ml/train_kol_scorer_v3.py
    python ml/train_kol_scorer_v3.py --optuna --trials 50
    python ml/train_kol_scorer_v3.py --include-live  # merge kol_dataset_live.csv if outcomes available
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    f1_score,
    mean_squared_error,
    precision_score,
    recall_score,
    roc_auc_score,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = PROJECT_ROOT / "ml"
OOF_CSV = ML_DIR / "kol_oof_predictions_v3.csv"

KOL_LETTERS = list("ABCDEFGHIJK")
KOL_IDX = {c: i for i, c in enumerate(KOL_LETTERS)}

# Tier rank: A=0 (best/rarest), K=10 (weakest/most common)
KOL_TIER_RANK = {c: i for i, c in enumerate(KOL_LETTERS)}


def _cjk_ratio(name: str) -> float:
    if not name:
        return 0.0
    cjk = sum(1 for c in name if unicodedata.category(c).startswith("Lo"))
    return cjk / len(name) if len(name) > 0 else 0.0


def compute_combo_stats(df: pd.DataFrame, target_mult: float = 2.0) -> dict[str, tuple[float, int]]:
    """
    Compute per-combo (win_rate, count) from the full training set.
    Returns dict: combo_str -> (smoothed_2x_rate, n)

    Bayesian smoothing: blend combo win rate toward base rate with weight=20.
      smoothed = (n * combo_rate + 20 * base_rate) / (n + 20)
    This means combos with N<20 are heavily pulled toward base rate.
    """
    peak = pd.to_numeric(df["peak_mult_vs_slot2_entry"], errors="coerce").fillna(0)
    y = (peak >= target_mult).astype(int)
    base_rate = float(y.mean())

    combo = df["combo_k1k2"].fillna("")
    stats: dict[str, tuple[float, int]] = {}

    for c in combo.unique():
        if not c:
            continue
        mask = combo == c
        n = int(mask.sum())
        if n == 0:
            continue
        raw_rate = float(y[mask].mean())
        # Bayesian shrinkage toward base rate (pseudo-count = 20)
        smoothed = (n * raw_rate + 20 * base_rate) / (n + 20)
        stats[c] = (smoothed, n)

    return stats, base_rate


def build_features_v3(
    df: pd.DataFrame,
    target_mult: float = 2.0,
    combo_stats: dict | None = None,
    base_rate: float | None = None,
) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    """
    Build feature matrix for v3. Returns X, y_binary, feature_names, peak_mult.
    If combo_stats is None, computes it from df (use only for standalone training).
    For CV folds, pass combo_stats computed from training fold only.
    """
    feature_names: list[str] = []
    columns: list[np.ndarray] = []

    def add(name: str, arr):
        feature_names.append(name)
        columns.append(np.asarray(arr, dtype=np.float32))

    # KOL identity (ordinal index, 0=A best, 10=K weakest)
    add("kol1_idx", df["kol1_name"].fillna("").map(lambda x: KOL_IDX.get(x, -1)))
    add("kol2_idx", df["kol2_name"].fillna("").map(lambda x: KOL_IDX.get(x, -1)))

    # KOL tier rank (same as idx but named explicitly for clarity)
    add("kol1_tier_rank", df["kol1_name"].fillna("").map(lambda x: KOL_TIER_RANK.get(x, 10)))
    add("kol2_tier_rank", df["kol2_name"].fillna("").map(lambda x: KOL_TIER_RANK.get(x, 10)))

    # ── REPLACED: combo one-hot (24 features) → 2 continuous features ──────────
    # combo_2x_rate_smoothed: Bayesian-smoothed win rate for this combo
    # combo_log_n: log1p(training_count) — model knows how reliable the rate is
    if combo_stats is None:
        combo_stats, base_rate = compute_combo_stats(df, target_mult)

    combo_col = df["combo_k1k2"].fillna("")
    smoothed_rates = combo_col.map(lambda c: combo_stats.get(c, (base_rate, 0))[0]).astype(float)
    combo_ns = combo_col.map(lambda c: combo_stats.get(c, (0, 0))[1]).astype(float)

    add("combo_2x_rate_smoothed", smoothed_rates)
    add("combo_log_n", np.log1p(combo_ns))
    # ───────────────────────────────────────────────────────────────────────────

    # Core features (identical to v2)
    add("kol_count_at_entry", pd.to_numeric(df["kol_count_at_entry"], errors="coerce").fillna(1))
    add("kol1_buy_usd", pd.to_numeric(df["kol1_buy_usd"], errors="coerce").fillna(0))
    add("kol2_buy_usd", pd.to_numeric(df["kol2_buy_usd"], errors="coerce").fillna(0))
    add("combined_notional", pd.to_numeric(df["combined_notional_k1k2_usd"], errors="coerce").fillna(0))
    add("delta_blocks", pd.to_numeric(df["kol1_kol2_delta_blocks"], errors="coerce").fillna(0))
    add("entry_mcap", pd.to_numeric(df["entry_mcap_usd"], errors="coerce").fillna(0))
    add("bonding_curve_pct", pd.to_numeric(df["bonding_curve_pct"], errors="coerce").fillna(0))
    add("age_blocks", pd.to_numeric(df["age_blocks_at_entry"], errors="coerce").fillna(0))
    add("dev_sell_usd", pd.to_numeric(df["dev_sell_usd"], errors="coerce").fillna(0))
    add("dev_sell_pct", pd.to_numeric(df["dev_sell_pct_supply"], errors="coerce").fillna(0))
    add("holder_count", pd.to_numeric(df["holder_count_at_entry"], errors="coerce").fillna(0))
    add("deployer_grads", pd.to_numeric(df["deployer_prior_grads"], errors="coerce").fillna(0))
    add("deployer_grad_rate", pd.to_numeric(df["deployer_grad_rate"], errors="coerce").fillna(0))
    add("hour_utc", pd.to_numeric(df["create_hour_utc"], errors="coerce").fillna(12))
    add("dow", pd.to_numeric(df["create_dow"], errors="coerce").fillna(3))
    add("bnb_price", pd.to_numeric(df["bnb_price_usd"], errors="coerce").fillna(600))
    add("btc_4h_chg", pd.to_numeric(df["btc_4h_change_pct"], errors="coerce").fillna(0))
    add("bnb_4h_chg", pd.to_numeric(df["bnb_4h_change_pct"], errors="coerce").fillna(0))

    # Derived features
    k1 = pd.to_numeric(df["kol1_buy_usd"], errors="coerce").fillna(0)
    k2 = pd.to_numeric(df["kol2_buy_usd"], errors="coerce").fillna(0)
    add("k1k2_ratio", np.where(k2 > 0, k1 / k2, 0))
    age = pd.to_numeric(df["age_blocks_at_entry"], errors="coerce").fillna(1).clip(lower=1)
    add("dev_sell_rate", pd.to_numeric(df["dev_sell_usd"], errors="coerce").fillna(0) / age)

    rep = (pd.to_numeric(df["deployer_reputation_score"], errors="coerce").fillna(0)
           if "deployer_reputation_score" in df.columns
           else pd.Series(0.0, index=df.index))
    add("deployer_reputation_score", rep)

    names = df["name"].fillna("")
    add("name_len", names.str.len().astype(float))
    add("name_cjk_ratio", names.map(_cjk_ratio).astype(float))

    mcap = pd.to_numeric(df["entry_mcap_usd"], errors="coerce").fillna(1).clip(lower=1)
    add("kol1_buy_pct_mcap", (k1 / mcap).clip(upper=1.0))

    dl = (pd.to_numeric(df["deployer_prior_launches"], errors="coerce").fillna(0)
          if "deployer_prior_launches" in df.columns
          else pd.Series(0.0, index=df.index))
    add("deployer_launches", dl)

    X = np.column_stack(columns)
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    peak = pd.to_numeric(df["peak_mult_vs_slot2_entry"], errors="coerce").fillna(0)
    y = (peak >= target_mult).astype(np.int32).values

    return X, y, feature_names, peak.values


def _sort_df_chronological(df: pd.DataFrame) -> pd.DataFrame:
    if "create_block" in df.columns:
        key = pd.to_numeric(df["create_block"], errors="coerce").fillna(0)
    elif "create_time" in df.columns:
        key = pd.to_datetime(df["create_time"], errors="coerce").astype("int64").fillna(0) // 10**9
    else:
        key = pd.Series(np.arange(len(df)), index=df.index)
    return df.assign(_sort_key=key).sort_values("_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)


def _time_blocked_folds(n: int, n_splits: int = 5):
    fold_size = max(1, n // n_splits)
    for k in range(n_splits):
        val_start = k * fold_size
        val_end = (k + 1) * fold_size if k < n_splits - 1 else n
        val_idx = np.arange(val_start, val_end)
        train_idx = np.concatenate([np.arange(0, val_start), np.arange(val_end, n)]).astype(int)
        if len(train_idx) < 10 or len(val_idx) < 2:
            continue
        yield train_idx, val_idx


def _x_frame(X, feature_names):
    return pd.DataFrame(X, columns=feature_names)


def train_binary(df_sorted, target_mult, lgb_params, n_splits=5):
    """
    Time-CV training with per-fold combo stats to prevent data leakage.
    Combo smoothed rates are computed from the TRAINING fold only.
    """
    n = len(df_sorted)
    oof_probs = np.zeros(n)
    fold_metrics = []

    # Compute global combo stats once (for feature_names reference)
    _, _, feature_names, _ = build_features_v3(df_sorted, target_mult)
    y_all = (pd.to_numeric(df_sorted["peak_mult_vs_slot2_entry"], errors="coerce").fillna(0) >= target_mult).astype(int).values

    print(f"\nFeatures: {len(feature_names)}")
    print(f"Samples:  {n}  (pos={y_all.sum()}, neg={n-y_all.sum()}, rate={y_all.mean()*100:.1f}%)")

    for fold_idx, (train_idx, val_idx) in enumerate(_time_blocked_folds(n, n_splits)):
        df_tr = df_sorted.iloc[train_idx].reset_index(drop=True)
        df_val = df_sorted.iloc[val_idx].reset_index(drop=True)

        # Compute combo stats from training fold only (no leakage)
        fold_combo_stats, fold_base_rate = compute_combo_stats(df_tr, target_mult)

        X_tr, y_tr, _, _ = build_features_v3(df_tr, target_mult, fold_combo_stats, fold_base_rate)
        X_val, y_val, _, _ = build_features_v3(df_val, target_mult, fold_combo_stats, fold_base_rate)

        model = lgb.LGBMClassifier(**lgb_params)
        model.fit(_x_frame(X_tr, feature_names), y_tr,
                  eval_set=[(_x_frame(X_val, feature_names), y_val)])
        probs = model.predict_proba(_x_frame(X_val, feature_names))[:, 1]
        oof_probs[val_idx] = probs

        auc = roc_auc_score(y_val, probs) if len(np.unique(y_val)) > 1 else 0.0
        preds = (probs >= 0.5).astype(int)
        prec = precision_score(y_val, preds, zero_division=0)
        rec = recall_score(y_val, preds, zero_division=0)
        f1 = f1_score(y_val, preds, zero_division=0)
        fold_metrics.append({"auc": auc, "prec": prec, "rec": rec, "f1": f1})
        print(f"  Fold {fold_idx}: AUC={auc:.4f} P={prec:.4f} R={rec:.4f} F1={f1:.4f}")

    oof_auc = roc_auc_score(y_all, oof_probs) if len(np.unique(y_all)) > 1 else 0.0
    avg = {k: np.mean([m[k] for m in fold_metrics]) for k in fold_metrics[0]}
    print(f"\n  OOF AUC: {oof_auc:.4f}")
    print(f"  CV avg:  AUC={avg['auc']:.4f} P={avg['prec']:.4f} R={avg['rec']:.4f} F1={avg['f1']:.4f}")

    # Final model on all data with global combo stats
    global_combo_stats, global_base_rate = compute_combo_stats(df_sorted, target_mult)
    X_all, y_all2, feature_names2, peak_mult = build_features_v3(df_sorted, target_mult, global_combo_stats, global_base_rate)
    final_model = lgb.LGBMClassifier(**lgb_params)
    final_model.fit(_x_frame(X_all, feature_names2), y_all2)

    return final_model, avg, oof_auc, oof_probs, y_all, feature_names, global_combo_stats, global_base_rate, peak_mult


def get_feature_importance(model, feature_names):
    imp = model.booster_.feature_importance(importance_type="split")
    pairs = sorted(zip(feature_names, imp), key=lambda x: -x[1])
    return {name: int(val) for name, val in pairs}


def platt_calibrate(oof_probs, y):
    lr = LogisticRegression(C=1e10, max_iter=10000, solver="lbfgs")
    lr.fit(oof_probs.reshape(-1, 1), y)
    return lr


def write_oof_csv(df, oof_probs, y, path):
    out = pd.DataFrame({
        "row_index": range(len(y)),
        "y_true": y,
        "oof_prob": oof_probs,
    })
    if "token_address" in df.columns:
        out["token_address"] = df["token_address"].values
    if "create_block" in df.columns:
        out["create_block"] = df["create_block"].values
    out.to_csv(path, index=False)
    print(f"Saved OOF → {path}")


# ── Tree export (generates C header for kol_monitor) ─────────────────────────

def parse_lgbm_trees(model_str):
    trees = []
    lines = model_str.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].startswith("Tree="):
            tree = {}
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("Tree=") and not lines[i].startswith("end of trees"):
                if "=" in lines[i]:
                    key, val = lines[i].split("=", 1)
                    tree[key.strip()] = val.strip()
                i += 1
            if tree:
                trees.append(tree)
        else:
            i += 1
    return trees


def tree_to_c(tree, indent=4):
    num_leaves = int(tree.get("num_leaves", 1))
    if num_leaves <= 1:
        leaf_val = tree.get("leaf_value", "0")
        return " " * indent + f"return {leaf_val};\n"

    split_feature = list(map(int, tree.get("split_feature", "").split()))
    threshold = list(map(float, tree.get("threshold", "").split()))
    left_child = list(map(int, tree.get("left_child", "").split()))
    right_child = list(map(int, tree.get("right_child", "").split()))
    leaf_value = list(map(float, tree.get("leaf_value", "").split()))
    num_nodes = len(split_feature)

    def node_to_c(node_idx, depth):
        pad = " " * (indent + depth * 4)
        if node_idx < 0:
            leaf_idx = ~node_idx
            if leaf_idx < len(leaf_value):
                return pad + f"return {leaf_value[leaf_idx]:.10f};\n"
            return pad + "return 0.0;\n"
        if node_idx >= num_nodes:
            return pad + "return 0.0;\n"
        feat = split_feature[node_idx]
        thresh = threshold[node_idx]
        left = left_child[node_idx]
        right = right_child[node_idx]
        code = pad + f"if (f[{feat}] <= {thresh:.10f}f) {{\n"
        code += node_to_c(left, depth + 1)
        code += pad + "} else {\n"
        code += node_to_c(right, depth + 1)
        code += pad + "}\n"
        return code

    return node_to_c(0, 0)


def generate_c_header(model, feature_names, combo_stats, base_rate, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    booster = model.booster_
    model_str = booster.model_to_string()
    trees = parse_lgbm_trees(model_str)

    header = out_dir / "kol_scorer.h"
    with open(header, "w") as f:
        f.write("// Auto-generated KOL scorer v3 — LightGBM as C lookup.\n")
        f.write("// Fixes v2 combo one-hot overfitting: uses smoothed win rates instead.\n")
        f.write(f"// Features: {len(feature_names)}\n")
        f.write("// Feature order: " + ", ".join(feature_names[:10]) + "...\n\n")
        f.write("#pragma once\n")
        f.write("#include <cmath>\n")
        f.write("#include <string>\n")
        f.write("#include <unordered_map>\n\n")
        f.write("namespace lumina {\n\n")
        f.write(f"static constexpr int KOL_SCORER_N_FEATURES = {len(feature_names)};\n\n")

        f.write("static const char* KOL_SCORER_FEATURE_NAMES[] = {\n")
        for name in feature_names:
            f.write(f'    "{name}",\n')
        f.write("};\n\n")

        # Emit combo lookup table for C++
        f.write("// Combo smoothed 2x win rates (Bayesian shrinkage, pseudo-count=20)\n")
        f.write(f"static const double KOL_COMBO_BASE_RATE = {base_rate:.6f};\n\n")
        f.write("static inline double combo_smoothed_rate(const std::string& combo) {\n")
        f.write("    static const std::unordered_map<std::string, double> tbl = {\n")
        for combo, (rate, n) in sorted(combo_stats.items()):
            f.write(f'        {{"{combo}", {rate:.6f}}},  // N={n}\n')
        f.write("    };\n")
        f.write("    auto it = tbl.find(combo);\n")
        f.write(f"    return (it != tbl.end()) ? it->second : {base_rate:.6f};\n")
        f.write("}\n\n")

        f.write("static inline double combo_log_n(const std::string& combo) {\n")
        f.write("    static const std::unordered_map<std::string, double> tbl = {\n")
        for combo, (rate, n) in sorted(combo_stats.items()):
            f.write(f'        {{"{combo}", {float(np.log1p(n)):.6f}}},  // N={n}\n')
        f.write("    };\n")
        f.write("    auto it = tbl.find(combo);\n")
        f.write("    return (it != tbl.end()) ? it->second : 0.0;\n")
        f.write("}\n\n")

        f.write(f"// {len(trees)} trees\n\n")
        for i, tree in enumerate(trees):
            f.write(f"static inline double tree_{i}(const float* f) {{\n")
            f.write(tree_to_c(tree, indent=4))
            f.write("}\n\n")

        f.write("static inline double predict_kol_score(const float* features) {\n")
        f.write("    double sum = 0.0;\n")
        for i in range(len(trees)):
            f.write(f"    sum += tree_{i}(features);\n")
        f.write("    return 1.0 / (1.0 + std::exp(-sum));\n")
        f.write("}\n\n")
        f.write("} // namespace lumina\n")

    print(f"Generated C header → {header}")

    inc = PROJECT_ROOT / "include" / "lumina" / "ml" / "kol_scorer.h"
    shutil.copy(header, inc)
    print(f"Copied → {inc}")
    return header


def run_optuna(df_sorted, target_mult, n_splits=5, n_trials=30):
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        print("Install optuna: pip install optuna", file=sys.stderr)
        return None

    n = len(df_sorted)
    y_all = (pd.to_numeric(df_sorted["peak_mult_vs_slot2_entry"], errors="coerce").fillna(0) >= target_mult).astype(int).values
    _, _, feature_names, _ = build_features_v3(df_sorted, target_mult)

    def objective(trial):
        params = {
            "objective": "binary",
            "metric": "auc",
            "n_estimators": trial.suggest_int("n_estimators", 30, 300),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "num_leaves": trial.suggest_int("num_leaves", 8, 128),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "is_unbalance": True,
            "verbose": -1,
            "random_state": 42,
            "n_jobs": -1,
        }
        oof = np.zeros(n)
        for train_idx, val_idx in _time_blocked_folds(n, n_splits):
            df_tr = df_sorted.iloc[train_idx].reset_index(drop=True)
            df_val = df_sorted.iloc[val_idx].reset_index(drop=True)
            cs, br = compute_combo_stats(df_tr, target_mult)
            X_tr, y_tr, _, _ = build_features_v3(df_tr, target_mult, cs, br)
            X_val, y_val, _, _ = build_features_v3(df_val, target_mult, cs, br)
            m = lgb.LGBMClassifier(**params)
            m.fit(_x_frame(X_tr, feature_names), y_tr)
            oof[val_idx] = m.predict_proba(_x_frame(X_val, feature_names))[:, 1]
        return roc_auc_score(y_all, oof)

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    print(f"\nOptuna best AUC: {study.best_value:.4f}")
    print(f"Best params: {json.dumps(study.best_params, indent=2)}")
    return study.best_params


def main():
    p = argparse.ArgumentParser(description="KOL scorer v3 — fixes combo one-hot overfitting")
    p.add_argument("--input", default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_90d_full_kol2plus.csv"))
    p.add_argument("--include-live", action="store_true",
                   help="Merge kol_dataset_live.csv rows that have resolved peak_mult")
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--target", choices=("2x", "3x"), default="2x")
    p.add_argument("--n-estimators", type=int, default=100)
    p.add_argument("--max-depth", type=int, default=6)
    p.add_argument("--learning-rate", type=float, default=0.1)
    p.add_argument("--min-child-samples", type=int, default=10)
    p.add_argument("--optuna", action="store_true")
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--calibrate", action="store_true")
    p.add_argument("--no-export-c", action="store_true")
    args = p.parse_args()

    target_mult = 3.0 if args.target == "3x" else 2.0

    df = pd.read_csv(args.input)
    df = _sort_df_chronological(df)
    print(f"Loaded {len(df)} rows from {args.input} (time-sorted)")

    if args.include_live:
        live_path = PROJECT_ROOT / "backtest_results" / "kol_dataset_live.csv"
        if live_path.exists():
            live = pd.read_csv(live_path)
            live = live[pd.to_numeric(live["peak_mult_vs_slot2_entry"], errors="coerce").notna()]
            live = live[pd.to_numeric(live["peak_mult_vs_slot2_entry"], errors="coerce") > 0]
            if len(live) > 0:
                df = pd.concat([df, live], ignore_index=True)
                df = _sort_df_chronological(df)
                print(f"Merged {len(live)} live rows → total {len(df)}")
            else:
                print("No resolved live rows to add (peak_mult still empty)")

    # Optuna search
    best_params = None
    if args.optuna:
        best_params = run_optuna(df, target_mult, args.n_splits, args.trials)

    lgb_params = {
        **(best_params or {}),
        "objective": "binary",
        "metric": "auc",
        "n_estimators": best_params.get("n_estimators", args.n_estimators) if best_params else args.n_estimators,
        "max_depth": best_params.get("max_depth", args.max_depth) if best_params else args.max_depth,
        "num_leaves": best_params.get("num_leaves", min(63, max(2, (1 << args.max_depth) - 1))) if best_params else min(63, max(2, (1 << args.max_depth) - 1)),
        "min_child_samples": best_params.get("min_child_samples", args.min_child_samples) if best_params else args.min_child_samples,
        "learning_rate": best_params.get("learning_rate", args.learning_rate) if best_params else args.learning_rate,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "is_unbalance": True,
        "verbose": -1,
        "random_state": 42,
        "n_jobs": -1,
    }

    print("\n" + "=" * 60)
    print("BINARY CLASSIFICATION (v3 — smoothed combo rates)")
    print("=" * 60)

    (model, cv_metrics, oof_auc, oof_probs, y_all,
     feature_names, global_combo_stats, global_base_rate, peak_mult) = train_binary(
        df, target_mult, lgb_params, args.n_splits)

    print("\nThreshold analysis (OOF):")
    print(f"{'Thresh':>6s}  {'Prec':>6s}  {'Rec':>6s}  {'F1':>6s}  {'N_pos':>6s}")
    for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        preds = (oof_probs >= t).astype(int)
        if preds.sum() == 0:
            continue
        prec = precision_score(y_all, preds, zero_division=0)
        rec = recall_score(y_all, preds, zero_division=0)
        f1 = f1_score(y_all, preds, zero_division=0)
        print(f"  {t:.1f}   {prec:.4f}  {rec:.4f}  {f1:.4f}  {preds.sum():5d}")

    # OOF score distribution
    print("\nOOF score distribution:")
    for lo, hi in [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.01)]:
        mask = (oof_probs >= lo) & (oof_probs < hi)
        if mask.sum() > 0:
            pos_r = y_all[mask].mean()
            print(f"  [{lo:.1f}-{hi:.2f})  n={mask.sum():4d}  pos%={pos_r*100:.1f}%")

    # Feature importance
    importance = get_feature_importance(model, feature_names)
    print("\nTop 20 features (split importance):")
    for i, (name, val) in enumerate(list(importance.items())[:20]):
        print(f"  {i+1:2d}. {name:35s} {val}")

    # Compare v3 vs v2 combo handling
    print("\nV3 combo stats (top 15 by N):")
    top_by_n = sorted(global_combo_stats.items(), key=lambda x: -x[1][1])[:15]
    print(f"  {'combo':<8} {'N':>4}  {'raw%':>6}  {'smoothed%':>10}")
    for combo, (smoothed, n) in top_by_n:
        # recover raw rate from smoothing formula: raw = (smoothed * (n+20) - 20*base) / n
        raw = (smoothed * (n + 20) - 20 * global_base_rate) / n if n > 0 else global_base_rate
        print(f"  {combo:<8} {n:>4}  {raw*100:>5.1f}%  {smoothed*100:>9.1f}%")

    # Save OOF
    write_oof_csv(df, oof_probs, y_all, OOF_CSV)

    # Calibration
    platt_payload = None
    if args.calibrate:
        lr = platt_calibrate(oof_probs, y_all)
        platt_payload = {
            "coef": lr.coef_.tolist(),
            "intercept": float(lr.intercept_[0]),
        }
        print("Platt calibration fitted")

    # Save model
    model_path = ML_DIR / "kol_scorer_model_v3.txt"
    model.booster_.save_model(str(model_path))
    print(f"\nSaved LightGBM model → {model_path}")

    # Export C header
    if not args.no_export_c:
        treelite_dir = ML_DIR / "kol_scorer_treelite_v3"
        generate_c_header(model, feature_names, global_combo_stats, global_base_rate, treelite_dir)

    # Save config
    config = {
        "model_type": "lightgbm_binary_v3",
        "version": "v3",
        "target": f"peak_mult >= {target_mult:g}",
        "cv_mode": "time_blocked_no_leakage",
        "n_splits": args.n_splits,
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "model_params": {k: v for k, v in lgb_params.items() if k != "verbose"},
        "cv_metrics": {k: round(v, 4) for k, v in cv_metrics.items()},
        "oof_auc": round(oof_auc, 4),
        "combo_base_rate": round(global_base_rate, 4),
        "combo_stats": {k: {"smoothed_rate": round(v[0], 4), "n": v[1]}
                        for k, v in sorted(global_combo_stats.items())},
        "feature_importance": importance,
        "v3_changes": [
            "Removed 24 combo one-hot features (caused overfitting to rare combos N=1-2)",
            "Added combo_2x_rate_smoothed (Bayesian shrinkage, pseudo-count=20)",
            "Added combo_log_n (log1p training sample size)",
            "Added kol1_tier_rank, kol2_tier_rank (ordinal)",
            "Per-fold combo stats prevent leakage in CV",
        ],
    }
    if platt_payload:
        config["platt_calibration"] = platt_payload

    config_path = ML_DIR / "kol_scorer_config_v3.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Saved config → {config_path}")

    print("\nTo use v3 in C++:")
    print("  1. Update build_ml_features() in bench/kol_monitor.cpp for new feature layout")
    print("  2. Replace include/lumina/ml/kol_scorer.h with ml/kol_scorer_treelite_v3/kol_scorer.h")
    print("  3. Rebuild: cmake --build build --target lumina_kol_monitor -j$(nproc)")


if __name__ == "__main__":
    main()
