"""
Exchange data service using ccxt for multi-exchange support.
Fetches tickers, funding rates, open interest, and order book data.
"""

import asyncio
import logging
from typing import Any, Optional

import ccxt.async_support as ccxt

from app.core.config import get_settings
from app.db.memcache import cache_get, cache_set

logger = logging.getLogger(__name__)
settings = get_settings()

# Supported exchanges — CEX via ccxt + Hyperliquid DEX
EXCHANGE_IDS = ["binance", "bybit", "okx", "gate", "kucoin", "mexc", "bitget", "hyperliquid"]

# Exchange instance pool
_exchanges: dict[str, ccxt.Exchange] = {}


# ccxt exchange id mapping (some need different ids)
_CCXT_ID_MAP = {
    "gate": "gateio",
    "hyperliquid": "hyperliquid",
}


def _get_exchange(exchange_id: str, market_type: str = "swap") -> ccxt.Exchange:
    cache_key = f"{exchange_id}:{market_type}"
    if cache_key not in _exchanges:
        ccxt_id = _CCXT_ID_MAP.get(exchange_id, exchange_id)
        cls = getattr(ccxt, ccxt_id, None)
        if cls is None:
            raise ValueError(f"Unsupported exchange: {exchange_id} (ccxt id: {ccxt_id})")
        config: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": market_type},
        }
        # Attach API keys if available
        if exchange_id == "binance" and settings.BINANCE_API_KEY:
            config["apiKey"] = settings.BINANCE_API_KEY
            config["secret"] = settings.BINANCE_API_SECRET
        elif exchange_id == "bybit" and settings.BYBIT_API_KEY:
            config["apiKey"] = settings.BYBIT_API_KEY
            config["secret"] = settings.BYBIT_API_SECRET
        elif exchange_id == "okx" and settings.OKX_API_KEY:
            config["apiKey"] = settings.OKX_API_KEY
            config["secret"] = settings.OKX_API_SECRET
            config["password"] = settings.OKX_PASSPHRASE

        _exchanges[cache_key] = cls(config)
    return _exchanges[cache_key]


async def close_exchanges():
    for ex in _exchanges.values():
        await ex.close()
    _exchanges.clear()


# ── Tickers ──────────────────────────────────────────────────────────────────

async def fetch_tickers(
    exchange_id: str = "binance",
    symbols: Optional[list[str]] = None,
) -> list[dict]:
    cache_key = f"tickers:{exchange_id}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        ex = _get_exchange(exchange_id)
        raw = await ex.fetch_tickers(symbols)
        tickers = []
        for symbol, t in raw.items():
            if "/USDT" not in symbol and "/USD" not in symbol:
                continue
            base = t.get("base") or symbol.split("/")[0]
            quote = t.get("quote") or symbol.split("/")[-1].split(":")[0]
            tickers.append({
                "symbol": symbol,
                "base": base,
                "quote": quote,
                "price": t.get("last") or 0,
                "price_change_24h": t.get("percentage") or 0,
                "volume_24h": t.get("quoteVolume") or 0,
                "high_24h": t.get("high") or 0,
                "low_24h": t.get("low") or 0,
                "market_cap": None,
                "exchange": exchange_id,
                "timestamp": t.get("datetime"),
            })
        # Sort by volume
        tickers.sort(key=lambda x: x["volume_24h"], reverse=True)
        await cache_set(cache_key, tickers, ttl=90)
        return tickers
    except Exception as e:
        logger.error(f"Error fetching tickers from {exchange_id}: {e}")
        return []


