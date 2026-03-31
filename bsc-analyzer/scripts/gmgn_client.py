#!/usr/bin/env python3
"""
GMGN OpenAPI client (standard auth) — K-line for hybrid mcap enrichment.

Docs: https://github.com/GMGNAI/gmgn-skills/wiki/API-Market
Auth: https://github.com/GMGNAI/gmgn-skills/wiki/API-Auth

Env:
  GMGN_API_KEY   — required
  GMGN_API_BASE  — default https://gmgn.ai/api

Token info (POST /v1/token/info): holder_count, liquidity, etc. See:
  https://github.com/GMGNAI/gmgn-skills/wiki/API-Token
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def resolution_seconds(resolution: str) -> int:
    """K-line bar length in seconds (GMGN token_kline)."""
    m = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    return m.get(resolution, 60)


def filter_candles_in_window(
    candles: list[dict[str, Any]],
    our_entry_sec: int,
    end_sec: int,
    resolution: str,
) -> list[dict[str, Any]]:
    """Keep candles that overlap [our_entry_sec, end_sec]."""
    res = resolution_seconds(resolution)
    out: list[dict[str, Any]] = []
    for c in candles:
        try:
            t = int(c.get("time") or 0)
        except (TypeError, ValueError):
            continue
        if t + res > our_entry_sec and t < end_sec:
            out.append(c)
    return out


def _headers(api_key: str) -> dict[str, str]:
    return {"X-APIKEY": api_key, "Accept": "application/json"}


def token_kline(
    chain: str,
    address: str,
    resolution: str,
    from_ms: Optional[int] = None,
    to_ms: Optional[int] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """GET /v1/market/token_kline — returns data.list candles."""
    key = api_key or os.environ.get("GMGN_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set GMGN_API_KEY")
    base = (base_url or os.environ.get("GMGN_API_BASE", "https://gmgn.ai/api")).rstrip("/")
    ts = int(time.time())
    cid = str(uuid.uuid4())
    params: dict[str, Any] = {
        "chain": chain,
        "address": address,
        "resolution": resolution,
        "timestamp": ts,
        "client_id": cid,
    }
    if from_ms is not None:
        params["from"] = from_ms
    if to_ms is not None:
        params["to"] = to_ms
    q = urlencode(params)
    url = f"{base}/v1/market/token_kline?{q}"
    req = Request(url, headers=_headers(key))
    try:
        with urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"GMGN HTTP {e.code}: {body}") from e
    except URLError as e:
        raise RuntimeError(f"GMGN network error: {e}") from e

    j = json.loads(raw)
    if j.get("code") != 0:
        raise RuntimeError(f"GMGN error: {j}")
    data = j.get("data") or {}
    return list(data.get("list") or [])


def token_info(
    chain: str,
    address: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    """POST /v1/token/info — metadata, holder_count, liquidity, nested pool/dev/price."""
    key = api_key or os.environ.get("GMGN_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set GMGN_API_KEY")
    base = (base_url or os.environ.get("GMGN_API_BASE", "https://gmgn.ai/api")).rstrip("/")
    ts = int(time.time())
    cid = str(uuid.uuid4())
    q = urlencode({"timestamp": ts, "client_id": cid})
    url = f"{base}/v1/token/info?{q}"
    body = json.dumps({"chain": chain, "address": address.lower()}).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={**_headers(key), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        b = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"GMGN HTTP {e.code}: {b}") from e
    except URLError as e:
        raise RuntimeError(f"GMGN network error: {e}") from e

    j = json.loads(raw)
    if j.get("code") != 0:
        raise RuntimeError(f"GMGN error: {j}")
    return dict(j.get("data") or {})


def holder_count_from_token_info(data: dict[str, Any]) -> Optional[int]:
    """Prefer top-level holder_count; fall back to stat.holder_count."""
    if not data:
        return None
    hc = data.get("holder_count")
    if hc is not None:
        try:
            return int(hc)
        except (TypeError, ValueError):
            pass
    stat = data.get("stat")
    if isinstance(stat, dict) and stat.get("holder_count") is not None:
        try:
            return int(stat["holder_count"])
        except (TypeError, ValueError):
            pass
    return None


def candles_to_mcap_range_usd(
    candles: list[dict[str, Any]], total_supply: float
) -> tuple[Optional[float], Optional[float]]:
    """
    FDV-style mcap from OHLC in USD: mcap ≈ price_usd * total_supply.
    peak = max(high) * supply, low = min(low) * supply over candles.
    """
    if not candles or total_supply <= 0:
        return None, None
    highs: list[float] = []
    lows: list[float] = []
    for c in candles:
        try:
            highs.append(float(c.get("high") or 0))
            lows.append(float(c.get("low") or 0))
        except (TypeError, ValueError):
            continue
    if not highs:
        return None, None
    return max(highs) * total_supply, min(lows) * total_supply


def merge_peak_low(
    peak_rpc: float,
    low_rpc: float,
    peak_gmgn: Optional[float],
    low_gmgn: Optional[float],
    tolerance_pct: float = 25.0,
) -> dict[str, Any]:
    """Combine RPC and GMGN; flag large divergence on peak (and optionally low)."""
    out: dict[str, Any] = {
        "peak_mcap_usd": peak_rpc,
        "low_mcap_usd": low_rpc,
        "peak_mcap_gmgn": peak_gmgn,
        "low_mcap_gmgn": low_gmgn,
        "peak_mcap_hybrid": peak_rpc,
        "low_mcap_hybrid": low_rpc,
        "discrepancy": False,
    }
    if peak_gmgn is not None and peak_gmgn > 0:
        out["peak_mcap_hybrid"] = max(peak_rpc, peak_gmgn)
        if peak_rpc > 0:
            d = abs(peak_gmgn - peak_rpc) / peak_rpc * 100.0
            if d > tolerance_pct:
                out["discrepancy"] = True
                out["discrepancy_peak_pct"] = d
    if low_gmgn is not None and low_gmgn > 0:
        out["low_mcap_hybrid"] = min(low_rpc, low_gmgn) if low_rpc > 0 else low_gmgn
        if low_rpc > 0:
            d_low = abs(low_gmgn - low_rpc) / low_rpc * 100.0
            if d_low > tolerance_pct:
                out["discrepancy"] = True
                out["discrepancy_low_pct"] = d_low
    return out


def gmgn_mcap_range_for_window(
    chain: str,
    address: str,
    our_entry_sec: int,
    end_sec: int,
    total_supply: float,
    resolution: str = "1m",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple[Optional[float], Optional[float], list[dict[str, Any]]]:
    """
    Fetch K-line for [our_entry_ms, end_ms], filter candles overlapping the window,
    return (peak_mcap_usd, low_mcap_usd, filtered_candles).
    """
    from_ms = max(0, our_entry_sec * 1000)
    to_ms = max(from_ms + 1, end_sec * 1000)
    candles = token_kline(
        chain,
        address.lower(),
        resolution,
        from_ms=from_ms,
        to_ms=to_ms,
        api_key=api_key,
        base_url=base_url,
    )
    filt = filter_candles_in_window(candles, our_entry_sec, end_sec, resolution)
    peak, low = candles_to_mcap_range_usd(filt, total_supply)
    return peak, low, filt
