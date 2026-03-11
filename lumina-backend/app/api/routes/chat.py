"""
AI Copilot chat endpoint — uses Grok API with real-time market context.
"""

import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.rate_limit import rate_limit

from app.core.config import get_settings

settings = get_settings()
from app.db.memcache import cache_get, cache_set
from app.services.exchange import fetch_all_tickers, fetch_all_funding_rates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


COPILOT_SYSTEM = """You are Lumina AI — an expert crypto market analyst copilot.
You have access to real-time market data provided in the context below.

CRITICAL RULES:
1. ONLY use numbers, prices, and statistics that appear in the LIVE MARKET DATA section below. NEVER invent or guess prices.
2. If data for a specific token is not in the context, say "I don't have current data for that token" instead of guessing.
3. Always cite the source (e.g. "BTC is at $67,092 per Binance data") when referencing numbers.
4. If the user asks about something outside the provided data, clearly state what you know vs what you're uncertain about.
5. Never predict exact future prices. Use phrases like "based on current momentum" or "historically" when discussing trends.

Format with markdown: **bold** for key numbers, bullet points for lists.
Keep responses under 300 words unless the user asks for detail."""


class ChatRequest(BaseModel):
    message: str  # max 2000 chars enforced in handler
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}] max 10
    model: str = "grok"  # "grok" or "claude"


class ChatResponse(BaseModel):
    reply: str
    context_used: bool = False


async def _build_market_context() -> str:
    """Build a brief market snapshot from cached data for the AI."""
    cached_overview = await cache_get("market:overview")
    lines = []

    if cached_overview:
        lines.append(f"BTC Dominance: {cached_overview.get('btc_dominance', 'N/A')}%")
        lines.append(f"Fear & Greed: {cached_overview.get('fear_greed_index', 'N/A')} ({cached_overview.get('fear_greed_label', 'N/A')})")
        lines.append(f"24h Volume: ${cached_overview.get('total_volume_24h', 0):,.0f}")
        lines.append(f"Active Pairs: {cached_overview.get('active_pairs', 'N/A')}")

        gainers = cached_overview.get("top_gainers", [])[:3]
        if gainers:
            lines.append("Top Gainers: " + ", ".join(
                f"{g.get('base','?')} {g.get('price_change_24h', 0):+.1f}%" for g in gainers
            ))
        losers = cached_overview.get("top_losers", [])[:3]
        if losers:
            lines.append("Top Losers: " + ", ".join(
                f"{g.get('base','?')} {g.get('price_change_24h', 0):+.1f}%" for g in losers
            ))

    # Get top tickers for price context
    cached_tickers = await cache_get("tickers:all")
    if cached_tickers:
        top = cached_tickers[:10]
        prices = ", ".join(f"{t.get('base','?')}: ${t.get('price', 0):,.2f}" for t in top if t.get("price", 0) > 0)
        if prices:
            lines.append(f"Prices: {prices}")

    # Funding rates summary
    cached_funding = await cache_get("funding:all")
    if cached_funding and len(cached_funding) > 0:
        avg_rate = sum(f.get("rate", 0) for f in cached_funding[:20]) / min(len(cached_funding), 20)
        lines.append(f"Avg Funding Rate: {avg_rate * 100:.4f}% (8h)")

    return "\n".join(lines) if lines else "No cached market data available."


