"""
Trading Strategy routes — God of Scalper: Overlap Volume Spike Scanner.

Scans Binance Futures (USDT-M) low-volume pairs for dual-timeframe overlap spikes:
  - 5m: current candle volume ≥ 100× previous candle volume
  - 1m: current candle volume ≥ 20× SMA(10) of previous candle volumes
Both must fire simultaneously (overlap) → alert + watchlist.
"""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Query

from app.db.memcache import cache_get, cache_set

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategy", tags=["strategy"])

# ── In-memory stores ────────────────────────────────────────────────────────
_spike_alerts: list[dict] = []   # rolling overlap-spike alerts
_watchlist: list[dict] = []      # user's watchlist (persisted in-memory)
MAX_ALERTS = 200

# Scanner liveness stats (updated after each scan cycle)
_last_scan_stats: dict = {
    "pairs_total": 0,       # total futures pairs on Binance
    "pairs_filtered": 0,    # pairs matching 1h volume range
    "pairs_checked": 0,     # pairs actually checked for overlap
    "spikes_found": 0,      # overlap spikes found this cycle
    "errors": 0,            # errors during OHLCV fetch
    "last_scan_ts": 0,      # unix timestamp of last completed scan
    "scan_duration_ms": 0,  # how long the scan took
}

# ── Scanner config (mutable from frontend) ──────────────────────────────────
_scanner_config: dict = {
    "vol_1h_min": 10_000,        # min 1h quote volume in USD
    "vol_1h_max": 2_000_000,     # max 1h quote volume in USD
    "spike_5m": 100.0,           # 5m: vol / prev_candle_vol ≥ this
    "spike_1m": 20.0,            # 1m: vol / SMA(10 prev candles) ≥ this
    "ma_window": 10,             # MA window for 1m spike detection
}


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/alerts")
async def get_spike_alerts(limit: int = Query(50, ge=1, le=200)):
    """Return recent overlap-spike alerts from the background scanner."""
    return {
        "data": _spike_alerts[:limit],
        "total": len(_spike_alerts),
        "scanner_active": True,
    }


@router.get("/watchlist")
async def get_watchlist():
    """Return the current watchlist."""
    return {"data": _watchlist}


@router.post("/watchlist/add")
async def add_to_watchlist(symbol: str = Query(...)):
    """Add a symbol to watchlist (from alert click)."""
    # Find matching alert to copy full data
    alert = next((a for a in _spike_alerts if a["symbol"] == symbol), None)
    if alert and not any(w["symbol"] == symbol for w in _watchlist):
        _watchlist.insert(0, {**alert, "added_ts": time.time()})
    return {"data": _watchlist}


@router.post("/watchlist/remove")
async def remove_from_watchlist(symbol: str = Query(...)):
    """Remove a symbol from watchlist."""
    _watchlist[:] = [w for w in _watchlist if w["symbol"] != symbol]
    return {"data": _watchlist}


@router.get("/ohlcv")
async def get_chart_ohlcv(
    symbol: str = Query("BTC/USDT:USDT"),
    timeframe: str = Query("5m"),
    limit: int = Query(200, ge=10, le=1500),
):
    """Fetch OHLCV candles for the lightweight-charts frontend."""
    try:
        from app.services.exchange import _get_exchange
        ex = _get_exchange("binance", market_type="swap")
        if not ex.markets:
            await ex.load_markets()
        raw = await ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        candles = []
        for c in (raw or []):
            candles.append({
                "time": int(c[0] / 1000),
                "open": c[1],
                "high": c[2],
                "low": c[3],
                "close": c[4],
                "volume": c[5],
            })
        return {"data": candles, "symbol": symbol, "timeframe": timeframe}
    except Exception as e:
        logger.error(f"OHLCV fetch error for {symbol}/{timeframe}: {e}")
        return {"data": [], "symbol": symbol, "timeframe": timeframe, "error": str(e)}


@router.get("/config")
async def get_scanner_config():
    """Return current scanner configuration."""
    return _scanner_config


@router.post("/config")
async def set_scanner_config(
    vol_1h_min: float = Query(10_000, ge=0),
    vol_1h_max: float = Query(2_000_000, ge=1_000),
    spike_5m: float = Query(100.0, ge=5, le=10000),
    spike_1m: float = Query(20.0, ge=2, le=5000),
    ma_window: int = Query(10, ge=5, le=30),
):
    """Update scanner configuration."""
    _scanner_config["vol_1h_min"] = vol_1h_min
    _scanner_config["vol_1h_max"] = vol_1h_max
    _scanner_config["spike_5m"] = spike_5m
    _scanner_config["spike_1m"] = spike_1m
    _scanner_config["ma_window"] = ma_window
    return _scanner_config