async def fetch_all_tickers() -> list[dict]:
    cache_key = "tickers:all"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    tasks = [fetch_tickers(eid) for eid in EXCHANGE_IDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    combined = []
    for r in results:
        if isinstance(r, list):
            combined.extend(r)

    combined.sort(key=lambda x: x["volume_24h"], reverse=True)
    await cache_set(cache_key, combined, ttl=120)
    return combined


# ── Funding Rates ────────────────────────────────────────────────────────────

async def fetch_funding_rates(exchange_id: str = "binance") -> list[dict]:
    cache_key = f"funding:{exchange_id}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        ex = _get_exchange(exchange_id)
        rates = []

        if hasattr(ex, "fetch_funding_rates"):
            raw = await ex.fetch_funding_rates()
            for symbol, fr in raw.items():
                rate = fr.get("fundingRate") or 0
                rates.append({
                    "symbol": symbol,
                    "exchange": exchange_id,
                    "rate": rate,
                    "predicted_rate": fr.get("nextFundingRate"),
                    "next_funding_time": fr.get("fundingDatetime"),
                    "annualized": rate * 3 * 365 * 100,  # 8h intervals → annual %
                    "timestamp": fr.get("datetime"),
                })

        rates.sort(key=lambda x: abs(x["rate"]), reverse=True)
        await cache_set(cache_key, rates, ttl=120)
        return rates
    except Exception as e:
        logger.error(f"Error fetching funding rates from {exchange_id}: {e}")
        return []


async def fetch_all_funding_rates() -> list[dict]:
    cache_key = "funding:all"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    tasks = [fetch_funding_rates(eid) for eid in EXCHANGE_IDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    combined = []
    for r in results:
        if isinstance(r, list):
            combined.extend(r)

    combined.sort(key=lambda x: abs(x.get("rate", 0)), reverse=True)
    await cache_set(cache_key, combined, ttl=120)
    return combined


# ── Open Interest ────────────────────────────────────────────────────────────

async def fetch_open_interest(
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT:USDT",
) -> Optional[dict]:
    cache_key = f"oi:{exchange_id}:{symbol}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        ex = _get_exchange(exchange_id)
        if not hasattr(ex, "fetch_open_interest"):
            return None

        oi = await ex.fetch_open_interest(symbol)
        result = {
            "symbol": symbol,
            "exchange": exchange_id,
            "open_interest": oi.get("openInterestAmount") or 0,
            "open_interest_usd": oi.get("openInterestValue") or 0,
            "long_short_ratio": None,
            "timestamp": oi.get("datetime"),
        }
        await cache_set(cache_key, result, ttl=30)
        return result
    except Exception as e:
        logger.error(f"Error fetching OI for {symbol} from {exchange_id}: {e}")
        return None


async def fetch_open_interest_batch(
    exchange_id: str = "binance",
    symbols: Optional[list[str]] = None,
) -> list[dict]:
    if not symbols:
        symbols = [
            "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
            "DOGE/USDT:USDT", "XRP/USDT:USDT", "ARB/USDT:USDT",
            "AVAX/USDT:USDT", "LINK/USDT:USDT", "OP/USDT:USDT",
            "MATIC/USDT:USDT",
        ]

    tasks = [fetch_open_interest(exchange_id, s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


# ── Order Book (for order flow approximation) ───────────────────────────────

async def fetch_order_book(
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    limit: int = 50,
) -> Optional[dict]:
    cache_key = f"orderbook:{exchange_id}:{symbol}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        ex = _get_exchange(exchange_id)
        ob = await ex.fetch_order_book(symbol, limit)

        bid_volume = sum(b[1] for b in ob.get("bids", []))
        ask_volume = sum(a[1] for a in ob.get("asks", []))
        bid_price = ob["bids"][0][0] if ob.get("bids") else 0
        ask_price = ob["asks"][0][0] if ob.get("asks") else 0

        result = {
            "symbol": symbol,
            "exchange": exchange_id,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "spread": ask_price - bid_price if bid_price and ask_price else 0,
            "spread_pct": ((ask_price - bid_price) / bid_price * 100) if bid_price else 0,
            "buy_pressure": bid_volume / (bid_volume + ask_volume) * 100 if (bid_volume + ask_volume) > 0 else 50,
            "top_bids": ob.get("bids", [])[:10],
            "top_asks": ob.get("asks", [])[:10],
        }
        await cache_set(cache_key, result, ttl=5)
        return result
    except Exception as e:
        logger.error(f"Error fetching order book for {symbol} from {exchange_id}: {e}")
        return None


# ── Recent Trades (for whale detection) ──────────────────────────────────────
# Individual exchange fills are small — we aggregate consecutive same-side
# trades within a 2-second window to detect whale-level activity clusters.

async def fetch_recent_trades(
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    limit: int = 200,
    min_usd: float = 20_000,
) -> list[dict]:
    cache_key = f"trades:{exchange_id}:{symbol}:{min_usd}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        ex = _get_exchange(exchange_id, market_type="spot")
        trades = await ex.fetch_trades(symbol, limit=1000)

        if not trades:
            return []

        # Aggregate consecutive same-side trades within 2s windows
        aggregated: list[dict] = []
        current = None

        for t in trades:
            ts = t.get("timestamp") or 0
            side = t.get("side") or "buy"
            cost = t.get("cost") or 0
            amount = t.get("amount") or 0
            price = t.get("price") or 0

            if current and current["side"] == side and abs(ts - current["_ts"]) < 2000:
                current["amount"] += amount
                current["usd_value"] += cost
                current["price"] = price  # use last price
                current["_ts"] = ts
                current["timestamp"] = t.get("datetime") or current["timestamp"]
            else:
                if current and current["usd_value"] >= min_usd:
                    del current["_ts"]
                    aggregated.append(current)
                current = {
                    "symbol": symbol,
                    "exchange": exchange_id,
                    "side": side,
                    "amount": amount,
                    "price": price,
                    "usd_value": cost,
                    "timestamp": t.get("datetime"),
                    "_ts": ts,
                }

        # Don't forget the last cluster
        if current and current["usd_value"] >= min_usd:
            del current["_ts"]
            aggregated.append(current)

        # Sort by value desc
        aggregated.sort(key=lambda x: x["usd_value"], reverse=True)

        await cache_set(cache_key, aggregated, ttl=60)
        return aggregated
    except Exception as e:
        logger.error(f"Error fetching trades for {symbol} from {exchange_id}: {e}")
        return []


# ── OHLCV (for charts) ──────────────────────────────────────────────────────

async def fetch_ohlcv(
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    limit: int = 100,
) -> list[dict]:
    cache_key = f"ohlcv:{exchange_id}:{symbol}:{timeframe}:{limit}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        ex = _get_exchange(exchange_id)
        raw = await ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        candles = [
            {
                "timestamp": c[0],
                "open": c[1],
                "high": c[2],
                "low": c[3],
                "close": c[4],
                "volume": c[5],
            }
            for c in raw
        ]
        await cache_set(cache_key, candles, ttl=60)
        return candles
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol} from {exchange_id}: {e}")
        return []