async def _call_grok(messages: list[dict]) -> str:
    """Call Grok API and return the reply text."""
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(
            f"{settings.GROK_API_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-3-mini",
                "messages": messages,
                "temperature": 0.15,
                "max_tokens": 1000,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _call_claude(messages: list[dict], system_content: str) -> str:
    """Call Claude API (Anthropic Messages API) and return the reply text."""
    # Claude uses a separate system param, not in messages array
    claude_messages = [m for m in messages if m["role"] != "system"]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": system_content,
                "messages": claude_messages,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


@router.post("", response_model=ChatResponse, dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60))])
async def chat(req: ChatRequest):
    # Input validation
    if not req.message or not req.message.strip():
        return ChatResponse(reply="Please enter a message.", context_used=False)
    if len(req.message) > 2000:
        return ChatResponse(reply="Message too long (max 2000 characters).", context_used=False)
    req.history = req.history[-10:]  # Cap history

    use_claude = req.model == "claude"

    if use_claude and not settings.CLAUDE_API_KEY:
        return ChatResponse(
            reply="Claude API key not configured. Please set `CLAUDE_API_KEY` in the backend `.env` file, or switch to Grok.",
            context_used=False,
        )
    if not use_claude and not settings.GROK_API_KEY:
        return ChatResponse(
            reply="Grok API key not configured. Please set `GROK_API_KEY` in the backend `.env` file, or switch to Claude.",
            context_used=False,
        )

    # Build market context
    context = await _build_market_context()
    has_context = "No cached" not in context

    system_content = COPILOT_SYSTEM + f"\n\n--- LIVE MARKET DATA ---\n{context}\n---"

    # Build messages
    messages = [
        {"role": "system", "content": system_content},
    ]

    # Add conversation history (last 10 messages max)
    for msg in req.history[-10:]:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": msg.get("content", "")})

    messages.append({"role": "user", "content": req.message})

    try:
        if use_claude:
            reply = await _call_claude(messages, system_content)
        else:
            reply = await _call_grok(messages)
        return ChatResponse(reply=reply, context_used=has_context)
    except Exception as e:
        model_name = "Claude" if use_claude else "Grok"
        logger.error(f"{model_name} chat error: {e}")
        return ChatResponse(
            reply=f"Sorry, I couldn't process that request right now. Please try again in a moment.",
            context_used=False,
        )


# ── Quick Insights — generated from real market data ──

