#!/usr/bin/env python3
"""
Phase 2: Train compact LightGBM scorer on entry-time features from the
90d kol2plus dataset.  Export to:
  - LightGBM model file  (kol_scorer_model.txt)
  - OOF predictions      (kol_oof_predictions.csv) — use Phase 3 backtest (honest ML PnL)
  - Treelite C source     (kol_scorer_treelite/)
  - Config JSON           (kol_scorer_config.json)

Usage:
    python ml/train_kol_scorer.py [--input ...] [--cv stratified|time|group] [--holdout-pct P] [--target 2x|3x]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, StratifiedKFold

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = PROJECT_ROOT / "ml"
OOF_CSV = ML_DIR / "kol_oof_predictions.csv"

# KOL letter → integer mapping (for combo encoding)
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


def build_features(
    df: pd.DataFrame,
    target_mult: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build feature matrix (54 features: 0–51 legacy C++ order, 52–53 deployer CSV PIT fields)."""
    feature_names: list[str] = []
    columns: list[np.ndarray] = []

    def add(name: str, arr):
        feature_names.append(name)
        columns.append(np.asarray(arr, dtype=np.float32))

    add("kol1_idx", df["kol1_name"].fillna("").map(lambda x: KOL_IDX.get(x, -1)))
    add("kol2_idx", df["kol2_name"].fillna("").map(lambda x: KOL_IDX.get(x, -1)))

    combo = df["combo_k1k2"].fillna("")
    for c in TOP_COMBOS:
        add(f"combo_{c}", (combo == c).astype(int))
    add("combo_other", (~combo.isin(TOP_COMBOS) & (combo != "")).astype(int))

    add("kol_count_at_entry", pd.to_numeric(df["kol_count_at_entry"], errors="coerce").fillna(1))
    add("kol1_buy_usd", pd.to_numeric(df["kol1_buy_usd"], errors="coerce").fillna(0))
    add("kol2_buy_usd", pd.to_numeric(df["kol2_buy_usd"], errors="coerce").fillna(0))
    add("combined_notional", pd.to_numeric(df["combined_notional_k1k2_usd"], errors="coerce").fillna(0))
    add("kol1_7d_wr", pd.to_numeric(df["kol1_7d_win_rate"], errors="coerce").fillna(0))
    add("kol2_7d_wr", pd.to_numeric(df["kol2_7d_win_rate"], errors="coerce").fillna(0))
    add("delta_blocks", pd.to_numeric(df["kol1_kol2_delta_blocks"], errors="coerce").fillna(0))
    add("entry_mcap", pd.to_numeric(df["entry_mcap_usd"], errors="coerce").fillna(0))
    add("bonding_curve_pct", pd.to_numeric(df["bonding_curve_pct"], errors="coerce").fillna(0))
    add("age_blocks", pd.to_numeric(df["age_blocks_at_entry"], errors="coerce").fillna(0))
    add("dev_sell_usd", pd.to_numeric(df["dev_sell_usd"], errors="coerce").fillna(0))
    add("dev_sell_pct", pd.to_numeric(df["dev_sell_pct_supply"], errors="coerce").fillna(0))
    add("holder_count", pd.to_numeric(df["holder_count_at_entry"], errors="coerce").fillna(0))
    add("holder_growth_k1k2", pd.to_numeric(df["holder_growth_kol1_to_kol2"], errors="coerce").fillna(0))
    add("deployer_grads", pd.to_numeric(df["deployer_prior_grads"], errors="coerce").fillna(0))
    add("deployer_grad_rate", pd.to_numeric(df["deployer_grad_rate"], errors="coerce").fillna(0))

    add("hour_utc", pd.to_numeric(df["create_hour_utc"], errors="coerce").fillna(12))
    add("dow", pd.to_numeric(df["create_dow"], errors="coerce").fillna(3))
    add("bnb_price", pd.to_numeric(df["bnb_price_usd"], errors="coerce").fillna(600))
    add("btc_4h_chg", pd.to_numeric(df["btc_4h_change_pct"], errors="coerce").fillna(0))
    add("bnb_4h_chg", pd.to_numeric(df["bnb_4h_change_pct"], errors="coerce").fillna(0))

    k1 = pd.to_numeric(df["kol1_buy_usd"], errors="coerce").fillna(0)
    k2 = pd.to_numeric(df["kol2_buy_usd"], errors="coerce").fillna(0)
    add("k1k2_ratio", np.where(k2 > 0, k1 / k2, 0))
    add("dev_sell_rate", pd.to_numeric(df["dev_sell_usd"], errors="coerce").fillna(0) /
        pd.to_numeric(df["age_blocks_at_entry"], errors="coerce").fillna(1).clip(lower=1))

    kol1_held = df["kol1_held_at_entry"].astype(str).str.lower().isin(["true", "1"])
    kol2_held = df["kol2_held_at_entry"].astype(str).str.lower().isin(["true", "1"])
    add("kol1_held", kol1_held.astype(int))
    add("kol2_held", kol2_held.astype(int))

    # Indices 52–53: must match C++ build_ml_features after kol2_held (KOL_SCORER_N_FEATURES = 54)
    rep = (
        pd.to_numeric(df["deployer_reputation_score"], errors="coerce").fillna(0)
        if "deployer_reputation_score" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    apm = (
        pd.to_numeric(df["deployer_prior_avg_peak_mult"], errors="coerce").fillna(0)
        if "deployer_prior_avg_peak_mult" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    add("deployer_reputation_score", rep)
    add("deployer_prior_avg_peak_mult", apm)

    X = np.column_stack(columns)
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    peak = pd.to_numeric(df["peak_mult_vs_slot2_entry"], errors="coerce").fillna(0)
    y = (peak >= target_mult).astype(np.int32).values

    return X, y, feature_names


def _x_frame(X: np.ndarray, feature_names: list[str]) -> pd.DataFrame:
    """LightGBM sklearn wrapper warns when fit with ndarray after seeing feature names; use DataFrame."""
    return pd.DataFrame(X, columns=feature_names)


def _sort_df_chronological(df: pd.DataFrame) -> pd.DataFrame:
    if "create_block" in df.columns:
        key = pd.to_numeric(df["create_block"], errors="coerce").fillna(0)
    elif "create_time" in df.columns:
        key = pd.to_datetime(df["create_time"], errors="coerce").astype("int64").fillna(0) // 10**9
    else:
        key = pd.Series(np.arange(len(df)), index=df.index)
    return df.assign(_sort_key=key).sort_values("_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)


def _time_blocked_folds(n: int, n_splits: int = 5):
    """Contiguous time blocks: fold k validates on k-th segment (rows must be time-sorted)."""
    fold_size = max(1, n // n_splits)
    for k in range(n_splits):
        val_start = k * fold_size
        val_end = (k + 1) * fold_size if k < n_splits - 1 else n
        val_idx = np.arange(val_start, val_end)
        train_idx = np.concatenate([np.arange(0, val_start), np.arange(val_end, n)]).astype(int)
        if len(train_idx) < 10 or len(val_idx) < 2:
            continue
        yield train_idx, val_idx


def train_and_evaluate(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    *,
    cv_mode: str,
    groups: np.ndarray | None,
    lgb_params: dict,
    n_splits: int = 5,
):
    oof_probs = np.zeros(len(y))
    fold_metrics = []

    print(f"\nFeatures: {len(feature_names)}")
    print(f"Samples:  {len(y)}  (pos={y.sum()}, neg={len(y)-y.sum()}, rate={y.mean()*100:.1f}%)")
    print(f"CV mode:  {cv_mode}")
    print(f"\n{'Fold':>4s}  {'AUC':>6s}  {'Prec':>6s}  {'Rec':>6s}  {'F1':>6s}")
    print("-" * 36)

    fold_id = 0
    if cv_mode == "stratified":
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        splits = list(skf.split(X, y))
    elif cv_mode == "time":
        splits = list(_time_blocked_folds(len(y), n_splits))
    elif cv_mode == "group":
        if groups is None:
            raise ValueError("--cv group requires creator column")
        n_g = len(np.unique(groups))
        if n_g < n_splits:
            print(f"WARNING: only {n_g} unique creators < {n_splits} folds; falling back to stratified", file=sys.stderr)
            ns = min(n_splits, max(2, n_g))
            skf = StratifiedKFold(n_splits=ns, shuffle=True, random_state=42)
            splits = list(skf.split(X, y))
        else:
            gkf = GroupKFold(n_splits=n_splits)
            splits = list(gkf.split(X, y, groups=groups))
    else:
        raise ValueError(cv_mode)

    if not splits:
        raise RuntimeError("No CV splits produced (check n_splits and dataset size)")

    for train_idx, val_idx in splits:
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]
        X_tr_df = _x_frame(X_tr, feature_names)
        X_val_df = _x_frame(X_val, feature_names)

        model = lgb.LGBMClassifier(**lgb_params)
        model.fit(X_tr_df, y_tr, eval_set=[(X_val_df, y_val)])

        probs = model.predict_proba(X_val_df)[:, 1]
        oof_probs[val_idx] = probs

        preds = (probs >= 0.5).astype(int)
        auc = roc_auc_score(y_val, probs) if len(np.unique(y_val)) > 1 else 0.0
        prec = precision_score(y_val, preds, zero_division=0)
        rec = recall_score(y_val, preds, zero_division=0)
        f1 = f1_score(y_val, preds, zero_division=0)
        fold_metrics.append({"auc": auc, "prec": prec, "rec": rec, "f1": f1})
        fold_id += 1
        print(f"  {fold_id:2d}   {auc:.4f}  {prec:.4f}  {rec:.4f}  {f1:.4f}")

    avg = {k: np.mean([m[k] for m in fold_metrics]) for k in fold_metrics[0]}
    print(f" AVG   {avg['auc']:.4f}  {avg['prec']:.4f}  {avg['rec']:.4f}  {avg['f1']:.4f}")

    oof_preds = (oof_probs >= 0.5).astype(int)
    oof_auc = roc_auc_score(y, oof_probs) if len(np.unique(y)) > 1 else 0.0
    print(f"\nOOF AUC: {oof_auc:.4f}")
    print(classification_report(y, oof_preds, target_names=["neg", "pos"]))

    final_model = lgb.LGBMClassifier(**lgb_params)
    final_model.fit(_x_frame(X, feature_names), y)

    imp = final_model.feature_importances_
    sorted_idx = np.argsort(imp)[::-1]
    print("Feature importance (top 20):")
    for i in sorted_idx[:20]:
        print(f"  {feature_names[i]:30s}: {imp[i]:4d}")

    return final_model, avg, oof_auc, oof_probs


def write_oof_csv(
    df: pd.DataFrame,
    oof_probs: np.ndarray,
    y: np.ndarray,
    cv_mode: str,
    target_desc: str,
    path: Path,
    *,
    is_holdout: np.ndarray | None = None,
) -> None:
    tok = df["token_address"].astype(str).values if "token_address" in df.columns else [""] * len(df)
    cb = pd.to_numeric(df.get("create_block", 0), errors="coerce").fillna(0).astype(int).values
    out = pd.DataFrame({
        "row_index": np.arange(len(df)),
        "token_address": tok,
        "create_block": cb,
        "oof_prob": oof_probs,
        "y_true": y,
    })
    if is_holdout is not None:
        out["is_holdout"] = is_holdout.astype(bool)
    out.attrs = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    print(f"\nWrote OOF predictions → {path} ({len(out)} rows, checksum len={len(out)})")
    print(f"  Join Phase 3 backtest on row_index or (token_address, create_block). CV={cv_mode} target={target_desc}")


def platt_calibrate(oof_probs: np.ndarray, y: np.ndarray) -> tuple[LogisticRegression, np.ndarray]:
    lr = LogisticRegression(max_iter=1000, random_state=42)
    lr.fit(oof_probs.reshape(-1, 1), y)
    calibrated = lr.predict_proba(oof_probs.reshape(-1, 1))[:, 1]
    return lr, calibrated


def export_treelite(model: lgb.LGBMClassifier, feature_names: list[str], out_dir: Path):
    import treelite

    model_path = ML_DIR / "kol_scorer_model.txt"
    model.booster_.save_model(str(model_path))
    print(f"\nSaved LightGBM model → {model_path}")

    tl_model = treelite.frontend.load_lightgbm_model(str(model_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    treelite.export_lib(
        model=tl_model,
        toolchain="gcc",
        libpath=str(out_dir / "kol_scorer.so"),
        params={"parallel_comp": 1},
        verbose=False,
    )
    print(f"Exported treelite shared library → {out_dir / 'kol_scorer.so'}")

    src_dir = out_dir / "src"
    if src_dir.exists():
        shutil.rmtree(src_dir)
    treelite.export_srcpkg(
        model=tl_model,
        toolchain="gcc",
        pkgpath=str(src_dir),
        libname="kol_scorer",
        params={"parallel_comp": 1},
        verbose=False,
    )
    print(f"Exported treelite C source → {src_dir}")


def export_config(
    feature_names,
    cv_metrics,
    oof_auc,
    model_params,
    out_path,
    *,
    cv_mode: str,
    target_desc: str,
    oof_csv: str,
    platt_coef: dict | None = None,
    holdout_report: dict | None = None,
):
    config = {
        "model_type": "lightgbm_binary",
        "target": target_desc,
        "cv_mode": cv_mode,
        "oof_predictions_csv": oof_csv,
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "model_params": {k: v for k, v in model_params.items() if k != "verbose"},
        "cv_metrics": {k: round(v, 4) for k, v in cv_metrics.items()},
        "oof_auc": round(oof_auc, 4),
        "threshold": 0.5,
        "top_combos_encoded": TOP_COMBOS,
        "kol_letter_map": KOL_IDX,
        "note": (
            "OOF rows: each prob from a model that did not train on that row (K-fold CV). "
            "Phase 3 rules_ml uses this file by default — PnL aligns with OOF metrics, not in-sample booster predict. "
            "Optional is_holdout column: chronological test rows scored by a model trained only on earlier data."
        ),
    }
    if holdout_report:
        config["chronological_holdout"] = holdout_report
    if platt_coef:
        config["platt_calibration"] = platt_coef
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Saved config → {out_path}")


def copy_header_to_include(header_path: Path) -> None:
    inc = PROJECT_ROOT / "include" / "lumina" / "ml" / "kol_scorer.h"
    if header_path.is_file():
        shutil.copy(header_path, inc)
        print(f"Copied → {inc}")


def generate_manual_c(model: lgb.LGBMClassifier, feature_names: list[str], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    booster = model.booster_
    model_str = booster.model_to_string()

    header = out_dir / "kol_scorer.h"
    with open(header, "w") as f:
        f.write("// Auto-generated KOL scorer — LightGBM model as C lookup.\n")
        f.write("// Use predict_kol_score(features) → probability [0,1].\n")
        f.write(f"// Features: {len(feature_names)}\n")
        f.write(f"// Feature order: {', '.join(feature_names[:8])}...\n\n")
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

    print(f"Generated manual C header → {header}")
    copy_header_to_include(header)


def parse_lgbm_trees(model_str: str) -> list[dict]:
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


def tree_to_c(tree: dict, indent: int = 4) -> str:
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

    def node_to_c(node_idx: int, depth: int) -> str:
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_90d_full_kol2plus.csv"))
    p.add_argument("--cv", choices=("stratified", "time", "group"), default="stratified")
    p.add_argument("--n-splits", type=int, default=5)
    p.add_argument("--target", choices=("2x", "3x"), default="2x", help="Label = peak_mult >= 2 or 3")
    p.add_argument("--n-estimators", type=int, default=20)
    p.add_argument("--max-depth", type=int, default=4)
    p.add_argument("--learning-rate", type=float, default=0.1)
    p.add_argument("--min-child-samples", type=int, default=15)
    p.add_argument("--calibrate", action="store_true", help="Fit Platt scaling on OOF probs (saved in config only)")
    p.add_argument("--no-export-c", action="store_true", help="Skip treelite / manual C generation")
    p.add_argument(
        "--holdout-pct",
        type=float,
        default=0.0,
        metavar="P",
        help="Chronological holdout: after sorting by time, last P%% of rows are never in CV; "
        "scored by one model fit only on earlier rows. OOF CSV marks them is_holdout=true. "
        "Exported booster still trains on ALL rows for deployment. Default 0 = pure K-fold OOF on full set.",
    )
    args = p.parse_args()

    target_mult = 3.0 if args.target == "3x" else 2.0
    target_desc = f"peak_mult_vs_slot2_entry >= {target_mult:g}"

    df = pd.read_csv(args.input)
    print(f"Loaded {len(df)} rows from {args.input}")

    if args.cv == "time" or args.holdout_pct > 0:
        df = _sort_df_chronological(df)
        why = "time CV" if args.cv == "time" else "holdout split"
        print(f"Sorted rows chronologically ({why}).")

    groups = None
    if args.cv == "group" and "creator" in df.columns:
        creators = df["creator"].astype(str).fillna("")
        _, groups = np.unique(creators.values, return_inverse=True)

    X, y, feature_names = build_features(df, target_mult=target_mult)
    n = len(y)
    holdout_report: dict | None = None
    is_holdout = None

    lgb_params = {
        "objective": "binary",
        "metric": "auc",
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "num_leaves": min(31, max(2, (1 << args.max_depth) - 1)),
        "min_child_samples": args.min_child_samples,
        "learning_rate": args.learning_rate,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "is_unbalance": True,
        "verbose": -1,
        "random_state": 42,
        "n_jobs": -1,
    }

    if args.holdout_pct > 0:
        if not (0 < args.holdout_pct < 0.5):
            print("ERROR: --holdout-pct must be in (0, 0.5)", file=sys.stderr)
            sys.exit(1)
        n_ho = max(1, int(round(n * args.holdout_pct)))
        n_tr = n - n_ho
        if n_tr < 50:
            print(f"ERROR: holdout leaves only {n_tr} training rows; reduce --holdout-pct", file=sys.stderr)
            sys.exit(1)
        print(
            f"\nChronological holdout: train/CV on first {n_tr} rows, "
            f"strict test on last {n_ho} rows ({100 * args.holdout_pct:.1f}%)."
        )
        X_tr, y_tr = X[:n_tr], y[:n_tr]
        X_ho, y_ho = X[n_tr:], y[n_tr:]

        model, cv_metrics, oof_auc, oof_tr = train_and_evaluate(
            X_tr, y_tr, feature_names,
            cv_mode=args.cv,
            groups=groups[:n_tr] if groups is not None else None,
            lgb_params=lgb_params,
            n_splits=args.n_splits,
        )

        ho_model = lgb.LGBMClassifier(**lgb_params)
        ho_model.fit(_x_frame(X_tr, feature_names), y_tr)
        ho_probs = ho_model.predict_proba(_x_frame(X_ho, feature_names))[:, 1]
        ho_auc = roc_auc_score(y_ho, ho_probs) if len(np.unique(y_ho)) > 1 else 0.0
        print(f"\nHoldout AUC (model never saw these {n_ho} rows): {ho_auc:.4f}")
        print(classification_report(y_ho, (ho_probs >= 0.5).astype(int), target_names=["neg", "pos"], zero_division=0))

        oof_probs = np.concatenate([oof_tr, ho_probs])
        is_holdout = np.concatenate([np.zeros(n_tr, dtype=bool), np.ones(n_ho, dtype=bool)])
        holdout_report = {
            "fraction": round(args.holdout_pct, 4),
            "n_train": n_tr,
            "n_holdout": n_ho,
            "holdout_auc": round(ho_auc, 4),
            "oof_auc_train_subset_only": round(oof_auc, 4),
        }

        model = lgb.LGBMClassifier(**lgb_params)
        model.fit(_x_frame(X, y), feature_names)
        print("\nExported booster fit on ALL rows (deployment); holdout metrics above are from train-only model.")
    else:
        model, cv_metrics, oof_auc, oof_probs = train_and_evaluate(
            X, y, feature_names,
            cv_mode=args.cv,
            groups=groups,
            lgb_params=lgb_params,
            n_splits=args.n_splits,
        )

    write_oof_csv(df, oof_probs, y, args.cv, target_desc, OOF_CSV, is_holdout=is_holdout)

    platt_payload = None
    oof_for_threshold = oof_probs
    if args.calibrate:
        lr, cal = platt_calibrate(oof_probs, y)
        platt_payload = {
            "coef": lr.coef_.tolist(),
            "intercept": float(lr.intercept_[0]),
        }
        print(f"\nPlatt calibration fitted (coef shape {lr.coef_.shape})")
        oof_for_threshold = cal

    print("\nThreshold analysis (OOF):")
    print(f"{'Thresh':>6s}  {'Prec':>6s}  {'Rec':>6s}  {'F1':>6s}  {'N_pos':>6s}")
    for t in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        preds = (oof_for_threshold >= t).astype(int)
        if preds.sum() == 0:
            continue
        prec = precision_score(y, preds, zero_division=0)
        rec = recall_score(y, preds, zero_division=0)
        f1 = f1_score(y, preds, zero_division=0)
        print(f"  {t:.1f}   {prec:.4f}  {rec:.4f}  {f1:.4f}  {preds.sum():5d}")

    model_path = ML_DIR / "kol_scorer_model.txt"
    model.booster_.save_model(str(model_path))
    print(f"\nSaved LightGBM model → {model_path}")

    treelite_dir = ML_DIR / "kol_scorer_treelite"
    if not args.no_export_c:
        try:
            export_treelite(model, feature_names, treelite_dir)
        except Exception as e:
            print(f"WARNING: treelite export failed: {e}")
    generate_manual_c(model, feature_names, treelite_dir)

    export_config(
        feature_names, cv_metrics, oof_auc,
        {**model.get_params(), "n_splits": args.n_splits},
        ML_DIR / "kol_scorer_config.json",
        cv_mode=args.cv,
        target_desc=target_desc,
        oof_csv="ml/kol_oof_predictions.csv",
        platt_coef=platt_payload,
        holdout_report=holdout_report,
    )

    print("\nDone.")


if __name__ == "__main__":
    main()
