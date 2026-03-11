"""
Claude AI analysis service — generates trading narratives, risk assessments,
and perp/spot signals for tokens using Anthropic's Claude API.
"""

import json
import logging
from typing import Optional

import httpx

from app.core.config import get_settings
from app.db.redis import cache_get, cache_set

logger = logging.getLogger(__name__)
settings = get_settings()

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-3-haiku-20240307"


async def analyze_token_with_claude(
    token_data: dict,
    wallets: list[dict],
    candle_summary: dict,
    flow_summary: dict,
) -> Optional[dict]:
    """Call Claude API with token + wallet + chart data to generate AI analysis.
    Returns structured JSON with narrative, risk assessment, and trading signals."""

    if not settings.CLAUDE_API_KEY:
        logger.warning("CLAUDE_API_KEY not set, skipping AI analysis")
        return None

    # Build cache key from token address + chain
    addr = token_data.get("address", "")
    chain = token_data.get("chain_id", "unknown")
    cache_key = f"claude:token:{chain}:{addr}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # Build context for Claude
    symbol = token_data.get("symbol", "UNKNOWN")
    name = token_data.get("name", "")
    price = token_data.get("price_usd", 0)
    mcap = token_data.get("market_cap", 0)
    fdv = token_data.get("fdv", 0)
    liq = token_data.get("liquidity_usd", 0)
    vol_24h = token_data.get("volume_24h", 0)
    holders = token_data.get("holder_count")
    pc_5m = token_data.get("price_change_5m", 0)
    pc_1h = token_data.get("price_change_1h", 0)
    pc_6h = token_data.get("price_change_6h", 0)
    pc_24h = token_data.get("price_change_24h", 0)
    txns_buy = token_data.get("txns_24h_buys", 0)
    txns_sell = token_data.get("txns_24h_sells", 0)

    # Wallet summary
    whale_wallets = [w for w in wallets if w.get("tag") in ("whale", "smart")]
    seller_wallets = [w for w in wallets if w.get("tag") == "sell"]
    total_whale_buy = sum(w.get("buy_usd", 0) for w in whale_wallets)
    total_whale_sell = sum(w.get("sell_usd", 0) for w in whale_wallets)
    total_dump = sum(w.get("sell_usd", 0) for w in seller_wallets)

    # Candle summary
    candle_count = candle_summary.get("count", 0)
    price_range = candle_summary.get("price_range", "")
    vol_trend = candle_summary.get("vol_trend", "")
    biggest_move = candle_summary.get("biggest_move", "")

    # Flow summary
    net_flow = flow_summary.get("net_usd", 0)
    buy_pressure = flow_summary.get("buy_pressure_pct", 50)

    vl_ratio = vol_24h / liq if liq > 0 else 0
    buy_sell_ratio = txns_buy / (txns_sell or 1)

    prompt = f"""You are Lumina AI, a precision trading signal engine. Your job: identify EARLY WAVE entries (before pump) and SHORT AT PEAK (before dump). Use ONLY the data below. Never invent numbers.

STRICT RULES:
- Prices MUST be within the chart range
- Confidence reflects signal strength (low data = low confidence)
- If no clear setup, say NEUTRAL — never force a trade
- Focus on: momentum shifts, volume divergence, whale accumulation/distribution, buy/sell ratio extremes

MOMENTUM SIGNALS TO DETECT:
- EARLY WAVE: Rising buy pressure + whale accumulation + volume increasing + price consolidating = breakout setup
- SHORT AT PEAK: Parabolic price rise + volume declining + whales selling + buy ratio dropping = reversal setup
- DISTRIBUTION: Price flat/rising but whales dumping = exit signal
- ACCUMULATION: Price dipping but whales buying heavily = entry signal

DATA:
{symbol} ({name}) | {chain} | ${price}
MCap ${mcap:,.0f} | FDV ${fdv:,.0f} | Liq ${liq:,.0f} | Vol ${vol_24h:,.0f} | V/L {vl_ratio:.1f}x
Holders: {holders or 'N/A'}
Change: 5m {pc_5m:+.2f}% | 1h {pc_1h:+.2f}% | 6h {pc_6h:+.2f}% | 24h {pc_24h:+.2f}%
Txns: {txns_buy}B/{txns_sell}S (ratio {buy_sell_ratio:.2f})
Whales: {len(whale_wallets)} found, buying ${total_whale_buy:,.0f} / selling ${total_whale_sell:,.0f}
Dumpers: {len(seller_wallets)} heavy sellers, ${total_dump:,.0f} total
Chart: {candle_count} candles, range {price_range}, vol trend: {vol_trend}, biggest move: {biggest_move}
Net flow: ${net_flow:,.0f} | Buy pressure: {buy_pressure:.1f}%

Respond with ONLY valid JSON (no markdown):
{{
  "narrative": "2-3 sentences: what phase is this token in (accumulation/markup/distribution/markdown)? Is it early wave or peaked?",
  "risk_level": "LOW|MEDIUM|HIGH|EXTREME",
  "risk_factors": ["2-4 data-backed risks"],
  "spot_signal": {{"direction":"LONG|SHORT|NEUTRAL","confidence":0-100,"entry_zone":"near ${price}","targets":["price1","price2"],"stop_loss":"price","reasoning":"why this is early wave or reversal based on data"}},
  "perp_signal": {{"direction":"LONG|SHORT|NEUTRAL","confidence":0-100,"leverage_suggestion":"1-3x","entry_zone":"near ${price}","targets":["price1","price2"],"stop_loss":"price","reasoning":"momentum/reversal reasoning from data"}},
  "whale_verdict": "Are whales accumulating (bullish) or distributing (bearish)? 1 sentence with $ amounts.",
  "key_levels": {{"support":["price","price"],"resistance":["price","price"]}},
  "tldr": "One line: EARLY WAVE / PEAK REVERSAL / DISTRIBUTION / ACCUMULATION / NO CLEAR SETUP — with reason"
}}"""

    try:
        logger.info(f"Claude AI: calling {CLAUDE_MODEL} for {symbol} ({chain})")
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": settings.CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 768,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            logger.info(f"Claude AI: response status {resp.status_code}")
            if resp.status_code != 200:
                logger.error(f"Claude API error {resp.status_code}: {resp.text[:500]}")
                return None

            data = resp.json()
            text = data.get("content", [{}])[0].get("text", "")
            logger.info(f"Claude AI: got {len(text)} chars response")

            # Parse JSON response
            try:
                analysis = json.loads(text)
                await cache_set(cache_key, analysis, ttl=120)  # cache 2 min
                return analysis
            except json.JSONDecodeError:
                logger.error(f"Claude returned non-JSON: {text[:200]}")
                return None

    except Exception as e:
        logger.error(f"Claude API call failed: {e}")
        return None
