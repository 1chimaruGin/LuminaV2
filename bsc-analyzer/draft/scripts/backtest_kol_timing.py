#!/usr/bin/env python3
"""
Backtest KOL copy-trade strategy using ClickHouse kol_swaps + kol_token_trades.

Answers:
  - What is each KOL's win rate?
  - How does copy-timing affect outcomes (0-15s, 15-60s, 1-5m, 5m+)?
  - Does KOL convergence (2+ KOLs buying same token) beat single-KOL buys?
  - What is the optimal "copy delay" window?

Usage:
    python scripts/backtest_kol_timing.py [--min-usd 50] [--output backtest_results/kol_backtest.json]

Requires: ClickHouse with lumina.kol_swaps and lumina.kol_token_trades populated.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLICKHOUSE_BIN = os.environ.get("CLICKHOUSE_BIN", str(PROJECT_ROOT / "clickhouse-bin"))

TIMING_BUCKETS = [
    ("0-15s",    0,    15),
    ("15-60s",   16,   60),
    ("1-5min",   61,   300),
    ("5-30min",  301,  1800),
    ("30min+",   1801, 999999),
]

PNL_THRESHOLDS = {
    "2x": 100.0,
    "5x": 400.0,
    "10x": 900.0,
}


def ch_query(query: str) -> list[dict]:
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"{query} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        sys.stderr.write(f"ClickHouse error: {result.stderr[:500]}\n")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


def load_kol_wallets(top_path: Path) -> dict[str, str]:
    """Returns {lowercase_address: label}."""
    if not top_path.exists():
        return {}
    data = json.loads(top_path.read_text())
    out = {}
    for row in data:
        addr = (row.get("address") or "").strip().lower()
        label = row.get("label") or row.get("name") or addr[:12]
        if len(addr) == 42 and addr.startswith("0x"):
            out[addr] = label
    return out


def bucket_label(seconds: float) -> str:
    for label, lo, hi in TIMING_BUCKETS:
        if lo <= seconds <= hi:
            return label
    return "unknown"


def main():
    ap = argparse.ArgumentParser(description="Backtest KOL copy-trade strategy")
    ap.add_argument("--min-usd", type=float, default=50,
                    help="Minimum USD value per trade to include (filter dust)")
    ap.add_argument("--top-json", type=Path, default=PROJECT_ROOT / "top.json")
    ap.add_argument("--output", type=Path, default=PROJECT_ROOT / "backtest_results" / "kol_backtest.json")
    args = ap.parse_args()

    kol_wallets = load_kol_wallets(args.top_json)
    if not kol_wallets:
        sys.stderr.write(f"No KOL wallets in {args.top_json}\n")
        sys.exit(1)
    sys.stderr.write(f"Loaded {len(kol_wallets)} KOL wallets\n")

    # ── 1. Per-KOL win rates from kol_token_trades ────────────────────────
    sys.stderr.write("Querying per-KOL trade outcomes...\n")
    in_list = ",".join(f"'{w}'" for w in kol_wallets)
    trades = ch_query(f"""
        SELECT
            wallet_address,
            token_address,
            token_symbol,
            buy_count,
            sell_count,
            total_buy_usd,
            total_sell_usd,
            realized_pnl_usd,
            realized_pnl_pct,
            first_buy_ts,
            last_sell_ts,
            hold_duration_sec,
            exit_type
        FROM lumina.kol_token_trades FINAL
        WHERE wallet_address IN ({in_list})
          AND total_buy_usd >= {args.min_usd}
        ORDER BY wallet_address, first_buy_ts
    """)
    sys.stderr.write(f"  Got {len(trades)} token trades\n")

    # ── 2. Per-KOL summary ────────────────────────────────────────────────
    kol_stats: dict[str, dict] = {}
    for t in trades:
        w = t["wallet_address"]
        if w not in kol_stats:
            kol_stats[w] = {
                "label": kol_wallets.get(w, w[:12]),
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0,
                "total_pnl_usd": 0.0,
                "pnl_list": [],
                "tokens": [],
            }
        s = kol_stats[w]
        s["total_trades"] += 1
        pnl = float(t["realized_pnl_pct"])
        s["pnl_list"].append(pnl)
        s["total_pnl_usd"] += float(t["realized_pnl_usd"])
        if pnl > 20:
            s["wins"] += 1
        elif pnl < -20:
            s["losses"] += 1
        else:
            s["breakeven"] += 1
        s["tokens"].append({
            "token": t["token_address"],
            "symbol": t["token_symbol"],
            "pnl_pct": pnl,
            "buy_usd": float(t["total_buy_usd"]),
            "sell_usd": float(t["total_sell_usd"]),
        })

    # Compute win rates
    for w, s in kol_stats.items():
        n = s["total_trades"]
        s["win_rate"] = s["wins"] / n if n else 0
        if s["pnl_list"]:
            pl = sorted(s["pnl_list"])
            s["avg_pnl_pct"] = sum(pl) / len(pl)
            s["median_pnl_pct"] = pl[len(pl) // 2]
            s["best_pnl_pct"] = pl[-1]
            s["worst_pnl_pct"] = pl[0]
        else:
            s["avg_pnl_pct"] = s["median_pnl_pct"] = s["best_pnl_pct"] = s["worst_pnl_pct"] = 0

    # ── 3. Timing analysis from kol_swaps ─────────────────────────────────
    sys.stderr.write("Querying KOL buy timing vs token first appearance...\n")
    timing_data = ch_query(f"""
        SELECT
            s.wallet_address as wallet,
            s.token_address as token,
            s.token_symbol as symbol,
            min(s.block_timestamp) as kol_first_buy_ts,
            f.pair_created_ts as token_created_ts,
            f.kol_buyer_count as kol_count
        FROM lumina.kol_swaps s
        LEFT JOIN lumina.token_features f ON lower(s.token_address) = lower(f.token_address)
        WHERE s.wallet_address IN ({in_list})
          AND s.side = 'buy'
          AND s.usd_value >= {args.min_usd}
          AND f.pair_created_ts > 0
        GROUP BY s.wallet_address, s.token_address, s.token_symbol, f.pair_created_ts, f.kol_buyer_count
    """)
    sys.stderr.write(f"  Got {len(timing_data)} timed entries\n")

    # Join timing with PnL from kol_token_trades
    pnl_lookup: dict[tuple[str, str], float] = {}
    for t in trades:
        key = (t["wallet_address"], t["token_address"])
        pnl_lookup[key] = float(t["realized_pnl_pct"])

    # Bucket analysis
    bucket_stats: dict[str, dict] = {label: {"count": 0, "wins": 0, "pnl_sum": 0.0, "pnl_list": []}
                                      for label, _, _ in TIMING_BUCKETS}
    convergence_stats: dict[int, dict] = {}

    for td in timing_data:
        kol_ts = int(td["kol_first_buy_ts"])
        token_ts = int(td["token_created_ts"])
        if token_ts <= 0 or kol_ts <= 0:
            continue
        delay_sec = kol_ts - token_ts
        if delay_sec < 0:
            continue

        key = (td["wallet"], td["token"])
        pnl = pnl_lookup.get(key)
        if pnl is None:
            continue

        b = bucket_label(delay_sec)
        if b in bucket_stats:
            bs = bucket_stats[b]
            bs["count"] += 1
            bs["pnl_sum"] += pnl
            bs["pnl_list"].append(pnl)
            if pnl > 20:
                bs["wins"] += 1

        kc = int(td.get("kol_count", 1))
        if kc not in convergence_stats:
            convergence_stats[kc] = {"count": 0, "wins": 0, "pnl_sum": 0.0, "pnl_list": []}
        cs = convergence_stats[kc]
        cs["count"] += 1
        cs["pnl_sum"] += pnl
        cs["pnl_list"].append(pnl)
        if pnl > 20:
            cs["wins"] += 1

    # ── 4. Print results ──────────────────────────────────────────────────
    print("=" * 80)
    print("KOL COPY-TRADE BACKTEST RESULTS")
    print("=" * 80)

    print("\n── Per-KOL Win Rates ──")
    print(f"{'Wallet':<14s} {'Label':<16s} {'Trades':>7s} {'WinRate':>8s} {'AvgPnL':>8s} {'MedPnL':>8s} {'TotalPnL$':>10s}")
    print("-" * 80)
    for w in sorted(kol_stats, key=lambda x: kol_stats[x]["win_rate"], reverse=True):
        s = kol_stats[w]
        print(f"{w[:12]}.."
              f" {s['label']:<16s}"
              f" {s['total_trades']:>7d}"
              f" {s['win_rate']:>7.1%}"
              f" {s['avg_pnl_pct']:>7.1f}%"
              f" {s['median_pnl_pct']:>7.1f}%"
              f" {s['total_pnl_usd']:>10.0f}")

    print("\n── Timing Bucket Analysis ──")
    print(f"{'Bucket':<12s} {'Count':>7s} {'WinRate':>8s} {'AvgPnL':>8s} {'MedPnL':>8s} {'2x+':>6s} {'5x+':>6s} {'10x+':>6s}")
    print("-" * 70)
    for label, _, _ in TIMING_BUCKETS:
        bs = bucket_stats.get(label)
        if not bs or bs["count"] == 0:
            print(f"{label:<12s} {'0':>7s}   --")
            continue
        n = bs["count"]
        wr = bs["wins"] / n
        avg = bs["pnl_sum"] / n
        pl = sorted(bs["pnl_list"])
        med = pl[len(pl) // 2]
        hits = {k: sum(1 for p in pl if p >= v) for k, v in PNL_THRESHOLDS.items()}
        print(f"{label:<12s} {n:>7d} {wr:>7.1%} {avg:>7.1f}% {med:>7.1f}%"
              f" {hits['2x']:>5d} {hits['5x']:>5d} {hits['10x']:>5d}")

    print("\n── KOL Convergence Analysis (N KOLs bought same token) ──")
    print(f"{'KOLs':>5s} {'Count':>7s} {'WinRate':>8s} {'AvgPnL':>8s} {'MedPnL':>8s}")
    print("-" * 40)
    for kc in sorted(convergence_stats):
        cs = convergence_stats[kc]
        n = cs["count"]
        if n == 0:
            continue
        wr = cs["wins"] / n
        avg = cs["pnl_sum"] / n
        pl = sorted(cs["pnl_list"])
        med = pl[len(pl) // 2]
        print(f"{kc:>5d} {n:>7d} {wr:>7.1%} {avg:>7.1f}% {med:>7.1f}%")

    # ── 5. Save full results as JSON ──────────────────────────────────────
    output = {
        "kol_stats": {
            w: {k: v for k, v in s.items() if k != "pnl_list"}
            for w, s in kol_stats.items()
        },
        "timing_buckets": {
            label: {k: v for k, v in bs.items() if k != "pnl_list"}
            for label, bs in bucket_stats.items()
        },
        "convergence": {
            str(kc): {k: v for k, v in cs.items() if k != "pnl_list"}
            for kc, cs in convergence_stats.items()
        },
        "config": {
            "min_usd": args.min_usd,
            "kol_count": len(kol_wallets),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    sys.stderr.write(f"\nFull results saved to {args.output}\n")


if __name__ == "__main__":
    main()
