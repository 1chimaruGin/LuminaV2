#!/usr/bin/env python3
"""
Join shadow/live JSONL signals to a labeled CSV on (token_address, create_block).

Expects JSON lines with event kol_signal (token, create_block, ml_score, ...).
Labeled CSV must include token_address, create_block, and outcome columns
(e.g. peak_mult_vs_slot2_entry).

Usage:
  python3 ml/join_shadow_signals.py \\
    --signals backtest_results/kol_shadow.jsonl \\
    --labeled backtest_results/kol_shadow_labeled.csv \\
    --out backtest_results/kol_shadow_joined.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--signals", type=Path, required=True, help="JSONL from monitor + collector")
    p.add_argument("--labeled", type=Path, required=True, help="CSV with outcomes")
    p.add_argument("--out", type=Path, required=True, help="Output CSV")
    args = p.parse_args()

    rows = []
    with open(args.signals, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("event") != "kol_signal":
                continue
            tok = str(o.get("token", "")).lower()
            cb = o.get("create_block")
            try:
                cb = int(cb)
            except (TypeError, ValueError):
                continue
            rows.append({
                "token_address": tok,
                "create_block": cb,
                "signal_ml_score": o.get("ml_score"),
                "signal_mode": o.get("mode"),
                "signal_shadow": o.get("shadow"),
                "kol_combo": o.get("kol_combo"),
                "kol_count": o.get("kol_count"),
            })

    if not rows:
        print("No kol_signal rows found in JSONL")
        return

    sig = pd.DataFrame(rows)
    sig = sig.drop_duplicates(subset=["token_address", "create_block"], keep="last")

    lab = pd.read_csv(args.labeled)
    if "token_address" not in lab.columns or "create_block" not in lab.columns:
        raise SystemExit("labeled CSV needs token_address and create_block")
    lab = lab.copy()
    lab["token_address"] = lab["token_address"].astype(str).str.lower()
    lab["create_block"] = pd.to_numeric(lab["create_block"], errors="coerce").fillna(-1).astype(int)

    merged = sig.merge(lab, on=["token_address", "create_block"], how="inner")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.out, index=False)
    print(f"Joined {len(merged)} / {len(sig)} signals → {args.out}")


if __name__ == "__main__":
    main()
