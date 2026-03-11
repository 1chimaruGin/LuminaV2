"""
Market data API routes — tickers, funding rates, open interest,
liquidations, order flow, support/resistance, heatmap, OHLCV.
"""

import asyncio
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Query

from app.services.exchange import (
    fetch_all_funding_rates,
    fetch_all_tickers,
    fetch_funding_rates,
    fetch_ohlcv,
    fetch_open_interest_batch,
    fetch_order_book,
    fetch_recent_trades,
    fetch_tickers,
)
from app.db.memcache import cache_get, cache_set

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["Market"])

_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH")

def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol to ccxt format: BTC/USDT.
    Handles: BTCUSDT → BTC/USDT, BTC → BTC/USDT, BTC/USDT → BTC/USDT."""
    symbol = symbol.strip().upper()
    if "/" in symbol:
        return symbol
    # Try to split concatenated pairs like BTCUSDT
    for q in _QUOTE_SUFFIXES:
        if symbol.endswith(q) and len(symbol) > len(q):
            return f"{symbol[:-len(q)]}/{q}"
    # Single base token
    return f"{symbol}/USDT"


# ── Tickers ──────────────────────────────────────────────────────────────────

@router.get("/tickers")
async def get_tickers(
    exchange: Optional[str] = Query(None, description="Exchange ID (binance, bybit, okx). Omit for all."),
    limit: int = Query(100, ge=1, le=5000),
):
    if exchange:
        data = await fetch_tickers(exchange)
    else:
        data = await fetch_all_tickers()
    return {"data": data[:limit], "total": len(data), "exchange": exchange or "all"}


@router.get("/tickers/{symbol:path}")
async def get_ticker(
    symbol: str,
    exchange: str = Query("binance"),
):
    data = await fetch_tickers(exchange)
    # Match by base symbol (e.g., "BTC" matches "BTC/USDT:USDT")
    matches = [t for t in data if symbol.upper() in t["symbol"].upper()]
    if not matches:
        return {"data": None, "message": f"No ticker found for {symbol} on {exchange}"}
    return {"data": matches[0]}


# ── Market Overview ──────────────────────────────────────────────────────────

async def _fetch_fear_greed() -> tuple[int, str]:
    """Fetch Fear & Greed index — returns (index, label)."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1")
            if r.status_code == 200:
                d = r.json().get("data", [{}])[0]
                return int(d.get("value", 50)), d.get("value_classification", "Neutral")
    except Exception:
        pass
    return 50, "Neutral"


