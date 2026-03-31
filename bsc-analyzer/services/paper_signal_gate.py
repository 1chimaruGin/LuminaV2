#!/usr/bin/env python3
"""
DEPRECATED: Paper gate is now built into lumina_kol_monitor C++ binary.
Use:  bash scripts/run.sh --paper-csv backtest_results/paper_hits.csv

--- Original docstring ---
Paper-trading gate: read lumina_kol_monitor JSONL from stdin, forward every line to stdout,
and append a row when rule + ML thresholds are met (no on-chain execution).

Typical pipeline:
  ./build/lumina_kol_monitor --format json --shadow --no-ipc \\
    | python3 services/paper_signal_gate.py --paper-csv backtest_results/paper_hits.csv \\
    | python3 services/live_dataset_collector.py ...
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _f(obj: Dict[str, Any], key: str, default: float = 0.0) -> float:
    v = obj.get(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(obj: Dict[str, Any], key: str, default: int = 0) -> int:
    v = obj.get(key, default)
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _b(obj: Dict[str, Any], key: str) -> Optional[bool]:
    v = obj.get(key)
    if v is True or v is False:
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
    return None


def passes_gate(o: Dict[str, Any], args: argparse.Namespace) -> bool:
    if o.get("event") != "kol_signal":
        return False
    if args.shadow_only and _b(o, "shadow") is not True:
        return False
    mode = _i(o, "mode", 0)
    if mode < args.min_mode:
        return False
    if args.max_mode is not None and mode > args.max_mode:
        return False
    if _f(o, "ml_score", -1.0) < args.min_ml_score:
        return False
    if _i(o, "kol_count", 0) < args.min_kol_count:
        return False
    if args.require_create_block_known:
        if _b(o, "create_block_known") is False:
            return False
        if _b(o, "create_block_known") is None and _i(o, "create_block", 0) <= 0:
            return False
    if args.min_create_block > 0 and _i(o, "create_block", 0) < args.min_create_block:
        return False
    return True


PAPER_CSV_FIELDS = [
    "paper_ts_utc",
    "token",
    "mode",
    "mode_label",
    "ml_score",
    "kol_count",
    "create_block",
    "create_block_known",
    "shadow",
    "age_blocks",
    "entry_mcap_usd",
    "current_mcap_usd",
    "signal_block",
    "signal_tx",
    "position_bnb",
    "sl_x",
]


def main() -> None:
    p = argparse.ArgumentParser(description="Paper gate: threshold kol_signal JSONL, log hits to CSV")
    p.add_argument("--paper-csv", required=True, help="Append one row per matched signal")
    p.add_argument("--min-mode", type=int, default=2, help="Minimum mode (1=PROBE, 2=CONFIRMED, 3=STRONG)")
    p.add_argument("--max-mode", type=int, default=None, help="Optional maximum mode")
    p.add_argument("--min-ml-score", type=float, default=0.5, help="Minimum ml_score")
    p.add_argument("--min-kol-count", type=int, default=2, help="Minimum kol_count")
    p.add_argument(
        "--require-create-block-known",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require JSON create_block_known true (or create_block>0 if key missing)",
    )
    p.add_argument("--min-create-block", type=int, default=0, help="Optional minimum create_block")
    p.add_argument("--shadow-only", action="store_true", help="Only count signals with shadow=true")
    args = p.parse_args()

    need_header = (not os.path.exists(args.paper_csv)) or os.path.getsize(args.paper_csv) == 0

    hits = 0
    with open(args.paper_csv, "a", newline="", encoding="utf-8") as csvf:
        writer = csv.DictWriter(csvf, fieldnames=PAPER_CSV_FIELDS, extrasaction="ignore")
        if need_header:
            writer.writeheader()

        for line in sys.stdin:
            if not line.strip():
                continue
            raw = line.rstrip("\n")
            try:
                o = json.loads(raw)
            except json.JSONDecodeError:
                sys.stdout.write(line)
                sys.stdout.flush()
                continue

            if passes_gate(o, args):
                now = datetime.now(timezone.utc).isoformat()
                row = {
                    "paper_ts_utc": now,
                    "token": o.get("token", ""),
                    "mode": _i(o, "mode", 0),
                    "mode_label": o.get("mode_label", ""),
                    "ml_score": _f(o, "ml_score", 0.0),
                    "kol_count": _i(o, "kol_count", 0),
                    "create_block": _i(o, "create_block", 0),
                    "create_block_known": json.dumps(o.get("create_block_known")),
                    "shadow": json.dumps(o.get("shadow")),
                    "age_blocks": json.dumps(o.get("age_blocks")),
                    "entry_mcap_usd": _f(o, "entry_mcap_usd", 0.0),
                    "current_mcap_usd": _f(o, "current_mcap_usd", 0.0),
                    "signal_block": o.get("block", ""),
                    "signal_tx": o.get("tx", ""),
                    "position_bnb": _f(o, "position_bnb", 0.0),
                    "sl_x": _f(o, "sl_x", 0.0),
                }
                writer.writerow(row)
                csvf.flush()
                hits += 1
                print(f"[paper_gate] hit #{hits} {row['token'][:10]}... mode={row['mode']} ml={row['ml_score']:.3f}", file=sys.stderr)

            sys.stdout.write(line)
            sys.stdout.flush()


if __name__ == "__main__":
    main()
