"""
Four.meme deployer reputation — shared stats and scoring.

Used by compute_deployer_reputation.py, enrich_full_dataset.py,
build_fourmeme_deployers_csv.py, and live_dataset_collector (via import).

Point-in-time rule: only tokens with create_block < current row's create_block
count toward that row's deployer_* fields.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Rug proxy: dev took some exit and token never ran
RUG_DEV_SELL_MIN_USD = 200.0
RUG_PEAK_MULT_MAX = 1.15
WIN_PEAK_MULT = 2.0


@dataclass
class PriorTokenSnapshot:
    """One prior token outcome for a deployer (used in rolling history)."""

    create_block: int
    graduated: bool
    peak_mult: Optional[float]
    dev_sell_usd: float


@dataclass
class DeployerPointInTimeStats:
    prior_launches: int = 0
    prior_grads: int = 0
    prior_win_count: int = 0
    prior_rug_proxy_count: int = 0
    prior_avg_peak_mult: float = 0.0
    prior_win_rate: float = 0.0
    rug_proxy_rate: float = 0.0
    grad_rate: float = 0.0
    reputation_score: float = 0.0


def is_rug_proxy(peak_mult: Optional[float], dev_sell_usd: float, graduated: bool) -> bool:
    if graduated:
        return False
    if peak_mult is None or peak_mult > RUG_PEAK_MULT_MAX:
        return False
    return dev_sell_usd >= RUG_DEV_SELL_MIN_USD


def is_win(peak_mult: Optional[float]) -> bool:
    return peak_mult is not None and peak_mult >= WIN_PEAK_MULT


def fourmeme_reputation_score(
    prior_launches: int,
    prior_grads: int,
    prior_win_count: int,
    prior_rug_proxy_count: int,
    avg_peak_mult: float,
) -> float:
    """
    Map prior-token statistics to [-100, 100], same spirit as build_deployer_db.compute_score.
    """
    if prior_launches <= 0:
        return 0.0

    grad_rate = prior_grads / prior_launches
    win_rate = prior_win_count / prior_launches
    rug_rate = prior_rug_proxy_count / prior_launches

    score = 0.0
    score += grad_rate * 40.0
    score += win_rate * 35.0
    score += min(avg_peak_mult, 10.0) * 2.0
    score -= rug_rate * 80.0
    if prior_launches >= 5:
        score += 8.0
    elif prior_launches >= 3:
        score += 4.0

    return max(-100.0, min(100.0, score))


def stats_from_priors(priors: List[PriorTokenSnapshot]) -> DeployerPointInTimeStats:
    n = len(priors)
    if n == 0:
        return DeployerPointInTimeStats()

    grads = sum(1 for p in priors if p.graduated)
    wins = sum(1 for p in priors if is_win(p.peak_mult))
    rugs = sum(1 for p in priors if is_rug_proxy(p.peak_mult, p.dev_sell_usd, p.graduated))
    peaks = [p.peak_mult for p in priors if p.peak_mult is not None]
    avg_peak = sum(peaks) / len(peaks) if peaks else 0.0

    grad_rate = grads / n
    win_rate = wins / n
    rug_rate = rugs / n
    rep = fourmeme_reputation_score(n, grads, wins, rugs, avg_peak)

    return DeployerPointInTimeStats(
        prior_launches=n,
        prior_grads=grads,
        prior_win_count=wins,
        prior_rug_proxy_count=rugs,
        prior_avg_peak_mult=round(avg_peak, 6),
        prior_win_rate=round(win_rate, 6),
        rug_proxy_rate=round(rug_rate, 6),
        grad_rate=round(grad_rate, 6),
        reputation_score=round(rep, 4),
    )


def row_to_snapshot(rec: Dict[str, Any]) -> PriorTokenSnapshot:
    cb = int(rec.get("create_block") or 0)
    g = rec.get("graduated")
    if isinstance(g, str):
        graduated = g.lower() in ("true", "1", "yes")
    else:
        graduated = bool(g)

    pm = rec.get("peak_mult_vs_slot2_entry")
    if pm is None:
        pm = rec.get("peak_x")
    try:
        peak_mult = float(pm) if pm is not None and pm != "" else None
    except (TypeError, ValueError):
        peak_mult = None

    try:
        ds = float(rec.get("dev_sell_usd") or 0)
    except (TypeError, ValueError):
        ds = 0.0

    return PriorTokenSnapshot(
        create_block=cb,
        graduated=graduated,
        peak_mult=peak_mult,
        dev_sell_usd=ds,
    )


def apply_point_in_time_to_records(records: List[dict]) -> List[dict]:
    """
    Sort by create_block, compute point-in-time deployer columns for each record.
    Mutates records in place and returns them.
    """
    indexed = list(enumerate(records))
    indexed.sort(key=lambda x: (int(x[1].get("create_block") or 0), x[0]))

    history: Dict[str, List[PriorTokenSnapshot]] = {}

    for _, rec in indexed:
        creator = (rec.get("creator") or "").lower()
        cb = int(rec.get("create_block") or 0)

        if creator:
            priors = [p for p in history.get(creator, []) if p.create_block < cb]
            st = stats_from_priors(priors)
            rec["deployer_prior_launches"] = st.prior_launches
            rec["deployer_prior_grads"] = st.prior_grads
            rec["deployer_grad_rate"] = st.grad_rate
            rec["deployer_prior_avg_peak_mult"] = st.prior_avg_peak_mult
            rec["deployer_prior_win_rate"] = st.prior_win_rate
            rec["deployer_rug_proxy_rate"] = st.rug_proxy_rate
            rec["deployer_reputation_score"] = st.reputation_score
            history.setdefault(creator, []).append(row_to_snapshot(rec))
        else:
            rec["deployer_prior_launches"] = 0
            rec["deployer_prior_grads"] = 0
            rec["deployer_grad_rate"] = 0.0
            rec["deployer_prior_avg_peak_mult"] = 0.0
            rec["deployer_prior_win_rate"] = 0.0
            rec["deployer_rug_proxy_rate"] = 0.0
            rec["deployer_reputation_score"] = 0.0

    return records


def aggregate_deployer_rows(records: List[dict]) -> Dict[str, DeployerPointInTimeStats]:
    """Final per-creator stats using all tokens (for static CSV)."""
    by_creator: Dict[str, List[PriorTokenSnapshot]] = {}
    for rec in records:
        c = (rec.get("creator") or "").lower()
        if not c:
            continue
        by_creator.setdefault(c, []).append(row_to_snapshot(rec))

    out: Dict[str, DeployerPointInTimeStats] = {}
    for c, snaps in by_creator.items():
        snaps.sort(key=lambda s: s.create_block)
        out[c] = stats_from_priors(snaps)
    return out


def cpp_csv_row_from_snapshots(address: str, snaps: List[PriorTokenSnapshot]) -> Dict[str, Any]:
    """
    One row compatible with lumina::DeployerDB::load_csv / build_deployer_db.py header.
    successful = graduated OR peak >= 2x; rugged = rug_proxy heuristic.
    """
    if not snaps:
        return {
            "deployer": address,
            "total_tokens": 0,
            "rugged": 0,
            "honeypots": 0,
            "successful": 0,
            "avg_lifespan_hours": 0.0,
            "success_rate": 0.0,
            "rug_rate": 0.0,
            "score": 0.0,
            "first_seen_block": 0,
            "last_seen_block": 0,
        }
    snaps = sorted(snaps, key=lambda s: s.create_block)
    n = len(snaps)
    successful = sum(1 for p in snaps if p.graduated or is_win(p.peak_mult))
    rugged = sum(1 for p in snaps if is_rug_proxy(p.peak_mult, p.dev_sell_usd, p.graduated))
    honeypots = 0
    valid = max(0, n - honeypots)
    success_rate = successful / valid if valid > 0 else 0.0
    rug_rate = rugged / n if n > 0 else 0.0
    peaks = [p.peak_mult for p in snaps if p.peak_mult is not None]
    avg_peak = sum(peaks) / len(peaks) if peaks else 0.0
    wins = sum(1 for p in snaps if is_win(p.peak_mult))
    grads = sum(1 for p in snaps if p.graduated)
    score = fourmeme_reputation_score(n, grads, wins, rugged, avg_peak)

    return {
        "deployer": address,
        "total_tokens": n,
        "rugged": rugged,
        "honeypots": honeypots,
        "successful": successful,
        "avg_lifespan_hours": 0.0,
        "success_rate": round(success_rate, 6),
        "rug_rate": round(rug_rate, 6),
        "score": round(score, 4),
        "first_seen_block": snaps[0].create_block,
        "last_seen_block": snaps[-1].create_block,
    }


def fix_csv_header_names(fieldnames: List[str]) -> List[str]:
    """Map legacy empty column (between creator and deployer_prior_grads) to deployer_prior_launches."""
    out: List[str] = []
    for c in fieldnames:
        if c == "" or (isinstance(c, str) and c.strip() == ""):
            out.append("deployer_prior_launches")
        else:
            out.append(c)
    return out


def load_csv_records(path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Read dataset CSV with stdlib only; empty cells → None for downstream parsers."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_fn = list(reader.fieldnames or [])
        new_fn = fix_csv_header_names(old_fn)
        records: List[Dict[str, Any]] = []
        for row in reader:
            rec: Dict[str, Any] = {}
            for ok, nk in zip(old_fn, new_fn):
                v = row.get(ok, "")
                rec[nk] = None if v == "" else v
            records.append(rec)
        return records, new_fn
