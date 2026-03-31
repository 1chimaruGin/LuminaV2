#!/usr/bin/env python3
"""
Phase 1: Research & validate 60d insights on the 90d kol2plus dataset.

Outputs strategy_config_90d.json with validated thresholds, combo list,
and feature importance rankings for downstream ML training and C++ integration.

Usage:
    python ml/research_90d_strategy.py [--input backtest_results/kol_dataset_90d_full_kol2plus.csv]
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("display.max_columns", 40)
pd.set_option("display.width", 200)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dataset(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["peak_mult"] = pd.to_numeric(df["peak_mult_vs_slot2_entry"], errors="coerce")
    df["kol_count"] = pd.to_numeric(df["kol_count_final"], errors="coerce").fillna(0).astype(int)
    df["kc_at_entry"] = pd.to_numeric(df["kol_count_at_entry"], errors="coerce").fillna(1).astype(int)
    df["entry_mcap"] = pd.to_numeric(df["entry_mcap_usd"], errors="coerce").fillna(0)
    df["dev_sell"] = pd.to_numeric(df["dev_sell_usd"], errors="coerce").fillna(0)
    df["delta_blocks"] = pd.to_numeric(df["kol1_kol2_delta_blocks"], errors="coerce").fillna(0)
    df["k1_usd"] = pd.to_numeric(df["kol1_buy_usd"], errors="coerce").fillna(0)
    df["k2_usd"] = pd.to_numeric(df["kol2_buy_usd"], errors="coerce").fillna(0)
    df["holders"] = pd.to_numeric(df["holder_count_at_entry"], errors="coerce").fillna(0)
    df["bc_pct"] = pd.to_numeric(df["bonding_curve_pct"], errors="coerce").fillna(0)
    df["age_blocks"] = pd.to_numeric(df["age_blocks_at_entry"], errors="coerce").fillna(0)
    df["hour"] = pd.to_numeric(df["create_hour_utc"], errors="coerce").fillna(12)
    df["dow"] = pd.to_numeric(df["create_dow"], errors="coerce").fillna(3)
    df["k1_wr"] = pd.to_numeric(df["kol1_7d_win_rate"], errors="coerce").fillna(0)
    df["k2_wr"] = pd.to_numeric(df["kol2_7d_win_rate"], errors="coerce").fillna(0)
    df["btc_4h"] = pd.to_numeric(df["btc_4h_change_pct"], errors="coerce").fillna(0)
    df["bnb_4h"] = pd.to_numeric(df["bnb_4h_change_pct"], errors="coerce").fillna(0)
    df["dep_grads"] = pd.to_numeric(df["deployer_prior_grads"], errors="coerce").fillna(0)
    df["dep_rate"] = pd.to_numeric(df["deployer_grad_rate"], errors="coerce").fillna(0)
    df["grad"] = df["graduated"].astype(str).str.lower().isin(["true", "1"])
    df["notional"] = pd.to_numeric(df["combined_notional_k1k2_usd"], errors="coerce").fillna(0)
    df["k1_name"] = df["kol1_name"].fillna("")
    df["k2_name"] = df["kol2_name"].fillna("")
    df["combo"] = df["combo_k1k2"].fillna("")
    df["win_2x"] = df["peak_mult"] >= 2.0
    df["win_3x"] = df["peak_mult"] >= 3.0
    df["win_5x"] = df["peak_mult"] >= 5.0
    if "deployer_reputation_score" in df.columns:
        df["dep_rep"] = pd.to_numeric(df["deployer_reputation_score"], errors="coerce").fillna(0)
    if "deployer_prior_avg_peak_mult" in df.columns:
        df["dep_avg_peak"] = pd.to_numeric(df["deployer_prior_avg_peak_mult"], errors="coerce").fillna(0)
    return df


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI for binomial proportion (clamped to [0,1])."""
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def combo_stats(df: pd.DataFrame, min_n: int = 3) -> pd.DataFrame:
    rows = []
    for combo, g in df.groupby("combo"):
        if len(g) < min_n or not combo:
            continue
        n = len(g)
        k2 = int(g["win_2x"].sum())
        wlo, whi = wilson_interval(k2, n)
        rows.append({
            "combo": combo,
            "N": n,
            "avg_mult": g["peak_mult"].mean(),
            "median_mult": g["peak_mult"].median(),
            "win_2x_pct": g["win_2x"].mean() * 100,
            "win_2x_wilson_lo_pct": round(wlo * 100, 1),
            "win_2x_wilson_hi_pct": round(whi * 100, 1),
            "win_3x_pct": g["win_3x"].mean() * 100,
            "win_5x_pct": g["win_5x"].mean() * 100,
            "avg_profit_bnb": ((g["peak_mult"] - 1) * 0.03).mean(),
            "low_n": n < max(20, min_n * 3),
        })
    return pd.DataFrame(rows).sort_values("avg_mult", ascending=False).reset_index(drop=True)


