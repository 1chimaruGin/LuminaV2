"""
Investigate API — surface top wallets that caused a price move.

Flow:
1. GET /investigate/ohlcv  → fetch OHLCV candles for a token pair (DexScreener)
2. POST /investigate/wallets → given a token + timestamp window, fetch swaps
   from Moralis, group by wallet, rank by USD impact.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.redis import cache_get, cache_set

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/investigate", tags=["Investigate"])

# ── API Keys — loaded from .env ──────────────────────────────────────────────
MORALIS_API_KEY = settings.MORALIS_API_KEY
THEGRAPH_API_KEY = getattr(settings, 'THEGRAPH_API_KEY', '')

# Moralis chain mapping
MORALIS_CHAIN_MAP = {
    "solana": "solana",
    "ethereum": "eth",
    "bsc": "bsc",
    "base": "base",
    "arbitrum": "arbitrum",
    "polygon": "polygon",
}


# ── OHLCV endpoint (DexScreener) ─────────────────────────────────────────────

@router.get("/ohlcv")
async def get_ohlcv(
    pair_address: str = Query(..., description="DEX pair address"),
    chain: str = Query("solana", description="Chain"),
    timeframe: str = Query("5m", description="Candle timeframe: 1m, 5m, 15m, 1h, 4h"),
):
    """Fetch OHLCV candle data for a token pair from DexScreener."""
    cache_key = f"investigate:ohlcv:{chain}:{pair_address}:{timeframe}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # DexScreener doesn't have a public OHLCV API, so we use their
            # token page API + bars endpoint
            # Alternative: use GeckoTerminal OHLCV API
            url = f"https://api.geckoterminal.com/api/v2/networks/{_gecko_chain(chain)}/pools/{pair_address}/ohlcv/{_gecko_tf(timeframe)}"
            params = {"aggregate": _gecko_agg(timeframe), "limit": "200", "currency": "usd"}
            resp = await client.get(url, params=params, headers={"Accept": "application/json"})

            if resp.status_code != 200:
                logger.warning(f"GeckoTerminal OHLCV {resp.status_code}: {resp.text[:200]}")
                return {"candles": [], "error": f"GeckoTerminal returned {resp.status_code}"}

            data = resp.json()
            ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])

            candles = []
            for c in ohlcv_list:
                if len(c) < 6:
                    continue
                candles.append({
                    "ts": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                })

            # GeckoTerminal returns newest first, reverse to oldest first
            candles.sort(key=lambda x: x["ts"])

            result = {"candles": candles, "pair_address": pair_address, "chain": chain, "timeframe": timeframe}
            await cache_set(cache_key, result, ttl=30)
            return result

    except Exception as e:
        logger.error(f"OHLCV fetch error: {e}")
        return {"candles": [], "error": str(e)}


def _gecko_chain(chain: str) -> str:
    return {"solana": "solana", "ethereum": "eth", "bsc": "bsc", "base": "base",
            "arbitrum": "arbitrum", "polygon": "polygon_pos"}.get(chain, chain)


def _gecko_tf(tf: str) -> str:
    """Map timeframe to GeckoTerminal period."""
    if tf in ("1m", "3m", "5m", "15m", "30m"):
        return "minute"
    if tf in ("1h", "4h"):
        return "hour"
    if tf in ("1W", "1w"):
        return "day"  # aggregate=7 for weekly
    if tf in ("1M", "1mo"):
        return "day"  # aggregate=30 for monthly
    return "day"


def _gecko_agg(tf: str) -> str:
    """Map timeframe to GeckoTerminal aggregate value."""
    return {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "1", "4h": "4", "1d": "1", "1D": "1", "1W": "7", "1w": "7", "1M": "30", "1mo": "30"}.get(tf, "5")


# ── Wallet Investigation endpoint ────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    token_address: str
    pair_address: str
    chain: str = "solana"
    timestamp: int  # Unix seconds — center of the window
    window_minutes: int = 10  # ±N minutes around timestamp
    token_symbol: str = ""
    token_name: str = ""


@router.post("/wallets")
async def investigate_wallets(req: InvestigateRequest):
    """Given a token + timestamp, find top wallets that caused the move.
    Uses Moralis Token Swaps API for Solana, EVM token transfers for others."""

    cache_key = f"investigate:wallets:{req.chain}:{req.token_address}:{req.timestamp}:{req.window_minutes}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    ts_start = req.timestamp - req.window_minutes * 60
    ts_end = req.timestamp + req.window_minutes * 60

    try:
        if req.chain == "solana":
            wallets = await _fetch_solana_swaps(req.token_address, req.pair_address, ts_start, ts_end)
        else:
            wallets = await _fetch_evm_swaps(req.token_address, req.pair_address, req.chain, ts_start, ts_end)

        result = {
            "wallets": wallets,
            "token_address": req.token_address,
            "pair_address": req.pair_address,
            "chain": req.chain,
            "timestamp": req.timestamp,
            "window_minutes": req.window_minutes,
            "window_start": ts_start,
            "window_end": ts_end,
            "total_wallets": len(wallets),
        }
        await cache_set(cache_key, result, ttl=60)
        return result

    except Exception as e:
        logger.error(f"Investigate error: {e}")
        return {"wallets": [], "error": str(e)}


async def _fetch_solana_swaps(token_address: str, pair_address: str, ts_start: int, ts_end: int) -> list[dict]:
    """Fetch Solana token swaps via Moralis Solana API."""
    wallets: dict[str, dict] = {}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # Moralis Solana token swaps — get swaps for a pair
            # Try the pair swaps endpoint first
            headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}
            url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/swaps"
            params = {"order": "DESC", "limit": "100"}
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code != 200:
                logger.warning(f"Moralis Solana swaps {resp.status_code}: {resp.text[:300]}")
                # Fallback: try token transfers
                return await _fetch_solana_transfers_fallback(token_address, ts_start, ts_end)

            data = resp.json()
            swaps = data if isinstance(data, list) else data.get("result", data.get("swaps", []))
            if not isinstance(swaps, list):
                swaps = []

            logger.info(f"Moralis returned {len(swaps)} swaps for {token_address}")

            for swap in swaps:
                # Parse swap data — Moralis format varies
                block_ts = _parse_timestamp(swap)
                if block_ts and (block_ts < ts_start or block_ts > ts_end):
                    continue

                wallet_addr = (swap.get("walletAddress")
                               or swap.get("wallet_address")
                               or swap.get("owner")
                               or swap.get("from_address")
                               or swap.get("buyer", ""))
                if not wallet_addr:
                    continue

                # Determine buy/sell
                bought_token = swap.get("bought", {}) if isinstance(swap.get("bought"), dict) else {}
                sold_token = swap.get("sold", {}) if isinstance(swap.get("sold"), dict) else {}
                bought_symbol = bought_token.get("symbol", "") or bought_token.get("token", "")
                sold_symbol = sold_token.get("symbol", "") or sold_token.get("token", "")

                bought_usd = float(bought_token.get("usdAmount", 0) or bought_token.get("valueUsd", 0) or 0)
                sold_usd = float(sold_token.get("usdAmount", 0) or sold_token.get("valueUsd", 0) or 0)
                usd_value = max(bought_usd, sold_usd)

                # Determine side relative to our token
                is_buy = _is_token_buy(token_address, bought_token, sold_token)
                side = "buy" if is_buy else "sell"

                # Also try flat fields
                if usd_value == 0:
                    usd_value = abs(float(swap.get("totalValueUsd", 0) or swap.get("usd_value", 0) or swap.get("valueUsd", 0) or 0))
                if usd_value == 0:
                    usd_value = abs(float(swap.get("amountUsd", 0) or 0))

                tx_hash = swap.get("transactionHash", swap.get("signature", swap.get("txHash", "")))

                if wallet_addr not in wallets:
                    wallets[wallet_addr] = {
                        "address": wallet_addr,
                        "short_addr": f"{wallet_addr[:4]}…{wallet_addr[-4:]}" if len(wallet_addr) > 10 else wallet_addr,
                        "buys": 0, "sells": 0,
                        "buy_usd": 0, "sell_usd": 0,
                        "net_usd": 0,
                        "first_tx": block_ts or 0,
                        "last_tx": block_ts or 0,
                        "txns": [],
                    }

                w = wallets[wallet_addr]
                if side == "buy":
                    w["buys"] += 1
                    w["buy_usd"] += usd_value
                    w["net_usd"] += usd_value
                else:
                    w["sells"] += 1
                    w["sell_usd"] += usd_value
                    w["net_usd"] -= usd_value

                if block_ts:
                    w["first_tx"] = min(w["first_tx"] or block_ts, block_ts)
                    w["last_tx"] = max(w["last_tx"], block_ts)

                w["txns"].append({
                    "side": side,
                    "usd_value": round(usd_value, 2),
                    "timestamp": block_ts,
                    "tx_hash": tx_hash[:16] + "..." if tx_hash and len(tx_hash) > 16 else tx_hash,
                })

    except Exception as e:
        logger.error(f"Solana swap fetch error: {e}")

    return _rank_wallets(wallets)


async def _fetch_solana_transfers_fallback(token_address: str, ts_start: int, ts_end: int) -> list[dict]:
    """Fallback: use Moralis token transfers if swaps endpoint doesn't work."""
    wallets: dict[str, dict] = {}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}
            # Try the SPL transfers endpoint
            url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/transfers"
            params = {"order": "DESC", "limit": "100"}
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code != 200:
                logger.warning(f"Moralis Solana transfers fallback {resp.status_code}")
                return []

            data = resp.json()
            transfers = data if isinstance(data, list) else data.get("result", [])
            if not isinstance(transfers, list):
                return []

            for tx in transfers:
                block_ts = _parse_timestamp(tx)
                if block_ts and (block_ts < ts_start or block_ts > ts_end):
                    continue

                from_addr = tx.get("fromAddress", tx.get("from_address", ""))
                to_addr = tx.get("toAddress", tx.get("to_address", ""))
                amount = float(tx.get("amount", 0) or tx.get("value", 0) or 0)

                # Seller
                if from_addr and from_addr != "0x0000000000000000000000000000000000000000":
                    _add_transfer_to_wallets(wallets, from_addr, "sell", amount, block_ts, tx)
                # Buyer
                if to_addr and to_addr != "0x0000000000000000000000000000000000000000":
                    _add_transfer_to_wallets(wallets, to_addr, "buy", amount, block_ts, tx)

    except Exception as e:
        logger.error(f"Solana transfers fallback error: {e}")

    return _rank_wallets(wallets)


