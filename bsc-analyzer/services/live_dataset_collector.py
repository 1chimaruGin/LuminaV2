#!/usr/bin/env python3
"""
DEPRECATED: This pipeline is replaced by native C++ output in lumina_kol_monitor.
Use:  bash scripts/run.sh [--fresh-output]
The C++ binary now writes CSV, JSONL, and paper CSV directly.

--- Original docstring ---
Lumina BSC — Live KOL Dataset Collector

Subscribes to `lumina_kol_monitor` live JSON lines and writes the **same column
order** as `enrich_full_dataset.py` (see `scripts/kol_dataset_schema.py`), plus
optional live-only columns (ML score, signal block/tx, etc.).

Architecture:
  ./build/lumina_kol_monitor --format json | python services/live_dataset_collector.py ...

Enrichment:
  - Parses `kol_buys[]` from the monitor (buy_block, notional, names) when present
  - Deployer PIT + static CSV, Binance 4h macro, rolling KOL 7d win rates

Label/outcome definitions for training merges: see `ml/DATASET_LABEL_SPEC.md`.

Output:
  - `--output` JSONL (full row dict per line)
  - `--csv` same rows as CSV (header on first create; append-safe)
  - Periodic / final Parquet uses the same column set as CSV

Usage:
    ./build/lumina_kol_monitor --format json \\
      | python3 services/live_dataset_collector.py \\
          --deployers-csv data/deployers_fourmeme.csv \\
          --output backtest_results/kol_dataset_live.jsonl \\
          --csv backtest_results/kol_dataset_live.csv \\
          --first-signal-min-kol-count 2 \\
          --tokens-newer-than-session-start

  --first-signal-min-kol-count 2  → one CSV/JSONL row per token (first time kol_count reaches 2+),
                                   not a new row on every extra KOL buy.
  --tokens-newer-than-session-start → drop tokens whose Four.meme create_block is below chain tip
                                   at collector startup (only tokens created after you start live capture).
  --require-positive-create-block → skip garbage rows with create_block=0.
  --first-signal-min-kol-count > 0 → also implies positive create_block (cannot dedupe on K without it).
  --fresh-output → truncate JSONL/CSV once (clears old runs that ignored flags or wrong CSV schema).
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

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
_SCRIPTS = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
except ImportError:
    pass

import aiohttp

from deployer_reputation import PriorTokenSnapshot, row_to_snapshot, stats_from_priors  # noqa: E402
from kol_dataset_schema import live_csv_columns  # noqa: E402

TOTAL_SUPPLY = 1_000_000_000.0
BSC_BLOCK_TIME_SEC = 3.0
BLOCKS_PER_DAY = int(86400 / BSC_BLOCK_TIME_SEC)


def _coerce_int(v, default=None):
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _coerce_float(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _fmt_csv_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


class LiveCsvAppender:
    """Append rows with a fixed header (matches kol_dataset_schema)."""

    def __init__(self, path: str, columns: List[str]):
        self.path = path
        self.columns = columns
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        exists_nonempty = os.path.exists(path) and os.path.getsize(path) > 0
        if exists_nonempty:
            with open(path, newline="", encoding="utf-8") as rf:
                line1 = rf.readline()
            if line1.strip():
                existing = next(csv.reader([line1]))
                if len(existing) != len(columns):
                    raise SystemExit(
                        f"[collector] FATAL: {path}: CSV header has {len(existing)} columns, "
                        f"this run expects {len(columns)}. Delete the file or pass --fresh-output."
                    )
        need_header = not exists_nonempty
        self._file = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=columns, extrasaction="ignore")
        if need_header:
            self._writer.writeheader()
            self._file.flush()

    def write_row(self, rec: Dict[str, Any]) -> None:
        self._writer.writerow({c: _fmt_csv_cell(rec.get(c)) for c in self.columns})

    def close(self) -> None:
        self._file.close()


# ── Deployer DB ───────────────────────────────────────────────────────────────

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


class DeployerDB:
    def __init__(self, csv_path: str = ""):
        self.deployers: Dict[str, dict] = {}
        if csv_path and os.path.exists(csv_path):
            self._load(csv_path)

    def _load(self, path: str):
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
                self.deployers[addr] = dep
        print(f"[deployer] Loaded {len(self.deployers)} deployers", file=sys.stderr)

    def lookup(self, creator: str) -> dict:
        return self.deployers.get(creator.lower(), {
            "deployer_prior_launches": 0,
            "deployer_prior_grads": 0,
            "deployer_grad_rate": 0.0,
            "deployer_csv_score": None,
            "deployer_csv_rug_rate": None,
            "deployer_csv_rugged": None,
            "deployer_csv_honeypots": None,
        })


class RollingDeployerTracker:
    """Point-in-time deployer stats from live-seen tokens (same semantics as backtest)."""

    def __init__(self):
        self.history: Dict[str, List[PriorTokenSnapshot]] = defaultdict(list)

    def priors_before(self, creator: str, block: int) -> List[PriorTokenSnapshot]:
        c = creator.lower()
        return [p for p in self.history.get(c, []) if p.create_block < int(block or 0)]

    def record(self, creator: str, snap: PriorTokenSnapshot) -> None:
        if not creator:
            return
        self.history[creator.lower()].append(snap)
        h = self.history[creator.lower()]
        h.sort(key=lambda s: s.create_block)

    def to_json_serializable(self) -> dict:
        out = {}
        for k, snaps in self.history.items():
            out[k] = [
                {
                    "create_block": s.create_block,
                    "graduated": s.graduated,
                    "peak_mult": s.peak_mult,
                    "dev_sell_usd": s.dev_sell_usd,
                }
                for s in snaps
            ]
        return out

    def load_from_dict(self, data: dict) -> None:
        self.history.clear()
        for addr, lst in data.items():
            for d in lst:
                self.history[addr.lower()].append(
                    PriorTokenSnapshot(
                        create_block=int(d.get("create_block", 0)),
                        graduated=bool(d.get("graduated")),
                        peak_mult=d.get("peak_mult"),
                        dev_sell_usd=float(d.get("dev_sell_usd", 0)),
                    )
                )
        for h in self.history.values():
            h.sort(key=lambda s: s.create_block)

    def load_from_csv_bootstrap(self, path: str) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            import pandas as pd
        except ImportError:
            print("[deployer] pandas required for --bootstrap-deployers", file=sys.stderr)
            return
        df = pd.read_csv(path)
        cols = list(df.columns)
        for i, c in enumerate(cols):
            if c == "" or str(c).strip() == "":
                cols[i] = "deployer_prior_launches"
        df.columns = cols
        records = df.replace({pd.NA: None}).to_dict(orient="records")
        records.sort(key=lambda r: int(r.get("create_block") or 0))
        for rec in records:
            c = (rec.get("creator") or "").lower()
            if c:
                self.record(c, row_to_snapshot(rec))
        print(f"[deployer] Bootstrapped rolling history from {path} ({len(records)} rows)",
              file=sys.stderr)

    def save_state(self, path: str) -> None:
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w") as f:
                json.dump(self.to_json_serializable(), f)
        except OSError as e:
            print(f"[deployer] save_state failed: {e}", file=sys.stderr)

    def load_state(self, path: str) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as f:
                self.load_from_dict(json.load(f))
            n = sum(len(v) for v in self.history.values())
            print(f"[deployer] Loaded rolling state {path} ({n} snapshots)", file=sys.stderr)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[deployer] load_state failed: {e}", file=sys.stderr)


# ── Binance Klines Cache ─────────────────────────────────────────────────────

class BinanceKlinesCache:
    """Spot 4h klines for btc_4h_change_pct / bnb_4h_change_pct. Override base URL if geo-blocked."""

    def __init__(self):
        self.btc_changes: List[Tuple[int, float]] = []
        self.bnb_changes: List[Tuple[int, float]] = []
        self.last_refresh = 0
        self.refresh_interval = 4 * 3600  # 4 hours
        self._base = (os.environ.get("BINANCE_SPOT_API_BASE") or "https://api.binance.com").rstrip("/")

    async def refresh_if_needed(self):
        now = time.time()
        if now - self.last_refresh < self.refresh_interval:
            return
        print("[klines] Refreshing Binance 4h klines...", file=sys.stderr)
        headers = {"User-Agent": "lumina-live-dataset-collector/1.0"}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                btc_task = self._fetch("BTCUSDT", "4h", session)
                bnb_task = self._fetch("BNBUSDT", "4h", session)
                btc_klines, bnb_klines = await asyncio.gather(btc_task, bnb_task)

                self.btc_changes = self._to_changes(btc_klines)
                self.bnb_changes = self._to_changes(bnb_klines)
                self.last_refresh = now
                print(f"[klines] BTC: {len(self.btc_changes)} candles, BNB: {len(self.bnb_changes)} candles",
                      file=sys.stderr)
                if not self.btc_changes and not self.bnb_changes:
                    print(
                        "[klines] Hint: Binance may be blocked (HTTP 451) or returned an error. "
                        "Set BINANCE_SPOT_API_BASE to a reachable mirror or check network.",
                        file=sys.stderr,
                    )
        except Exception as e:
            print(f"[klines] Refresh error: {e}", file=sys.stderr)

    async def _fetch(self, symbol: str, interval: str, session: aiohttp.ClientSession) -> List[dict]:
        """Single request: latest `limit` closed 4h candles (no start/end window bugs)."""
        url = f"{self._base}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": 60}
        klines: List[dict] = []
        try:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    print(f"[klines] {symbol}: non-JSON body (HTTP {resp.status}): {text[:200]!r}", file=sys.stderr)
                    return klines
                if resp.status != 200:
                    print(f"[klines] {symbol}: HTTP {resp.status} {data!r}", file=sys.stderr)
                    return klines
                if isinstance(data, dict):
                    print(
                        f"[klines] {symbol}: Binance error {data.get('code')} — {data.get('msg', data)}",
                        file=sys.stderr,
                    )
                    return klines
                if not isinstance(data, list) or not data:
                    print(f"[klines] {symbol}: empty or unexpected payload type={type(data).__name__}", file=sys.stderr)
                    return klines
                for k in data:
                    if len(k) >= 5:
                        klines.append(
                            {"open_time": k[0], "open": float(k[1]), "close": float(k[4])}
                        )
        except Exception as e:
            print(f"[klines] {symbol}: request failed: {e}", file=sys.stderr)
        return klines

    @staticmethod
    def _to_changes(klines: List[dict]) -> List[Tuple[int, float]]:
        changes = []
        for k in klines:
            if k["open"] > 0:
                pct = (k["close"] - k["open"]) / k["open"] * 100
                changes.append((k["open_time"] // 1000, pct))
        changes.sort()
        return changes

    def get_4h_change(self, timestamp_sec: int) -> Tuple[Optional[float], Optional[float]]:
        btc = self._find_nearest(self.btc_changes, timestamp_sec)
        bnb = self._find_nearest(self.bnb_changes, timestamp_sec)
        return btc, bnb

    @staticmethod
    def _find_nearest(changes: List[Tuple[int, float]], ts: int) -> Optional[float]:
        if not changes:
            return None
        times = [c[0] for c in changes]
        idx = bisect_right(times, ts) - 1
        idx = max(0, min(idx, len(changes) - 1))
        return changes[idx][1]


# ── KOL Win Rate Tracker ─────────────────────────────────────────────────────

class KolWinRateTracker:
    """Track rolling 7d win rate per KOL from accumulated live data."""

    def __init__(self, win_threshold: float = 2.0):
        self.win_threshold = win_threshold
        self.window_blocks = 7 * BLOCKS_PER_DAY
        # Per KOL: list of (create_block, won_bool)
        self.history: Dict[str, List[Tuple[int, bool]]] = defaultdict(list)

    def record_outcome(self, kol_name: str, create_block: int, peak_x: float):
        won = peak_x >= self.win_threshold
        self.history[kol_name].append((create_block, won))

    def get_7d_win_rate(self, kol_name: str, current_block: int) -> Optional[float]:
        if not kol_name or kol_name not in self.history:
            return None
        start_block = current_block - self.window_blocks
        wins, total = 0, 0
        for block, won in self.history[kol_name]:
            if block >= current_block:
                break
            if block >= start_block:
                total += 1
                if won:
                    wins += 1
        return wins / total if total > 0 else None

    def load_from_jsonl(self, path: str):
        """Bootstrap from existing dataset JSONL."""
        if not path or not os.path.exists(path):
            return
        count = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cb = rec.get("create_block", 0)
                    peak_x = rec.get("peak_x", 0)
                    buys = rec.get("kol_buys", [])
                    for b in buys[:5]:
                        kn = b.get("kol_name", "")
                        if kn:
                            self.record_outcome(kn, cb, peak_x)
                            count += 1
                except json.JSONDecodeError:
                    pass
        print(f"[win_rate] Bootstrapped {count} KOL outcomes from {path}", file=sys.stderr)


# ── Signal Enricher ──────────────────────────────────────────────────────────

class SignalEnricher:
    def __init__(
        self,
        deployer_db: DeployerDB,
        klines_cache: BinanceKlinesCache,
        win_rate_tracker: KolWinRateTracker,
        rolling_deployers: RollingDeployerTracker,
        output_columns: List[str],
    ):
        self.deployer_db = deployer_db
        self.klines_cache = klines_cache
        self.win_rate_tracker = win_rate_tracker
        self.rolling_deployers = rolling_deployers
        self.output_columns = output_columns

    async def enrich(self, signal: dict) -> Optional[dict]:
        """Enrich a raw kol_monitor live signal into the full dataset schema."""
        if signal.get("event") != "kol_signal":
            return None

        rec: Dict[str, Any] = {}

        # Direct fields from signal
        rec["token_address"] = signal.get("token", "")
        rec["name"] = signal.get("name", "")
        rec["creator"] = signal.get("creator", "")
        rec["create_block"] = signal.get("create_block", 0)

        # Time derivation (current time as proxy since live)
        now = datetime.now(timezone.utc)
        rec["create_time"] = now.isoformat()
        rec["create_hour_utc"] = now.hour
        rec["create_dow"] = now.weekday()

        # Deployer: point-in-time from rolling history, else static CSV; always attach CSV extras
        creator_lc = (rec["creator"] or "").lower()
        cb_sig = int(rec["create_block"] or 0)
        dep = self.deployer_db.lookup(rec["creator"])
        priors = self.rolling_deployers.priors_before(creator_lc, cb_sig)
        if priors:
            st = stats_from_priors(priors)
            rec["deployer_prior_launches"] = st.prior_launches
            rec["deployer_prior_grads"] = st.prior_grads
            rec["deployer_grad_rate"] = st.grad_rate
            rec["deployer_prior_avg_peak_mult"] = st.prior_avg_peak_mult
            rec["deployer_prior_win_rate"] = st.prior_win_rate
            rec["deployer_rug_proxy_rate"] = st.rug_proxy_rate
            rec["deployer_reputation_score"] = st.reputation_score
        else:
            rec["deployer_prior_launches"] = dep.get("deployer_prior_launches", 0)
            rec["deployer_prior_grads"] = dep.get("deployer_prior_grads", 0)
            rec["deployer_grad_rate"] = dep.get("deployer_grad_rate", 0.0)
            rec["deployer_prior_avg_peak_mult"] = 0.0
            rec["deployer_prior_win_rate"] = 0.0
            rec["deployer_rug_proxy_rate"] = 0.0
            rec["deployer_reputation_score"] = 0.0
        for k in ("deployer_csv_score", "deployer_csv_rug_rate", "deployer_csv_rugged", "deployer_csv_honeypots"):
            if k in dep and dep[k] is not None:
                rec[k] = dep[k]
            else:
                rec[k] = None

        # KOL fields: prefer kol_buys[] from lumina_kol_monitor (backtest-parity JSON)
        kol_names = signal.get("kol_names") or []
        buys = signal.get("kol_buys")
        rec["kol_count_final"] = signal.get("kol_count", 0)
        rec["kol_count_at_entry"] = rec["kol_count_final"]

        for i in range(5):
            prefix = f"kol{i+1}_"
            rec[prefix + "sell_usd"] = None
            rec[prefix + "pnl_usd"] = None
            rec[prefix + "held_at_entry"] = None
            rec[prefix + "holder_count"] = None

        if isinstance(buys, list) and buys:
            for i in range(5):
                prefix = f"kol{i+1}_"
                if i < len(buys):
                    b = buys[i]
                    rec[prefix + "name"] = b.get("kol_name") or None
                    rec[prefix + "buy_block"] = _coerce_int(b.get("buy_block"))
                    rec[prefix + "buy_usd"] = _coerce_float(b.get("buy_notional_usd_approx"), 0.0)
                else:
                    rec[prefix + "name"] = None
                    rec[prefix + "buy_block"] = None
                    rec[prefix + "buy_usd"] = None
        else:
            for i in range(5):
                prefix = f"kol{i+1}_"
                rec[prefix + "name"] = kol_names[i] if i < len(kol_names) else None
                rec[prefix + "buy_block"] = None
                rec[prefix + "buy_usd"] = None

        k1 = (rec.get("kol1_name") or "") or ""
        k2 = (rec.get("kol2_name") or "") or ""
        k3 = (rec.get("kol3_name") or "") or ""
        rec["combo_k1k2"] = f"{k1}→{k2}" if k1 and k2 else ""
        rec["combo_k1k2k3"] = f"{k1}→{k2}→{k3}" if k1 and k2 and k3 else ""

        u1 = rec.get("kol1_buy_usd") or 0.0
        u2 = rec.get("kol2_buy_usd") or 0.0
        if u1 or u2:
            rec["combined_notional_k1k2_usd"] = float(u1) + float(u2)
        else:
            rec["combined_notional_k1k2_usd"] = _coerce_float(signal.get("latest_buy_notional_usd"), 0.0) or 0.0

        cb = rec["create_block"]
        rec["kol1_7d_win_rate"] = self.win_rate_tracker.get_7d_win_rate(k1, cb) if k1 else None
        rec["kol2_7d_win_rate"] = self.win_rate_tracker.get_7d_win_rate(k2, cb) if k2 else None

        rec["kol1_kol2_delta_blocks"] = None
        rec["kol2_kol3_delta_blocks"] = None
        if isinstance(buys, list) and len(buys) >= 2:
            b0 = _coerce_int(buys[0].get("buy_block"))
            b1 = _coerce_int(buys[1].get("buy_block"))
            if b0 is not None and b1 is not None:
                rec["kol1_kol2_delta_blocks"] = b1 - b0
        if isinstance(buys, list) and len(buys) >= 3:
            b1 = _coerce_int(buys[1].get("buy_block"))
            b2 = _coerce_int(buys[2].get("buy_block"))
            if b1 is not None and b2 is not None:
                rec["kol2_kol3_delta_blocks"] = b2 - b1

        # Dev fields
        rec["dev_sell_usd"] = signal.get("dev_sell_usd", 0)
        rec["dev_sell_pct_supply"] = 0.0  # not available live
        rec["dev_buy_usd"] = 0.0
        rec["dev_net_usd"] = -(rec["dev_sell_usd"])

        # Market fields from signal
        rec["entry_mcap_usd"] = signal.get("entry_mcap_usd", 0)
        rec["bonding_curve_pct"] = signal.get("bonding_curve_pct", 0)
        rec["bnb_price_usd"] = signal.get("bnb_price_usd", 0)
        rec["age_blocks_at_entry"] = signal.get("age_blocks", 0)
        rec["holder_count_at_entry"] = signal.get("holder_proxy", 0)
        rec["holder_growth_kol1_to_kol2"] = None
        rec["holder_growth_kol2_to_entry"] = None

        # Outcome fields (not known yet in live mode)
        rec["peak_mcap_usd"] = None
        rec["low_mcap_usd"] = None
        rec["graduated"] = None
        rec["peak_mult_vs_slot2_entry"] = None

        # BTC/BNB 4h change
        await self.klines_cache.refresh_if_needed()
        ts = int(now.timestamp())
        btc_chg, bnb_chg = self.klines_cache.get_4h_change(ts)
        rec["btc_4h_change_pct"] = btc_chg
        rec["bnb_4h_change_pct"] = bnb_chg

        # Live-only columns (for CSV/Parquet; not in historical training CSV)
        rec["ml_score"] = _coerce_float(signal.get("ml_score"))
        rec["current_mcap_usd"] = _coerce_float(signal.get("current_mcap_usd"))
        rec["signal_mode"] = _coerce_int(signal.get("mode"))
        rec["signal_mode_label"] = signal.get("mode_label") or ""
        rec["position_bnb"] = _coerce_float(signal.get("position_bnb"))
        rec["sl_x"] = _coerce_float(signal.get("sl_x"))
        rec["signal_block"] = signal.get("block") or ""
        rec["signal_tx"] = signal.get("tx") or ""
        rec["deployer_score_signal"] = _coerce_float(signal.get("deployer_score"))
        rec["deployer_success_rate_signal"] = _coerce_float(signal.get("deployer_success_rate"))
        rec["deployer_successful_signal"] = _coerce_int(signal.get("deployer_successful"))
        rec["deployer_total_tokens_signal"] = _coerce_int(signal.get("deployer_total_tokens"))

        for c in self.output_columns:
            rec.setdefault(c, None)

        # Append this token to rolling deployer history (next signal sees it as prior)
        if creator_lc:
            self.rolling_deployers.record(
                creator_lc,
                PriorTokenSnapshot(
                    create_block=cb_sig,
                    graduated=False,
                    peak_mult=None,
                    dev_sell_usd=float(rec.get("dev_sell_usd") or 0),
                ),
            )

        return rec


async def fetch_eth_block_number(rpc_url: str) -> int:
    """JSON-RPC eth_blockNumber; returns int block height."""
    import aiohttp

    payload = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            rpc_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            data = await resp.json()
    if "result" not in data:
        raise RuntimeError(f"eth_blockNumber bad response: {data}")
    return int(data["result"], 16)


def hydrate_emitted_tokens_from_jsonl(path: str, min_kc: int) -> set[str]:
    """Tokens that already have a JSONL row with kol_count_final >= min_kc (restart-safe dedupe)."""
    out: set[str] = set()
    if min_kc <= 0 or not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kcf = int(o.get("kol_count_final") or 0)
                if kcf < min_kc:
                    continue
                t = (o.get("token_address") or "").strip().lower()
                if t:
                    out.add(t)
    except OSError:
        pass
    return out


def should_emit_row(
    rec: dict,
    *,
    min_token_create_block: int,
    floor_create_block: int,
    require_positive_create_block: bool,
    first_signal_min_kol_count: int,
    emitted_tokens: set[str],
) -> tuple[bool, str]:
    """
    Returns (emit?, skip_reason empty if emit).
    """
    tok = (rec.get("token_address") or "").strip().lower()
    if not tok:
        return False, "empty_token"

    cb = int(rec.get("create_block") or 0)
    if require_positive_create_block and cb <= 0:
        return False, "missing_create_block"

    if min_token_create_block and cb < min_token_create_block:
        return False, "create_block_below_min"

    if floor_create_block and cb < floor_create_block:
        return False, "token_older_than_session_start"

    kc = int(rec.get("kol_count_final") or 0)
    if first_signal_min_kol_count > 0:
        if kc < first_signal_min_kol_count:
            return False, "kol_count_below_threshold"
        if tok in emitted_tokens:
            return False, "token_already_emitted"

    return True, ""


# ── Main Loop ─────────────────────────────────────────────────────────────────

async def read_stdin_lines():
    """Async generator that reads lines from stdin."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            break
        yield line.decode("utf-8", errors="replace").strip()


