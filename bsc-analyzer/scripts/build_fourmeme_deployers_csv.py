#!/usr/bin/env python3
"""
Build data/deployers_fourmeme.csv from a full KOL dataset (CSV or Parquet).

Output schema matches lumina::DeployerDB::load_csv and build_deployer_db.py.

Usage:
  python scripts/build_fourmeme_deployers_csv.py \\
    --input backtest_results/kol_dataset_90d_full.csv \\
    --output data/deployers_fourmeme.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from deployer_reputation import (  # noqa: E402
    cpp_csv_row_from_snapshots,
    load_csv_records,
    row_to_snapshot,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", "-i", required=True)
    p.add_argument("--output", "-o", default="data/deployers_fourmeme.csv")
    args = p.parse_args()

    if args.input.lower().endswith(".parquet"):
        try:
            import pandas as pd
        except ImportError as e:
            print("Parquet input requires pandas", file=sys.stderr)
            raise SystemExit(1) from e
        df = pd.read_parquet(args.input)
        new_cols = []
        for c in df.columns:
            if c == "" or (isinstance(c, str) and c.strip() == ""):
                new_cols.append("deployer_prior_launches")
            else:
                new_cols.append(c)
        df.columns = new_cols
        records = df.replace({pd.NA: None}).to_dict(orient="records")
    else:
        records, _ = load_csv_records(args.input)
    by_c: dict[str, list] = defaultdict(list)
    for rec in records:
        c = (rec.get("creator") or "").lower()
        if c:
            by_c[c].append(row_to_snapshot(rec))

    fieldnames = [
        "deployer",
        "total_tokens",
        "rugged",
        "honeypots",
        "successful",
        "avg_lifespan_hours",
        "success_rate",
        "rug_rate",
        "score",
        "first_seen_block",
        "last_seen_block",
    ]
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for addr in sorted(by_c.keys()):
            w.writerow(cpp_csv_row_from_snapshots(addr, by_c[addr]))

    print(f"Wrote {args.output} ({len(by_c)} deployers) from {len(records)} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