async def _fetch_evm_swaps(token_address: str, pair_address: str, chain: str, ts_start: int, ts_end: int) -> list[dict]:
    """Fetch EVM token swaps via Moralis."""
    wallets: dict[str, dict] = {}
    moralis_chain = MORALIS_CHAIN_MAP.get(chain, "eth")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}

            # Moralis EVM token transfers
            url = f"https://deep-index.moralis.io/api/v2.2/erc20/{token_address}/transfers"
            params = {
                "chain": moralis_chain,
                "order": "DESC",
                "limit": "100",
                "from_date": _ts_to_iso(ts_start),
                "to_date": _ts_to_iso(ts_end),
            }
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code != 200:
                logger.warning(f"Moralis EVM transfers {resp.status_code}: {resp.text[:300]}")
                return []

            data = resp.json()
            transfers = data.get("result", [])

            for tx in transfers:
                block_ts = _parse_timestamp(tx)
                from_addr = tx.get("from_address", "")
                to_addr = tx.get("to_address", "")
                value_raw = float(tx.get("value", 0) or 0)
                decimals = int(tx.get("token_decimals", 18) or 18)
                amount = value_raw / (10 ** decimals)
                usd_val = float(tx.get("value_decimal", 0) or 0)

                if from_addr:
                    _add_transfer_to_wallets(wallets, from_addr, "sell", usd_val or amount, block_ts, tx)
                if to_addr:
                    _add_transfer_to_wallets(wallets, to_addr, "buy", usd_val or amount, block_ts, tx)

    except Exception as e:
        logger.error(f"EVM swap fetch error: {e}")

    return _rank_wallets(wallets)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_timestamp(obj: dict) -> Optional[int]:
    """Extract unix timestamp from various Moralis response formats."""
    for key in ("blockTimestamp", "block_timestamp", "blockTime", "timestamp", "block_time"):
        val = obj.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            # If it's in milliseconds, convert
            return int(val) if val < 1e12 else int(val / 1000)
        if isinstance(val, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return int(dt.timestamp())
            except Exception:
                pass
    return None


def _is_token_buy(token_addr: str, bought: dict, sold: dict) -> bool:
    """Determine if the swap is buying our token."""
    bought_addr = bought.get("address", bought.get("mint", "")).lower()
    sold_addr = sold.get("address", sold.get("mint", "")).lower()
    return bought_addr == token_addr.lower()


def _add_transfer_to_wallets(wallets: dict, addr: str, side: str, amount: float, ts: Optional[int], tx: dict):
    if addr not in wallets:
        wallets[addr] = {
            "address": addr,
            "short_addr": f"{addr[:4]}…{addr[-4:]}" if len(addr) > 10 else addr,
            "buys": 0, "sells": 0,
            "buy_usd": 0, "sell_usd": 0,
            "net_usd": 0,
            "first_tx": ts or 0,
            "last_tx": ts or 0,
            "txns": [],
        }
    w = wallets[addr]
    if side == "buy":
        w["buys"] += 1
        w["buy_usd"] += amount
        w["net_usd"] += amount
    else:
        w["sells"] += 1
        w["sell_usd"] += amount
        w["net_usd"] -= amount
    if ts:
        w["first_tx"] = min(w["first_tx"] or ts, ts)
        w["last_tx"] = max(w["last_tx"], ts)
    w["txns"].append({
        "side": side,
        "usd_value": round(amount, 2),
        "timestamp": ts,
        "tx_hash": (tx.get("transaction_hash", tx.get("signature", ""))[:16] + "...") if tx.get("transaction_hash") or tx.get("signature") else "",
    })


def _rank_wallets(wallets: dict) -> list[dict]:
    """Rank wallets by absolute USD impact, tag them, limit top N.
    Uses DYNAMIC thresholds based on percentiles of actual trading data
    so it works for tokens of any market cap."""
    import statistics

    # Compute volumes for dynamic thresholds
    all_vols = [w["buy_usd"] + w["sell_usd"] for w in wallets.values() if (w["buy_usd"] + w["sell_usd"]) > 0]
    all_impacts = [abs(w["net_usd"]) for w in wallets.values() if abs(w["net_usd"]) > 0]

    if len(all_vols) >= 3:
        sorted_vols = sorted(all_vols)
        sorted_impacts = sorted(all_impacts)
        p90_vol = sorted_vols[int(len(sorted_vols) * 0.90)]
        p75_vol = sorted_vols[int(len(sorted_vols) * 0.75)]
        p50_vol = sorted_vols[int(len(sorted_vols) * 0.50)]
        p90_impact = sorted_impacts[int(len(sorted_impacts) * 0.90)] if sorted_impacts else p90_vol
        p75_impact = sorted_impacts[int(len(sorted_impacts) * 0.75)] if sorted_impacts else p75_vol
        median_vol = statistics.median(all_vols)
    else:
        p90_vol = p75_vol = p50_vol = p90_impact = p75_impact = median_vol = 1000

    # Dynamic thresholds — whale = top 10%, smart = top 25%, active = top 50%
    whale_vol_t = max(p90_vol, 500)     # At least $500 to be whale
    whale_impact_t = max(p90_impact, 300)
    smart_impact_t = max(p75_impact, 200)
    bot_vol_t = max(p90_vol * 2, 1000)
    active_vol_t = max(p50_vol, 100)

    logger.info(f"Dynamic thresholds: whale_vol={whale_vol_t:.0f} whale_impact={whale_impact_t:.0f} smart={smart_impact_t:.0f} bot={bot_vol_t:.0f} active={active_vol_t:.0f} (from {len(all_vols)} wallets)")

    result = []
    for w in wallets.values():
        abs_impact = abs(w["net_usd"])
        total_vol = w["buy_usd"] + w["sell_usd"]
        w["total_volume"] = round(total_vol, 2)
        w["net_usd"] = round(w["net_usd"], 2)
        w["buy_usd"] = round(w["buy_usd"], 2)
        w["sell_usd"] = round(w["sell_usd"], 2)
        w["abs_impact"] = round(abs_impact, 2)

        # Tag using dynamic thresholds
        if total_vol >= bot_vol_t and w["buys"] > 15:
            w["tag"] = "bot"
            w["label"] = "Institutional Bot"
        elif abs_impact >= whale_impact_t and w["sells"] == 0 and w["buys"] >= 2:
            w["tag"] = "whale"
            w["label"] = "Whale Accumulator"
        elif abs_impact >= whale_impact_t and w["buys"] == 0 and w["sells"] >= 2:
            w["tag"] = "sell"
            w["label"] = "Whale Dumper"
        elif abs_impact >= whale_impact_t:
            w["tag"] = "whale"
            w["label"] = "Whale" if w["buys"] >= w["sells"] else "Whale Seller"
        elif abs_impact >= smart_impact_t and w["buys"] > w["sells"] * 2:
            w["tag"] = "smart"
            w["label"] = "Smart Money"
        elif abs_impact >= smart_impact_t and w["sells"] > w["buys"] * 2:
            w["tag"] = "sell"
            w["label"] = "Heavy Seller"
        elif total_vol >= active_vol_t:
            w["tag"] = "degen"
            w["label"] = "Active Trader"
        else:
            w["tag"] = "degen"
            w["label"] = "Trader"

        # Limit txns to latest 10
        w["txns"] = sorted(w["txns"], key=lambda t: t.get("timestamp") or 0, reverse=True)[:10]

        result.append(w)

    # Sort by absolute impact descending
    result.sort(key=lambda w: w["abs_impact"], reverse=True)
    return result[:20]  # Top 20


def _ts_to_iso(ts: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── Full-scan endpoint (auto-overlay, no click needed) ───────────────────────

class ScanRequest(BaseModel):
    token_address: str
    pair_address: str
    chain: str = "solana"
    candle_timestamps: list[int] = []  # sorted candle ts list for bucketing
    timeframe_seconds: int = 300       # candle width in seconds (5m = 300)
    timeframe: str = "5m"              # timeframe string for OHLCV cache lookup


@router.post("/scan")
async def scan_token_activity(req: ScanRequest):
    """Fetch ALL recent swaps for a token, bucket by candle timestamp,
    return per-candle buy/sell aggregates + top wallets across whole range.

    Uses three data sources:
    1. Moralis swap API (paginated, ~500 recent swaps)
    2. GeckoTerminal trades (free, ~300 trades)
    3. Big-move detection from OHLCV candles (covers ENTIRE chart range)"""

    # Short-lived result cache per timeframe
    result_key = f"investigate:scan:{req.chain}:{req.token_address}:{req.timeframe_seconds}:{len(req.candle_timestamps)}"
    cached = await cache_get(result_key)
    if cached:
        return cached

    # Long-lived swap accumulation pool (per token, independent of TF)
    pool_key = f"investigate:swappool:{req.chain}:{req.token_address}"

    try:
        # Fetch swaps from multiple sources in parallel
        if req.chain == "solana":
            moralis_task = _fetch_solana_raw_swaps(req.token_address)
        else:
            ts_min = min(req.candle_timestamps) if req.candle_timestamps else 0
            ts_max = max(req.candle_timestamps) if req.candle_timestamps else int(time.time())
            moralis_task = _fetch_evm_raw_swaps(req.token_address, req.chain, ts_min, ts_max + req.timeframe_seconds)

        gecko_task = _fetch_gecko_trades(req.pair_address, req.chain)

        # Run both fetchers in parallel
        moralis_swaps, gecko_swaps = await asyncio.gather(moralis_task, gecko_task, return_exceptions=True)
        if isinstance(moralis_swaps, Exception):
            logger.error(f"Moralis fetch failed: {moralis_swaps}")
            moralis_swaps = []
        if isinstance(gecko_swaps, Exception):
            logger.error(f"Gecko fetch failed: {gecko_swaps}")
            gecko_swaps = []

        fresh_swaps = list(moralis_swaps) + list(gecko_swaps)

        # Merge with previously cached swap pool
        pool: list[dict] = await cache_get(pool_key) or []
        seen_tx: set[str] = set()
        merged: list[dict] = []

        # Add pool swaps first (older history preserved)
        for s in pool:
            tx_id = f"{s.get('tx','')}-{s.get('wallet','')}-{s.get('ts','')}"
            if tx_id not in seen_tx:
                seen_tx.add(tx_id)
                merged.append(s)

        # Add fresh swaps (new data)
        for s in fresh_swaps:
            tx_id = f"{s.get('tx','')}-{s.get('wallet','')}-{s.get('ts','')}"
            if tx_id not in seen_tx:
                seen_tx.add(tx_id)
                merged.append(s)

        # Sort by timestamp
        merged.sort(key=lambda s: s.get("ts", 0))

        # Persist merged pool with long TTL (1 hour)
        await cache_set(pool_key, merged, ttl=3600)

        logger.info(f"Scan: {len(moralis_swaps)} moralis + {len(gecko_swaps)} gecko + {len(pool)} cached = {len(merged)} total for {req.token_address}")

        raw_swaps = merged

        # Detect big price moves from cached OHLCV data (covers ENTIRE chart)
        ohlcv_key = f"investigate:ohlcv:{req.chain}:{req.pair_address}:{req.timeframe}"
        ohlcv_cached = await cache_get(ohlcv_key)
        candles_data = ohlcv_cached.get("candles", []) if ohlcv_cached else []
        big_moves = _detect_big_moves(req.candle_timestamps, candles_data) if candles_data else []

        # Bucket swaps into candle intervals
        candle_flow = _bucket_swaps(raw_swaps, req.candle_timestamps, req.timeframe_seconds)

        # Aggregate wallets across all swaps
        wallets = _aggregate_wallets(raw_swaps, req.token_address)

        result = {
            "candle_flow": candle_flow,
            "wallets": wallets,
            "raw_swaps": raw_swaps,
            "big_moves": big_moves,
            "total_swaps": len(raw_swaps),
            "total_wallets": len(wallets),
        }
        await cache_set(result_key, result, ttl=45)
        return result

    except Exception as e:
        logger.error(f"Scan error: {e}")
        return {"candle_flow": {}, "wallets": [], "raw_swaps": [], "big_moves": [], "total_swaps": 0, "error": str(e)}


async def _fetch_solana_raw_swaps(token_address: str) -> list[dict]:
    """Fetch raw swap events from Moralis for Solana. Paginates to get up to ~500 swaps."""
    raw: list[dict] = []
    max_pages = 5
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}
            url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/swaps"
            cursor = None

            for page in range(max_pages):
                params: dict = {"order": "DESC", "limit": "100"}
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(url, headers=headers, params=params)

                if resp.status_code != 200:
                    if page == 0:
                        logger.warning(f"Moralis scan swaps {resp.status_code}: {resp.text[:300]}")
                        return await _fetch_solana_raw_transfers(token_address)
                    break

                data = resp.json()
                swaps = data if isinstance(data, list) else data.get("result", data.get("swaps", []))
                if not isinstance(swaps, list):
                    swaps = []

                if page == 0:
                    logger.info(f"Scan: Moralis returned {len(swaps)} raw swaps (page 1) for {token_address}")

                if len(swaps) == 0:
                    break

                for swap in swaps:
                    block_ts = _parse_timestamp(swap)
                    wallet_addr = (swap.get("walletAddress")
                                   or swap.get("wallet_address")
                                   or swap.get("owner")
                                   or swap.get("from_address")
                                   or swap.get("buyer", ""))
                    if not wallet_addr:
                        continue

                    bought_token = swap.get("bought", {}) if isinstance(swap.get("bought"), dict) else {}
                    sold_token = swap.get("sold", {}) if isinstance(swap.get("sold"), dict) else {}

                    bought_usd = float(bought_token.get("usdAmount", 0) or bought_token.get("valueUsd", 0) or 0)
                    sold_usd = float(sold_token.get("usdAmount", 0) or sold_token.get("valueUsd", 0) or 0)
                    usd_value = max(bought_usd, sold_usd)

                    is_buy = _is_token_buy(token_address, bought_token, sold_token)
                    side = "buy" if is_buy else "sell"

                    if usd_value == 0:
                        usd_value = abs(float(swap.get("totalValueUsd", 0) or swap.get("usd_value", 0) or swap.get("valueUsd", 0) or 0))
                    if usd_value == 0:
                        usd_value = abs(float(swap.get("amountUsd", 0) or 0))

                    raw.append({
                        "wallet": wallet_addr,
                        "side": side,
                        "usd": usd_value,
                        "ts": block_ts,
                        "tx": (swap.get("transactionHash") or swap.get("signature") or swap.get("txHash") or "")[:16],
                    })

                # Get next cursor for pagination
                next_cursor = None
                if isinstance(data, dict):
                    next_cursor = data.get("cursor") or data.get("next_cursor")
                if not next_cursor or len(swaps) < 100:
                    break
                cursor = next_cursor

            logger.info(f"Scan: total {len(raw)} raw swaps fetched for {token_address} across {min(page + 1, max_pages)} pages")

    except Exception as e:
        logger.error(f"Scan Solana raw swaps error: {e}")

    return raw


async def _fetch_solana_raw_transfers(token_address: str) -> list[dict]:
    """Fallback: raw transfers. Paginates to get up to ~500."""
    raw: list[dict] = []
    max_pages = 5
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}
            url = f"https://solana-gateway.moralis.io/token/mainnet/{token_address}/transfers"
            cursor = None

            for page in range(max_pages):
                params: dict = {"order": "DESC", "limit": "100"}
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    break
                data = resp.json()
                transfers = data if isinstance(data, list) else data.get("result", [])
                if not isinstance(transfers, list) or len(transfers) == 0:
                    break

                for tx in transfers:
                    block_ts = _parse_timestamp(tx)
                    from_addr = tx.get("fromAddress", tx.get("from_address", ""))
                    to_addr = tx.get("toAddress", tx.get("to_address", ""))
                    amount = float(tx.get("amount", 0) or tx.get("value", 0) or 0)
                    if from_addr:
                        raw.append({"wallet": from_addr, "side": "sell", "usd": amount, "ts": block_ts, "tx": ""})
                    if to_addr:
                        raw.append({"wallet": to_addr, "side": "buy", "usd": amount, "ts": block_ts, "tx": ""})

                next_cursor = None
                if isinstance(data, dict):
                    next_cursor = data.get("cursor") or data.get("next_cursor")
                if not next_cursor or len(transfers) < 100:
                    break
                cursor = next_cursor

    except Exception as e:
        logger.error(f"Scan Solana raw transfers error: {e}")
    return raw


