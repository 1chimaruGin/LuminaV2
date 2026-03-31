#!/usr/bin/env python3
"""
Retrain KOL scorer by merging historical + labeled live data, then deploy.

Pipeline:
  1. Merge historical CSV + labeled live CSV
  2. Train with train_kol_scorer_v2.py
  3. Compare old vs new model metrics
  4. Export new C header → rebuild C++ binary

Usage:
    python ml/retrain_and_deploy.py [--historical backtest_results/kol_dataset_90d_full_kol2plus.csv]
                                     [--live backtest_results/kol_dataset_live_labeled.csv]
                                     [--auto-build]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = PROJECT_ROOT / "ml"


def merge_datasets(historical_path: str, live_path: str, output_path: str) -> int:
    hist = pd.read_csv(historical_path)
    print(f"Historical: {len(hist)} rows from {historical_path}")

    live = pd.read_csv(live_path)
    # Only include labeled rows (peak_mult > 0)
    live["peak_mult_vs_slot2_entry"] = pd.to_numeric(
        live.get("peak_mult_vs_slot2_entry", 0), errors="coerce"
    ).fillna(0)
    labeled = live[live["peak_mult_vs_slot2_entry"] > 0].copy()
    print(f"Live: {len(live)} rows, {len(labeled)} labeled from {live_path}")

    if len(labeled) == 0:
        print("No labeled live data. Run label_live_data.py first.", file=sys.stderr)
        return 0

    # Dedup by token_address (keep live version if overlapping)
    if "token_address" in hist.columns and "token_address" in labeled.columns:
        live_tokens = set(labeled["token_address"].dropna())
        hist = hist[~hist["token_address"].isin(live_tokens)]
        print(f"After dedup: {len(hist)} historical + {len(labeled)} live")

    # Align columns
    shared_cols = [c for c in hist.columns if c in labeled.columns]
    merged = pd.concat([hist[shared_cols], labeled[shared_cols]], ignore_index=True)
    merged.to_csv(output_path, index=False)
    print(f"Merged: {len(merged)} rows → {output_path}")
    return len(labeled)


def compare_models():
    """Compare old and new model config metrics."""
    old_cfg = ML_DIR / "kol_scorer_config.json"
    new_cfg = ML_DIR / "kol_scorer_config_v2.json"

    if not old_cfg.exists() or not new_cfg.exists():
        return

    with open(old_cfg) as f:
        old = json.load(f)
    with open(new_cfg) as f:
        new = json.load(f)

    print("\n── Model Comparison ──")
    print(f"{'Metric':<25s} {'Old':>8s} {'New':>8s} {'Delta':>8s}")
    print("-" * 55)

    for key in ["oof_auc"]:
        old_val = old.get(key, 0)
        new_val = new.get(key, 0)
        delta = new_val - old_val
        print(f"{key:<25s} {old_val:8.4f} {new_val:8.4f} {delta:+8.4f}")

    old_cv = old.get("cv_metrics", {})
    new_cv = new.get("cv_metrics", {})
    for key in ["auc", "prec", "rec", "f1"]:
        ov = old_cv.get(key, 0)
        nv = new_cv.get(key, 0)
        delta = nv - ov
        print(f"cv_{key:<21s} {ov:8.4f} {nv:8.4f} {delta:+8.4f}")

    old_n = old.get("n_features", 0)
    new_n = new.get("n_features", 0)
    print(f"{'n_features':<25s} {old_n:>8d} {new_n:>8d} {new_n - old_n:>+8d}")


def main():
    p = argparse.ArgumentParser(description="Retrain and deploy KOL scorer")
    p.add_argument("--historical",
                    default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_90d_full_kol2plus.csv"))
    p.add_argument("--live",
                    default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_live_labeled.csv"))
    p.add_argument("--merged-output",
                    default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_merged.csv"))
    p.add_argument("--auto-build", action="store_true",
                    help="Rebuild C++ binary after training")
    p.add_argument("--train-args", nargs=argparse.REMAINDER, default=[],
                    help="Extra args passed to train_kol_scorer_v2.py")
    args = p.parse_args()

    if not Path(args.historical).exists():
        print(f"Historical CSV not found: {args.historical}", file=sys.stderr)
        sys.exit(1)
    if not Path(args.live).exists():
        print(f"Live labeled CSV not found: {args.live}", file=sys.stderr)
        print("Run:  python ml/label_live_data.py", file=sys.stderr)
        sys.exit(1)

    n_live = merge_datasets(args.historical, args.live, args.merged_output)
    if n_live == 0:
        sys.exit(1)

    # Train
    train_cmd = [
        sys.executable, str(ML_DIR / "train_kol_scorer_v2.py"),
        "--input", args.merged_output,
        *args.train_args,
    ]
    print(f"\nTraining: {' '.join(train_cmd)}")
    rc = subprocess.run(train_cmd).returncode
    if rc != 0:
        print(f"Training failed (exit {rc})", file=sys.stderr)
        sys.exit(rc)

    compare_models()

    if args.auto_build:
        build_dir = PROJECT_ROOT / "build"
        print(f"\nRebuilding C++...")
        rc = subprocess.run(
            ["cmake", "--build", ".", "--target", "lumina_kol_monitor", f"-j{os.cpu_count()}"],
            cwd=build_dir,
        ).returncode
        if rc == 0:
            print("Build succeeded.")
        else:
            print(f"Build failed (exit {rc})", file=sys.stderr)
            sys.exit(rc)

    print("\nDone. New model deployed.")


if __name__ == "__main__":
    main()
