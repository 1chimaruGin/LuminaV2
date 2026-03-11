import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.db.database import init_db
from app.services.exchange import close_exchanges
from app.services.token_resolver import preload_jupiter

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lumina")

_bg_tasks: list[asyncio.Task] = []


async def _cache_warmer():
    """Background task: pre-fetch expensive data so all pages load instantly."""
    from app.api.routes.market import _build_overview
    from app.api.routes.strategy import run_volume_spike_scan
    from app.db.memcache import cache_set
    from app.services.exchange import (
        fetch_all_tickers,
        fetch_all_funding_rates,
        fetch_open_interest_batch,
        fetch_recent_trades,
    )

    WHALE_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]

    # Wait a moment for exchanges to init
    await asyncio.sleep(1)
    logger.info("🔥 Cache warmer starting first fetch...")

    while True:
        try:
            # Phase 1: tickers + overview (needed by everything)
            tickers = await fetch_all_tickers()
            await cache_set("tickers:all", tickers, ttl=120)

            overview = await _build_overview()
            await cache_set("market:overview", overview, ttl=300)

            # Phase 2: funding + OI + whale trades (parallel)
            async def _warm_funding():
                try:
                    funding = await fetch_all_funding_rates()
                    await cache_set("funding:all", funding, ttl=120)
                    return len(funding)
                except Exception:
                    return 0

            async def _warm_oi():
                try:
                    oi = await fetch_open_interest_batch("binance")
                    await cache_set("oi:binance:batch", oi, ttl=60)
                    return len(oi)
                except Exception:
                    return 0

            async def _warm_whales():
                try:
                    all_trades = []
                    whale_exchanges = ["binance", "bybit", "okx"]
                    tasks = []
                    for ex in whale_exchanges:
                        for sym in WHALE_SYMBOLS:
                            tasks.append(fetch_recent_trades(ex, sym, limit=100, min_usd=20000))
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, list):
                            all_trades.extend(r)
                    all_trades.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                    await cache_set("whale:all", all_trades, ttl=60)
                    return len(all_trades)
                except Exception:
                    return 0

            async def _warm_strategy():
                try:
                    return await run_volume_spike_scan()
                except Exception:
                    return 0

            fc, oc, wc, sc = await asyncio.gather(_warm_funding(), _warm_oi(), _warm_whales(), _warm_strategy())

            logger.info(f"✅ Cache warmed: {overview.get('active_pairs', 0)} pairs, {len(tickers)} tickers, {fc} funding, {oc} OI, {wc} whale trades, {sc} spikes")
        except Exception as e:
            logger.warning(f"⚠️  Cache warmer error: {e}")

        # Refresh every 45 seconds
        await asyncio.sleep(45)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Lumina Backend starting...")

    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.warning(f"⚠️  Database not available (will use in-memory): {e}")

    # Preload Jupiter token list in background (non-blocking)
    _bg_tasks.append(asyncio.create_task(preload_jupiter()))

    # Start cache warmer — pre-fetches dashboard data so first load is instant
    _bg_tasks.append(asyncio.create_task(_cache_warmer()))

    logger.info(f"✅ API ready at {settings.API_PREFIX}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    for t in _bg_tasks:
        t.cancel()
    await close_exchanges()
    logger.info("👋 Lumina Backend stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — restricted to configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Routes
app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "service": settings.APP_NAME,
    }