async def _fetch_evm_raw_swaps(token_address: str, chain: str, ts_start: int, ts_end: int) -> list[dict]:
    """Fetch raw EVM token transfers for scan. Paginates to get up to ~500."""
    raw: list[dict] = []
    moralis_chain = MORALIS_CHAIN_MAP.get(chain, "eth")
    max_pages = 5
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}
            url = f"https://deep-index.moralis.io/api/v2.2/erc20/{token_address}/transfers"
            cursor = None

            for page in range(max_pages):
                params: dict = {
                    "chain": moralis_chain, "order": "DESC", "limit": "100",
                    "from_date": _ts_to_iso(ts_start), "to_date": _ts_to_iso(ts_end),
                }
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    break
                data = resp.json()
                results = data.get("result", [])
                if not results or len(results) == 0:
                    break

                for tx in results:
                    block_ts = _parse_timestamp(tx)
                    from_addr = tx.get("from_address", "")
                    to_addr = tx.get("to_address", "")
                    value_raw = float(tx.get("value", 0) or 0)
                    decimals = int(tx.get("token_decimals", 18) or 18)
                    amount = value_raw / (10 ** decimals)
                    usd_val = float(tx.get("value_decimal", 0) or 0) or amount
                    if from_addr:
                        raw.append({"wallet": from_addr, "side": "sell", "usd": usd_val, "ts": block_ts, "tx": tx.get("transaction_hash", "")[:16]})
                    if to_addr:
                        raw.append({"wallet": to_addr, "side": "buy", "usd": usd_val, "ts": block_ts, "tx": tx.get("transaction_hash", "")[:16]})

                next_cursor = data.get("cursor") or data.get("next_cursor")
                if not next_cursor or len(results) < 100:
                    break
                cursor = next_cursor

    except Exception as e:
        logger.error(f"Scan EVM raw swaps error: {e}")
    return raw