async def read_ipc_lines(ipc_path: str):
    """Async generator that reads lines from a FIFO/IPC file."""
    while True:
        try:
            with open(ipc_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        yield line
        except FileNotFoundError:
            await asyncio.sleep(1)
        except Exception as e:
            print(f"[ipc] Error reading {ipc_path}: {e}", file=sys.stderr)
            await asyncio.sleep(1)


async def main():
    parser = argparse.ArgumentParser(description="Live KOL dataset collector")
    parser.add_argument("--deployers", default="data/deployers.csv",
                        help="Path to deployers.csv")
    parser.add_argument("--output", default="kol_dataset_live.jsonl",
                        help="Output JSONL file (append mode)")
    parser.add_argument("--bootstrap", default="",
                        help="Existing backtest JSONL to bootstrap win rates from")
    parser.add_argument("--ipc", default="",
                        help="Read from IPC FIFO instead of stdin")
    parser.add_argument("--snapshot-interval", type=int, default=100,
                        help="Write parquet snapshot every N records")
    parser.add_argument("--deployers-csv", default="",
                        help="Alias for --deployers (Four.meme deployers_fourmeme.csv)")
    parser.add_argument("--deployer-state", default="",
                        help="Persist rolling deployer JSON (load on start, save periodically)")
    parser.add_argument("--deployer-save-interval", type=int, default=50,
                        help="Save deployer rolling state every N records (0=disable)")
    parser.add_argument("--bootstrap-deployers", default="",
                        help="Bootstrap rolling history from KOL dataset CSV (sorted by create_block)")
    parser.add_argument(
        "--csv",
        default="",
        help="Append rows to CSV (schema via --schema; default matches kol_dataset_90d.csv)",
    )
    parser.add_argument(
        "--schema",
        choices=("90d", "full"),
        default="90d",
        help="CSV/Parquet columns: '90d' = kol_dataset_90d.csv (76 cols); 'full' = enrich FINAL_COLUMNS + deployer extras",
    )
    parser.add_argument(
        "--live-extras",
        action="store_true",
        help="Append ml_score, signal_*, deployer_*_signal columns after the core schema",
    )
    parser.add_argument(
        "--first-signal-min-kol-count",
        type=int,
        default=0,
        metavar="K",
        help="Emit at most one row per token: the first signal where kol_count>=K (e.g. 2 matches "
        "kol2+ training rows; later KOL buys on the same token are skipped). 0 = emit every signal (legacy).",
    )
    parser.add_argument(
        "--min-token-create-block",
        type=int,
        default=0,
        metavar="B",
        help="Skip tokens with Four.meme create_block < B (0 = no filter).",
    )
    parser.add_argument(
        "--tokens-newer-than-session-start",
        action="store_true",
        help="At startup, query eth_blockNumber via QUICK_NODE_BSC_RPC (or --rpc-url); skip tokens "
        "with create_block < that block so only tokens created after this collector run starts are kept.",
    )
    parser.add_argument(
        "--rpc-url",
        default="",
        help="BSC HTTP RPC for --tokens-newer-than-session-start (default: env QUICK_NODE_BSC_RPC).",
    )
    parser.add_argument(
        "--require-positive-create-block",
        action="store_true",
        help="Skip signals with token create_block missing or 0 (recommended for live dataset quality).",
    )
    parser.add_argument(
        "--verbose-skips",
        action="store_true",
        help="Log each skipped signal to stderr (default: only summary count).",
    )
    parser.add_argument(
        "--fresh-output",
        action="store_true",
        help="Truncate --output JSONL and --csv at startup (new schema, or wipe bad append runs).",
    )
    parser.add_argument(
        "--no-hydrate-emitted",
        action="store_true",
        help="When using --first-signal-min-kol-count K>0, do not preload emitted tokens from existing JSONL.",
    )
    args = parser.parse_args()

    dep_path = args.deployers_csv or args.deployers
    out_columns = live_csv_columns(schema=args.schema, include_live_extras=args.live_extras)

    print(f"[collector] Starting live dataset collector", file=sys.stderr)
    print(f"[collector] Output: {args.output}", file=sys.stderr)
    if args.csv:
        print(f"[collector] CSV: {args.csv} ({len(out_columns)} columns)", file=sys.stderr)

    floor_create_block = 0
    if args.tokens_newer_than_session_start:
        rpc = (args.rpc_url or os.environ.get("QUICK_NODE_BSC_RPC") or "").strip()
        if not rpc:
            print(
                "[collector] ERROR: --tokens-newer-than-session-start needs --rpc-url or QUICK_NODE_BSC_RPC",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            floor_create_block = await fetch_eth_block_number(rpc)
        except Exception as e:
            print(f"[collector] ERROR: could not fetch chain tip: {e}", file=sys.stderr)
            sys.exit(1)
        print(
            f"[collector] Session floor: token create_block must be >= {floor_create_block} "
            f"(tokens created before live start are dropped)",
            file=sys.stderr,
        )

    if args.first_signal_min_kol_count > 0:
        print(
            f"[collector] One row per token when kol_count first reaches >= {args.first_signal_min_kol_count}",
            file=sys.stderr,
        )
    effective_require_positive = (
        args.require_positive_create_block
        or bool(args.tokens_newer_than_session_start)
        or (args.first_signal_min_kol_count > 0)
    )
    if effective_require_positive:
        print(
            "[collector] Skipping rows without positive token create_block "
            "(required when using session floor and/or --first-signal-min-kol-count > 0)",
            file=sys.stderr,
        )

    if args.fresh_output:
        for p in (args.output, args.csv or ""):
            if p:
                try:
                    open(p, "w", encoding="utf-8").close()
                except OSError as e:
                    print(f"[collector] ERROR: could not truncate {p}: {e}", file=sys.stderr)
                    sys.exit(1)
        print("[collector] --fresh-output: truncated JSONL and/or CSV", file=sys.stderr)

    deployer_db = DeployerDB(dep_path)
    klines_cache = BinanceKlinesCache()
    win_rate_tracker = KolWinRateTracker()
    rolling_deployers = RollingDeployerTracker()

    if args.deployer_state:
        rolling_deployers.load_state(args.deployer_state)
    if args.bootstrap_deployers:
        rolling_deployers.load_from_csv_bootstrap(args.bootstrap_deployers)

    if args.bootstrap:
        win_rate_tracker.load_from_jsonl(args.bootstrap)

    enricher = SignalEnricher(
        deployer_db, klines_cache, win_rate_tracker, rolling_deployers, out_columns
    )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    out_f = open(args.output, "a")
    csv_app: Optional[LiveCsvAppender] = None
    if args.csv:
        csv_app = LiveCsvAppender(args.csv, out_columns)
    record_count = 0
    skipped = 0
    emitted_tokens: set[str] = set()
    if args.first_signal_min_kol_count > 0 and not args.no_hydrate_emitted:
        emitted_tokens = hydrate_emitted_tokens_from_jsonl(
            args.output, args.first_signal_min_kol_count
        )
        if emitted_tokens:
            print(
                f"[collector] Hydrated {len(emitted_tokens)} token(s) from existing JSONL "
                f"(kol_count>={args.first_signal_min_kol_count}); those addresses will not emit again",
                file=sys.stderr,
            )

    try:
        if args.ipc:
            line_source = read_ipc_lines(args.ipc)
        else:
            line_source = read_stdin_lines()

        async for line in line_source:
            if not line:
                continue
            try:
                signal = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec = await enricher.enrich(signal)
            if rec is None:
                continue

            emit, reason = should_emit_row(
                rec,
                min_token_create_block=args.min_token_create_block,
                floor_create_block=floor_create_block,
                require_positive_create_block=effective_require_positive,
                first_signal_min_kol_count=args.first_signal_min_kol_count,
                emitted_tokens=emitted_tokens,
            )
            if not emit:
                skipped += 1
                if args.verbose_skips:
                    tok_short = (rec.get("token_address") or "?")[:10]
                    print(
                        f"[collector] skip {tok_short}... ({reason}) kc={rec.get('kol_count_final')} "
                        f"create_block={rec.get('create_block')}",
                        file=sys.stderr,
                    )
                continue

            if args.first_signal_min_kol_count > 0:
                emitted_tokens.add((rec.get("token_address") or "").strip().lower())

            record_count += 1
            rec["row"] = record_count

            out_f.write(json.dumps(rec, default=str) + "\n")
            out_f.flush()
            if csv_app:
                csv_app.write_row(rec)

            print(f"[collector] #{record_count} {rec.get('token_address', '?')[:10]}... "
                  f"kols={rec.get('kol_count_final',0)} mcap=${rec.get('entry_mcap_usd',0):.0f}",
                  file=sys.stderr)

            if args.deployer_state and args.deployer_save_interval > 0:
                if record_count % args.deployer_save_interval == 0:
                    rolling_deployers.save_state(args.deployer_state)

            # Periodic parquet snapshot
            if args.snapshot_interval > 0 and record_count % args.snapshot_interval == 0:
                try:
                    import pandas as pd

                    snapshot_path = args.output.replace(".jsonl", f"_snapshot.parquet")
                    records = []
                    with open(args.output) as sf:
                        for sline in sf:
                            sline = sline.strip()
                            if sline:
                                records.append(json.loads(sline))
                    if records:
                        df = pd.DataFrame(records)
                        for c in out_columns:
                            if c not in df.columns:
                                df[c] = None
                        df = df[[c for c in out_columns if c in df.columns]]
                        df.to_parquet(snapshot_path, index=False, engine="pyarrow")
                        print(f"[collector] Parquet snapshot: {snapshot_path} ({len(df)} rows)",
                              file=sys.stderr)
                except Exception as e:
                    print(f"[collector] Snapshot error: {e}", file=sys.stderr)

    except KeyboardInterrupt:
        print(f"\n[collector] Interrupted after {record_count} records", file=sys.stderr)
    finally:
        out_f.close()
        if csv_app:
            csv_app.close()

    # Final parquet export
    if record_count > 0:
        try:
            import pandas as pd

            records = []
            with open(args.output) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            if records:
                parquet_path = args.output.replace(".jsonl", ".parquet")
                df = pd.DataFrame(records)
                for c in out_columns:
                    if c not in df.columns:
                        df[c] = None
                df = df[[c for c in out_columns if c in df.columns]]
                df.to_parquet(parquet_path, index=False, engine="pyarrow")
                print(f"[collector] Final parquet: {parquet_path} ({len(df)} rows)",
                      file=sys.stderr)
        except Exception as e:
            print(f"[collector] Final export error: {e}", file=sys.stderr)

    print(
        f"[collector] Done. {record_count} records written to {args.output} ({skipped} skipped by filters)",
        file=sys.stderr,
    )
    if record_count == 0:
        print(
            "[collector] 0 rows usually means lumina_kol_monitor exited immediately "
            "(stdin closed with no JSON lines). The C++ binary does NOT read Python's load_dotenv — "
            "export QUICK_NODE_BSC_RPC in the shell or run:  bash scripts/run_live_dataset_collect.sh",
            file=sys.stderr,
        )


if __name__ == "__main__":
    asyncio.run(main())
