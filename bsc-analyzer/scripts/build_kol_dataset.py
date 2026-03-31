#!/usr/bin/env python3
"""
Read `lumina_kol_monitor` JSONL, enrich slot_delay with GMGN K-line mcap (required by default),
write canonical SQLite + enriched JSONL.

Loads `bsc-analyzer/.env` first (GMGN_API_KEY, GMGN_API_BASE).

Usage:
  # Put GMGN_API_KEY in bsc-analyzer/.env (see .env.example)
  python3 scripts/build_kol_dataset.py backtest_results/kol.jsonl \\
    --sqlite kol_dataset.sqlite --jsonl kol_dataset_enriched.jsonl

  # Align GMGN window with your RPC scan end (recommended for backtests):
  python3 scripts/build_kol_dataset.py kol.jsonl --sqlite out.sqlite --jsonl out.jsonl \\
    --forward-sec 2592000

  # RPC-only (tests / no key): explicit opt-out
  python3 scripts/build_kol_dataset.py kol.jsonl --sqlite out.sqlite --jsonl out.jsonl --no-gmgn
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

# Allow `python scripts/build_kol_dataset.py` from repo root
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


def _load_repo_dotenv() -> None:
    path = os.path.join(_REPO_ROOT, ".env")
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
    except ImportError:
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as ef:
            for line in ef:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v


import gmgn_client as gmgn


def parse_create_ts(create_time: str) -> Optional[int]:
    if not create_time or create_time == "unknown":
        return None
    s = create_time.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def our_entry_timestamp_sec(
    create_ts: Optional[int],
    create_block: int,
    our_entry_block: int,
    block_time_sec: float,
) -> Optional[int]:
    if create_ts is None or our_entry_block == 0:
        return None
    delta_b = int(our_entry_block) - int(create_block)
    return int(create_ts + delta_b * float(block_time_sec))


def end_sec_for_row(
    our_entry_sec: int,
    forward_sec: int,
    end_ms_override: Optional[int],
) -> int:
    now_sec = int(time.time())
    if end_ms_override is not None:
        return max(our_entry_sec + 1, end_ms_override // 1000)
    cap = our_entry_sec + max(60, forward_sec)
    return min(now_sec, cap)


SLOT_KEYS = ("slot_1", "slot_2", "slot_3")
DELAY_KEYS = ("plus_1_block", "plus_2_block", "plus_2s")


def enrich_slot_delay(
    row: dict[str, Any],
    *,
    chain: str,
    total_supply: float,
    tolerance_pct: float,
    resolution: str,
    forward_sec: int,
    end_ms_override: Optional[int],
    api_key: Optional[str],
    base_url: Optional[str],
    sleep_s: float,
) -> tuple[dict[str, Any], int, int]:
    """Returns (enriched_row, gmgn_ok, gmgn_err)."""
    bt = float(row.get("block_time_sec") or 3.0)
    create_block = int(row.get("create_block") or 0)
    ct = parse_create_ts(row.get("create_time") or "")
    token = (row.get("token") or "").lower()
    sd_in = row.get("slot_delay") or {}
    out_sd: dict[str, Any] = copy.deepcopy(sd_in) if sd_in else {}
    ok = 0
    err = 0

    for sk in SLOT_KEYS:
        slot = out_sd.get(sk)
        if not isinstance(slot, dict):
            continue
        for dk in DELAY_KEYS:
            block = slot.get(dk)
            if not isinstance(block, dict):
                continue
            our_b = int(block.get("our_entry_block") or 0)
            peak_rpc = float(block.get("peak_mcap_usd") or 0)
            low_rpc = float(block.get("low_mcap_usd") or 0)
            if our_b <= 0 or not token:
                block["peak_mcap_gmgn"] = None
                block["low_mcap_gmgn"] = None
                block["gmgn_error"] = "no_entry"
                continue
            if not api_key:
                block["peak_mcap_gmgn"] = None
                block["low_mcap_gmgn"] = None
                block["gmgn_skipped"] = True
                continue

            our_sec = our_entry_timestamp_sec(ct, create_block, our_b, bt)
            if our_sec is None:
                block["peak_mcap_gmgn"] = None
                block["low_mcap_gmgn"] = None
                block["gmgn_error"] = "bad_create_time"
                err += 1
                continue
            end_s = end_sec_for_row(our_sec, forward_sec, end_ms_override)

            try:
                time.sleep(sleep_s)
                pg, lg, _filt = gmgn.gmgn_mcap_range_for_window(
                    chain,
                    token,
                    our_sec,
                    end_s,
                    total_supply,
                    resolution=resolution,
                    api_key=api_key,
                    base_url=base_url,
                )
                merged = gmgn.merge_peak_low(peak_rpc, low_rpc, pg, lg, tolerance_pct=tolerance_pct)
                block["peak_mcap_gmgn"] = pg
                block["low_mcap_gmgn"] = lg
                block["peak_mcap_hybrid"] = merged["peak_mcap_hybrid"]
                block["low_mcap_hybrid"] = merged["low_mcap_hybrid"]
                block["discrepancy"] = merged["discrepancy"]
                if merged.get("discrepancy_peak_pct") is not None:
                    block["discrepancy_peak_pct"] = merged["discrepancy_peak_pct"]
                if merged.get("discrepancy_low_pct") is not None:
                    block["discrepancy_low_pct"] = merged["discrepancy_low_pct"]
                block["gmgn_window"] = {
                    "our_entry_ts": our_sec,
                    "end_ts": end_s,
                    "resolution": resolution,
                }
                ok += 1
            except Exception as e:  # noqa: BLE001 — surface API errors per cell
                block["peak_mcap_gmgn"] = None
                block["low_mcap_gmgn"] = None
                block["gmgn_error"] = str(e)[:500]
                err += 1

    row["slot_delay"] = out_sd
    row["chain_id"] = 56
    row["gmgn_enriched"] = bool(api_key)
    return row, ok, err


def init_sqlite(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            row_num INTEGER,
            token TEXT NOT NULL,
            name TEXT,
            first_buyer TEXT,
            kol_count INTEGER,
            create_block INTEGER,
            create_time TEXT,
            entry_mcap_usd REAL,
            peak_mcap_usd REAL,
            low_mcap_usd REAL,
            peak_x REAL,
            low_x REAL,
            graduated INTEGER,
            block_time_sec REAL,
            gmgn_holder_count INTEGER,
            gmgn_liquidity TEXT,
            json_full TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tokens_addr ON tokens(token);

        CREATE TABLE IF NOT EXISTS slot_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL,
            slot TEXT NOT NULL,
            delay_profile TEXT NOT NULL,
            kol_address TEXT,
            our_entry_block INTEGER,
            our_entry_mcap_usd REAL,
            peak_mcap_rpc REAL,
            low_mcap_rpc REAL,
            peak_mcap_gmgn REAL,
            low_mcap_gmgn REAL,
            peak_mcap_hybrid REAL,
            low_mcap_hybrid REAL,
            peak_x_rpc REAL,
            peak_x_hybrid REAL,
            discrepancy INTEGER,
            UNIQUE(token, slot, delay_profile)
        );
        CREATE INDEX IF NOT EXISTS idx_slot_kol ON slot_metrics(kol_address);
        """
    )


