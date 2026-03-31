#!/usr/bin/env python3
"""
Analyze KOL backtest results — win rates, key factors, KOL rankings.

Usage:
    python3 scripts/analyze_backtest.py backtest_results/kol_backtest_30d.jsonl

For per-slot / per-delay sniper stats (slot_1..3 × plus_1_block / plus_2_block / plus_2s), see:
    python3 scripts/analyze_by_slot.py backtest_results/kol_dataset.jsonl
"""

import json
import sys
import os
from collections import defaultdict
from datetime import datetime

def load_data(path):
    tokens = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("{\"summary"):
                continue
            try:
                rec = json.loads(line)
                if "token" in rec:
                    tokens.append(rec)
            except json.JSONDecodeError:
                continue
    return tokens

def load_kol_names(top_json_path):
    names = {}
    if not os.path.exists(top_json_path):
        return names
    with open(top_json_path) as f:
        data = json.load(f)
    for entry in data:
        addr = entry.get("address", "").lower()
        name = entry.get("name", "")
        groups = entry.get("groups", [])
        label = name if name else (groups[0] if groups else addr[:10])
        names[addr] = label
    return names

def kol_label(addr, kol_names):
    label = kol_names.get(addr.lower(), "")
    if not label or label in ("GOAT", ""):
        return addr[:6] + "…" + addr[-4:]
    return label