def bucket_stats(
    df: pd.DataFrame,
    col: str,
    buckets: list[tuple],
    label: str,
    *,
    min_n: int = 3,
):
    rows = []
    for lo, hi, name in buckets:
        mask = (df[col] >= lo) & (df[col] < hi)
        g = df[mask]
        n = len(g)
        if n < min_n:
            continue
        k2 = int(g["win_2x"].sum())
        wlo, whi = wilson_interval(k2, n)
        rows.append({
            label: name,
            "N": n,
            "avg_mult": round(g["peak_mult"].mean(), 2),
            "median": round(g["peak_mult"].median(), 2),
            "win_2x%": round(g["win_2x"].mean() * 100, 1),
            "win_2x_wilson_lo%": round(wlo * 100, 1),
            "win_2x_wilson_hi%": round(whi * 100, 1),
            "win_3x%": round(g["win_3x"].mean() * 100, 1),
            "low_n": n < max(20, min_n * 3),
        })
    return pd.DataFrame(rows)


def slice_headline_stats(df: pd.DataFrame, good_combos: list[str], label: str) -> dict:
    """Small-N-safe headline slices for time-split comparison."""
    m4 = df["kol_count"] >= 4
    gc = df["combo"].isin(good_combos)
    out = {"label": label, "n_rows": int(len(df))}
    for name, mask in [
        ("kc_ge_4", m4),
        ("good_combo_kc_ge_3", gc & (df["kol_count"] >= 3)),
    ]:
        g = df[mask]
        n = len(g)
        if n == 0:
            out[name] = {"N": 0}
            continue
        k2 = int(g["win_2x"].sum())
        wlo, whi = wilson_interval(k2, n)
        out[name] = {
            "N": n,
            "avg_mult": round(float(g["peak_mult"].mean()), 3),
            "win_2x_pct": round(float(g["win_2x"].mean() * 100), 1),
            "win_2x_wilson_lo_pct": round(wlo * 100, 1),
            "win_2x_wilson_hi_pct": round(whi * 100, 1),
        }
    return out


