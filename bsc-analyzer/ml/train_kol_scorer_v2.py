#!/usr/bin/env python3
"""
Phase 2 v2: Improved KOL scorer training pipeline.

Changes from v1:
  - Drops features that are always 0 in live (kol_held, 7d_wr, holder_growth)
  - Adds new features: name_len, name_cjk_ratio, deployer_velocity, buy_pct_mcap
  - Supports regression on log1p(peak_mult) alongside binary classification
  - XGBoost comparison
  - Optuna hyperparameter search
  - Time-based CV by default (realistic regime test)
  - Feature importance export (SHAP + split-based)
  - Platt calibration coefficients stored in config

Usage:
    python ml/train_kol_scorer_v2.py [--input ...] [--mode binary|regression|both]
    python ml/train_kol_scorer_v2.py --optuna --trials 30
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
    classification_report,
    f1_score,
    mean_squared_error,
    precision_score,
    recall_score,
    roc_auc_score,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = PROJECT_ROOT / "ml"
OOF_CSV = ML_DIR / "kol_oof_predictions_v2.csv"

KOL_LETTERS = list("ABCDEFGHIJK")
KOL_IDX = {c: i for i, c in enumerate(KOL_LETTERS)}

TOP_COMBOS = [
    "B→A", "D→A", "C→A", "K→A",
    "D→C", "C→D", "B→C", "A→C",
    "D→E", "B→E", "C→E",
    "D→B", "C→B", "E→B",
    "A→G", "D→K", "A→K", "C→K", "K→C",
    "A→D", "B→D",
    "B→H", "K→B", "K→D",
]


def _cjk_ratio(name: str) -> float:
    if not name:
        return 0.0
    cjk = sum(1 for c in name if unicodedata.category(c).startswith("Lo"))
    return cjk / len(name) if len(name) > 0 else 0.0


def build_features_v2(
    df: pd.DataFrame,
    target_mult: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    """Build feature matrix. Returns X, y_binary, feature_names, peak_mult."""
    feature_names: list[str] = []
    columns: list[np.ndarray] = []

    def add(name: str, arr):
        feature_names.append(name)
        columns.append(np.asarray(arr, dtype=np.float32))

    # KOL identity
    add("kol1_idx", df["kol1_name"].fillna("").map(lambda x: KOL_IDX.get(x, -1)))
    add("kol2_idx", df["kol2_name"].fillna("").map(lambda x: KOL_IDX.get(x, -1)))

    # Combo one-hot
    combo = df["combo_k1k2"].fillna("")
    for c in TOP_COMBOS:
        add(f"combo_{c}", (combo == c).astype(int))
    add("combo_other", (~combo.isin(TOP_COMBOS) & (combo != "")).astype(int))

    # Core features (available in C++ live)
    add("kol_count_at_entry", pd.to_numeric(df["kol_count_at_entry"], errors="coerce").fillna(1))
    add("kol1_buy_usd", pd.to_numeric(df["kol1_buy_usd"], errors="coerce").fillna(0))
    add("kol2_buy_usd", pd.to_numeric(df["kol2_buy_usd"], errors="coerce").fillna(0))
    add("combined_notional", pd.to_numeric(df["combined_notional_k1k2_usd"], errors="coerce").fillna(0))

    # DROPPED: kol1_7d_wr, kol2_7d_wr (always 0 in live)

    add("delta_blocks", pd.to_numeric(df["kol1_kol2_delta_blocks"], errors="coerce").fillna(0))
    add("entry_mcap", pd.to_numeric(df["entry_mcap_usd"], errors="coerce").fillna(0))
    add("bonding_curve_pct", pd.to_numeric(df["bonding_curve_pct"], errors="coerce").fillna(0))
    add("age_blocks", pd.to_numeric(df["age_blocks_at_entry"], errors="coerce").fillna(0))
    add("dev_sell_usd", pd.to_numeric(df["dev_sell_usd"], errors="coerce").fillna(0))
    add("dev_sell_pct", pd.to_numeric(df["dev_sell_pct_supply"], errors="coerce").fillna(0))
    add("holder_count", pd.to_numeric(df["holder_count_at_entry"], errors="coerce").fillna(0))

    # DROPPED: holder_growth_k1k2 (always 0 in live)

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

    # DROPPED: kol1_held, kol2_held (always 0 in live)

    # Deployer reputation
    rep = (pd.to_numeric(df["deployer_reputation_score"], errors="coerce").fillna(0)
           if "deployer_reputation_score" in df.columns
           else pd.Series(0.0, index=df.index))
    add("deployer_reputation_score", rep)
    # DROPPED: deployer_prior_avg_peak_mult — always 0 in live (not wired), causes calibration drift

    # NEW: Token name features
    names = df["name"].fillna("")
    add("name_len", names.str.len().astype(float))
    add("name_cjk_ratio", names.map(_cjk_ratio).astype(float))

    # NEW: Buy conviction (kol1 buy as % of mcap)
    mcap = pd.to_numeric(df["entry_mcap_usd"], errors="coerce").fillna(1).clip(lower=1)
    add("kol1_buy_pct_mcap", (k1 / mcap).clip(upper=1.0))

    # NEW: Deployer velocity (launches count -- proxy for recent activity)
    dl = pd.to_numeric(df["deployer_prior_launches"], errors="coerce").fillna(0) if "deployer_prior_launches" in df.columns else pd.Series(0.0, index=df.index)
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


def train_binary(X, y, feature_names, lgb_params, n_splits=5):
    oof_probs = np.zeros(len(y))
    fold_metrics = []

    print(f"\nFeatures: {len(feature_names)}")
    print(f"Samples:  {len(y)}  (pos={y.sum()}, neg={len(y)-y.sum()}, rate={y.mean()*100:.1f}%)")

    for fold_idx, (train_idx, val_idx) in enumerate(_time_blocked_folds(len(y), n_splits)):
        X_tr, y_tr = X[train_idx], y[train_idx]
        X_val, y_val = X[val_idx], y[val_idx]
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

    oof_auc = roc_auc_score(y, oof_probs) if len(np.unique(y)) > 1 else 0.0
    avg = {k: np.mean([m[k] for m in fold_metrics]) for k in fold_metrics[0]}
    print(f"\n  OOF AUC: {oof_auc:.4f}")
    print(f"  CV avg:  AUC={avg['auc']:.4f} P={avg['prec']:.4f} R={avg['rec']:.4f} F1={avg['f1']:.4f}")

    # Final model on all data
    final_model = lgb.LGBMClassifier(**lgb_params)
    final_model.fit(_x_frame(X, feature_names), y)

    return final_model, avg, oof_auc, oof_probs


def train_regression(X, peak_mult, feature_names, lgb_params_base, n_splits=5):
    """Train regression on log1p(peak_mult) for magnitude-aware scoring."""
    y_reg = np.log1p(np.clip(peak_mult, 0, 100))
    oof_preds = np.zeros(len(y_reg))

    reg_params = {k: v for k, v in lgb_params_base.items()
                  if k not in ("objective", "metric", "is_unbalance")}
    reg_params["objective"] = "regression"
    reg_params["metric"] = "rmse"

    print(f"\nRegression on log1p(peak_mult):")
    for fold_idx, (train_idx, val_idx) in enumerate(_time_blocked_folds(len(y_reg), n_splits)):
        model = lgb.LGBMRegressor(**reg_params)
        model.fit(_x_frame(X[train_idx], feature_names), y_reg[train_idx],
                  eval_set=[(_x_frame(X[val_idx], feature_names), y_reg[val_idx])])
        preds = model.predict(_x_frame(X[val_idx], feature_names))
        oof_preds[val_idx] = preds
        rmse = np.sqrt(mean_squared_error(y_reg[val_idx], preds))
        print(f"  Fold {fold_idx}: RMSE={rmse:.4f}")

    total_rmse = np.sqrt(mean_squared_error(y_reg, oof_preds))
    print(f"  OOF RMSE: {total_rmse:.4f}")

    # Check if regression preds rank well for 2x classification
    y_bin = (peak_mult >= 2.0).astype(int)
    if len(np.unique(y_bin)) > 1:
        reg_auc = roc_auc_score(y_bin, oof_preds)
        print(f"  Regression OOF → binary 2x AUC: {reg_auc:.4f}")

    final_model = lgb.LGBMRegressor(**reg_params)
    final_model.fit(_x_frame(X, feature_names), y_reg)
    return final_model, total_rmse, oof_preds


def run_optuna(X, y, feature_names, n_splits=5, n_trials=30):
    """Optuna hyperparameter search for LightGBM binary."""
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        print("Install optuna: pip install optuna", file=sys.stderr)
        return None

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

        oof_probs = np.zeros(len(y))
        for train_idx, val_idx in _time_blocked_folds(len(y), n_splits):
            model = lgb.LGBMClassifier(**params)
            model.fit(_x_frame(X[train_idx], feature_names), y[train_idx])
            oof_probs[val_idx] = model.predict_proba(
                _x_frame(X[val_idx], feature_names))[:, 1]

        return roc_auc_score(y, oof_probs)

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    print(f"\nOptuna best AUC: {study.best_value:.4f}")
    print(f"Best params: {json.dumps(study.best_params, indent=2)}")
    return study.best_params


def xgboost_comparison(X, y, feature_names, n_splits=5):
    """Quick XGBoost comparison."""
    try:
        import xgboost as xgb
    except ImportError:
        print("XGBoost not installed, skipping comparison.")
        return

    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "n_estimators": 100,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": (len(y) - y.sum()) / max(1, y.sum()),
        "verbosity": 0,
        "random_state": 42,
        "n_jobs": -1,
    }

    oof_probs = np.zeros(len(y))
    for train_idx, val_idx in _time_blocked_folds(len(y), n_splits):
        model = xgb.XGBClassifier(**params)
        model.fit(X[train_idx], y[train_idx])
        oof_probs[val_idx] = model.predict_proba(X[val_idx])[:, 1]

    auc = roc_auc_score(y, oof_probs) if len(np.unique(y)) > 1 else 0.0
    print(f"\nXGBoost OOF AUC: {auc:.4f}")
    return auc


def get_feature_importance(model, feature_names):
    """Get split-based feature importance."""
    imp = model.booster_.feature_importance(importance_type="split")
    pairs = sorted(zip(feature_names, imp), key=lambda x: -x[1])
    return {name: int(val) for name, val in pairs}


def platt_calibrate(oof_probs, y):
    lr = LogisticRegression(C=1e10, max_iter=10000, solver="lbfgs")
    lr.fit(oof_probs.reshape(-1, 1), y)
    cal = lr.predict_proba(oof_probs.reshape(-1, 1))[:, 1]
    return lr, cal


def write_oof_csv(df, oof_probs, y, oof_csv, is_holdout=None):
    out = pd.DataFrame({
        "row_index": range(len(y)),
        "y_true": y,
        "oof_prob": oof_probs,
    })
    if "token_address" in df.columns:
        out["token_address"] = df["token_address"].values
    if "create_block" in df.columns:
        out["create_block"] = df["create_block"].values
    if is_holdout is not None:
        out["is_holdout"] = is_holdout
    out.to_csv(oof_csv, index=False)
    print(f"Saved OOF → {oof_csv}")


# ── Tree export (same as v1, generates C header) ─────────────────────────────

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


def generate_manual_c(model, feature_names, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    booster = model.booster_
    model_str = booster.model_to_string()

    header = out_dir / "kol_scorer.h"
    with open(header, "w") as f:
        f.write("// Auto-generated KOL scorer v2 — LightGBM model as C lookup.\n")
        f.write("// Use predict_kol_score(features) → probability [0,1].\n")
        f.write(f"// Features: {len(feature_names)}\n")
        f.write(f"// Feature order: {', '.join(feature_names[:10])}...\n\n")
        f.write("#pragma once\n")
        f.write("#include <cmath>\n\n")
        f.write("namespace lumina {\n\n")
        f.write(f"static constexpr int KOL_SCORER_N_FEATURES = {len(feature_names)};\n\n")

        f.write("static const char* KOL_SCORER_FEATURE_NAMES[] = {\n")
        for name in feature_names:
            f.write(f'    "{name}",\n')
        f.write("};\n\n")

        trees = parse_lgbm_trees(model_str)
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


def main():
    p = argparse.ArgumentParser(description="KOL scorer v2 training")
    p.add_argument("--input", default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_90d_full_kol2plus.csv"))
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--target", choices=("2x", "3x"), default="2x")
    p.add_argument("--mode", choices=("binary", "regression", "both"), default="binary")
    p.add_argument("--n-estimators", type=int, default=100)
    p.add_argument("--max-depth", type=int, default=6)
    p.add_argument("--learning-rate", type=float, default=0.1)
    p.add_argument("--min-child-samples", type=int, default=10)
    p.add_argument("--optuna", action="store_true", help="Run Optuna hyperparameter search")
    p.add_argument("--trials", type=int, default=30, help="Optuna trials")
    p.add_argument("--xgboost", action="store_true", help="Run XGBoost comparison")
    p.add_argument("--calibrate", action="store_true")
    p.add_argument("--no-export-c", action="store_true")
    args = p.parse_args()

    target_mult = 3.0 if args.target == "3x" else 2.0

    df = pd.read_csv(args.input)
    df = _sort_df_chronological(df)
    print(f"Loaded {len(df)} rows from {args.input} (time-sorted)")

    X, y, feature_names, peak_mult = build_features_v2(df, target_mult=target_mult)
    print(f"Features: {len(feature_names)}")

    # Optuna
    best_params = None
    if args.optuna:
        best_params = run_optuna(X, y, feature_names, args.n_splits, args.trials)

    # XGBoost comparison
    if args.xgboost:
        xgboost_comparison(X, y, feature_names, args.n_splits)

    # LightGBM params
    if best_params:
        lgb_params = {
            **best_params,
            "objective": "binary",
            "metric": "auc",
            "is_unbalance": True,
            "verbose": -1,
            "random_state": 42,
            "n_jobs": -1,
        }
    else:
        lgb_params = {
            "objective": "binary",
            "metric": "auc",
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "num_leaves": min(63, max(2, (1 << args.max_depth) - 1)),
            "min_child_samples": args.min_child_samples,
            "learning_rate": args.learning_rate,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "is_unbalance": True,
            "verbose": -1,
            "random_state": 42,
            "n_jobs": -1,
        }

    # Binary classification
    model = None
    oof_probs = None
    cv_metrics = {}
    oof_auc = 0.0
    if args.mode in ("binary", "both"):
        print("\n" + "=" * 60)
        print("BINARY CLASSIFICATION")
        print("=" * 60)
        model, cv_metrics, oof_auc, oof_probs = train_binary(
            X, y, feature_names, lgb_params, args.n_splits)

        print("\nThreshold analysis (OOF):")
        print(f"{'Thresh':>6s}  {'Prec':>6s}  {'Rec':>6s}  {'F1':>6s}  {'N_pos':>6s}")
        for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
            preds = (oof_probs >= t).astype(int)
            if preds.sum() == 0:
                continue
            prec = precision_score(y, preds, zero_division=0)
            rec = recall_score(y, preds, zero_division=0)
            f1 = f1_score(y, preds, zero_division=0)
            print(f"  {t:.1f}   {prec:.4f}  {rec:.4f}  {f1:.4f}  {preds.sum():5d}")

    # Regression
    if args.mode in ("regression", "both"):
        print("\n" + "=" * 60)
        print("REGRESSION on log1p(peak_mult)")
        print("=" * 60)
        reg_model, reg_rmse, reg_oof = train_regression(
            X, peak_mult, feature_names, lgb_params, args.n_splits)

    if model is None:
        print("No binary model trained (--mode regression). Skipping export.")
        return

    # Feature importance
    importance = get_feature_importance(model, feature_names)
    print("\nTop 20 features (split importance):")
    for i, (name, val) in enumerate(list(importance.items())[:20]):
        print(f"  {i+1:2d}. {name:30s} {val}")

    # Save OOF
    write_oof_csv(df, oof_probs, y, OOF_CSV)

    # Calibration
    platt_payload = None
    if args.calibrate:
        lr, cal = platt_calibrate(oof_probs, y)
        platt_payload = {
            "coef": lr.coef_.tolist(),
            "intercept": float(lr.intercept_[0]),
        }
        print(f"\nPlatt calibration fitted")

    # Save model
    model_path = ML_DIR / "kol_scorer_model_v2.txt"
    model.booster_.save_model(str(model_path))
    print(f"\nSaved LightGBM model → {model_path}")

    # Export C header
    if not args.no_export_c:
        treelite_dir = ML_DIR / "kol_scorer_treelite"
        generate_manual_c(model, feature_names, treelite_dir)

    # Save config
    config = {
        "model_type": "lightgbm_binary_v2",
        "target": f"peak_mult >= {target_mult:g}",
        "cv_mode": "time",
        "n_splits": args.n_splits,
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "model_params": {k: v for k, v in lgb_params.items() if k != "verbose"},
        "cv_metrics": {k: round(v, 4) for k, v in cv_metrics.items()},
        "oof_auc": round(oof_auc, 4),
        "feature_importance": importance,
        "dropped_features": [
            "kol1_7d_wr (always 0 live)",
            "kol2_7d_wr (always 0 live)",
            "kol1_held (always 0 live)",
            "kol2_held (always 0 live)",
            "holder_growth_k1k2 (always 0 live)",
            "deployer_prior_avg_peak_mult (always 0 live — calibration drift)",
        ],
        "new_features": [
            "name_len",
            "name_cjk_ratio",
            "kol1_buy_pct_mcap",
            "deployer_launches",
        ],
    }
    if platt_payload:
        config["platt_calibration"] = platt_payload

    config_path = ML_DIR / "kol_scorer_config_v2.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Saved config → {config_path}")

    print("\nDone. Rebuild C++ to use new model: cd build && cmake --build . --target lumina_kol_monitor -j$(nproc)")


if __name__ == "__main__":
    main()
