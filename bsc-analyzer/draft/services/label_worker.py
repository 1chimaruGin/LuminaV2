#!/usr/bin/env python3
"""
============================================================
Lumina BSC - Label Worker Service
============================================================
Runs every 30 minutes to label token outcomes.
For each token migrated >30 min ago with no label:
  1. Fetches 1-min OHLCV from GeckoTerminal for 30-min window
  2. Computes max_return_pct
  3. Subtracts 15% friction (slippage + tax)
  4. Sets label_hit = 1 if net return > 20%, else 0
  5. Updates ClickHouse record
============================================================
"""
import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

import aiohttp
from clickhouse_driver import Client as ClickHouseClient

# ============================================================
# Configuration
# ============================================================
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "lumina")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")

# Labeling parameters
LABEL_DELAY_MINUTES = 30      # Wait 30 min before labeling
FRICTION_PCT = 15.0           # Slippage + tax estimate
HIT_THRESHOLD_PCT = 20.0      # Net return needed for hit=1
BATCH_SIZE = 100              # Process in batches

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


# ============================================================
# ClickHouse Client
# ============================================================
class ClickHouseDB:
    """ClickHouse database interface for label worker"""
    
    def __init__(self):
        self.client: Optional[ClickHouseClient] = None
        
    def connect(self):
        """Connect to ClickHouse"""
        self.client = ClickHouseClient(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            database=CLICKHOUSE_DB,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD
        )
        log.info(f"Connected to ClickHouse at {CLICKHOUSE_HOST}:{CLICKHOUSE_PORT}/{CLICKHOUSE_DB}")
        
    def get_unlabeled_tokens(self, cutoff_time: datetime, limit: int = BATCH_SIZE) -> List[Dict]:
        """Get tokens that need labeling"""
        if not self.client:
            return []
            
        result = self.client.execute(
            """
            SELECT 
                token_address,
                pair_address,
                block_timestamp,
                initial_price_usd
            FROM token_migrations
            WHERE label_hit IS NULL
              AND block_timestamp < %(cutoff)s
              AND initial_price_usd > 0
            ORDER BY block_timestamp ASC
            LIMIT %(limit)s
            """,
            {"cutoff": cutoff_time, "limit": limit}
        )
        
        return [
            {
                "token_address": row[0],
                "pair_address": row[1],
                "block_timestamp": row[2],
                "initial_price_usd": row[3]
            }
            for row in result
        ]
        
    def update_label(self, token_address: str, pair_address: str, 
                     label_hit: int, max_price: float, max_return_pct: float,
                     min_price: float, max_drawdown_pct: float):
        """Update token with computed label"""
        if not self.client:
            return
            
        self.client.execute(
            """
            ALTER TABLE token_migrations
            UPDATE 
                label_hit = %(label_hit)s,
                max_price_30m = %(max_price)s,
                max_return_pct = %(max_return)s,
                min_price_30m = %(min_price)s,
                max_drawdown_pct = %(max_dd)s,
                labeled_at = now64(3)
            WHERE token_address = %(token)s AND pair_address = %(pair)s
            """,
            {
                "label_hit": label_hit,
                "max_price": max_price,
                "max_return": max_return_pct,
                "min_price": min_price,
                "max_dd": max_drawdown_pct,
                "token": token_address,
                "pair": pair_address
            }
        )
        
    def get_labeling_stats(self) -> Dict:
        """Get labeling statistics"""
        if not self.client:
            return {}
            
        result = self.client.execute(
            """
            SELECT
                count() AS total,
                countIf(label_hit IS NOT NULL) AS labeled,
                countIf(label_hit = 1) AS hits,
                countIf(label_hit = 0) AS misses,
                avg(max_return_pct) AS avg_return
            FROM token_migrations
            """
        )
        
        if result:
            row = result[0]
            return {
                "total": row[0],
                "labeled": row[1],
                "hits": row[2],
                "misses": row[3],
                "avg_return": row[4] or 0,
                "hit_rate": (row[2] / row[1] * 100) if row[1] > 0 else 0
            }
        return {}