def ensure_tokens_gmgn_columns(conn: sqlite3.Connection) -> None:
    """Add GMGN token-info columns when upgrading an older SQLite file."""
    cur = conn.execute("PRAGMA table_info(tokens)")
    cols = {str(r[1]) for r in cur.fetchall()}
    if "gmgn_holder_count" not in cols:
        conn.execute("ALTER TABLE tokens ADD COLUMN gmgn_holder_count INTEGER")
    if "gmgn_liquidity" not in cols:
        conn.execute("ALTER TABLE tokens ADD COLUMN gmgn_liquidity TEXT")


def insert_row_sqlite(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO tokens (row_num, token, name, first_buyer, kol_count, create_block,
            create_time, entry_mcap_usd, peak_mcap_usd, low_mcap_usd, peak_x, low_x,
            graduated, block_time_sec, gmgn_holder_count, gmgn_liquidity, json_full)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row.get("row"),
            (row.get("token") or "").lower(),
            row.get("name"),
            (row.get("first_buyer") or "").lower(),
            row.get("kol_count"),
            row.get("create_block"),
            row.get("create_time"),
            row.get("entry_mcap_usd"),
            row.get("peak_mcap_usd"),
            row.get("low_mcap_usd"),
            row.get("peak_x"),
            row.get("low_x"),
            1 if row.get("graduated") else 0,
            row.get("block_time_sec"),
            row.get("gmgn_holder_count"),
            row.get("gmgn_liquidity"),
            json.dumps(row, separators=(",", ":"), ensure_ascii=False),
        ),
    )

    tok = (row.get("token") or "").lower()
    kol_buys = row.get("kol_buys") or []
    sd = row.get("slot_delay") or {}

    slot_idx = {"slot_1": 0, "slot_2": 1, "slot_3": 2}
    for sk, si in slot_idx.items():
        slot = sd.get(sk)
        if not isinstance(slot, dict):
            continue
        kol_addr = ""
        if isinstance(kol_buys, list) and si < len(kol_buys):
            kol_addr = (kol_buys[si].get("kol") or "").lower()
        for dk in DELAY_KEYS:
            cell = slot.get(dk)
            if not isinstance(cell, dict):
                continue
            our_e = float(cell.get("our_entry_mcap_usd") or 0)
            pr = float(cell.get("peak_mcap_usd") or 0)
            lr = float(cell.get("low_mcap_usd") or 0)
            pg = cell.get("peak_mcap_gmgn")
            lg = cell.get("low_mcap_gmgn")
            ph = cell.get("peak_mcap_hybrid", pr)
            lh = cell.get("low_mcap_hybrid", lr)
            if pg is None and "peak_mcap_hybrid" not in cell:
                ph, lh = pr, lr
            pg = float(pg) if pg is not None else None
            lg = float(lg) if lg is not None else None
            ph = float(ph) if ph is not None else pr
            lh = float(lh) if lh is not None else lr

            peak_x_rpc = (pr / our_e) if our_e > 1 else None
            peak_x_hyb = (ph / our_e) if our_e > 1 else None
            disc = 1 if cell.get("discrepancy") else 0

            conn.execute(
                """INSERT INTO slot_metrics (token, slot, delay_profile, kol_address, our_entry_block,
                    our_entry_mcap_usd, peak_mcap_rpc, low_mcap_rpc, peak_mcap_gmgn, low_mcap_gmgn,
                    peak_mcap_hybrid, low_mcap_hybrid, peak_x_rpc, peak_x_hybrid, discrepancy)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(token, slot, delay_profile) DO UPDATE SET
                    kol_address=excluded.kol_address,
                    our_entry_block=excluded.our_entry_block,
                    our_entry_mcap_usd=excluded.our_entry_mcap_usd,
                    peak_mcap_rpc=excluded.peak_mcap_rpc,
                    low_mcap_rpc=excluded.low_mcap_rpc,
                    peak_mcap_gmgn=excluded.peak_mcap_gmgn,
                    low_mcap_gmgn=excluded.low_mcap_gmgn,
                    peak_mcap_hybrid=excluded.peak_mcap_hybrid,
                    low_mcap_hybrid=excluded.low_mcap_hybrid,
                    peak_x_rpc=excluded.peak_x_rpc,
                    peak_x_hybrid=excluded.peak_x_hybrid,
                    discrepancy=excluded.discrepancy
                """,
                (
                    tok,
                    sk,
                    dk,
                    kol_addr,
                    int(cell.get("our_entry_block") or 0),
                    our_e,
                    pr,
                    lr,
                    pg,
                    lg,
                    ph,
                    lh,
                    peak_x_rpc,
                    peak_x_hyb,
                    disc,
                ),
            )