async def _fetch_gecko_trades(pair_address: str, chain: str) -> list[dict]:
    """Fetch recent trades from GeckoTerminal (free, no API key).
    Returns up to 300 trades with wallet, side, usd, ts."""
    raw: list[dict] = []
    network = _gecko_chain(chain)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pair_address}/trades"
            params = {"trade_volume_in_usd_greater_than": "100"}
            resp = await client.get(url, params=params, headers={"Accept": "application/json"})
            if resp.status_code != 200:
                logger.warning(f"GeckoTerminal trades {resp.status_code}")
                return raw
            data = resp.json()
            trades = data.get("data", [])
            for t in trades:
                attrs = t.get("attributes", {})
                block_ts = 0
                if attrs.get("block_timestamp"):
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(attrs["block_timestamp"].replace("Z", "+00:00"))
                        block_ts = int(dt.timestamp())
                    except Exception:
                        pass
                if not block_ts:
                    continue
                usd = abs(float(attrs.get("volume_in_usd", 0) or 0))
                kind = attrs.get("kind", "")  # "buy" or "sell"
                side = "buy" if kind == "buy" else "sell"
                tx_hash = attrs.get("tx_hash", "")
                from_addr = attrs.get("tx_from_address", "")
                raw.append({
                    "wallet": from_addr,
                    "side": side,
                    "usd": usd,
                    "ts": block_ts,
                    "tx": (tx_hash or "")[:16],
                })
            logger.info(f"GeckoTerminal trades: {len(raw)} for {pair_address}")
    except Exception as e:
        logger.error(f"GeckoTerminal trades error: {e}")
    return raw


