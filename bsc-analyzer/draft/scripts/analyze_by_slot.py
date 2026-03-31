#!/usr/bin/env python3
"""
Win rate and peak multiples by **KOL slot** (1st / 2nd / 3rd distinct KOL) and
**delay profile** (+1 block, +2 blocks, +2s→blocks), using enriched JSONL from
`build_kol_dataset.py` or raw `kol_monitor` JSONL (RPC-only peak_x).

Usage:
  python3 scripts/analyze_by_slot.py kol_dataset_enriched.jsonl [top.json]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any, Optional

SLOT_KEYS = ("slot_1", "slot_2", "slot_3")
DELAY_KEYS = ("plus_1_block", "plus_2_block", "plus_2s")


def load_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('{"summary'):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "token" in rec:
                rows.append(rec)
    return rows


def load_kol_names(top_json_path: str) -> dict[str, str]:
    import os

    names: dict[str, str] = {}
    if not os.path.exists(top_json_path):
        return names
    with open(top_json_path, encoding="utf-8") as f:
        data = json.load(f)
    for entry in data:
        addr = (entry.get("address") or "").lower()
        name = entry.get("name", "")
        groups = entry.get("groups", [])
        label = name if name else (groups[0] if groups else addr[:10])
        names[addr] = label
    return names


def kol_label(addr: str, kol_names: dict[str, str]) -> str:
    if not addr:
        return "?"
    a = addr.lower()
    label = kol_names.get(a, "")
    if not label or label in ("GOAT", ""):
        return a[:6] + "…" + a[-4:]
    return label


def peak_x_from_cell(cell: dict[str, Any], prefer_hybrid: bool = True) -> Optional[float]:
    """peak_mcap / our_entry_mcap for this sniper slot."""
    our = float(cell.get("our_entry_mcap_usd") or 0)
    if our < 1:
        return None
    if prefer_hybrid and cell.get("peak_mcap_hybrid") is not None:
        return float(cell["peak_mcap_hybrid"]) / our
    return float(cell.get("peak_mcap_usd") or 0) / our


def analyze(rows: list[dict[str, Any]], kol_names: dict[str, str]) -> None:
    # (slot, delay) -> aggregates
    by_delay: dict[tuple[str, str], list[float]] = defaultdict(list)
    # (slot, delay, kol_addr) -> list peak_x
    by_kol: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    for t in rows:
        sd = t.get("slot_delay") or {}
        kol_buys = t.get("kol_buys") or []
        idx_map = {"slot_1": 0, "slot_2": 1, "slot_3": 2}
        for sk, kidx in idx_map.items():
            slot = sd.get(sk)
            if not isinstance(slot, dict):
                continue
            kol_addr = ""
            if isinstance(kol_buys, list) and kidx < len(kol_buys):
                kol_addr = (kol_buys[kidx].get("kol") or "").lower()
            for dk in DELAY_KEYS:
                cell = slot.get(dk)
                if not isinstance(cell, dict):
                    continue
                if int(cell.get("our_entry_block") or 0) <= 0:
                    continue
                px = peak_x_from_cell(cell)
                if px is None:
                    continue
                by_delay[(sk, dk)].append(px)
                if kol_addr:
                    by_kol[(sk, dk, kol_addr)].append(px)

    print(f"\n{'='*80}")
    print(f"  SLOT × DELAY — peak multiple after our entry ({len(rows)} tokens)")
    print(f"{'='*80}\n")
    header = f"  {'Slot':<10} {'Delay':<16} {'N':>6} {'Win≥2x':>8} {'Win≥5x':>8} {'MedPx':>8} {'AvgPx':>8}"
    print(header)
    print(f"  {'-'*len(header)}")
    keys_sorted = []
    for sk in SLOT_KEYS:
        for dk in DELAY_KEYS:
            keys_sorted.append((sk, dk))
    for sk, dk in keys_sorted:
        xs = by_delay.get((sk, dk), [])
        n = len(xs)
        if not n:
            continue
        xs_sorted = sorted(xs)
        med = xs_sorted[n // 2]
        avg = sum(xs) / n
        w2 = sum(1 for x in xs if x >= 2.0) / n
        w5 = sum(1 for x in xs if x >= 5.0) / n
        print(f"  {sk:<10} {dk:<16} {n:>6} {w2:>7.0%} {w5:>7.0%} {med:>7.2f}x {avg:>7.2f}x")

    print(f"\n{'─'*80}")
    print("  BY KOL (per slot — which wallet filled that ordered slot)")
    print(f"{'─'*80}\n")

    kol_keys = sorted(by_kol.keys(), key=lambda k: (-len(by_kol[k]), k[0], k[1]))
    printed = 0
    for sk, dk, addr in kol_keys:
        xs = by_kol[(sk, dk, addr)]
        if len(xs) < 3:
            continue
        n = len(xs)
        w2 = sum(1 for x in xs if x >= 2.0) / n
        w5 = sum(1 for x in xs if x >= 5.0) / n
        avg = sum(xs) / n
        lab = kol_label(addr, kol_names)
        print(f"  {sk} {dk}  {lab:<20} n={n:<4} Win≥2x:{w2:>5.0%} Win≥5x:{w5:>5.0%} AvgPx:{avg:.2f}x  {addr}")
        printed += 1
    if not printed:
        print("  (no KOL with ≥3 samples in any slot×delay — lower min or add data)")

    print(f"\n{'='*80}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/analyze_by_slot.py <dataset.jsonl> [top.json]")
        sys.exit(1)
    path = sys.argv[1]
    top_path = sys.argv[2] if len(sys.argv) > 2 else "top.json"
    rows = load_jsonl(path)
    if not rows:
        print(f"No rows in {path}")
        sys.exit(1)
    names = load_kol_names(top_path)
    analyze(rows, names)


if __name__ == "__main__":
    main()