def analyze(tokens, kol_names):
    print(f"\n{'='*80}")
    print(f"  LUMINA KOL BACKTEST ANALYSIS — {len(tokens)} tokens")
    print(f"{'='*80}\n")

    # ── Overall stats ──
    graduated = [t for t in tokens if t.get("graduated")]
    peak_2x = [t for t in tokens if t.get("peak_x", 0) >= 2.0]
    peak_5x = [t for t in tokens if t.get("peak_x", 0) >= 5.0]
    peak_10x = [t for t in tokens if t.get("peak_x", 0) >= 10.0]
    dumped = [t for t in tokens if t.get("low_x", 1) < 0.5]

    dates = set()
    for t in tokens:
        ct = t.get("create_time", "")
        if ct and ct != "unknown":
            dates.add(ct[:10])
    date_range = f"{min(dates)} to {max(dates)}" if dates else "unknown"

    print(f"  Date range:      {date_range}")
    print(f"  Total tokens:    {len(tokens)}")
    print(f"  Graduated (DEX): {len(graduated)} ({100*len(graduated)/max(len(tokens),1):.1f}%)")
    print(f"  Peak ≥ 2x:       {len(peak_2x)} ({100*len(peak_2x)/max(len(tokens),1):.1f}%)")
    print(f"  Peak ≥ 5x:       {len(peak_5x)} ({100*len(peak_5x)/max(len(tokens),1):.1f}%)")
    print(f"  Peak ≥ 10x:      {len(peak_10x)} ({100*len(peak_10x)/max(len(tokens),1):.1f}%)")
    print(f"  Dumped < 0.5x:   {len(dumped)} ({100*len(dumped)/max(len(tokens),1):.1f}%)")

    avg_peak = sum(t.get("peak_x", 0) for t in tokens) / max(len(tokens), 1)
    median_peak = sorted(t.get("peak_x", 0) for t in tokens)[len(tokens)//2] if tokens else 0
    print(f"  Avg peak_x:      {avg_peak:.2f}x")
    print(f"  Median peak_x:   {median_peak:.2f}x")

    # ── KOL Performance Rankings ──
    print(f"\n{'─'*80}")
    print(f"  KOL PERFORMANCE RANKINGS (by first-buyer win rate)")
    print(f"{'─'*80}\n")

    kol_stats = defaultdict(lambda: {
        "tokens": [], "wins_2x": 0, "wins_5x": 0, "wins_10x": 0,
        "graduated": 0, "total_peak_x": 0, "total_entry_mcap": 0,
        "ages": []
    })

    for t in tokens:
        buyer = t.get("first_buyer", "")
        if not buyer:
            continue
        s = kol_stats[buyer]
        s["tokens"].append(t)
        peak_x = t.get("peak_x", 0)
        if peak_x >= 2.0: s["wins_2x"] += 1
        if peak_x >= 5.0: s["wins_5x"] += 1
        if peak_x >= 10.0: s["wins_10x"] += 1
        if t.get("graduated"): s["graduated"] += 1
        s["total_peak_x"] += peak_x
        s["total_entry_mcap"] += t.get("entry_mcap_usd", 0)
        s["ages"].append(t.get("age_blocks", 0))

    kol_list = []
    for addr, s in kol_stats.items():
        n = len(s["tokens"])
        kol_list.append({
            "address": addr,
            "label": kol_label(addr, kol_names),
            "count": n,
            "win_rate_2x": s["wins_2x"] / n if n else 0,
            "win_rate_5x": s["wins_5x"] / n if n else 0,
            "win_rate_10x": s["wins_10x"] / n if n else 0,
            "grad_rate": s["graduated"] / n if n else 0,
            "avg_peak_x": s["total_peak_x"] / n if n else 0,
            "avg_entry_mcap": s["total_entry_mcap"] / n if n else 0,
            "median_age": sorted(s["ages"])[len(s["ages"])//2] if s["ages"] else 0,
            "wins_2x": s["wins_2x"],
            "wins_5x": s["wins_5x"],
            "wins_10x": s["wins_10x"],
            "graduated": s["graduated"],
        })

    kol_list.sort(key=lambda k: (-k["win_rate_2x"], -k["avg_peak_x"]))

    header = f"  {'KOL':<22} {'Tokens':>6} {'Win≥2x':>8} {'Win≥5x':>8} {'Win≥10x':>8} {'Grad%':>7} {'AvgPeakX':>9} {'AvgEntry$':>10} {'MedAge':>7}"
    print(header)
    print(f"  {'─'*len(header.strip())}")
    for k in kol_list:
        print(f"  {k['label']:<22} {k['count']:>6} {k['win_rate_2x']:>7.0%} {k['win_rate_5x']:>7.0%} {k['win_rate_10x']:>7.0%} {k['grad_rate']:>6.0%} {k['avg_peak_x']:>9.2f}x {k['avg_entry_mcap']:>9,.0f} {k['median_age']:>6}b")

    # ── Factor Analysis ──
    print(f"\n{'─'*80}")
    print(f"  FACTOR ANALYSIS — What predicts a win?")
    print(f"{'─'*80}\n")

    # Factor 1: Entry mcap bucket
    print("  1. ENTRY MCAP vs WIN RATE")
    mcap_buckets = [
        (0, 5000, "<$5K"),
        (5000, 8000, "$5-8K"),
        (8000, 12000, "$8-12K"),
        (12000, 20000, "$12-20K"),
        (20000, 50000, "$20-50K"),
        (50000, 1e9, ">$50K"),
    ]
    print(f"     {'Bucket':<12} {'Count':>6} {'Win≥2x':>8} {'Win≥5x':>8} {'AvgPeakX':>9} {'Grad%':>7}")
    for lo, hi, label in mcap_buckets:
        bucket = [t for t in tokens if lo <= t.get("entry_mcap_usd", 0) < hi]
        if not bucket:
            continue
        n = len(bucket)
        w2 = sum(1 for t in bucket if t.get("peak_x", 0) >= 2) / n
        w5 = sum(1 for t in bucket if t.get("peak_x", 0) >= 5) / n
        ap = sum(t.get("peak_x", 0) for t in bucket) / n
        gr = sum(1 for t in bucket if t.get("graduated")) / n
        print(f"     {label:<12} {n:>6} {w2:>7.0%} {w5:>7.0%} {ap:>9.2f}x {gr:>6.0%}")

    # Factor 2: Age blocks (how early KOL entered)
    print(f"\n  2. ENTRY TIMING (age_blocks) vs WIN RATE")
    age_buckets = [
        (0, 20, "<1min"),
        (20, 100, "1-5min"),
        (100, 600, "5-30min"),
        (600, 2400, "30m-2h"),
        (2400, 28800, "2-24h"),
        (28800, 1e9, ">24h"),
    ]
    print(f"     {'Timing':<12} {'Count':>6} {'Win≥2x':>8} {'Win≥5x':>8} {'AvgPeakX':>9} {'Grad%':>7}")
    for lo, hi, label in age_buckets:
        bucket = [t for t in tokens if lo <= t.get("age_blocks", 0) < hi]
        if not bucket:
            continue
        n = len(bucket)
        w2 = sum(1 for t in bucket if t.get("peak_x", 0) >= 2) / n
        w5 = sum(1 for t in bucket if t.get("peak_x", 0) >= 5) / n
        ap = sum(t.get("peak_x", 0) for t in bucket) / n
        gr = sum(1 for t in bucket if t.get("graduated")) / n
        print(f"     {label:<12} {n:>6} {w2:>7.0%} {w5:>7.0%} {ap:>9.2f}x {gr:>6.0%}")

    # Factor 3: KOL count
    print(f"\n  3. KOL COUNT (how many KOLs bought) vs WIN RATE")
    kc_buckets = [(1, 2, "1 KOL"), (2, 3, "2 KOLs"), (3, 4, "3 KOLs"), (4, 100, "4+ KOLs")]
    print(f"     {'KOLs':<12} {'Count':>6} {'Win≥2x':>8} {'Win≥5x':>8} {'AvgPeakX':>9} {'Grad%':>7}")
    for lo, hi, label in kc_buckets:
        bucket = [t for t in tokens if lo <= t.get("kol_count", 0) < hi]
        if not bucket:
            continue
        n = len(bucket)
        w2 = sum(1 for t in bucket if t.get("peak_x", 0) >= 2) / n
        w5 = sum(1 for t in bucket if t.get("peak_x", 0) >= 5) / n
        ap = sum(t.get("peak_x", 0) for t in bucket) / n
        gr = sum(1 for t in bucket if t.get("graduated")) / n
        print(f"     {label:<12} {n:>6} {w2:>7.0%} {w5:>7.0%} {ap:>9.2f}x {gr:>6.0%}")

    # Factor 4: Graduated vs not
    print(f"\n  4. GRADUATED vs BONDING CURVE")
    for grad_val, label in [(True, "Graduated"), (False, "On curve")]:
        bucket = [t for t in tokens if t.get("graduated") == grad_val]
        if not bucket:
            continue
        n = len(bucket)
        w2 = sum(1 for t in bucket if t.get("peak_x", 0) >= 2) / n
        w5 = sum(1 for t in bucket if t.get("peak_x", 0) >= 5) / n
        ap = sum(t.get("peak_x", 0) for t in bucket) / n
        print(f"     {label:<12} {n:>6} Win≥2x:{w2:>5.0%}  Win≥5x:{w5:>5.0%}  AvgPeakX:{ap:.2f}x")

    # Factor 5: Day of week
    print(f"\n  5. DAY OF WEEK")
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_stats = defaultdict(list)
    for t in tokens:
        ct = t.get("create_time", "")
        if ct and ct != "unknown":
            try:
                dt = datetime.strptime(ct, "%Y-%m-%dT%H:%M:%SZ")
                dow_stats[dt.weekday()].append(t)
            except ValueError:
                pass
    if dow_stats:
        print(f"     {'Day':<6} {'Count':>6} {'Win≥2x':>8} {'AvgPeakX':>9}")
        for dow in range(7):
            bucket = dow_stats.get(dow, [])
            if not bucket:
                continue
            n = len(bucket)
            w2 = sum(1 for t in bucket if t.get("peak_x", 0) >= 2) / n
            ap = sum(t.get("peak_x", 0) for t in bucket) / n
            print(f"     {dow_names[dow]:<6} {n:>6} {w2:>7.0%} {ap:>9.2f}x")

    # Factor 6: Hour of day
    print(f"\n  6. HOUR OF DAY (UTC)")
    hour_stats = defaultdict(list)
    for t in tokens:
        ct = t.get("create_time", "")
        if ct and ct != "unknown":
            try:
                dt = datetime.strptime(ct, "%Y-%m-%dT%H:%M:%SZ")
                hour_stats[dt.hour].append(t)
            except ValueError:
                pass
    if hour_stats:
        print(f"     {'Hour':<6} {'Count':>6} {'Win≥2x':>8} {'AvgPeakX':>9}")
        for h in range(24):
            bucket = hour_stats.get(h, [])
            if not bucket:
                continue
            n = len(bucket)
            w2 = sum(1 for t in bucket if t.get("peak_x", 0) >= 2) / n
            ap = sum(t.get("peak_x", 0) for t in bucket) / n
            print(f"     {h:02d}:00  {n:>6} {w2:>7.0%} {ap:>9.2f}x")

    # ── Combined Signal ──
    print(f"\n{'─'*80}")
    print(f"  COMBINED SIGNAL — Best KOL + early entry + multi-KOL")
    print(f"{'─'*80}\n")

    # Find the best KOL by win rate (min 10 tokens)
    qualified_kols = [k for k in kol_list if k["count"] >= 10]
    if qualified_kols:
        best_kol = qualified_kols[0]["address"]
        best_label = qualified_kols[0]["label"]
        print(f"  Best KOL (≥10 tokens): {best_label} ({qualified_kols[0]['address']})")
        print(f"    Win≥2x: {qualified_kols[0]['win_rate_2x']:.0%}, Win≥5x: {qualified_kols[0]['win_rate_5x']:.0%}, "
              f"AvgPeakX: {qualified_kols[0]['avg_peak_x']:.2f}x, Tokens: {qualified_kols[0]['count']}")

    # Combined: best KOL + early entry (<100 blocks) + kol_count >= 2
    combo = [t for t in tokens
             if t.get("age_blocks", 999) < 100
             and t.get("kol_count", 0) >= 2]
    if combo:
        n = len(combo)
        w2 = sum(1 for t in combo if t.get("peak_x", 0) >= 2) / n
        w5 = sum(1 for t in combo if t.get("peak_x", 0) >= 5) / n
        ap = sum(t.get("peak_x", 0) for t in combo) / n
        print(f"\n  Early entry (<5min) + 2+ KOLs: {n} tokens")
        print(f"    Win≥2x: {w2:.0%}, Win≥5x: {w5:.0%}, AvgPeakX: {ap:.2f}x")

    combo2 = [t for t in tokens
              if t.get("age_blocks", 999) < 100
              and t.get("kol_count", 0) >= 3]
    if combo2:
        n = len(combo2)
        w2 = sum(1 for t in combo2 if t.get("peak_x", 0) >= 2) / n
        w5 = sum(1 for t in combo2 if t.get("peak_x", 0) >= 5) / n
        ap = sum(t.get("peak_x", 0) for t in combo2) / n
        print(f"\n  Early entry (<5min) + 3+ KOLs: {n} tokens")
        print(f"    Win≥2x: {w2:.0%}, Win≥5x: {w5:.0%}, AvgPeakX: {ap:.2f}x")

    # ── Top 20 Best Tokens ──
    print(f"\n{'─'*80}")
    print(f"  TOP 20 TOKENS BY PEAK PERFORMANCE")
    print(f"{'─'*80}\n")

    top20 = sorted(tokens, key=lambda t: t.get("peak_x", 0), reverse=True)[:20]
    print(f"  {'#':<4} {'Name':<25} {'Entry$':>8} {'Peak$':>10} {'PeakX':>7} {'KOLs':>5} {'Age':>6} {'Buyer':<22} {'Grad':>5}")
    print(f"  {'─'*100}")
    for i, t in enumerate(top20, 1):
        buyer_label = kol_label(t.get("first_buyer", ""), kol_names)
        name = t.get("name", "?")[:24]
        print(f"  {i:<4} {name:<25} {t.get('entry_mcap_usd',0):>8,.0f} {t.get('peak_mcap_usd',0):>10,.0f} "
              f"{t.get('peak_x',0):>6.1f}x {t.get('kol_count',0):>5} {t.get('age_blocks',0):>5}b "
              f"{buyer_label:<22} {'YES' if t.get('graduated') else 'no':>5}")

    # ── Worst 10 Tokens ──
    print(f"\n{'─'*80}")
    print(f"  BOTTOM 10 TOKENS BY PERFORMANCE (biggest dumps)")
    print(f"{'─'*80}\n")

    bottom10 = sorted(tokens, key=lambda t: t.get("low_x", 1))[:10]
    print(f"  {'#':<4} {'Name':<25} {'Entry$':>8} {'Low$':>8} {'LowX':>7} {'PeakX':>7} {'Buyer':<22}")
    print(f"  {'─'*90}")
    for i, t in enumerate(bottom10, 1):
        buyer_label = kol_label(t.get("first_buyer", ""), kol_names)
        name = t.get("name", "?")[:24]
        print(f"  {i:<4} {name:<25} {t.get('entry_mcap_usd',0):>8,.0f} {t.get('low_mcap_usd',0):>8,.0f} "
              f"{t.get('low_x',1):>6.2f}x {t.get('peak_x',0):>6.1f}x {buyer_label:<22}")

    print(f"\n{'='*80}")
    print(f"  Analysis complete. {len(tokens)} tokens from {date_range}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/analyze_backtest.py <backtest.jsonl> [top.json]")
        sys.exit(1)

    data_path = sys.argv[1]
    kol_path = sys.argv[2] if len(sys.argv) > 2 else "top.json"

    tokens = load_data(data_path)
    if not tokens:
        print(f"No tokens found in {data_path}")
        sys.exit(1)

    kol_names = load_kol_names(kol_path)
    analyze(tokens, kol_names)
