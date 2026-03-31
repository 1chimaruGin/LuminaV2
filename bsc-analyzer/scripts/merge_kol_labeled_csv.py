#!/usr/bin/env python3
"""
Merge two KOL dataset CSVs with the same header, dedupe on (token_address, create_block).

Use after labeling live rows or combining historical chunks before training.

Example:
  python3 scripts/merge_kol_labeled_csv.py \\
    backtest_results/kol_dataset_90d.csv \\
    backtest_results/kol_dataset_live_labeled.csv \\
    -o backtest_results/kol_dataset_merged.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("base", type=Path, help="Primary CSV (rows win on tie)")
    p.add_argument("extra", type=Path, help="CSV to merge in")
    p.add_argument("-o", "--output", type=Path, required=True, help="Output CSV path")
    p.add_argument(
        "--require-peak",
        action="store_true",
        help="Drop rows where peak_mult_vs_slot2_entry is missing or non-positive",
    )
    args = p.parse_args()

    a = pd.read_csv(args.base)
    b = pd.read_csv(args.extra)
    if list(a.columns) != list(b.columns):
        missing_a = set(b.columns) - set(a.columns)
        missing_b = set(a.columns) - set(b.columns)
        raise SystemExit(
            f"Column mismatch. Only in base: {missing_b}. Only in extra: {missing_a}."
        )

    key_tok = "token_address" if "token_address" in a.columns else None
    key_blk = "create_block" if "create_block" in a.columns else None
    if not key_tok or not key_blk:
        raise SystemExit("CSV must contain token_address and create_block for dedupe.")

    merged = pd.concat([a, b], ignore_index=True)
    merged["_blk"] = pd.to_numeric(merged[key_blk], errors="coerce").fillna(-1).astype(int)
    merged["_tok"] = merged[key_tok].astype(str).str.lower()
    merged = merged.sort_values(["_tok", "_blk"], kind="mergesort")
    merged = merged.drop_duplicates(subset=["_tok", "_blk"], keep="first")
    merged = merged.drop(columns=["_tok", "_blk"])

    if args.require_peak:
        col = "peak_mult_vs_slot2_entry"
        if col in merged.columns:
            pm = pd.to_numeric(merged[col], errors="coerce")
            merged = merged[pm > 0].reset_index(drop=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False)
    print(f"Wrote {len(merged)} rows → {args.output}")


if __name__ == "__main__":
    main()