@router.get("/scanner-status")
async def scanner_status():
    """Health-check + liveness stats for the scanner background task."""
    return {
        "active": True,
        "total_alerts": len(_spike_alerts),
        "watchlist_count": len(_watchlist),
        **_last_scan_stats,
        "config": _scanner_config,
    }


# ── Background scanner (called from cache warmer in main.py) ────────────────

async def run_volume_spike_scan(
    vol_1h_min: float | None = None,
    vol_1h_max: float | None = None,
    spike_5m: float | None = None,
    spike_1m: float | None = None,
    ma_window: int | None = None,
):
    """
    Scan Binance Futures (USDT-M perpetuals) for overlap volume spikes.

    1. Fetch all futures tickers → filter by 1h quote volume ($10K–$2M)
    2. For each candidate, fetch 5m OHLCV + 1m OHLCV
    3. 5m spike: current_vol / prev_candle_vol ≥ spike_5m  (like Pine: volume / volume[1])
    4. 1m spike: current_vol / SMA(prev 10 candle vols) ≥ spike_1m  (like Pine: vol / ta.sma(vol[1], 10))
    5. If BOTH fire → overlap spike alert
    """
    from app.services.exchange import _get_exchange

    s5m = spike_5m if spike_5m is not None else _scanner_config["spike_5m"]
    s1m = spike_1m if spike_1m is not None else _scanner_config["spike_1m"]
    v_min = vol_1h_min if vol_1h_min is not None else _scanner_config["vol_1h_min"]
    v_max = vol_1h_max if vol_1h_max is not None else _scanner_config["vol_1h_max"]
    ma_w = ma_window if ma_window is not None else _scanner_config["ma_window"]

    scan_start = time.time()

    try:
        # Use Binance Futures (swap market)
        ex = _get_exchange("binance", market_type="swap")

        # Step 1: Fetch all futures tickers
        raw_tickers = await ex.fetch_tickers()
        total_futures = 0
        candidates = []
        for symbol, t in raw_tickers.items():
            # Only USDT-M perpetual futures (symbol format: "BTC/USDT:USDT")
            if "/USDT:USDT" not in symbol:
                continue
            total_futures += 1
            quote_vol_24h = t.get("quoteVolume") or 0
            price = t.get("last") or 0
            if price <= 0 or quote_vol_24h <= 0:
                continue
            # Estimate 1h volume ≈ 24h / 24
            vol_1h_est = quote_vol_24h / 24.0
            if v_min <= vol_1h_est <= v_max:
                candidates.append({
                    "symbol": symbol,
                    "price": price,
                    "vol_24h": quote_vol_24h,
                    "vol_1h_est": vol_1h_est,
                    "change_24h": t.get("percentage") or 0,
                })

        logger.info(
            f"🔍 Strategy scanner: {len(candidates)}/{total_futures} futures pairs with "
            f"1h vol ${v_min:,.0f}–${v_max:,.0f} (5m≥{s5m}× 1m≥{s1m}×)"
        )

        # Step 2: Check each candidate for overlap spike (5m + 1m)
        # ccxt has enableRateLimit=True, so we just pace the concurrency
        CHUNK = 8
        new_alerts = []
        checked = 0
        errors = 0

        for i in range(0, len(candidates), CHUNK):
            chunk = candidates[i : i + CHUNK]
            tasks = [_check_overlap_spike(ex, p, s5m, s1m, ma_w) for p in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                checked += 1
                if isinstance(r, dict):
                    new_alerts.append(r)
                elif isinstance(r, Exception):
                    errors += 1
            if i + CHUNK < len(candidates):
                await asyncio.sleep(1.0)

        scan_duration = int((time.time() - scan_start) * 1000)

        logger.info(
            f"🔍 Strategy scanner: checked {checked}, "
            f"found {len(new_alerts)} overlap spikes, {errors} errors, {scan_duration}ms"
        )

        # Update liveness stats
        _last_scan_stats["pairs_total"] = total_futures
        _last_scan_stats["pairs_filtered"] = len(candidates)
        _last_scan_stats["pairs_checked"] = checked
        _last_scan_stats["spikes_found"] = len(new_alerts)
        _last_scan_stats["errors"] = errors
        _last_scan_stats["last_scan_ts"] = time.time()
        _last_scan_stats["scan_duration_ms"] = scan_duration

        # Step 3: Merge into alert store (dedup by symbol within 5 min)
        new_alerts.sort(key=lambda x: x["ratio_5m"], reverse=True)

        if new_alerts:
            now = time.time()
            existing_keys = set()
            for a in _spike_alerts:
                if now - a.get("scan_ts", 0) < 300:
                    existing_keys.add(a["symbol"])

            added = 0
            for alert in new_alerts:
                if alert["symbol"] not in existing_keys:
                    _spike_alerts.insert(0, alert)
                    existing_keys.add(alert["symbol"])
                    added += 1

            while len(_spike_alerts) > MAX_ALERTS:
                _spike_alerts.pop()

            logger.info(f"🚨 Strategy: {added} new overlap spikes added to alerts")

        await cache_set("strategy:last_scan_ts", time.time(), ttl=300)
        return len(new_alerts)

    except Exception as e:
        logger.error(f"Strategy scanner error: {e}")
        return 0


async def _check_overlap_spike(
    ex, pair_info: dict, threshold_prev: float, threshold_ma: float, ma_window: int
) -> Optional[dict]:
    """
    Check a single futures pair for overlap spike — matching scalper.pine EXACTLY.

    Pine runs on a 1m chart. Both ratios use 1m data:
      prevRatio  = volume / volume[1]                    (cur 1m vol / prev 1m vol)
      maRatio    = volume / ta.sma(volume[1], ma_window) (cur 1m vol / SMA of prev N 1m vols)
      isOverlap  = prevRatio >= threshold_prev AND maRatio >= threshold_ma

    Zone: high/low/mid of the spike 1m candle.
    """
    symbol = pair_info["symbol"]
    try:
        # Single 1m fetch — need current + ma_window + 1 previous candles
        ohlcv_1m = await ex.fetch_ohlcv(symbol, "1m", limit=ma_window + 5)
        if not ohlcv_1m or len(ohlcv_1m) < ma_window + 2:
            return None

        cur = ohlcv_1m[-1]   # current 1m candle
        prev = ohlcv_1m[-2]  # previous 1m candle (volume[1])

        cur_vol = cur[5]
        prev_vol = prev[5]

        if cur_vol <= 0 or prev_vol <= 0:
            return None

        # Pine: volume / volume[1]
        ratio_prev = cur_vol / prev_vol

        # Quick exit
        if ratio_prev < threshold_prev:
            return None

        # Pine: ta.sma(volume[1], ma_window)  — SMA starting from volume[1]
        # volume[1] = prev candle, volume[2] = candle before that, etc.
        sma_vols = [ohlcv_1m[-(k + 1)][5] for k in range(1, ma_window + 1)
                     if -(k + 1) >= -len(ohlcv_1m) and ohlcv_1m[-(k + 1)][5] > 0]
        if len(sma_vols) < max(3, ma_window // 2):
            return None

        ma_val = sum(sma_vols) / len(sma_vols)
        if ma_val <= 0:
            return None

        # Pine: volume / sma(volume[1], ma_window)
        ratio_ma = cur_vol / ma_val

        if ratio_ma < threshold_ma:
            return None

        # ── OVERLAP SPIKE DETECTED ──
        cur_open = cur[1]
        cur_high = cur[2]
        cur_low = cur[3]
        cur_close = cur[4]
        price = pair_info["price"]

        is_bullish = cur_close >= cur_open
        body_high = max(cur_open, cur_close)
        body_low = min(cur_open, cur_close)
        body_pct = abs(cur_close - cur_open) / cur_open * 100 if cur_open > 0 else 0

        base = symbol.split("/")[0]

        return {
            "symbol": symbol,
            "base": base,
            "price": price,
            "vol_24h": pair_info["vol_24h"],
            "vol_1h_est": pair_info["vol_1h_est"],
            "change_24h": pair_info["change_24h"],
            "ratio_5m": round(ratio_prev, 1),
            "ratio_1m": round(ratio_ma, 1),
            "vol_5m_cur": cur_vol,
            "vol_5m_prev": prev_vol,
            "vol_1m_cur": cur_vol,
            "vol_1m_ma": round(ma_val, 2),
            "candle_open": cur_open,
            "candle_close": cur_close,
            "candle_high": cur_high,
            "candle_low": cur_low,
            "is_bullish": is_bullish,
            "body_pct": round(body_pct, 2),
            "zone_high": cur_high,
            "zone_low": cur_low,
            "zone_mid": (body_high + body_low) / 2,
            "timestamp": cur[0],
            "scan_ts": time.time(),
        }
    except Exception:
        return None
