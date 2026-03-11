"""
Token analysis API route — fetches real token data from DexScreener
by contract address, returns pair info, price, volume, liquidity, etc.
"""

import asyncio
import logging
from typing import Optional

import httpx
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.db.redis import cache_get, cache_set
from app.services.claude_ai import analyze_token_with_claude

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/token", tags=["Token"])

# Moralis API key — loaded from env (fallback to empty)
MORALIS_API_KEY = getattr(settings, 'MORALIS_API_KEY', '')


async def _fetch_holder_count(address: str, chain: str) -> Optional[int]:
    """Fetch holder count from Moralis (Solana) or GeckoTerminal."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if chain == "solana":
                url = f"https://solana-gateway.moralis.io/token/mainnet/{address}/analytics"
                resp = await client.get(url, headers={"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"})
                if resp.status_code == 200:
                    data = resp.json()
                    holders = data.get("totalHolders") or data.get("holderCount") or data.get("holders")
                    if holders:
                        return int(holders)
            # Fallback: GeckoTerminal token info
            gecko_chain = {"solana": "solana", "ethereum": "eth", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum"}.get(chain, chain)
            url = f"https://api.geckoterminal.com/api/v2/networks/{gecko_chain}/tokens/{address}/info"
            resp = await client.get(url, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                attrs = data.get("data", {}).get("attributes", {})
                holders = attrs.get("holders") or attrs.get("holder_count")
                if holders:
                    return int(holders)
    except Exception as e:
        logger.debug(f"Holder count fetch failed: {e}")
    return None


def _detect_chain_from_address(address: str) -> str | None:
    """Heuristic chain detection from address format."""
    if address.startswith("0x") and len(address) == 42:
        return None  # Could be any EVM chain — need DexScreener to resolve
    if len(address) >= 32 and len(address) <= 44 and not address.startswith("0x"):
        return "solana"
    return None


EVM_CHAINS_TO_TRY = ["bsc", "ethereum", "base", "arbitrum", "optimism", "polygon", "avalanche"]


@router.get("/analyze", dependencies=[Depends(rate_limit(max_requests=15, window_seconds=60))])
async def analyze_token(
    address: str = Query(..., description="Token contract address (Solana or EVM)"),
    chain: str = Query("auto", description="Chain: auto, solana, ethereum, bsc, base, arbitrum, etc."),
):
    """Fetch token data from DexScreener by contract address.
    When chain='auto', tries DexScreener's chain-agnostic search to detect the correct chain.
    Returns pair info, price, volume, liquidity, price changes, and TradingView symbol."""
    # Input validation
    if not address or len(address) < 10 or len(address) > 128:
        raise HTTPException(status_code=400, detail="Invalid address length")
    if not re.match(r'^[a-zA-Z0-9]+$', address):
        raise HTTPException(status_code=400, detail="Invalid address characters")

    # Auto-detect chain if not specified
    resolved_chain = chain
    if chain == "auto" or chain == "":
        detected = _detect_chain_from_address(address)
        if detected:
            resolved_chain = detected
        else:
            resolved_chain = "auto"  # Will try multi-chain search below

    cache_key = f"token:analyze:{resolved_chain}:{address}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    try:
        pairs = []
        async with httpx.AsyncClient(timeout=12) as client:
            if resolved_chain == "auto":
                # Try DexScreener chain-agnostic search: /tokens/v1/<address>
                # This searches across ALL chains
                search_url = f"https://api.dexscreener.com/tokens/v1/{address}"
                resp = await client.get(search_url)
                if resp.status_code == 200:
                    pairs = resp.json()
                    if isinstance(pairs, list) and len(pairs) > 0:
                        # Detect chain from best pair
                        resolved_chain = pairs[0].get("chainId", "ethereum")
                        logger.info(f"Auto-detected chain={resolved_chain} for {address[:12]}")
                # If chain-agnostic search failed, try EVM chains sequentially
                if not pairs or not isinstance(pairs, list) or len(pairs) == 0:
                    for try_chain in EVM_CHAINS_TO_TRY:
                        url = f"https://api.dexscreener.com/tokens/v1/{try_chain}/{address}"
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            result = resp.json()
                            if isinstance(result, list) and len(result) > 0:
                                pairs = result
                                resolved_chain = try_chain
                                logger.info(f"Found token on {try_chain} via sequential search")
                                break
            else:
                url = f"https://api.dexscreener.com/tokens/v1/{resolved_chain}/{address}"
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {"error": f"DexScreener returned {resp.status_code}", "pairs": [], "token": None}
                pairs = resp.json()

            if not isinstance(pairs, list) or len(pairs) == 0:
                return {"error": "No pairs found for this token on any chain", "pairs": [], "token": None}

        # Fetch holder count in parallel (use resolved chain)
        holder_task = asyncio.create_task(_fetch_holder_count(address, resolved_chain))

        # Await holder count (ran in parallel with DexScreener fetch)
        holder_count = await holder_task

        # Sort pairs by volume (highest first) to pick the best one
        pairs.sort(key=lambda p: float(p.get("volume", {}).get("h24", 0) or 0), reverse=True)
        best = pairs[0]

        base = best.get("baseToken", {})
        quote = best.get("quoteToken", {})
        info = best.get("info", {})
        volume = best.get("volume", {})
        price_change = best.get("priceChange", {})
        liquidity = best.get("liquidity", {})
        txns = best.get("txns", {})

        dex_id = best.get("dexId", "")
        pair_address = best.get("pairAddress", "")
        chain_id = best.get("chainId", "")

        websites = info.get("websites", [])
        socials = info.get("socials", [])

        token_data = {
            "address": base.get("address", address),
            "symbol": base.get("symbol", ""),
            "name": base.get("name", ""),
            "logo": info.get("imageUrl", ""),
            "header": info.get("header", ""),
            "price_usd": float(best.get("priceUsd", 0) or 0),
            "price_native": float(best.get("priceNative", 0) or 0),
            "price_change_5m": float(price_change.get("m5", 0) or 0),
            "price_change_1h": float(price_change.get("h1", 0) or 0),
            "price_change_6h": float(price_change.get("h6", 0) or 0),
            "price_change_24h": float(price_change.get("h24", 0) or 0),
            "volume_5m": float(volume.get("m5", 0) or 0),
            "volume_1h": float(volume.get("h1", 0) or 0),
            "volume_6h": float(volume.get("h6", 0) or 0),
            "volume_24h": float(volume.get("h24", 0) or 0),
            "liquidity_usd": float(liquidity.get("usd", 0) or 0),
            "liquidity_base": float(liquidity.get("base", 0) or 0),
            "liquidity_quote": float(liquidity.get("quote", 0) or 0),
            "fdv": float(best.get("fdv", 0) or 0),
            "market_cap": float(best.get("marketCap", 0) or 0),
            "pair_created_at": best.get("pairCreatedAt", 0),
            "txns_24h_buys": txns.get("h24", {}).get("buys", 0),
            "txns_24h_sells": txns.get("h24", {}).get("sells", 0),
            "txns_1h_buys": txns.get("h1", {}).get("buys", 0),
            "txns_1h_sells": txns.get("h1", {}).get("sells", 0),
            "holder_count": holder_count,
            "dex_id": dex_id,
            "pair_address": pair_address,
            "chain_id": chain_id,
            "quote_token": {
                "symbol": quote.get("symbol", ""),
                "name": quote.get("name", ""),
                "address": quote.get("address", ""),
            },
            "websites": websites,
            "socials": socials,
            "dex_url": best.get("url", ""),
        }

        # Build top pairs summary (top 5 by volume)
        top_pairs = []
        for p in pairs[:5]:
            pb = p.get("baseToken", {})
            pq = p.get("quoteToken", {})
            pv = p.get("volume", {})
            top_pairs.append({
                "pair_address": p.get("pairAddress", ""),
                "dex": p.get("dexId", ""),
                "base_symbol": pb.get("symbol", ""),
                "quote_symbol": pq.get("symbol", ""),
                "price_usd": float(p.get("priceUsd", 0) or 0),
                "volume_24h": float(pv.get("h24", 0) or 0),
                "liquidity_usd": float(p.get("liquidity", {}).get("usd", 0) or 0),
            })

        result = {
            "token": token_data,
            "pairs": top_pairs,
            "total_pairs": len(pairs),
        }

        await cache_set(cache_key, result, ttl=30)
        return result

    except Exception as e:
        logger.error(f"Token analysis error for {address}: {e}")
        return {"error": str(e), "pairs": [], "token": None}


class AIAnalysisRequest(BaseModel):
    token_data: dict
    wallets: list[dict] = []
    candle_summary: dict = {}
    flow_summary: dict = {}


@router.post("/ai-analysis")
async def get_ai_analysis(req: AIAnalysisRequest):
    """Generate Claude AI-powered trading analysis for a token."""
    result = await analyze_token_with_claude(
        token_data=req.token_data,
        wallets=req.wallets,
        candle_summary=req.candle_summary,
        flow_summary=req.flow_summary,
    )
    if result is None:
        return {"error": "AI analysis unavailable", "analysis": None}
    return {"analysis": result}