def _detect_big_moves(candle_ts_list: list[int], candles_data: list[dict], percentile: float = 92) -> list[dict]:
    """Detect candles with unusually large price moves or volume spikes.
    Returns synthetic 'big_move' markers covering the entire chart range.
    candles_data: list of {ts, open, high, low, close, volume}."""
    if not candles_data or len(candles_data) < 5:
        return []

    # Calculate % move and volume for each candle
    moves = []
    for c in candles_data:
        o, cl, h, l = c.get("open", 0), c.get("close", 0), c.get("high", 0), c.get("low", 0)
        vol = c.get("volume", 0)
        if o == 0:
            continue
        pct_move = abs(cl - o) / o * 100
        range_pct = (h - l) / o * 100 if o else 0
        moves.append({"ts": c["ts"], "pct": pct_move, "range": range_pct, "vol": vol, "side": "buy" if cl >= o else "sell"})

    if not moves:
        return []

    # Find threshold at given percentile
    pct_vals = sorted([m["pct"] for m in moves])
    vol_vals = sorted([m["vol"] for m in moves if m["vol"] > 0])
    pct_threshold = pct_vals[int(len(pct_vals) * percentile / 100)] if pct_vals else 0
    vol_threshold = vol_vals[int(len(vol_vals) * percentile / 100)] if vol_vals else 0

    big: list[dict] = []
    for m in moves:
        if m["pct"] >= pct_threshold or (vol_threshold > 0 and m["vol"] >= vol_threshold):
            big.append({
                "ts": m["ts"],
                "side": m["side"],
                "pct_move": round(m["pct"], 2),
                "volume": round(m["vol"], 2),
                "type": "big_move",
            })

    return big