def load_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('{"summary'):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "token" in rec:
                rows.append(rec)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Build KOL dataset SQLite + JSONL from kol_monitor output")
    ap.add_argument("input_jsonl", help="Path to kol_monitor JSONL")
    ap.add_argument("--sqlite", required=True, help="Output SQLite path")
    ap.add_argument("--jsonl", required=True, help="Output enriched JSONL path")
    ap.add_argument(
        "--no-gmgn",
        action="store_true",
        help="Skip GMGN (RPC-only rows). Default: require GMGN_API_KEY from .env",
    )
    ap.add_argument(
        "--gmgn",
        action="store_true",
        help=argparse.SUPPRESS,
    )  # backward compat; GMGN is default-on
    ap.add_argument("--chain", default="bsc", help="GMGN chain id (default bsc)")
    ap.add_argument("--supply", type=float, default=1e9, help="Total supply for FDV from K-line USD price")
    ap.add_argument("--resolution", default="1m", help="GMGN K-line resolution")
    ap.add_argument("--tolerance-pct", type=float, default=25.0, help="Discrepancy threshold RPC vs GMGN")
    ap.add_argument(
        "--forward-sec",
        type=int,
        default=30 * 86400,
        help="GMGN window end = min(now, our_entry + forward_sec) unless --end-ms",
    )
    ap.add_argument("--end-ms", type=int, default=None, help="Absolute end time for K-line (ms since epoch)")
    ap.add_argument("--sleep", type=float, default=0.15, help="Delay between GMGN calls (rate limits)")
    ap.add_argument("--gmgn-base", default=None, help="Override GMGN_API_BASE")
    ap.add_argument(
        "--skip-gmgn-token-info",
        action="store_true",
        help="When GMGN is on, only fetch K-line (skip POST /v1/token/info holder_count)",
    )
    args = ap.parse_args()

    _load_repo_dotenv()

    use_gmgn = not args.no_gmgn
    api_key = os.environ.get("GMGN_API_KEY", "").strip() if use_gmgn else ""
    if use_gmgn and not api_key:
        print(
            "GMGN is required by default. Set GMGN_API_KEY in bsc-analyzer/.env "
            "(see .env.example) or pass --no-gmgn for RPC-only output.",
            file=sys.stderr,
        )
        sys.exit(1)

    rows = load_jsonl(args.input_jsonl)
    if not rows:
        print(f"No token rows in {args.input_jsonl}", file=sys.stderr)
        sys.exit(1)

    base_url = args.gmgn_base or os.environ.get("GMGN_API_BASE")

    out_rows: list[dict[str, Any]] = []
    total_ok = total_err = 0

    token_info_ok = token_info_err = 0
    for row in rows:
        if use_gmgn and api_key and not args.skip_gmgn_token_info:
            tok = (row.get("token") or "").lower()
            if tok:
                try:
                    time.sleep(args.sleep)
                    info = gmgn.token_info(args.chain, tok, api_key=api_key, base_url=base_url)
                    row["gmgn_holder_count"] = gmgn.holder_count_from_token_info(info)
                    liq = info.get("liquidity")
                    row["gmgn_liquidity"] = str(liq) if liq is not None else None
                    row.pop("gmgn_token_info_error", None)
                    token_info_ok += 1
                except Exception as e:  # noqa: BLE001
                    row["gmgn_holder_count"] = None
                    row["gmgn_liquidity"] = None
                    row["gmgn_token_info_error"] = str(e)[:500]
                    token_info_err += 1
        if use_gmgn and api_key:
            row, ok, err = enrich_slot_delay(
                row,
                chain=args.chain,
                total_supply=args.supply,
                tolerance_pct=args.tolerance_pct,
                resolution=args.resolution,
                forward_sec=args.forward_sec,
                end_ms_override=args.end_ms,
                api_key=api_key,
                base_url=base_url,
                sleep_s=args.sleep,
            )
            total_ok += ok
            total_err += err
        else:
            row["gmgn_enriched"] = False
            row.setdefault("chain_id", 56)
        out_rows.append(row)

    _ds = os.path.dirname(os.path.abspath(args.sqlite))
    if _ds:
        os.makedirs(_ds, exist_ok=True)
    _dj = os.path.dirname(os.path.abspath(args.jsonl))
    if _dj:
        os.makedirs(_dj, exist_ok=True)

    conn = sqlite3.connect(args.sqlite)
    try:
        init_sqlite(conn)
        ensure_tokens_gmgn_columns(conn)
        conn.execute("DELETE FROM slot_metrics")
        conn.execute("DELETE FROM tokens")
        for row in out_rows:
            insert_row_sqlite(conn, row)
        conn.commit()
    finally:
        conn.close()

    with open(args.jsonl, "w", encoding="utf-8") as out:
        for row in out_rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"Wrote {len(out_rows)} rows -> {args.sqlite}, {args.jsonl}",
        file=sys.stderr,
    )
    if use_gmgn and api_key:
        print(f"GMGN cells OK={total_ok} ERR={total_err}", file=sys.stderr)
        if not args.skip_gmgn_token_info:
            print(f"GMGN token_info OK={token_info_ok} ERR={token_info_err}", file=sys.stderr)


if __name__ == "__main__":
    main()