# ============================================================
# Price Data Fetcher
# ============================================================
class PriceFetcher:
    """Fetches OHLCV data from GeckoTerminal"""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        
    async def get_ohlcv_30m(self, pair_address: str, start_time: datetime) -> List[Dict]:
        """
        Get 1-minute OHLCV candles for 30 minutes after start_time.
        Returns list of candles with 'high', 'low', 'close' prices.
        """
        try:
            # GeckoTerminal API for BSC
            # Endpoint: /networks/bsc/pools/{pool_address}/ohlcv/minute
            url = f"https://api.geckoterminal.com/api/v2/networks/bsc/pools/{pair_address}/ohlcv/minute"
            
            # Calculate time range
            end_time = start_time + timedelta(minutes=30)
            
            params = {
                "aggregate": 1,  # 1-minute candles
                "before_timestamp": int(end_time.timestamp()),
                "limit": 30
            }
            
            async with self.session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
                    
                    candles = []
                    for candle in ohlcv_list:
                        # Format: [timestamp, open, high, low, close, volume]
                        if len(candle) >= 5:
                            ts = candle[0]
                            # Only include candles within our 30-min window
                            if start_time.timestamp() <= ts <= end_time.timestamp():
                                candles.append({
                                    "timestamp": ts,
                                    "open": float(candle[1]),
                                    "high": float(candle[2]),
                                    "low": float(candle[3]),
                                    "close": float(candle[4]),
                                    "volume": float(candle[5]) if len(candle) > 5 else 0
                                })
                    return candles
                    
                elif resp.status == 404:
                    # Pool not found on GeckoTerminal
                    return []
                else:
                    log.warning(f"GeckoTerminal returned {resp.status} for {pair_address}")
                    
        except asyncio.TimeoutError:
            log.warning(f"GeckoTerminal timeout for {pair_address}")
        except Exception as e:
            log.warning(f"GeckoTerminal error for {pair_address}: {e}")
            
        return []
        
    async def get_dexscreener_price_history(self, token_address: str, start_time: datetime) -> Dict:
        """
        Fallback: Get price data from DexScreener.
        Returns max/min prices if available.
        """
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    if pairs:
                        pair = pairs[0]
                        price_usd = float(pair.get("priceUsd", 0) or 0)
                        
                        # Get price changes to estimate max
                        pc = pair.get("priceChange", {})
                        h1_change = float(pc.get("h1", 0) or 0)
                        
                        # Estimate max price from 1h change
                        # This is approximate but better than nothing
                        if h1_change > 0:
                            # Current price is after the pump, estimate peak
                            max_price = price_usd * (1 + h1_change / 100)
                        else:
                            max_price = price_usd
                            
                        return {
                            "current_price": price_usd,
                            "estimated_max": max_price,
                            "h1_change": h1_change
                        }
                        
        except Exception as e:
            log.warning(f"DexScreener error for {token_address}: {e}")
            
        return {}