def _bucket_swaps(swaps: list[dict], candle_ts_list: list[int], tf_seconds: int) -> dict[str, dict]:
    """Bucket swaps into candle intervals. Key is candle timestamp (string).
    Each bucket has: buy_count, sell_count, buy_usd, sell_usd, net_usd, whale_buy, whale_sell."""
    buckets: dict[str, dict] = {}
    half_tf = tf_seconds // 2
    # Dynamic whale threshold — top 10% of swap sizes, min $200
    swap_sizes = sorted([s["usd"] for s in swaps if s.get("usd", 0) > 0])
    whale_threshold = max(swap_sizes[int(len(swap_sizes) * 0.90)], 200) if len(swap_sizes) >= 5 else 200

    for ts in candle_ts_list:
        k = str(ts)
        buckets[k] = {"buy_count": 0, "sell_count": 0, "buy_usd": 0, "sell_usd": 0,
                       "net_usd": 0, "whale_buy": 0, "whale_sell": 0, "top_wallet": "", "top_usd": 0}

    for swap in swaps:
        st = swap.get("ts")
        if st is None:
            continue
        # Find closest candle
        best_k = None
        best_dist = float("inf")
        for ts in candle_ts_list:
            dist = abs(st - ts)
            if dist < best_dist:
                best_dist = dist
                best_k = str(ts)
        if best_k is None or best_dist > tf_seconds:
            continue

        b = buckets[best_k]
        usd = swap["usd"]
        if swap["side"] == "buy":
            b["buy_count"] += 1
            b["buy_usd"] += usd
            b["net_usd"] += usd
            if usd >= whale_threshold:
                b["whale_buy"] += 1
        else:
            b["sell_count"] += 1
            b["sell_usd"] += usd
            b["net_usd"] -= usd
            if usd >= whale_threshold:
                b["whale_sell"] += 1

        if usd > b["top_usd"]:
            b["top_usd"] = usd
            b["top_wallet"] = swap["wallet"]

    # Round values
    for b in buckets.values():
        b["buy_usd"] = round(b["buy_usd"], 2)
        b["sell_usd"] = round(b["sell_usd"], 2)
        b["net_usd"] = round(b["net_usd"], 2)
        b["top_usd"] = round(b["top_usd"], 2)

    return buckets


