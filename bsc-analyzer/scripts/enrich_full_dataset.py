#!/usr/bin/env python3
"""
Lumina BSC — Full KOL Dataset Enrichment Pipeline

Takes the enriched JSONL output from kol_monitor (backtest or live) and produces
a comprehensive ~70-column parquet/CSV dataset.

Pipeline:
  1. Load JSONL → list of dicts
  2. Flatten kol_buys[] → kol1_* through kol5_* columns
  3. Derive time features, combos, deltas
  4. Join deployer CSV on creator address
  5. Compute rolling 7d KOL win rates (self-referential)
  6. Async RPC batch: holder counts at each KOL buy block + entry block
  7. Async RPC batch: balanceOf for held_at_entry checks
  8. Async RPC batch: dev buy scanning (Transfer TO creator)
  9. Fetch Binance 4h klines, map to tokens by timestamp
  10. Output parquet + csv

Usage:
    python scripts/enrich_full_dataset.py \
        --input backtest_results/kol_backtest_90d.jsonl \
        --deployers data/deployers.csv \
        --kol-file top.json \
        --rpc-url $BSC_RPC \
        --output backtest_results/kol_dataset_90d.parquet
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from deployer_reputation import apply_point_in_time_to_records  # noqa: E402
from kol_dataset_schema import FINAL_COLUMNS  # noqa: E402


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

TOTAL_SUPPLY = 1_000_000_000.0  # Four.meme standard 1B supply
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_TOPIC_SUFFIX = "0" * 40
BSC_BLOCK_TIME_SEC = 3.0
BLOCKS_PER_DAY = int(86400 / BSC_BLOCK_TIME_SEC)

# ── 1. Load JSONL ────────────────────────────────────────────────────────────

def load_jsonl(path: str) -> List[dict]:
    records = []
    with open(path) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  WARN: skipping line {line_no}: {e}", file=sys.stderr)
    print(f"  Loaded {len(records)} records from {path}")
    return records


# ── 2. Flatten kol_buys ──────────────────────────────────────────────────────

def flatten_kol_buys(records: List[dict]) -> List[dict]:
    """Flatten kol_buys[] array into kol1_* through kol5_* columns."""
    for rec in records:
        buys = rec.get("kol_buys", [])
        for i in range(5):
            prefix = f"kol{i+1}_"
            if i < len(buys):
                b = buys[i]
                rec[prefix + "name"] = b.get("kol_name", "")
                rec[prefix + "address"] = b.get("kol", "")
                rec[prefix + "buy_block"] = b.get("buy_block", 0)
                rec[prefix + "buy_usd"] = b.get("buy_notional_usd_approx", 0)
                rec[prefix + "entry_mcap_usd"] = b.get("entry_mcap_usd", 0)
                rec[prefix + "sell_usd"] = None  # placeholder for GMGN
                rec[prefix + "pnl_usd"] = None
                rec[prefix + "holder_count"] = None  # filled by RPC
                rec[prefix + "held_at_entry"] = None  # filled by RPC
            else:
                for col in ["name", "address", "buy_block", "buy_usd", "entry_mcap_usd",
                            "sell_usd", "pnl_usd", "holder_count", "held_at_entry"]:
                    rec[prefix + col] = None
    return records


# ── 3. Derive time features, combos, deltas ──────────────────────────────────

def derive_features(records: List[dict]) -> List[dict]:
    """Derive computed columns from existing data."""
    for rec in records:
        ct = rec.get("create_time", "")
        if ct and ct != "unknown":
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                rec["create_hour_utc"] = dt.hour
                rec["create_dow"] = dt.weekday()  # 0=Monday
            except ValueError:
                rec["create_hour_utc"] = None
                rec["create_dow"] = None
        else:
            rec["create_hour_utc"] = None
            rec["create_dow"] = None

        # Rename fields for consistency
        rec["token_address"] = rec.get("token", rec.get("token_address", ""))
        rec["kol_count_final"] = rec.get("kol_count", 0)
        rec["age_blocks_at_entry"] = rec.get("age_blocks", 0)
        rec["dev_sell_usd"] = rec.get("dev_sell_usd_approx", 0)

        # dev_sell_pct_supply: dev_sell_tokens / 1e9
        dev_sell_tokens = rec.get("dev_sell_tokens", 0.0)
        rec["dev_sell_pct_supply"] = dev_sell_tokens / TOTAL_SUPPLY if dev_sell_tokens else 0.0

        # Combo strings
        k1 = rec.get("kol1_name", "") or ""
        k2 = rec.get("kol2_name", "") or ""
        k3 = rec.get("kol3_name", "") or ""
        rec["combo_k1k2"] = f"{k1}→{k2}" if k1 and k2 else ""
        rec["combo_k1k2k3"] = f"{k1}→{k2}→{k3}" if k1 and k2 and k3 else ""

        # Combined notional k1+k2
        k1_usd = rec.get("kol1_buy_usd") or 0
        k2_usd = rec.get("kol2_buy_usd") or 0
        rec["combined_notional_k1k2_usd"] = k1_usd + k2_usd

        # Delta blocks between KOLs
        k1b = rec.get("kol1_buy_block") or 0
        k2b = rec.get("kol2_buy_block") or 0
        k3b = rec.get("kol3_buy_block") or 0
        rec["kol1_kol2_delta_blocks"] = (k2b - k1b) if k1b and k2b else None
        rec["kol2_kol3_delta_blocks"] = (k3b - k2b) if k2b and k3b else None

        # kol_count_at_entry: KOLs bought at or before first buy block + 1
        entry_block = rec.get("kol1_buy_block") or 0
        if entry_block:
            count = 0
            for i in range(5):
                bb = rec.get(f"kol{i+1}_buy_block")
                if bb and bb <= entry_block + 1:
                    count += 1
            rec["kol_count_at_entry"] = count
        else:
            rec["kol_count_at_entry"] = 0

        # peak_mult_vs_slot2_entry: from slot_delay data
        sd = rec.get("slot_delay", {})
        slot2_peak = None
        if isinstance(sd, dict) and "slot_2" in sd:
            s2 = sd["slot_2"]
            if isinstance(s2, dict) and "plus_1_block" in s2:
                slot2_peak = s2["plus_1_block"].get("peak_mcap_usd")
        entry_mcap = rec.get("entry_mcap_usd", 0)
        if slot2_peak and entry_mcap and entry_mcap > 1.0:
            rec["peak_mult_vs_slot2_entry"] = slot2_peak / entry_mcap
        else:
            rec["peak_mult_vs_slot2_entry"] = None

    return records


# ── 4. Deployer join ─────────────────────────────────────────────────────────

def _safe_int(s, default=0) -> int:
    try:
        return int(float(s or 0))
    except (TypeError, ValueError):
        return default


def _safe_float(s, default=0.0) -> float:
    try:
        return float(s or 0)
    except (TypeError, ValueError):
        return default


def load_deployer_csv(path: str) -> Dict[str, dict]:
    """Load deployer reputation CSV into {address: stats} map (Pancake or Four.meme format)."""
    if not path or not os.path.exists(path):
        print(f"  WARN: deployers CSV not found at {path}, skipping deployer enrichment")
        return {}
    deployers = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = row.get("deployer", "").lower()
            if not addr:
                continue
            dep = {
                "deployer_prior_launches": _safe_int(row.get("total_tokens")),
                "deployer_prior_grads": _safe_int(row.get("successful")),
                "deployer_grad_rate": _safe_float(row.get("success_rate")),
            }
            if row.get("score", "") != "":
                dep["deployer_csv_score"] = _safe_float(row.get("score"))
            if row.get("rug_rate", "") != "":
                dep["deployer_csv_rug_rate"] = _safe_float(row.get("rug_rate"))
            if row.get("rugged", "") != "":
                dep["deployer_csv_rugged"] = _safe_int(row.get("rugged"))
            if row.get("honeypots", "") != "":
                dep["deployer_csv_honeypots"] = _safe_int(row.get("honeypots"))
            deployers[addr] = dep
    print(f"  Loaded {len(deployers)} deployer records")
    return deployers


def join_deployers(records: List[dict], deployers: Dict[str, dict]) -> List[dict]:
    """Join deployer stats on creator address (external CSV; may be overwritten by Four.meme PIT)."""
    matched = 0
    for rec in records:
        creator = (rec.get("creator") or "").lower()
        dep = deployers.get(creator)
        if dep:
            rec.update(dep)
            matched += 1
        else:
            rec["deployer_prior_launches"] = 0
            rec["deployer_prior_grads"] = 0
            rec["deployer_grad_rate"] = 0.0
            rec["deployer_csv_score"] = None
            rec["deployer_csv_rug_rate"] = None
            rec["deployer_csv_rugged"] = None
            rec["deployer_csv_honeypots"] = None
    print(f"  Deployer join: {matched}/{len(records)} matched")
    return records


# ── 5. Rolling 7d KOL win rates ──────────────────────────────────────────────

def compute_kol_win_rates(records: List[dict], win_threshold: float = 2.0) -> List[dict]:
    """
    For each token, compute 7d rolling win rate for kol1 and kol2.
    Win = peak_x >= win_threshold. Window = 7 days by create_block.
    """
    sorted_recs = sorted(records, key=lambda r: r.get("create_block", 0))

    # Build per-KOL history: list of (create_block, won)
    kol_history: Dict[str, List[Tuple[int, bool]]] = defaultdict(list)
    window_blocks = 7 * BLOCKS_PER_DAY

    for rec in sorted_recs:
        peak_x = rec.get("peak_x", 0)
        won = peak_x >= win_threshold
        cb = rec.get("create_block", 0)
        for i in range(1, 3):
            kname = rec.get(f"kol{i}_name", "")
            if kname:
                kol_history[kname].append((cb, won))

    # Now compute rolling win rate for each record
    kol_idx: Dict[str, int] = defaultdict(int)  # bisect pointer per KOL
    for rec in sorted_recs:
        cb = rec.get("create_block", 0)
        for i in range(1, 3):
            kname = rec.get(f"kol{i}_name", "")
            if not kname:
                rec[f"kol{i}_7d_win_rate"] = None
                continue
            hist = kol_history[kname]
            # Find entries in [cb - window_blocks, cb) for this KOL
            start_block = cb - window_blocks
            wins, total = 0, 0
            for block, won in hist:
                if block >= cb:
                    break
                if block >= start_block:
                    total += 1
                    if won:
                        wins += 1
            rec[f"kol{i}_7d_win_rate"] = wins / total if total > 0 else None
    return records


# ── 6. Async RPC: holder counts, balanceOf, dev buys ─────────────────────────

async def rpc_call(session: aiohttp.ClientSession, rpc_url: str,
                   method: str, params: list, request_id: int = 1) -> Optional[Any]:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            return data.get("result")
    except Exception:
        return None


async def rpc_batch_call(session: aiohttp.ClientSession, rpc_url: str,
                         calls: List[dict]) -> List[Optional[Any]]:
    """Send a batch JSON-RPC request."""
    if not calls:
        return []
    payload = [{"jsonrpc": "2.0", "method": c["method"], "params": c["params"], "id": i}
               for i, c in enumerate(calls)]
    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            results = await resp.json()
            if isinstance(results, list):
                id_map = {r.get("id"): r.get("result") for r in results}
                return [id_map.get(i) for i in range(len(calls))]
    except Exception:
        pass
    return [None] * len(calls)


def hex_block(block: int) -> str:
    return hex(block)


async def count_holders_proxy_rpc(session: aiohttp.ClientSession, rpc_url: str,
                                   token_addr: str, from_block: int, to_block: int) -> int:
    """Count unique transfer recipients (holder proxy) via eth_getLogs."""
    if to_block < from_block:
        return 0
    recipients = set()
    cur = from_block
    chunk = 2000
    while cur <= to_block:
        end = min(cur + chunk - 1, to_block)
        params = [{
            "fromBlock": hex_block(cur),
            "toBlock": hex_block(end),
            "address": token_addr,
            "topics": [TRANSFER_TOPIC]
        }]
        result = await rpc_call(session, rpc_url, "eth_getLogs", params)
        if result:
            for log in result:
                topics = log.get("topics", [])
                if len(topics) >= 3:
                    to_addr = topics[2][-40:]
                    recipients.add(to_addr)
        cur = end + 1
    return len(recipients)


async def balance_of_at_block(session: aiohttp.ClientSession, rpc_url: str,
                               token_addr: str, wallet: str, block: int) -> bool:
    """Check if wallet holds tokens at block via balanceOf call."""
    wallet_padded = "0x" + wallet.lower().replace("0x", "").zfill(64)
    call_data = "0x70a08231" + wallet_padded[2:]
    params = [{"to": token_addr, "data": call_data}, hex_block(block)]
    result = await rpc_call(session, rpc_url, "eth_call", params)
    if result and result != "0x" and len(result) > 2:
        try:
            val = int(result, 16)
            return val > 0
        except ValueError:
            pass
    return False


async def sum_dev_transfers_in(session: aiohttp.ClientSession, rpc_url: str,
                                token_addr: str, creator: str,
                                from_block: int, to_block: int) -> float:
    """Sum Transfer logs TO creator (dev buys) in token units."""
    if to_block < from_block or not creator or creator == "0x" + "0" * 40:
        return 0.0
    creator_topic = "0x" + creator.lower().replace("0x", "").zfill(64)
    total_tokens = 0.0
    cur = from_block
    chunk = 2000
    while cur <= to_block:
        end = min(cur + chunk - 1, to_block)
        params = [{
            "fromBlock": hex_block(cur),
            "toBlock": hex_block(end),
            "address": token_addr,
            "topics": [TRANSFER_TOPIC, None, creator_topic]
        }]
        result = await rpc_call(session, rpc_url, "eth_getLogs", params)
        if result:
            for log in result:
                data = log.get("data", "0x")
                if len(data) >= 66:
                    try:
                        amount = int(data, 16) / 1e18
                        total_tokens += amount
                    except ValueError:
                        pass
        cur = end + 1
    return total_tokens


async def enrich_rpc_batch(records: List[dict], rpc_url: str,
                           concurrency: int = 20) -> List[dict]:
    """Async RPC enrichment: holder counts, held_at_entry, dev buys."""
    if not rpc_url:
        print("  WARN: no RPC URL provided, skipping RPC enrichment")
        return records

    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
    async with aiohttp.ClientSession(connector=connector) as session:

        async def process_token(idx: int, rec: dict):
            async with sem:
                token_addr = rec.get("token_address", "").lower()
                creator = (rec.get("creator") or "").lower()
                create_block = rec.get("create_block", 0)
                entry_mcap = rec.get("entry_mcap_usd", 0)

                # Holder counts at each KOL buy block
                for i in range(1, 6):
                    bb = rec.get(f"kol{i}_buy_block")
                    if bb and create_block and token_addr:
                        try:
                            hc = await count_holders_proxy_rpc(
                                session, rpc_url, token_addr, create_block, bb)
                            rec[f"kol{i}_holder_count"] = hc
                        except Exception:
                            pass

                # holder_growth metrics
                hc1 = rec.get("kol1_holder_count")
                hc2 = rec.get("kol2_holder_count")
                hce = rec.get("holder_count_at_entry")
                if hc1 and hc2 and hc1 > 0:
                    rec["holder_growth_kol1_to_kol2"] = (hc2 - hc1) / hc1
                else:
                    rec["holder_growth_kol1_to_kol2"] = None
                if hc2 and hce and hc2 > 0:
                    rec["holder_growth_kol2_to_entry"] = (hce - hc2) / hc2
                else:
                    rec["holder_growth_kol2_to_entry"] = None

                # held_at_entry for kol1 and kol2
                entry_block = rec.get("kol1_buy_block") or 0
                if entry_block and token_addr:
                    for i in range(1, 3):
                        kol_addr = rec.get(f"kol{i}_address")
                        if kol_addr:
                            try:
                                held = await balance_of_at_block(
                                    session, rpc_url, token_addr, kol_addr, entry_block)
                                rec[f"kol{i}_held_at_entry"] = held
                            except Exception:
                                pass

                # Dev buy scan (Transfer TO creator)
                if creator and creator != "0x" + "0" * 40 and create_block and token_addr:
                    last_kol_block = create_block
                    for i in range(1, 6):
                        bb = rec.get(f"kol{i}_buy_block")
                        if bb:
                            last_kol_block = max(last_kol_block, bb)
                    try:
                        dev_buy_tokens = await sum_dev_transfers_in(
                            session, rpc_url, token_addr, creator, create_block, last_kol_block)
                        if dev_buy_tokens > 0 and entry_mcap > 1.0:
                            rec["dev_buy_usd"] = dev_buy_tokens * (entry_mcap / TOTAL_SUPPLY)
                        else:
                            rec["dev_buy_usd"] = 0.0
                        rec["dev_net_usd"] = (rec.get("dev_buy_usd") or 0) - (rec.get("dev_sell_usd") or 0)
                    except Exception:
                        rec["dev_buy_usd"] = 0.0
                        rec["dev_net_usd"] = 0.0

                if (idx + 1) % 25 == 0:
                    print(f"\r  RPC enrichment: {idx+1}/{len(records)}", end="", flush=True)

        tasks = [process_token(i, rec) for i, rec in enumerate(records)]
        await asyncio.gather(*tasks)
        print(f"\r  RPC enrichment: {len(records)}/{len(records)} done")

    return records


# ── 9. Binance 4h klines ─────────────────────────────────────────────────────

async def fetch_binance_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                                session: aiohttp.ClientSession) -> List[dict]:
    """Fetch klines from Binance API."""
    url = "https://api.binance.com/api/v3/klines"
    all_klines = []
    cur = start_ms
    while cur < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur,
            "endTime": end_ms,
            "limit": 1000
        }
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if not data or not isinstance(data, list):
                    break
                for k in data:
                    all_klines.append({
                        "open_time": k[0],
                        "close_time": k[6],
                        "open": float(k[1]),
                        "close": float(k[4]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                    })
                if len(data) < 1000:
                    break
                cur = data[-1][6] + 1
        except Exception as e:
            print(f"  WARN: Binance klines error for {symbol}: {e}", file=sys.stderr)
            break
        await asyncio.sleep(0.2)
    return all_klines


def map_klines_to_4h_change(klines: List[dict]) -> List[Tuple[int, float]]:
    """Convert klines to (open_time_sec, pct_change) sorted list."""
    changes = []
    for k in klines:
        if k["open"] > 0:
            pct = (k["close"] - k["open"]) / k["open"] * 100
            changes.append((k["open_time"] // 1000, pct))
    changes.sort(key=lambda x: x[0])
    return changes


def find_nearest_4h_change(changes: List[Tuple[int, float]], timestamp_sec: int) -> Optional[float]:
    """Find the 4h candle change for the nearest candle to given timestamp."""
    if not changes:
        return None
    times = [c[0] for c in changes]
    idx = bisect_right(times, timestamp_sec) - 1
    if idx < 0:
        idx = 0
    if idx >= len(changes):
        idx = len(changes) - 1
    return changes[idx][1]


async def enrich_binance_klines(records: List[dict]) -> List[dict]:
    """Fetch BTC and BNB 4h klines and map to each token by create_time."""
    timestamps = []
    for rec in records:
        ct = rec.get("create_time", "")
        if ct and ct != "unknown":
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                timestamps.append(int(dt.timestamp()))
            except ValueError:
                pass

    if not timestamps:
        print("  WARN: no valid create_time values, skipping Binance klines")
        return records

    min_ts = min(timestamps) - 4 * 3600
    max_ts = max(timestamps) + 4 * 3600

    print(f"  Fetching Binance 4h klines ({(max_ts - min_ts) / 86400:.0f} days)...")

    async with aiohttp.ClientSession() as session:
        btc_klines, bnb_klines = await asyncio.gather(
            fetch_binance_klines("BTCUSDT", "4h", min_ts * 1000, max_ts * 1000, session),
            fetch_binance_klines("BNBUSDT", "4h", min_ts * 1000, max_ts * 1000, session),
        )

    print(f"  BTC klines: {len(btc_klines)}, BNB klines: {len(bnb_klines)}")

    btc_changes = map_klines_to_4h_change(btc_klines)
    bnb_changes = map_klines_to_4h_change(bnb_klines)

    for rec in records:
        ct = rec.get("create_time", "")
        if ct and ct != "unknown":
            try:
                dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                ts = int(dt.timestamp())
                rec["btc_4h_change_pct"] = find_nearest_4h_change(btc_changes, ts)
                rec["bnb_4h_change_pct"] = find_nearest_4h_change(bnb_changes, ts)
            except ValueError:
                rec["btc_4h_change_pct"] = None
                rec["bnb_4h_change_pct"] = None
        else:
            rec["btc_4h_change_pct"] = None
            rec["bnb_4h_change_pct"] = None

    return records


# ── 10. Output ────────────────────────────────────────────────────────────────
# FINAL_COLUMNS imported from kol_dataset_schema.py


def build_dataframe(records: List[dict]) -> pd.DataFrame:
    """Build final DataFrame with correct column order and types."""
    df = pd.DataFrame(records)

    # Ensure all final columns exist
    for col in FINAL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Select and reorder
    df = df[[c for c in FINAL_COLUMNS if c in df.columns]]

    # Type conversions
    int_cols = ["row", "create_block", "create_hour_utc", "create_dow",
                "deployer_prior_launches", "deployer_prior_grads",
                "deployer_csv_rugged", "deployer_csv_honeypots",
                "kol_count_final", "kol_count_at_entry",
                "kol1_buy_block", "kol2_buy_block", "kol3_buy_block",
                "kol4_buy_block", "kol5_buy_block",
                "kol1_holder_count", "kol2_holder_count", "kol3_holder_count",
                "kol4_holder_count", "kol5_holder_count",
                "kol1_kol2_delta_blocks", "kol2_kol3_delta_blocks",
                "holder_count_at_entry", "age_blocks_at_entry"]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    float_cols = [
        "deployer_grad_rate",
        "deployer_prior_avg_peak_mult", "deployer_prior_win_rate", "deployer_rug_proxy_rate",
        "deployer_reputation_score",
        "deployer_csv_score", "deployer_csv_rug_rate",
        "dev_buy_usd", "dev_sell_usd", "dev_sell_pct_supply",
                  "dev_net_usd", "combined_notional_k1k2_usd",
                  "kol1_7d_win_rate", "kol2_7d_win_rate",
                  "kol1_buy_usd", "kol2_buy_usd", "kol3_buy_usd", "kol4_buy_usd", "kol5_buy_usd",
                  "kol1_sell_usd", "kol2_sell_usd", "kol3_sell_usd", "kol4_sell_usd", "kol5_sell_usd",
                  "kol1_pnl_usd", "kol2_pnl_usd", "kol3_pnl_usd", "kol4_pnl_usd", "kol5_pnl_usd",
                  "holder_growth_kol1_to_kol2", "holder_growth_kol2_to_entry",
                  "entry_mcap_usd", "bonding_curve_pct",
                  "peak_mcap_usd", "low_mcap_usd",
                  "peak_mult_vs_slot2_entry",
                  "bnb_price_usd", "btc_4h_change_pct", "bnb_4h_change_pct"]
    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    bool_cols = ["graduated", "kol1_held_at_entry", "kol2_held_at_entry"]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].astype("boolean")

    return df


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    _load_repo_dotenv()
    parser = argparse.ArgumentParser(description="Enrich KOL backtest JSONL into full dataset")
    parser.add_argument("--input", required=True, help="Input JSONL path from kol_monitor backtest")
    parser.add_argument("--deployers", default="", help="Path to deployers.csv")
    parser.add_argument("--kol-file", default="top.json", help="Path to KOL file (for reference)")
    parser.add_argument(
        "--rpc-url",
        default=os.environ.get("QUICK_NODE_BSC_RPC") or os.environ.get("BSC_RPC", ""),
        help="BSC RPC (defaults: QUICK_NODE_BSC_RPC or BSC_RPC from .env)",
    )
    parser.add_argument("--output", required=True, help="Output path (.parquet or .csv)")
    parser.add_argument("--skip-rpc", action="store_true", help="Skip RPC enrichment (faster)")
    parser.add_argument("--skip-binance", action="store_true", help="Skip Binance klines fetch")
    parser.add_argument("--rpc-concurrency", type=int, default=20, help="RPC concurrent requests")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  KOL DATASET ENRICHMENT PIPELINE")
    print(f"{'='*60}")
    print(f"  Input:  {args.input}")
    print(f"  Output: {args.output}")
    print(f"{'='*60}\n")

    t0 = time.time()

    # Step 1: Load
    print("[1/7] Loading JSONL...")
    records = load_jsonl(args.input)
    if not records:
        print("ERROR: no records loaded", file=sys.stderr)
        sys.exit(1)

    # Step 2: Flatten kol_buys
    print("[2/7] Flattening kol_buys...")
    records = flatten_kol_buys(records)

    # Step 3: Derive features
    print("[3/7] Deriving features...")
    records = derive_features(records)

    # Step 4: Deployer join + Four.meme point-in-time reputation (this dataset)
    print("[4/7] Joining deployer data...")
    deployers = load_deployer_csv(args.deployers)
    records = join_deployers(records, deployers)
    print("[4b/7] Four.meme point-in-time deployer reputation...")
    apply_point_in_time_to_records(records)

    # Step 5: KOL win rates
    print("[5/7] Computing 7d KOL win rates...")
    records = compute_kol_win_rates(records)

    # Step 6: RPC enrichment
    if not args.skip_rpc and args.rpc_url:
        print("[6/7] RPC enrichment (holder counts, balanceOf, dev buys)...")
        records = await enrich_rpc_batch(records, args.rpc_url, args.rpc_concurrency)
    else:
        print("[6/7] Skipping RPC enrichment")
        for rec in records:
            rec.setdefault("dev_buy_usd", 0.0)
            rec.setdefault("dev_net_usd", 0.0)
            rec.setdefault("holder_growth_kol1_to_kol2", None)
            rec.setdefault("holder_growth_kol2_to_entry", None)

    # Step 7: Binance klines
    if not args.skip_binance:
        print("[7/7] Fetching Binance 4h klines...")
        records = await enrich_binance_klines(records)
    else:
        print("[7/7] Skipping Binance klines")

    # Build DataFrame
    print("\nBuilding final DataFrame...")
    df = build_dataframe(records)

    # Output
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if output_path.endswith(".parquet"):
        df.to_parquet(output_path, index=False, engine="pyarrow")
        csv_path = output_path.replace(".parquet", ".csv")
        df.to_csv(csv_path, index=False)
        print(f"  Wrote {output_path} ({len(df)} rows, {len(df.columns)} cols)")
        print(f"  Wrote {csv_path}")
    elif output_path.endswith(".csv"):
        df.to_csv(output_path, index=False)
        print(f"  Wrote {output_path} ({len(df)} rows, {len(df.columns)} cols)")
    else:
        df.to_parquet(output_path + ".parquet", index=False, engine="pyarrow")
        df.to_csv(output_path + ".csv", index=False)
        print(f"  Wrote {output_path}.parquet and {output_path}.csv")

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  ENRICHMENT COMPLETE in {elapsed:.1f}s")
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")
    print(f"{'='*60}\n")

    # Print column summary
    print("Columns:")
    for col in df.columns:
        non_null = df[col].notna().sum()
        print(f"  {col:40s} {non_null:>6d}/{len(df)} non-null")


if __name__ == "__main__":
    asyncio.run(main())