# ============================================================
# Label Worker
# ============================================================
class LabelWorker:
    """Main label worker service"""
    
    def __init__(self):
        self.db = ClickHouseDB()
        self.session: Optional[aiohttp.ClientSession] = None
        self.fetcher: Optional[PriceFetcher] = None
        self.stats = {
            "processed": 0,
            "hits": 0,
            "misses": 0,
            "errors": 0
        }
        
    async def run_once(self):
        """Run one labeling cycle"""
        log.info("=" * 60)
        log.info("  LUMINA BSC LABEL WORKER")
        log.info("=" * 60)
        
        # Connect to ClickHouse
        try:
            self.db.connect()
        except Exception as e:
            log.error(f"ClickHouse connection failed: {e}")
            return
            
        # Setup HTTP session
        self.session = aiohttp.ClientSession()
        self.fetcher = PriceFetcher(self.session)
        
        try:
            # Get tokens that need labeling
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=LABEL_DELAY_MINUTES)
            tokens = self.db.get_unlabeled_tokens(cutoff)
            
            if not tokens:
                log.info("No tokens to label")
                return
                
            log.info(f"Found {len(tokens)} tokens to label")
            
            # Process each token
            for i, token in enumerate(tokens):
                try:
                    await self.label_token(token)
                    
                    if (i + 1) % 10 == 0:
                        log.info(f"Progress: {i+1}/{len(tokens)}")
                        
                    # Rate limit
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    log.error(f"Error labeling {token['token_address']}: {e}")
                    self.stats["errors"] += 1
                    
            # Print summary
            self.print_summary()
            
        finally:
            if self.session:
                await self.session.close()
                
    async def label_token(self, token: Dict):
        """Label a single token"""
        token_address = token["token_address"]
        pair_address = token["pair_address"]
        start_time = token["block_timestamp"]
        initial_price = token["initial_price_usd"]
        
        if initial_price <= 0:
            return
            
        # Try GeckoTerminal first
        candles = await self.fetcher.get_ohlcv_30m(pair_address, start_time)
        
        if candles:
            # Calculate max/min from candles
            max_price = max(c["high"] for c in candles)
            min_price = min(c["low"] for c in candles)
        else:
            # Fallback to DexScreener estimate
            dex_data = await self.fetcher.get_dexscreener_price_history(token_address, start_time)
            
            if dex_data:
                max_price = dex_data.get("estimated_max", initial_price)
                min_price = dex_data.get("current_price", initial_price)
            else:
                # No data available, mark as miss
                max_price = initial_price
                min_price = initial_price
                
        # Calculate returns
        max_return_pct = ((max_price - initial_price) / initial_price) * 100 if initial_price > 0 else 0
        max_drawdown_pct = ((initial_price - min_price) / initial_price) * 100 if initial_price > 0 else 0
        
        # Apply friction and determine label
        net_return = max_return_pct - FRICTION_PCT
        label_hit = 1 if net_return >= HIT_THRESHOLD_PCT else 0
        
        # Update database
        self.db.update_label(
            token_address=token_address,
            pair_address=pair_address,
            label_hit=label_hit,
            max_price=max_price,
            max_return_pct=max_return_pct,
            min_price=min_price,
            max_drawdown_pct=max_drawdown_pct
        )
        
        self.stats["processed"] += 1
        if label_hit:
            self.stats["hits"] += 1
        else:
            self.stats["misses"] += 1
            
        log.debug(f"Labeled {token_address[:10]}... | Return: {max_return_pct:.1f}% | Hit: {label_hit}")
        
    def print_summary(self):
        """Print labeling summary"""
        log.info("-" * 60)
        log.info("LABELING SUMMARY")
        log.info(f"  Processed: {self.stats['processed']}")
        log.info(f"  Hits: {self.stats['hits']}")
        log.info(f"  Misses: {self.stats['misses']}")
        log.info(f"  Errors: {self.stats['errors']}")
        
        if self.stats['processed'] > 0:
            hit_rate = self.stats['hits'] / self.stats['processed'] * 100
            log.info(f"  Hit Rate: {hit_rate:.1f}%")
            
        # Get overall stats from DB
        db_stats = self.db.get_labeling_stats()
        if db_stats:
            log.info("-" * 60)
            log.info("DATABASE STATS")
            log.info(f"  Total tokens: {db_stats['total']}")
            log.info(f"  Labeled: {db_stats['labeled']}")
            log.info(f"  Overall hit rate: {db_stats['hit_rate']:.1f}%")
            log.info(f"  Avg max return: {db_stats['avg_return']:.1f}%")
        log.info("-" * 60)


# ============================================================
# Continuous Runner
# ============================================================
async def run_continuous(interval_minutes: int = 30):
    """Run label worker continuously"""
    log.info(f"Starting continuous label worker (interval: {interval_minutes} min)")
    
    while True:
        try:
            worker = LabelWorker()
            await worker.run_once()
        except Exception as e:
            log.error(f"Label worker error: {e}")
            
        log.info(f"Sleeping for {interval_minutes} minutes...")
        await asyncio.sleep(interval_minutes * 60)


# ============================================================
# Main Entry Point
# ============================================================
async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Lumina BSC Label Worker")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=30, help="Interval in minutes (default: 30)")
    args = parser.parse_args()
    
    if args.once:
        worker = LabelWorker()
        await worker.run_once()
    else:
        await run_continuous(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