def _aggregate_wallets(swaps: list[dict], token_address: str) -> list[dict]:
    """Aggregate all swaps into wallet-level stats (same as _rank_wallets but from raw)."""
    wallets: dict[str, dict] = {}
    for swap in swaps:
        addr = swap["wallet"]
        if addr not in wallets:
            wallets[addr] = {
                "address": addr,
                "short_addr": f"{addr[:4]}…{addr[-4:]}" if len(addr) > 10 else addr,
                "buys": 0, "sells": 0,
                "buy_usd": 0, "sell_usd": 0,
                "net_usd": 0,
                "first_tx": swap.get("ts") or 0,
                "last_tx": swap.get("ts") or 0,
                "txns": [],
            }
        w = wallets[addr]
        usd = swap["usd"]
        if swap["side"] == "buy":
            w["buys"] += 1
            w["buy_usd"] += usd
            w["net_usd"] += usd
        else:
            w["sells"] += 1
            w["sell_usd"] += usd
            w["net_usd"] -= usd
        ts = swap.get("ts")
        if ts:
            w["first_tx"] = min(w["first_tx"] or ts, ts)
            w["last_tx"] = max(w["last_tx"], ts)
        w["txns"].append({"side": swap["side"], "usd_value": round(usd, 2), "timestamp": ts, "tx_hash": swap.get("tx", "")})

    return _rank_wallets(wallets)


