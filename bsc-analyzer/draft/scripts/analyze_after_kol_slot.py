#!/usr/bin/env python3
"""
After-KOL#N sniper stats: peak multiple (upside), low multiple (drawdown), hit rates.

Uses `slot_delay` from kol_monitor JSONL: `slot_1` = after 1st KOL buy, `slot_2` = after 2nd, etc.
Each slot has delay profiles: plus_1_block, plus_2_block, plus_2s.

Example — performance after the **2nd** KOL (your entry = sniper delay after KOL #2 buys):

  python3 scripts/analyze_after_kol_slot.py backtest_results/kol_count_gt2.jsonl --slot 2

Hit rates are share of tokens where peak_mcap / our_entry_mcap reaches 2x, 3x, etc.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from typing import Any, Optional

DELAY_KEYS = ("plus_1_block", "plus_2_block", "plus_2s")


def load_rows(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('{"summary"'):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "token" in rec:
                rows.append(rec)
    return rows


def metrics_for_cell(cell: dict[str, Any]) -> Optional[tuple[float, float]]:
    our = float(cell.get("our_entry_mcap_usd") or 0)
    peak = float(cell.get("peak_mcap_usd") or 0)
    low = float(cell.get("low_mcap_usd") or 0)
    if our < 1.0:
        return None
    peak_x = peak / our
    low_x = low / our
    return peak_x, low_x


def hit_rate(xs: list[float], threshold: float) -> float:
    if not xs:
        return 0.0
    return sum(1 for x in xs if x >= threshold) / len(xs)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Peak/low multiples and 2x/3x/… hit rates after a given KOL slot"
    )
    ap.add_argument("jsonl", help="kol_monitor JSONL (e.g. kol_count_gt2.jsonl)")
    ap.add_argument(
        "--slot",
        type=int,
        default=2,
        metavar="N",
        help="Which KOL index after which we model entry (1=first KOL, 2=second, …). Default: 2",
    )
    ap.add_argument(
        "--min-kol-count",
        type=int,
        default=0,
        metavar="K",
        help="Only rows with kol_count >= K (0 = no filter). E.g. 3 to require 3+ KOLs.",
    )
    args = ap.parse_args()

    slot_key = f"slot_{args.slot}"
    rows = load_rows(args.jsonl)

    # Collect peak_x per delay profile
    by_delay: dict[str, list[float]] = {dk: [] for dk in DELAY_KEYS}
    by_delay_low: dict[str, list[float]] = {dk: [] for dk in DELAY_KEYS}
    skipped = 0

    for rec in rows:
        if args.min_kol_count > 0 and int(rec.get("kol_count") or 0) < args.min_kol_count:
            skipped += 1
            continue
        sd = rec.get("slot_delay") or {}
        slot = sd.get(slot_key)
        if not isinstance(slot, dict):
            skipped += 1
            continue
        for dk in DELAY_KEYS:
            cell = slot.get(dk)
            if not isinstance(cell, dict):
                continue
            m = metrics_for_cell(cell)
            if m is None:
                continue
            px, lx = m
            by_delay[dk].append(px)
            by_delay_low[dk].append(lx)

    thresholds = [1.3, 1.5, 2.0, 3.0, 5.0, 10.0]

    print(f"\n{'='*72}")
    print(f"  After KOL #{args.slot} (`{slot_key}`) — sniper entry vs later peak/low")
    print(f"  Source: {args.jsonl}")
    print(f"  Rows in file: {len(rows)}")
    if args.min_kol_count > 0:
        print(f"  Filter: kol_count >= {args.min_kol_count}")
    print(f"{'='*72}\n")

    for dk in DELAY_KEYS:
        xs = by_delay[dk]
        lows = by_delay_low[dk]
        n = len(xs)
        if n == 0:
            print(f"  [{dk}] no valid rows (our_entry_mcap_usd missing or zero)\n")
            continue

        print(f"  Delay profile: {dk}  (n={n})")
        print(f"  {'Metric':<28} {'Value':>12}")
        print(f"  {'-'*42}")

        def pct(x: float) -> str:
            return f"{100.0 * x:5.1f}%"

        print(f"  {'Median peak_x':<28} {statistics.median(xs):>12.2f}x")
        print(f"  {'Mean peak_x':<28} {statistics.mean(xs):>12.2f}x")
        if n >= 2:
            print(f"  {'Stdev peak_x':<28} {statistics.stdev(xs):>12.2f}")
        print(f"  {'Median low_x (drawdown)':<28} {statistics.median(lows):>12.2f}x")
        print(f"  {'Mean low_x':<28} {statistics.mean(lows):>12.2f}x")
        dumped = sum(1 for l in lows if l < 0.5) / n
        print(f"  {'Share with low_x < 0.5 (≥50% dump)':<28} {pct(dumped):>12}")

        print(f"\n  Hit rate (peak_x ≥ threshold):")
        for t in thresholds:
            hr = hit_rate(xs, t)
            print(f"    ≥ {t:>4.1f}x  {pct(hr):>8}  ({int(round(hr * n))}/{n})")
        print()

    # Compact comparison table
    print(f"{'─'*72}")
    print("  Summary — peak hit rates by delay profile\n")
    hdr = f"  {'Profile':<16}"
    for t in thresholds:
        hdr += f"  ≥{t:g}x"
    print(hdr)
    print(f"  {'-'*len(hdr)}")
    for dk in DELAY_KEYS:
        xs = by_delay[dk]
        n = len(xs)
        if n == 0:
            line = f"  {dk:<16}" + "  (no data)" + " " * (len(hdr) - len(dk) - 20)
            print(line)
            continue
        line = f"  {dk:<16}"
        for t in thresholds:
            line += f"  {100.0 * hit_rate(xs, t):5.1f}%"
        print(line)
    print(f"\n{'='*72}\n")


if __name__ == "__main__":
    main()
