#!/usr/bin/env python3
"""
Phase 3: Backtest engine — simulate 3 strategies on the 90d kol2plus dataset
with realistic TP/SL ladder execution.

Strategies:
  1. Baseline: Enter every trade at 0.03 BNB
  2. Rules-only: Combo gate + kc gate + filters
  3. Rules + ML: Hard filters then ML score for position sizing

By default, Rules+ML uses **out-of-fold** scores from ml/kol_oof_predictions.csv (honest vs CV metrics).
Use --in-sample-ml only to reproduce the old biased full-dataset booster predict.

Usage:
    python ml/backtest_kol_strategy.py [--input ...] [--capture-pct 0.6] [--in-sample-ml]
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ML_DIR = PROJECT_ROOT / "ml"
OOF_CSV = ML_DIR / "kol_oof_predictions.csv"

sys.path.insert(0, str(ML_DIR))
from train_kol_scorer import build_features  # noqa: E402

WEAK_COMBOS = {"A→B", "E→C", "G→A"}

TP_LADDER = {
    "kc3": [
        {"x": 2.0, "sell_pct": 0.50},
        {"x": 4.0, "sell_pct": 0.50},
    ],
    "kc4": [
        {"x": 2.0, "sell_pct": 0.30},
        {"x": 5.0, "sell_pct": 0.30},
        {"x": 10.0, "sell_pct": 0.40},
    ],
    "kc5_plus": [
        {"x": 2.0, "sell_pct": 0.25},
        {"x": 5.0, "sell_pct": 0.25},
        {"x": 10.0, "sell_pct": 0.25},
        {"x": 20.0, "sell_pct": 0.25},
    ],
}


@dataclass
class TradeResult:
    token: str
    combo: str
    kol_count: int
    peak_mult: float
    entry_bnb: float
    pnl_bnb: float
    strategy: str
    ml_score: float = 0.0


def get_tp_ladder(kc: int) -> list[dict]:
    if kc <= 3:
        return TP_LADDER["kc3"]
    if kc == 4:
        return TP_LADDER["kc4"]
    return TP_LADDER["kc5_plus"]


def get_sl(kc: int) -> float:
    if kc <= 3:
        return 0.60
    if kc == 4:
        return 0.60
    return 0.70


def _effective_peak_mult(peak_mult: float, exit_slippage_mult: float) -> float:
    """Scale gains above 1x downward when exit_slippage_mult < 1 (worse sells / latency)."""
    if exit_slippage_mult >= 1.0:
        return peak_mult
    return 1.0 + max(0.0, (peak_mult - 1.0) * exit_slippage_mult)


def simulate_trade(
    peak_mult: float,
    entry_bnb: float,
    kc: int,
    capture_pct: float = 0.60,
    *,
    round_trip_fee_frac: float = 0.0,
    exit_slippage_mult: float = 1.0,
) -> float:
    """Simulate a single trade with TP/SL ladder.

    round_trip_fee_frac: fraction of entry_bnb charged once (open+close stylized), e.g. 0.004 = 0.4%.
    exit_slippage_mult: multiply (peak-1) for exit math; <1 simulates worse fills.
    """
    pk = _effective_peak_mult(peak_mult, exit_slippage_mult)
    sl = get_sl(kc)
    ladder = get_tp_ladder(kc)

    if pk <= sl:
        pnl = entry_bnb * (sl - 1.0)
    else:
        remaining = 1.0
        realized_value = 0.0

        for tp in ladder:
            if pk >= tp["x"]:
                sell_frac = tp["sell_pct"] * remaining
                realized_value += sell_frac * tp["x"] * entry_bnb
                remaining -= tp["sell_pct"] * remaining
            else:
                break

        if remaining > 0:
            exit_mult = max(sl, min(pk, capture_pct * pk))
            realized_value += remaining * exit_mult * entry_bnb

        pnl = realized_value - entry_bnb

    pnl -= entry_bnb * round_trip_fee_frac
    return pnl


def position_size_rules(kc: int) -> float:
    if kc <= 2:
        return 0.0
    if kc == 3:
        return 0.02
    if kc == 4:
        return 0.03
    if kc == 5:
        return 0.05
    return 0.07


def position_size_ml(kc: int, ml_score: float) -> float:
    base = position_size_rules(kc)
    if base == 0:
        if ml_score >= 0.7:
            return 0.015
        return 0.0

    if ml_score >= 0.7:
        return min(base * 1.5, 0.10)
    if ml_score >= 0.5:
        return base
    if ml_score >= 0.3:
        return base * 0.7
    return 0.0


def run_backtest(
    df: pd.DataFrame,
    strategy: str,
    ml_scores: np.ndarray | None = None,
    *,
    capture_pct: float = 0.60,
    round_trip_fee_frac: float = 0.0,
    exit_slippage_mult: float = 1.0,
    max_entry_bnb: float | None = None,
) -> list[TradeResult]:
    results = []
    for pos in range(len(df)):
        row = df.iloc[pos]
        combo = str(row.get("combo_k1k2", "") or "")
        kc = int(pd.to_numeric(row.get("kol_count_final", 2), errors="coerce") or 2)
        peak = float(pd.to_numeric(row.get("peak_mult_vs_slot2_entry", 1.0), errors="coerce") or 1.0)
        token = str(row.get("token_address", "") or "")
        ml_score = float(ml_scores[pos]) if ml_scores is not None else 0.0

        if strategy == "baseline":
            entry_bnb = 0.03
        elif strategy == "rules":
            if combo in WEAK_COMBOS:
                continue
            entry_bnb = position_size_rules(kc)
            if entry_bnb <= 0:
                continue
        elif strategy == "rules_ml":
            if combo in WEAK_COMBOS:
                continue
            entry_bnb = position_size_ml(kc, ml_score)
            if entry_bnb <= 0:
                continue
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        if max_entry_bnb is not None and entry_bnb > max_entry_bnb:
            entry_bnb = max_entry_bnb

        pnl = simulate_trade(
            peak,
            entry_bnb,
            kc,
            capture_pct=capture_pct,
            round_trip_fee_frac=round_trip_fee_frac,
            exit_slippage_mult=exit_slippage_mult,
        )
        results.append(
            TradeResult(
                token=token,
                combo=combo,
                kol_count=kc,
                peak_mult=peak,
                entry_bnb=entry_bnb,
                pnl_bnb=pnl,
                strategy=strategy,
                ml_score=ml_score,
            )
        )
    return results


def compute_metrics(results: list[TradeResult]) -> dict:
    if not results:
        return {}
    n = len(results)
    pnls = [r.pnl_bnb for r in results]
    total_pnl = sum(pnls)
    total_invested = sum(r.entry_bnb for r in results)
    wins = sum(1 for p in pnls if p > 0)
    big_wins = sum(1 for r in results if r.peak_mult >= 3.0)
    avg_pnl = np.mean(pnls)
    max_dd = min(pnls) if pnls else 0

    cum = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum - running_max
    max_drawdown = drawdowns.min() if len(drawdowns) > 0 else 0

    return {
        "trades": n,
        "total_pnl_bnb": round(total_pnl, 4),
        "total_invested_bnb": round(total_invested, 4),
        "roi_pct": round(total_pnl / total_invested * 100, 1),
        "win_rate": round(wins / n * 100, 1),
        "big_win_pct": round(big_wins / n * 100, 1),
        "avg_pnl": round(avg_pnl, 6),
        "max_drawdown": round(max_drawdown, 4),
    }


def summarize(results: list[TradeResult], label: str) -> dict:
    if not results:
        print(f"\n{label}: 0 trades")
        return {}
    m = compute_metrics(results)
    n = m["trades"]
    pnls = [r.pnl_bnb for r in results]
    max_dd = min(pnls) if pnls else 0
    wins = sum(1 for p in pnls if p > 0)
    big_wins = sum(1 for r in results if r.peak_mult >= 3.0)
    total_pnl = sum(pnls)
    total_invested = sum(r.entry_bnb for r in results)
    avg_pnl = float(m["avg_pnl"])
    cum = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cum)
    max_drawdown = float((cum - running_max).min()) if len(pnls) else 0.0

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Trades:      {n}")
    print(f"  Total PnL:   {total_pnl:+.4f} BNB  (${total_pnl * 600:+.2f})")
    print(f"  Total invest: {total_invested:.4f} BNB")
    print(f"  ROI:         {total_pnl / total_invested * 100:+.1f}%")
    print(f"  Avg PnL:     {avg_pnl:+.6f} BNB/trade")
    print(f"  Win rate:    {wins/n*100:.1f}%  ({wins}/{n})")
    print(f"  Big wins 3x+: {big_wins}  ({big_wins/n*100:.1f}%)")
    print(f"  Max drawdown: {max_drawdown:.4f} BNB")
    print(f"  Worst trade:  {max_dd:+.6f} BNB")

    kc_groups: dict[int, list[TradeResult]] = {}
    for r in results:
        kc_groups.setdefault(r.kol_count, []).append(r)
    print("\n  By kol_count:")
    for kc in sorted(kc_groups.keys()):
        gr = kc_groups[kc]
        kpnl = sum(r.pnl_bnb for r in gr)
        print(
            f"    kc={kc}: N={len(gr):3d}, PnL={kpnl:+.4f} BNB, "
            f"avg={np.mean([r.pnl_bnb for r in gr]):+.6f}"
        )

    return {"strategy": label, **m}


def load_ml_scores(
    df: pd.DataFrame,
    *,
    in_sample_ml: bool,
    model_path: Path,
) -> tuple[np.ndarray, str]:
    """Return (scores aligned to df row order, source description)."""
    n = len(df)

    if not in_sample_ml and OOF_CSV.is_file():
        oof = pd.read_csv(OOF_CSV)
        if len(oof) == n and "row_index" in oof.columns and "oof_prob" in oof.columns:
            oof_s = oof.sort_values("row_index").reset_index(drop=True)
            ri = pd.to_numeric(oof_s["row_index"], errors="coerce").fillna(-1).astype(int).values
            if len(ri) == n and np.array_equal(ri, np.arange(n, dtype=int)):
                probs = oof_s["oof_prob"].astype(float).values
                if len(probs) == n:
                    return probs, "oof_csv_row_index"

            if "token_address" in oof.columns and "create_block" in oof.columns and "token_address" in df.columns:
                key_df = (
                    df["token_address"].astype(str).values
                    + "\0"
                    + pd.to_numeric(df["create_block"], errors="coerce").fillna(-1).astype(int).astype(str)
                )
                key_oof = (
                    oof["token_address"].astype(str).values
                    + "\0"
                    + pd.to_numeric(oof["create_block"], errors="coerce").fillna(-1).astype(int).astype(str)
                )
                m = {k: float(p) for k, p in zip(key_oof, oof["oof_prob"].astype(float).values)}
                probs = np.array([m.get(k, np.nan) for k in key_df])
                if bool(np.isfinite(probs).all()) and len(probs) == n:
                    return probs, "oof_csv_token_block"

        warnings.warn(
            f"{OOF_CSV} exists but row count ({len(oof)}) != df ({n}) or alignment failed; "
            "use --in-sample-ml or re-run train_kol_scorer.py on this CSV.",
            stacklevel=2,
        )

    if in_sample_ml:
        if not model_path.is_file():
            print(f"ERROR: --in-sample-ml but missing model {model_path}", file=sys.stderr)
            sys.exit(1)
        model = lgb.Booster(model_file=str(model_path))
        X, _y, _fnames = build_features(df)
        try:
            nf_model = model.num_feature()
        except Exception:
            nf_model = -1
        if nf_model >= 0:
            if X.shape[1] > nf_model:
                print(
                    f"WARNING: slicing features {X.shape[1]}→{nf_model} for legacy model; "
                    "re-train train_kol_scorer.py for full 54-feature deployer inputs.",
                    file=sys.stderr,
                )
                X = X[:, :nf_model]
            elif X.shape[1] < nf_model:
                print(
                    f"ERROR: model expects {nf_model} features but build_features produced {X.shape[1]}. "
                    "Re-run: python3 ml/train_kol_scorer.py --input <same CSV as backtest>",
                    file=sys.stderr,
                )
                sys.exit(1)
        scores = model.predict(X)
        print(f"ML scores (in-sample booster): mean={scores.mean():.3f}, std={scores.std():.3f}")
        return scores, "in_sample_booster"

    print(
        "ERROR: No valid OOF file for honest Rules+ML. Expected:\n"
        f"  {OOF_CSV}\n"
        "with same row count as --input (or merge keys). Train with:\n"
        "  python3 ml/train_kol_scorer.py --input <same CSV>\n"
        "Or pass --in-sample-ml to use full-dataset booster predict (biased).",
        file=sys.stderr,
    )
    sys.exit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_90d_full_kol2plus.csv"))
    p.add_argument("--in-sample-ml", action="store_true", help="Use booster predict on full df (biased); default is OOF CSV")
    p.add_argument("--capture-pct", type=float, default=0.60, help="Fraction of peak taken on residual after TP ladder")
    p.add_argument("--seed", type=int, default=None, help="Optional RNG seed (reserved for future stochastic steps)")
    p.add_argument(
        "--sensitivity",
        action="store_true",
        help="Also run capture_pct in {0.5,0.6,0.7} and write ml/backtest_sensitivity.json",
    )
    p.add_argument(
        "--round-trip-fee-frac",
        type=float,
        default=0.0,
        metavar="F",
        help="Stylized fees: subtract F * entry_bnb from each trade PnL (e.g. 0.004 = 0.4%% of notional)",
    )
    p.add_argument(
        "--exit-slippage-mult",
        type=float,
        default=1.0,
        metavar="M",
        help="Scale (peak_mult-1) for exits; <1.0 worsens fills (default 1.0 = no slippage)",
    )
    p.add_argument(
        "--max-entry-bnb",
        type=float,
        default=None,
        metavar="X",
        help="Cap position size per trade (capacity / liquidity stress)",
    )
    args = p.parse_args()

    if args.seed is not None:
        np.random.seed(args.seed)

    df = pd.read_csv(args.input)
    df = df.reset_index(drop=True)
    print(f"Loaded {len(df)} rows (index reset for positional ML alignment)")

    model_path = ML_DIR / "kol_scorer_model.txt"
    ml_scores, ml_source = load_ml_scores(df, in_sample_ml=args.in_sample_ml, model_path=model_path)
    print(f"ML source: {ml_source}")
    if ml_source.startswith("oof"):
        print(
            "\nNote — honest Rules+ML: each row's score is out-of-fold (K-fold CV) unless the CSV "
            "column is_holdout=true (then it was scored by a model trained only on earlier rows). "
            "This is NOT the legacy in-sample booster curve (~+15.5 BNB); that path used labels to "
            "size positions and overstated live-like PnL. Use --in-sample-ml only to reproduce it.\n"
        )

    cap = args.capture_pct
    bt_kw = dict(
        capture_pct=cap,
        round_trip_fee_frac=args.round_trip_fee_frac,
        exit_slippage_mult=args.exit_slippage_mult,
        max_entry_bnb=args.max_entry_bnb,
    )
    if args.round_trip_fee_frac > 0 or args.exit_slippage_mult < 1.0 or args.max_entry_bnb:
        print(
            f"Friction: round_trip_fee_frac={args.round_trip_fee_frac}, "
            f"exit_slippage_mult={args.exit_slippage_mult}, max_entry_bnb={args.max_entry_bnb}"
        )

    results_baseline = run_backtest(df, "baseline", **bt_kw)
    results_rules = run_backtest(df, "rules", **bt_kw)
    results_ml = run_backtest(df, "rules_ml", ml_scores, **bt_kw)

    s1 = summarize(results_baseline, "1. BASELINE (all trades, 0.03 BNB)")
    s2 = summarize(results_rules, "2. RULES-ONLY (combo+kc gate)")
    s3 = summarize(results_ml, "3. RULES + ML (score-adjusted sizing)")

    print(f"\n{'='*60}")
    print("  STRATEGY COMPARISON")
    print(f"{'='*60}")
    print(f"{'Metric':<20s}  {'Baseline':>12s}  {'Rules':>12s}  {'Rules+ML':>12s}")
    print("-" * 60)
    for key in ["trades", "total_pnl_bnb", "roi_pct", "win_rate", "big_win_pct", "avg_pnl", "max_drawdown"]:
        v1 = s1.get(key, "N/A")
        v2 = s2.get(key, "N/A")
        v3 = s3.get(key, "N/A")
        print(f"  {key:<18s}  {str(v1):>12s}  {str(v2):>12s}  {str(v3):>12s}")

    out = {
        "strategies": [s1, s2, s3],
        "config": {
            "weak_combos": list(WEAK_COMBOS),
            "tp_ladder": TP_LADDER,
            "capture_pct": cap,
            "round_trip_fee_frac": args.round_trip_fee_frac,
            "exit_slippage_mult": args.exit_slippage_mult,
            "max_entry_bnb": args.max_entry_bnb,
            "ml_score_source": ml_source,
            "in_sample_ml": args.in_sample_ml,
        },
    }
    out_path = ML_DIR / "backtest_results_90d.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved → {out_path}")

    if args.sensitivity:
        sens = {"capture_pct_sweep": [], "ml_score_source": ml_source}
        for c in (0.5, 0.6, 0.7):
            sk = {**bt_kw, "capture_pct": c}
            rb = run_backtest(df, "baseline", **sk)
            rr = run_backtest(df, "rules", **sk)
            rm = run_backtest(df, "rules_ml", ml_scores, **sk)
            sens["capture_pct_sweep"].append(
                {
                    "capture_pct": c,
                    "baseline": compute_metrics(rb),
                    "rules": compute_metrics(rr),
                    "rules_ml": compute_metrics(rm),
                }
            )
        sp = ML_DIR / "backtest_sensitivity.json"
        with open(sp, "w") as f:
            json.dump(sens, f, indent=2, default=str)
        print(f"Saved sensitivity → {sp}")


if __name__ == "__main__":
    main()