@router.get("/insights", dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60))])
async def get_insights():
    """Generate quick insights from real cached market data."""
    insights = []

    overview = await cache_get("market:overview")
    if overview:
        fgi = overview.get("fear_greed_index", 50)
        fgl = overview.get("fear_greed_label", "Neutral")
        if fgi <= 25:
            insights.append({
                "icon": "warning", "iconColor": "text-accent-error",
                "title": f"Extreme Fear ({fgi})",
                "desc": f"Market sentiment is at Extreme Fear. Historically a contrarian buy signal — smart money often accumulates here.",
                "tag": "Contrarian", "tagColor": "bg-accent-warning/10 text-accent-warning border-accent-warning/20",
            })
        elif fgi >= 75:
            insights.append({
                "icon": "trending_up", "iconColor": "text-accent-success",
                "title": f"Extreme Greed ({fgi})",
                "desc": f"Market sentiment is at Extreme Greed. Consider taking partial profits and tightening stop-losses.",
                "tag": "Caution", "tagColor": "bg-accent-warning/10 text-accent-warning border-accent-warning/20",
            })
        else:
            insights.append({
                "icon": "monitoring", "iconColor": "text-neon-cyan",
                "title": f"Market Sentiment: {fgl} ({fgi})",
                "desc": f"Fear & Greed Index at {fgi} ({fgl}). BTC dominance at {overview.get('btc_dominance', 'N/A')}%.",
                "tag": fgl, "tagColor": "bg-neon-cyan/10 text-neon-cyan border-neon-cyan/20",
            })

        # Top gainers insight
        gainers = overview.get("top_gainers", [])[:3]
        if gainers:
            names = ", ".join(f"{g.get('base','?')} ({g.get('price_change_24h', 0):+.1f}%)" for g in gainers)
            insights.append({
                "icon": "trending_up", "iconColor": "text-accent-success",
                "title": "Top Gainers Today",
                "desc": f"Leading the market: {names}. Check volume confirmation before entering.",
                "tag": "Bullish", "tagColor": "bg-accent-success/10 text-accent-success border-accent-success/20",
            })

        # Top losers insight
        losers = overview.get("top_losers", [])[:3]
        if losers:
            names = ", ".join(f"{g.get('base','?')} ({g.get('price_change_24h', 0):+.1f}%)" for g in losers)
            insights.append({
                "icon": "trending_down", "iconColor": "text-accent-error",
                "title": "Biggest Drops",
                "desc": f"Underperforming: {names}. Watch for support levels before catching the knife.",
                "tag": "Bearish", "tagColor": "bg-accent-error/10 text-accent-error border-accent-error/20",
            })

    # Funding rate insight
    cached_funding = await cache_get("funding:all")
    if cached_funding and len(cached_funding) > 5:
        extreme_pos = [f for f in cached_funding if f.get("rate", 0) > 0.0005]
        extreme_neg = [f for f in cached_funding if f.get("rate", 0) < -0.0003]
        if extreme_pos:
            symbols = ", ".join(f.get("symbol", "?").split("/")[0] for f in extreme_pos[:3])
            insights.append({
                "icon": "percent", "iconColor": "text-neon-purple",
                "title": "High Funding Rates",
                "desc": f"Elevated positive funding on {symbols}. Longs are paying shorts — potential long squeeze risk.",
                "tag": "Risk", "tagColor": "bg-neon-purple/10 text-neon-purple border-neon-purple/20",
            })
        if extreme_neg:
            symbols = ", ".join(f.get("symbol", "?").split("/")[0] for f in extreme_neg[:3])
            insights.append({
                "icon": "swap_horiz", "iconColor": "text-neon-lime",
                "title": "Negative Funding Opportunity",
                "desc": f"Shorts paying longs on {symbols}. Potential short squeeze setup — watch for reversal signals.",
                "tag": "Opportunity", "tagColor": "bg-neon-lime/10 text-neon-lime border-neon-lime/20",
            })

    # Volume insight
    if overview:
        vol = overview.get("total_volume_24h", 0)
        if vol > 0:
            insights.append({
                "icon": "bar_chart", "iconColor": "text-neon-cyan",
                "title": f"24h Volume: ${vol / 1e9:.1f}B",
                "desc": f"Aggregate trading volume across {overview.get('exchanges_count', 8)} exchanges with {overview.get('active_pairs', 0):,} active pairs.",
                "tag": "Data", "tagColor": "bg-neon-cyan/10 text-neon-cyan border-neon-cyan/20",
            })

    if not insights:
        insights.append({
            "icon": "sync", "iconColor": "text-slate-400",
            "title": "Loading Market Data",
            "desc": "Market data is being fetched. Insights will appear once the cache warms up.",
            "tag": "Loading", "tagColor": "bg-white/5 text-slate-400 border-white/10",
        })

    return {"data": insights}


# ── Market Pulse — real top tokens with prices ──

@router.get("/market-pulse", dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60))])
async def get_market_pulse():
    """Return top tokens with real prices for the AI copilot sidebar."""
    tickers = await cache_get("tickers:all")
    if not tickers:
        # Try fetching fresh
        try:
            tickers = await fetch_all_tickers()
        except Exception:
            tickers = []

    # Pick well-known tokens
    WANTED = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK"]
    pulse = []
    seen = set()

    for t in tickers:
        base = t.get("base", "")
        if base in WANTED and base not in seen:
            seen.add(base)
            change = t.get("price_change_24h") or 0
            price = t.get("price", 0)

            # Determine sentiment from price change
            if change >= 5:
                sentiment, sent_color = "Strong Buy", "text-neon-lime"
            elif change >= 1:
                sentiment, sent_color = "Bullish", "text-accent-success"
            elif change >= -1:
                sentiment, sent_color = "Neutral", "text-slate-400"
            elif change >= -5:
                sentiment, sent_color = "Bearish", "text-accent-error"
            else:
                sentiment, sent_color = "Strong Sell", "text-accent-error"

            pulse.append({
                "symbol": base,
                "name": t.get("symbol", base),
                "price": price,
                "change": change,
                "changeColor": "text-accent-success" if change >= 0 else "text-accent-error",
                "sentiment": sentiment,
                "sentColor": sent_color,
            })

    # Maintain WANTED order
    ordered = []
    for w in WANTED:
        match = next((p for p in pulse if p["symbol"] == w), None)
        if match:
            ordered.append(match)

    return {"data": ordered}