def time_split_sanity(df: pd.DataFrame, good_combos: list[str], split_time: str | None) -> dict | None:
    if "create_time" not in df.columns:
        return None
    ts = pd.to_datetime(df["create_time"], errors="coerce")
    if ts.notna().sum() < max(20, len(df) // 4):
        return None
    if split_time and split_time != "median":
        cut = pd.Timestamp(split_time)
    else:
        cut = ts.median()
    early = df.loc[ts < cut]
    late = df.loc[ts >= cut]
    return {
        "split_cutoff_utc": str(cut),
        "early": slice_headline_stats(early, good_combos, "early"),
        "late": slice_headline_stats(late, good_combos, "late"),
    }


def kol_ranking(df: pd.DataFrame):
    section("KOL Rankings")

    print("\nKOL1 (first buyer) by avg mult:")
    for name, g in df.groupby("k1_name"):
        if len(g) >= 3 and name:
            print(f"  {name:4s}: {g['peak_mult'].mean():5.2f}x  (N={len(g):3d}, 2x={g['win_2x'].mean()*100:.0f}%)")

    print("\nKOL2 (second buyer) by avg mult:")
    for name, g in df.groupby("k2_name"):
        if len(g) >= 3 and name:
            print(f"  {name:4s}: {g['peak_mult'].mean():5.2f}x  (N={len(g):3d}, 2x={g['win_2x'].mean()*100:.0f}%)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_90d_full_kol2plus.csv"))
    p.add_argument("--min-n", type=int, default=3, help="Minimum rows per bucket/combo table row")
    p.add_argument(
        "--split-time",
        default=None,
        help='Time cutoff for early/late sanity (default: median create_time). Pass ISO UTC string to override.',
    )
    p.add_argument("--write-summary", action="store_true", help="Write short ml/research_summary.md")
    p.add_argument(
        "--print-feature-coverage",
        action="store_true",
        help="Print non-zero / non-null rates for deployer + macro columns (train/live parity check)",
    )
    args = p.parse_args()

    df = load_dataset(args.input)
    mn = args.min_n
    print(f"Loaded {len(df)} rows from {args.input}")
    print(f"Peak mult: mean={df['peak_mult'].mean():.2f}x, median={df['peak_mult'].median():.2f}x")
    print(f"Win rates: 2x={df['win_2x'].mean()*100:.1f}%, 3x={df['win_3x'].mean()*100:.1f}%, 5x={df['win_5x'].mean()*100:.1f}%")

    if args.print_feature_coverage:
        section("Feature coverage (ML / live parity)")
        check_cols = [
            "deployer_reputation_score",
            "deployer_prior_avg_peak_mult",
            "deployer_prior_grads",
            "deployer_grad_rate",
            "kol1_7d_win_rate",
            "kol2_7d_win_rate",
            "btc_4h_change_pct",
            "bnb_4h_change_pct",
            "kol1_held_at_entry",
            "kol2_held_at_entry",
        ]
        n = len(df)
        for c in check_cols:
            if c not in df.columns:
                print(f"  {c}: (missing column)")
                continue
            s = df[c]
            if c in ("kol1_held_at_entry", "kol2_held_at_entry"):
                m = s.astype(str).str.lower().isin(["true", "1"])
            else:
                sn = pd.to_numeric(s, errors="coerce").fillna(0)
                m = sn != 0
            nonzero = int(m.sum())
            print(f"  {c}: non-empty/non-zero {nonzero}/{n} ({100 * nonzero / max(1, n):.1f}%)")
        print("  See ml/FEATURE_PARITY.md for C++ live gaps.")

    # ── 1. Combo rankings ──
    section(f"1. Combo Rankings (N>={mn})")
    cs = combo_stats(df, min_n=mn)
    print(cs.to_string(index=False))

    good_combos = cs[cs["avg_mult"] >= 1.8]["combo"].tolist()
    weak_combos = cs[cs["avg_mult"] < 1.5]["combo"].tolist()
    print(f"\nGood combos (>=1.8x avg): {good_combos}")
    print(f"Weak combos (<1.5x avg):  {weak_combos}")

    # also show combos with N < 3 for reference
    print(f"\nSmall-sample combos (N<{mn}):")
    for combo, g in df.groupby("combo"):
        if 0 < len(g) < mn and combo:
            print(f"  {combo}: N={len(g)}, avg={g['peak_mult'].mean():.2f}x")

    # ── 2. kol_count multiplier curve ──
    section("2. kol_count_final Multiplier Curve")
    for kc in sorted(df["kol_count"].unique()):
        g = df[df["kol_count"] == kc]
        print(f"  kc={kc}: N={len(g):3d}, avg={g['peak_mult'].mean():5.2f}x, "
              f"med={g['peak_mult'].median():5.2f}x, 2x={g['win_2x'].mean()*100:.0f}%, "
              f"3x={g['win_3x'].mean()*100:.0f}%, 5x={g['win_5x'].mean()*100:.0f}%")

    # ── 3. Entry mcap ──
    section("3. Entry Mcap Buckets")
    mcap_buckets = [
        (0, 5000, "<$5k"), (5000, 10000, "$5-10k"), (10000, 15000, "$10-15k"),
        (15000, 25000, "$15-25k"), (25000, 40000, "$25-40k"), (40000, 60000, "$40-60k"),
        (60000, 1e9, ">$60k"),
    ]
    print(bucket_stats(df, "entry_mcap", mcap_buckets, "mcap", min_n=mn).to_string(index=False))

    # ── 4. Dev sell ──
    section("4. Dev Sell Buckets")
    dev_buckets = [
        (0, 0.01, "=0"), (0.01, 500, "$1-500"), (500, 2000, "$500-2k"),
        (2000, 5000, "$2-5k"), (5000, 1e9, ">$5k"),
    ]
    print(bucket_stats(df, "dev_sell", dev_buckets, "dev_sell", min_n=mn).to_string(index=False))

    # ── 5. Block delta ──
    section("5. KOL1→KOL2 Block Delta")
    delta_buckets = [
        (0, 5, "<5 blk"), (5, 20, "5-20 blk"), (20, 100, "20-100 blk"),
        (100, 500, "100-500 blk"), (500, 2000, "500-2000 blk"), (2000, 1e9, ">2000 blk"),
    ]
    print(bucket_stats(df, "delta_blocks", delta_buckets, "delta", min_n=mn).to_string(index=False))

    # ── 6. KOL1 notional ──
    section("6. KOL1 Buy Notional")
    k1_buckets = [
        (0, 30, "<$30"), (30, 75, "$30-75"), (75, 150, "$75-150"),
        (150, 300, "$150-300"), (300, 1e9, ">$300"),
    ]
    print(bucket_stats(df, "k1_usd", k1_buckets, "k1_usd", min_n=mn).to_string(index=False))

    # ── 7. KOL rankings ──
    kol_ranking(df)

    # ── 8. Feature interactions ──
    section("8. Feature Interactions")

    interactions = [
        ("kc>=4 + no dev sell", (df["kol_count"] >= 4) & (df["dev_sell"] < 1)),
        ("kc>=4 + dev sell", (df["kol_count"] >= 4) & (df["dev_sell"] >= 1)),
        ("kc>=3 + entry<$15k", (df["kol_count"] >= 3) & (df["entry_mcap"] < 15000)),
        ("kc>=3 + entry $15-30k", (df["kol_count"] >= 3) & (df["entry_mcap"].between(15000, 30000))),
        ("kc>=3 + entry>$30k", (df["kol_count"] >= 3) & (df["entry_mcap"] > 30000)),
        ("kc>=4 + k1>$150", (df["kol_count"] >= 4) & (df["k1_usd"] > 150)),
        ("kc>=3 + delta 20-100", (df["kol_count"] >= 3) & (df["delta_blocks"].between(20, 100))),
        ("good combo + kc>=3", df["combo"].isin(good_combos) & (df["kol_count"] >= 3)),
        ("good combo + kc>=4", df["combo"].isin(good_combos) & (df["kol_count"] >= 4)),
        ("graduated", df["grad"]),
        ("not graduated", ~df["grad"]),
    ]
    interaction_records: list[dict] = []
    for label, mask in interactions:
        g = df[mask]
        n = len(g)
        if n < mn:
            continue
        k2 = int(g["win_2x"].sum())
        wlo, whi = wilson_interval(k2, n)
        interaction_records.append({
            "name": label,
            "N": n,
            "avg_mult": round(float(g["peak_mult"].mean()), 3),
            "win_2x_pct": round(float(g["win_2x"].mean() * 100), 1),
            "win_2x_wilson_lo_pct": round(wlo * 100, 1),
            "win_2x_wilson_hi_pct": round(whi * 100, 1),
            "win_5x_pct": round(float(g["win_5x"].mean() * 100), 1),
            "low_n": n < max(20, mn * 3),
        })
        print(
            f"  {label:35s}: N={n:3d}, avg={g['peak_mult'].mean():5.2f}x, "
            f"2x={g['win_2x'].mean()*100:.0f}% [{wlo*100:.0f}-{whi*100:.0f}%], "
            f"5x={g['win_5x'].mean()*100:.0f}%"
        )

    # ── 9. Time of day ──
    section("9. Time of Day (UTC)")
    hour_buckets = [
        (0, 4, "0-4 UTC"), (4, 8, "4-8 UTC"), (8, 12, "8-12 UTC"),
        (12, 16, "12-16 UTC"), (16, 20, "16-20 UTC"), (20, 24, "20-24 UTC"),
    ]
    print(bucket_stats(df, "hour", hour_buckets, "hour", min_n=mn).to_string(index=False))

    # Day of week
    print("\nDay of week:")
    dow_buckets = [(i, i+1, ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][i]) for i in range(7)]
    print(bucket_stats(df, "dow", dow_buckets, "dow", min_n=mn).to_string(index=False))

    # ── 10. Deployer history ──
    section("10. Deployer History")
    dep_buckets = [
        (0, 0.01, "0 grads"), (0.01, 1.01, "1 grad"), (1.01, 3.01, "2-3 grads"),
        (3.01, 1e9, "4+ grads"),
    ]
    print(bucket_stats(df, "dep_grads", dep_buckets, "dep_grads", min_n=mn).to_string(index=False))

    dep_rep_buckets_json = None
    dep_avg_peak_buckets_json = None
    if "dep_rep" in df.columns:
        section("10b. Deployer reputation score (PIT)")
        rep_b = [
            (0, 0.2, "0-0.2"), (0.2, 0.4, "0.2-0.4"), (0.4, 0.6, "0.4-0.6"),
            (0.6, 0.8, "0.6-0.8"), (0.8, 1.01, "0.8-1.0"),
        ]
        dfr = bucket_stats(df, "dep_rep", rep_b, "rep", min_n=mn)
        print(dfr.to_string(index=False))
        dep_rep_buckets_json = dfr.to_dict(orient="records")
        if "dep_avg_peak" in df.columns:
            section("10c. Deployer prior avg peak mult")
            ap_b = [
                (0, 1.0, "<1x"), (1.0, 1.5, "1-1.5x"), (1.5, 2.0, "1.5-2x"),
                (2.0, 3.0, "2-3x"), (3.0, 1e9, ">3x"),
            ]
            dfa = bucket_stats(df, "dep_avg_peak", ap_b, "apm", min_n=mn)
            print(dfa.to_string(index=False))
            dep_avg_peak_buckets_json = dfa.to_dict(orient="records")

    # ── 11. BTC/BNB macro ──
    section("11. BTC/BNB 4h Macro")
    btc_buckets = [
        (-100, -1, "BTC down >1%"), (-1, -0.3, "BTC -0.3 to -1%"),
        (-0.3, 0.3, "BTC flat"), (0.3, 1, "BTC +0.3 to 1%"), (1, 100, "BTC up >1%"),
    ]
    print(bucket_stats(df, "btc_4h", btc_buckets, "btc_4h", min_n=mn).to_string(index=False))

    # ── 12. Holder count at entry ──
    section("12. Holder Count at Entry")
    holder_buckets = [
        (0, 1, "0"), (1, 10, "1-10"), (10, 30, "10-30"),
        (30, 60, "30-60"), (60, 100, "60-100"), (100, 1e9, "100+"),
    ]
    print(bucket_stats(df, "holders", holder_buckets, "holders", min_n=mn).to_string(index=False))

    # ── 13. Bonding curve ──
    section("13. Bonding Curve %")
    bc_buckets = [
        (0, 0.001, "0%"), (0.001, 0.10, "0-10%"), (0.10, 0.30, "10-30%"),
        (0.30, 0.60, "30-60%"), (0.60, 0.90, "60-90%"), (0.90, 1.01, "90-100%"),
    ]
    print(bucket_stats(df, "bc_pct", bc_buckets, "bc_pct", min_n=mn).to_string(index=False))

    # ── 14. Age at entry ──
    section("14. Age at Entry (blocks)")
    age_buckets = [
        (0, 10, "<10 blk"), (10, 50, "10-50 blk"), (50, 200, "50-200 blk"),
        (200, 500, "200-500 blk"), (500, 2000, "500-2k blk"), (2000, 1e9, ">2k blk"),
    ]
    print(bucket_stats(df, "age_blocks", age_buckets, "age", min_n=mn).to_string(index=False))

    # ── 15. Composite score (rule-based) ──
    section("15. Composite Score (rule-based)")
    df["score"] = 0
    df.loc[df["combo"].isin(good_combos), "score"] += 4
    df.loc[df["kol_count"] >= 3, "score"] += 3
    df.loc[df["kol_count"] >= 4, "score"] += 3
    df.loc[df["kol_count"] >= 5, "score"] += 2
    df.loc[df["dev_sell"] < 1, "score"] += 2
    df.loc[df["k1_usd"] > 100, "score"] += 2
    df.loc[df["entry_mcap"] < 15000, "score"] += 1
    df.loc[(df["entry_mcap"] >= 15000) & (df["entry_mcap"] <= 30000), "score"] += 2
    df.loc[df["delta_blocks"].between(5, 200), "score"] += 1
    df.loc[df["holders"] > 20, "score"] += 1
    df.loc[df["grad"], "score"] += 1

    score_buckets = [
        (0, 4, "0-3"), (4, 8, "4-7"), (8, 12, "8-11"),
        (12, 16, "12-15"), (16, 30, "16+"),
    ]
    print(bucket_stats(df, "score", score_buckets, "score", min_n=mn).to_string(index=False))

    split_arg = args.split_time if args.split_time is not None else "median"
    tss = time_split_sanity(df, good_combos, split_arg)
    if tss:
        section("16. Time split sanity (early vs late)")
        print(json.dumps(tss, indent=2, default=str))

    # ── Build strategy config ──
    section("OUTPUT: strategy_config_90d.json")

    config = {
        "dataset": {
            "file": args.input,
            "rows": len(df),
            "date_range": f"{df['create_time'].min()} to {df['create_time'].max()}",
        },
        "research_notes": {
            "multiple_comparisons": (
                "Many buckets and interaction slices are exploratory; Wilson 95% CIs are per-interval "
                "and do not correct for multiple testing — treat marginal effects as hypotheses."
            ),
            "min_n": mn,
            "split_time_arg": split_arg,
        },
        "overall": {
            "avg_mult": round(df["peak_mult"].mean(), 3),
            "median_mult": round(df["peak_mult"].median(), 3),
            "win_2x_pct": round(df["win_2x"].mean() * 100, 1),
            "win_3x_pct": round(df["win_3x"].mean() * 100, 1),
            "win_5x_pct": round(df["win_5x"].mean() * 100, 1),
        },
        "good_combos": good_combos,
        "weak_combos": weak_combos,
        "combo_stats": cs.to_dict(orient="records"),
        "interaction_results": interaction_records,
        "time_split_sanity": tss,
        "deployer_reputation_buckets": dep_rep_buckets_json,
        "deployer_prior_avg_peak_buckets": dep_avg_peak_buckets_json,
        "kc_curve": {},
        "filters": {
            "min_kol_count": 3,
            "max_dev_sell_usd_for_bonus": 1.0,
            "block_delta_min": 5,
            "block_delta_max": 2000,
            "mcap_sweet_spots": ["<5000", "15000-30000"],
            "mcap_dead_zone": "5000-15000",
            "k1_notional_bonus_threshold": 100,
        },
        "position_sizing": {
            "kc3_bnb": 0.02,
            "kc4_bnb": 0.03,
            "kc5_bnb": 0.05,
            "kc6_plus_bnb": 0.07,
        },
        "tp_sl": {
            "kc3": {"tp": [{"x": 2.0, "sell_pct": 50}, {"x": 4.0, "sell_pct": 50}], "sl_x": 0.60},
            "kc4": {"tp": [{"x": 2.0, "sell_pct": 30}, {"x": 5.0, "sell_pct": 30}, {"x": 10.0, "sell_pct": 40}], "sl_x": 0.60},
            "kc5_plus": {"tp": [{"x": 2.0, "sell_pct": 25}, {"x": 5.0, "sell_pct": 25}, {"x": 10.0, "sell_pct": 25}, {"x": 20.0, "sell_pct": 25}], "sl_x": 0.70},
        },
    }

    # Fill kc curve
    for kc in sorted(df["kol_count"].unique()):
        g = df[df["kol_count"] == kc]
        n_k = len(g)
        k2 = int(g["win_2x"].sum())
        wlo, whi = wilson_interval(k2, n_k)
        config["kc_curve"][str(kc)] = {
            "N": int(n_k),
            "avg_mult": round(float(g["peak_mult"].mean()), 3),
            "median_mult": round(float(g["peak_mult"].median()), 3),
            "win_2x_pct": round(float(g["win_2x"].mean() * 100), 1),
            "win_2x_wilson_lo_pct": round(wlo * 100, 1),
            "win_2x_wilson_hi_pct": round(whi * 100, 1),
            "low_n": n_k < max(20, mn * 3),
        }

    out_path = PROJECT_ROOT / "ml" / "strategy_config_90d.json"
    with open(out_path, "w") as f:
        json.dump(config, f, indent=2, default=str)
    print(f"\nWrote {out_path}")
    print(json.dumps(config, indent=2, default=str)[:2000])

    if args.write_summary:
        sp = PROJECT_ROOT / "ml" / "research_summary.md"
        lines = [
            "# 90d research summary (auto)",
            "",
            f"- Rows: {len(df)}",
            f"- Good combos: {len(good_combos)}, weak: {len(weak_combos)}",
            f"- Overall 2x rate: {config['overall']['win_2x_pct']}%",
            f"- Time split: documented in `strategy_config_90d.json` under `time_split_sanity`.",
            f"- OOF backtest: run `train_kol_scorer.py` then `backtest_kol_strategy.py` (default uses `kol_oof_predictions.csv`).",
            "",
        ]
        sp.write_text("\n".join(lines), encoding="utf-8")
        print(f"Wrote {sp}")


if __name__ == "__main__":
    main()
