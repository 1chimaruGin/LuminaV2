#!/usr/bin/env python3
"""
Copy lines from a kol_monitor JSONL where kol_count > 2.

Usage:
  python3 scripts/filter_kol_jsonl.py input.jsonl output.jsonl
  python3 scripts/filter_kol_jsonl.py backtest_results/kol_backtest_30d_latest.jsonl backtest_results/kol_gt2.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser(description="Keep only rows with kol_count > 2")
    ap.add_argument("input_jsonl", help="Source JSONL")
    ap.add_argument("output_jsonl", help="Destination JSONL")
    ap.add_argument(
        "--min",
        type=int,
        default=2,
        metavar="N",
        help="Minimum kol_count (default: 2, i.e. keep kol_count >= 2)",
    )
    args = ap.parse_args()
    # kol_count > 2  <=>  kol_count >= 3
    threshold = args.min

    n_in = n_out = 0
    with open(args.input_jsonl, encoding="utf-8") as inf, open(
        args.output_jsonl, "w", encoding="utf-8"
    ) as outf:
        for line in inf:
            line = line.strip()
            if not line:
                continue
            if line.startswith('{"summary"'):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_in += 1
            kc = rec.get("kol_count")
            if kc is None:
                continue
            try:
                kc_i = int(kc)
            except (TypeError, ValueError):
                continue
            if kc_i >= threshold:
                outf.write(line + "\n")
                n_out += 1

    print(f"Read {n_in} token rows, wrote {n_out} (kol_count >= {threshold})", file=sys.stderr)


if __name__ == "__main__":
    main()