async def _fetch_dominance() -> tuple[float, float]:
    """Fetch BTC/ETH dominance — returns (btc%, eth%)."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get("https://api.coingecko.com/api/v3/global")
            if r.status_code == 200:
                d = r.json().get("data", {}).get("market_cap_percentage", {})
                return round(d.get("btc", 54.2), 1), round(d.get("eth", 17.8), 1)
    except Exception:
        pass
    return 54.2, 17.8


async def _build_overview() -> dict:
    """Build full overview — expensive, meant to be cached."""
    # Parallelize: tickers + fear/greed + dominance all at once
    ticker_task = fetch_all_tickers()
    fg_task = _fetch_fear_greed()
    dom_task = _fetch_dominance()

    tickers, (fear_greed_index, fear_greed_label), (btc_dominance, eth_dominance) = await asyncio.gather(
        ticker_task, fg_task, dom_task
    )

    total_volume = sum(t["volume_24h"] for t in tickers)
    btc_tickers = [t for t in tickers if t["base"] == "BTC"]
    btc_price = btc_tickers[0]["price"] if btc_tickers else 0
    approx_btc_mcap = btc_price * 19_700_000

    with_change = [t for t in tickers if t["price_change_24h"] is not None]
    gainers = sorted(with_change, key=lambda x: x["price_change_24h"], reverse=True)[:5]
    losers = sorted(with_change, key=lambda x: x["price_change_24h"])[:5]

    return {
        "total_market_cap": approx_btc_mcap,
        "total_volume_24h": total_volume,
        "btc_dominance": btc_dominance,
        "eth_dominance": eth_dominance,
        "fear_greed_index": fear_greed_index,
        "fear_greed_label": fear_greed_label,
        "active_pairs": len(tickers),
        "exchanges_count": 8,
        "chains_count": 12,
        "top_gainers": gainers,
        "top_losers": losers,
    }


@router.get("/overview")
async def get_market_overview():
    # Return cached overview instantly (built by background task)
    cached = await cache_get("market:overview")
    if cached:
        return cached

    # First request — build it now, cache for 5 minutes
    overview = await _build_overview()
    await cache_set("market:overview", overview, ttl=300)
    return overview


# ── Funding Rates ────────────────────────────────────────────────────────────

@router.get("/funding")
async def get_funding_rates(
    exchange: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    if exchange:
        data = await fetch_funding_rates(exchange)
    else:
        data = await fetch_all_funding_rates()
    return {"data": data[:limit], "total": len(data)}


@router.get("/funding/{symbol}")
async def get_funding_rate(symbol: str, exchange: str = Query("binance")):
    data = await fetch_funding_rates(exchange)
    matches = [f for f in data if symbol.upper() in f["symbol"].upper()]
    if not matches:
        return {"data": None, "message": f"No funding rate for {symbol}"}
    return {"data": matches[0]}


# ── Open Interest ────────────────────────────────────────────────────────────

@router.get("/open-interest")
async def get_open_interest(
    exchange: str = Query("binance"),
    symbols: Optional[str] = Query(None, description="Comma-separated symbols"),
):
    # Try pre-warmed cache first for default binance batch
    if exchange == "binance" and not symbols:
        cached = await cache_get("oi:binance:batch")
        if cached:
            return {"data": cached, "total": len(cached)}

    symbol_list = symbols.split(",") if symbols else None
    data = await fetch_open_interest_batch(exchange, symbol_list)
    return {"data": data, "total": len(data)}


# ── Order Flow / Order Book ──────────────────────────────────────────────────

@router.get("/order-flow/{symbol:path}")
async def get_order_flow(
    symbol: str,
    exchange: str = Query("binance"),
):
    symbol = _normalize_symbol(symbol)

    ob = await fetch_order_book(exchange, symbol)
    if not ob:
        return {"data": None, "message": "Could not fetch order book"}
    return {"data": ob}


# ── Whale Trades ─────────────────────────────────────────────────────────────

@router.get("/whale-trades-all")
async def get_all_whale_trades(
    limit: int = Query(100, ge=1, le=500),
):
    """Return pre-cached whale trades across top symbols — instant response."""
    cached = await cache_get("whale:all")
    if cached:
        return {"data": cached[:limit], "total": len(cached), "cached": True}
    return {"data": [], "total": 0, "cached": False}


@router.get("/whale-trades/{symbol:path}")
async def get_whale_trades(
    symbol: str,
    exchange: str = Query("binance"),
    min_usd: float = Query(20_000, description="Minimum USD value to qualify as whale"),
    limit: int = Query(50, ge=1, le=200),
):
    symbol = _normalize_symbol(symbol)

    trades = await fetch_recent_trades(exchange, symbol, limit=200, min_usd=min_usd)
    return {"data": trades[:limit], "total": len(trades)}


# ── OHLCV / Candles ─────────────────────────────────────────────────────────

@router.get("/ohlcv/{symbol:path}")
async def get_ohlcv(
    symbol: str,
    exchange: str = Query("binance"),
    timeframe: str = Query("1h", description="1m, 5m, 15m, 1h, 4h, 1d"),
    limit: int = Query(100, ge=1, le=1000),
):
    symbol = _normalize_symbol(symbol)

    candles = await fetch_ohlcv(exchange, symbol, timeframe, limit)
    return {"data": candles, "total": len(candles)}