# ── Wallet-Token Trades endpoint (for chart overlay) ─────────────────────────

MORALIS_CHAIN_MAP_WTT = {"bsc": "0x38", "ethereum": "0x1", "arbitrum": "0xa4b1", "base": "0x2105", "optimism": "0xa", "polygon": "0x89", "avalanche": "0xa86a"}


class WalletTokenTradesRequest(BaseModel):
    wallet_address: str
    token_address: str
    chain: str = "bsc"


@router.post("/wallet-token-trades")
async def get_wallet_token_trades(req: WalletTokenTradesRequest):
    """Fetch a specific wallet's swap history for a specific token.
    Returns timestamped buy/sell events for chart overlay."""

    cache_key = f"investigate:wtt:{req.chain}:{req.wallet_address[:10]}:{req.token_address[:10]}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    trades: list[dict] = []
    moralis_chain = MORALIS_CHAIN_MAP_WTT.get(req.chain)
    if not moralis_chain:
        return {"trades": [], "error": f"Chain {req.chain} not supported for wallet trades"}

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}
            cursor = None
            token_lower = req.token_address.lower()

            for page in range(10):  # max 10 pages
                url = f"https://deep-index.moralis.io/api/v2.2/wallets/{req.wallet_address}/swaps"
                params: dict = {"chain": moralis_chain, "limit": "100", "order": "DESC"}
                if cursor:
                    params["cursor"] = cursor
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    logger.warning(f"Moralis wallet-token-trades {resp.status_code}")
                    break

                data = resp.json()
                swaps = data.get("result", [])
                if not swaps:
                    break

                for swap in swaps:
                    bought = swap.get("bought", {}) or {}
                    sold = swap.get("sold", {}) or {}
                    bought_addr = (bought.get("address") or "").lower()
                    sold_addr = (sold.get("address") or "").lower()

                    # Only include swaps involving our target token
                    if token_lower not in (bought_addr, sold_addr):
                        continue

                    tx_type = swap.get("transactionType", "")
                    is_buy = tx_type == "buy" or bought_addr == token_lower
                    ts_str = swap.get("blockTimestamp") or swap.get("block_timestamp") or ""
                    ts = 0
                    if ts_str:
                        try:
                            from datetime import datetime as _dt
                            dt = _dt.fromisoformat(ts_str.replace("Z", "+00:00"))
                            ts = int(dt.timestamp())
                        except Exception:
                            pass

                    if is_buy:
                        usd = float(bought.get("usdAmount") or bought.get("valueUsd") or 0)
                        amount = float(bought.get("amount") or 0)
                        symbol = bought.get("symbol") or bought.get("token") or ""
                    else:
                        usd = float(sold.get("usdAmount") or sold.get("valueUsd") or 0)
                        amount = float(sold.get("amount") or 0)
                        symbol = sold.get("symbol") or sold.get("token") or ""

                    trades.append({
                        "ts": ts,
                        "side": "buy" if is_buy else "sell",
                        "usd": round(usd, 2),
                        "amount": amount,
                        "symbol": symbol,
                        "tx_hash": swap.get("transactionHash", ""),
                    })

                cursor = data.get("cursor")
                if not cursor:
                    break

        trades.sort(key=lambda t: t["ts"])
        result = {
            "trades": trades,
            "wallet_address": req.wallet_address,
            "token_address": req.token_address,
            "chain": req.chain,
            "total_trades": len(trades),
        }
        await cache_set(cache_key, result, ttl=120)
        return result

    except Exception as e:
        logger.error(f"Wallet-token-trades error: {e}")
        return {"trades": [], "error": str(e)}
