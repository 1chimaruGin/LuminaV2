#!/usr/bin/env python3
"""
============================================================
Lumina BSC - Real-time Migration Collector Service
============================================================
Subscribes to PairCreated events via QuickNode WSS.
On each new pair:
  1. Fetches GoPlus security data
  2. Looks up deployer reputation from ClickHouse
  3. Gets holder distribution
  4. Inserts birth record into ClickHouse
  
Runs 24/7 as a standalone async service.
============================================================
"""
import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

# Add parent dir to path for ml imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import aiohttp
from web3 import Web3
from clickhouse_driver import Client as ClickHouseClient

# ============================================================
# Configuration
# ============================================================
QUICKNODE_WSS_URL = os.getenv("QUICKNODE_WSS_URL", "")
QUICKNODE_RPC_URL = os.getenv("QUICKNODE_RPC_URL", "")
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "lumina")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")

# GoPlus API key (optional, for higher rate limits)
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY", "")

# PancakeSwap V2 Factory
PANCAKE_FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
# PairCreated event signature
PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
# WBNB address
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

# Stablecoins to skip
SKIP_TOKENS = {
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    "0x55d398326f99059ff775485246999027b3197955",  # USDT
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
    "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3",  # DAI
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


# ============================================================
# Data Classes
# ============================================================
@dataclass
class TokenMigration:
    """Represents a new token migration (PairCreated event)"""
    token_address: str = ""
    pair_address: str = ""
    deployer_address: str = ""
    block_number: int = 0
    block_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Token metadata
    token_name: str = ""
    token_symbol: str = ""
    total_supply: float = 0
    decimals: int = 18
    
    # Liquidity
    initial_liq_bnb: float = 0
    initial_liq_usd: float = 0
    initial_price_usd: float = 0
    
    # GoPlus security
    is_honeypot: int = 0
    buy_tax: float = 0
    sell_tax: float = 0
    is_mintable: int = 0
    is_proxy: int = 0
    has_blacklist: int = 0
    has_whitelist: int = 0
    can_take_ownership: int = 0
    owner_can_change_balance: int = 0
    hidden_owner: int = 0
    selfdestruct: int = 0
    external_call: int = 0
    
    # Holder distribution
    holder_count: int = 0
    top10_holder_pct: float = 0
    creator_pct: float = 0
    lp_holder_pct: float = 0
    
    # Trading activity (first 5 min)
    buy_count_5m: int = 0
    sell_count_5m: int = 0
    unique_buyers_5m: int = 0
    volume_usd_5m: float = 0
    
    # Deployer reputation
    deployer_total_tokens: int = 0
    deployer_rug_count: int = 0
    deployer_honeypot_count: int = 0
    deployer_success_count: int = 0
    deployer_avg_lifespan_h: float = 0
    deployer_score: float = 0
    
    # LP lock
    lp_locked: int = 0
    lp_lock_pct: float = 0
    lp_lock_days: int = 0
    lp_lock_provider: str = ""
    
    # Contract verification
    is_verified: int = 0
    is_renounced: int = 0
    
    # Metadata
    data_source: str = "collector"
    feature_version: int = 1


# ============================================================
# ClickHouse Client
# ============================================================
class ClickHouseDB:
    """ClickHouse database interface"""
    
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
        
    def insert_migration(self, m: TokenMigration):
        """Insert a token migration record"""
        if not self.client:
            return
            
        self.client.execute(
            """
            INSERT INTO token_migrations (
                token_address, pair_address, deployer_address,
                block_number, block_timestamp,
                token_name, token_symbol, total_supply, decimals,
                initial_liq_bnb, initial_liq_usd, initial_price_usd,
                is_honeypot, buy_tax, sell_tax, is_mintable, is_proxy,
                has_blacklist, has_whitelist, can_take_ownership,
                owner_can_change_balance, hidden_owner, selfdestruct, external_call,
                holder_count, top10_holder_pct, creator_pct, lp_holder_pct,
                buy_count_5m, sell_count_5m, unique_buyers_5m, volume_usd_5m,
                deployer_total_tokens, deployer_rug_count, deployer_honeypot_count,
                deployer_success_count, deployer_avg_lifespan_h, deployer_score,
                lp_locked, lp_lock_pct, lp_lock_days, lp_lock_provider,
                is_verified, is_renounced,
                data_source, feature_version
            ) VALUES
            """,
            [(
                m.token_address, m.pair_address, m.deployer_address,
                m.block_number, m.block_timestamp,
                m.token_name, m.token_symbol, m.total_supply, m.decimals,
                m.initial_liq_bnb, m.initial_liq_usd, m.initial_price_usd,
                m.is_honeypot, m.buy_tax, m.sell_tax, m.is_mintable, m.is_proxy,
                m.has_blacklist, m.has_whitelist, m.can_take_ownership,
                m.owner_can_change_balance, m.hidden_owner, m.selfdestruct, m.external_call,
                m.holder_count, m.top10_holder_pct, m.creator_pct, m.lp_holder_pct,
                m.buy_count_5m, m.sell_count_5m, m.unique_buyers_5m, m.volume_usd_5m,
                m.deployer_total_tokens, m.deployer_rug_count, m.deployer_honeypot_count,
                m.deployer_success_count, m.deployer_avg_lifespan_h, m.deployer_score,
                m.lp_locked, m.lp_lock_pct, m.lp_lock_days, m.lp_lock_provider,
                m.is_verified, m.is_renounced,
                m.data_source, m.feature_version
            )]
        )
        
    def get_deployer_profile(self, deployer: str) -> Optional[Dict]:
        """Get deployer profile from ClickHouse"""
        if not self.client:
            return None
            
        result = self.client.execute(
            """
            SELECT 
                total_tokens, rug_count, honeypot_count, success_count,
                success_rate, rug_rate, avg_lifespan_hours, score
            FROM deployer_profiles
            WHERE deployer_address = %(addr)s
            LIMIT 1
            """,
            {"addr": deployer.lower()}
        )
        
        if result:
            row = result[0]
            return {
                "total_tokens": row[0],
                "rug_count": row[1],
                "honeypot_count": row[2],
                "success_count": row[3],
                "success_rate": row[4],
                "rug_rate": row[5],
                "avg_lifespan_hours": row[6],
                "score": row[7]
            }
        return None
        
    def upsert_deployer_profile(self, deployer: str, stats: Dict):
        """Insert or update deployer profile"""
        if not self.client:
            return
            
        self.client.execute(
            """
            INSERT INTO deployer_profiles (
                deployer_address, total_tokens, rug_count, honeypot_count,
                success_count, success_rate, rug_rate, avg_lifespan_hours,
                score, first_seen_at, last_seen_at
            ) VALUES
            """,
            [(
                deployer.lower(),
                stats.get("total_tokens", 0),
                stats.get("rug_count", 0),
                stats.get("honeypot_count", 0),
                stats.get("success_count", 0),
                stats.get("success_rate", 0),
                stats.get("rug_rate", 0),
                stats.get("avg_lifespan_hours", 0),
                stats.get("score", 0),
                datetime.now(timezone.utc),
                datetime.now(timezone.utc)
            )]
        )


# ============================================================
# Data Enrichment
# ============================================================
class DataEnricher:
    """Enriches token data from various sources"""
    
    def __init__(self, session: aiohttp.ClientSession, db: ClickHouseDB):
        self.session = session
        self.db = db
        self.bnb_price = 600.0  # Will be updated
        
    async def get_bnb_price(self) -> float:
        """Get current BNB price"""
        try:
            url = "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT"
            async with self.session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.bnb_price = float(data["price"])
        except:
            pass
        return self.bnb_price
        
    async def get_goplus_security(self, token: str) -> Dict:
        """Get GoPlus security data"""
        try:
            url = f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={token}"
            if GOPLUS_API_KEY:
                url += f"&api_key={GOPLUS_API_KEY}"
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result", {}).get(token.lower(), {})
                    return {
                        "is_honeypot": int(result.get("is_honeypot") == "1"),
                        "buy_tax": float(result.get("buy_tax", 0) or 0) * 100,
                        "sell_tax": float(result.get("sell_tax", 0) or 0) * 100,
                        "is_mintable": int(result.get("is_mintable") == "1"),
                        "is_proxy": int(result.get("is_proxy") == "1"),
                        "has_blacklist": int(result.get("is_blacklisted") == "1"),
                        "has_whitelist": int(result.get("is_whitelisted") == "1"),
                        "can_take_ownership": int(result.get("can_take_back_ownership") == "1"),
                        "owner_can_change_balance": int(result.get("owner_change_balance") == "1"),
                        "hidden_owner": int(result.get("hidden_owner") == "1"),
                        "selfdestruct": int(result.get("selfdestruct") == "1"),
                        "external_call": int(result.get("external_call") == "1"),
                        "holder_count": int(result.get("holder_count", 0) or 0),
                        "creator_pct": float(result.get("creator_percent", 0) or 0) * 100,
                        "lp_holder_pct": float(result.get("lp_holder_count", 0) or 0),
                    }
        except Exception as e:
            log.warning(f"GoPlus error for {token}: {e}")
        return {}
        
    async def get_dexscreener_data(self, token: str) -> Dict:
        """Get DexScreener liquidity and price data"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        # Get the BNB pair
                        bnb_pair = next(
                            (p for p in pairs if p.get("quoteToken", {}).get("address", "").lower() == WBNB.lower()),
                            pairs[0]
                        )
                        liq = bnb_pair.get("liquidity", {})
                        return {
                            "liquidity_usd": float(liq.get("usd", 0) or 0),
                            "liquidity_bnb": float(liq.get("quote", 0) or 0),
                            "price_usd": float(bnb_pair.get("priceUsd", 0) or 0),
                            "token_name": bnb_pair.get("baseToken", {}).get("name", ""),
                            "token_symbol": bnb_pair.get("baseToken", {}).get("symbol", ""),
                        }
        except Exception as e:
            log.warning(f"DexScreener error for {token}: {e}")
        return {}
        
    async def get_deployer_from_tx(self, tx_hash: str, w3: Web3) -> str:
        """Get deployer address from transaction"""
        try:
            tx = w3.eth.get_transaction(tx_hash)
            return tx["from"].lower() if tx else ""
        except:
            return ""
            
    def get_deployer_reputation(self, deployer: str) -> Dict:
        """Get deployer reputation from ClickHouse"""
        profile = self.db.get_deployer_profile(deployer)
        if profile:
            return {
                "deployer_total_tokens": profile["total_tokens"],
                "deployer_rug_count": profile["rug_count"],
                "deployer_honeypot_count": profile["honeypot_count"],
                "deployer_success_count": profile["success_count"],
                "deployer_avg_lifespan_h": profile["avg_lifespan_hours"],
                "deployer_score": profile["score"],
            }
        return {}


# ============================================================
# WebSocket Event Listener
# ============================================================
class MigrationCollector:
    """Main collector service"""
    
    def __init__(self):
        self.db = ClickHouseDB()
        self.session: Optional[aiohttp.ClientSession] = None
        self.enricher: Optional[DataEnricher] = None
        self.w3: Optional[Web3] = None
        self.running = False
        self.scorer = None  # ML scorer (lazy loaded)
        self.stats = {
            "pairs_detected": 0,
            "pairs_processed": 0,
            "snipes": 0,
            "rejects": 0,
            "errors": 0,
            "start_time": None
        }
        
    def score_token(self, migration) -> dict:
        """Score a token using ML model with primary tax filter"""
        # Lazy load scorer
        if self.scorer is None:
            try:
                from ml.inference import TokenScorer
                self.scorer = TokenScorer()
                log.info("ML scorer loaded successfully")
            except Exception as e:
                log.warning(f"ML scorer not available: {e}")
                return {"score": 0, "action": "SKIP", "reject_reason": "ml_unavailable"}
        
        # Build feature dict from migration
        token_data = {
            "initial_liq_usd": migration.initial_liq_usd,
            "is_honeypot": migration.is_honeypot,
            "buy_tax": migration.buy_tax,
            "sell_tax": migration.sell_tax,
            "is_mintable": migration.is_mintable,
            "holder_count": migration.holder_count,
        }
        
        result = self.scorer.score(token_data)
        
        # Update stats
        if result["action"] in ("SNIPE", "SNIPE_SMALL"):
            self.stats["snipes"] += 1
        elif result["action"] == "REJECT":
            self.stats["rejects"] += 1
            
        return result
        
    async def start(self):
        """Start the collector service"""
        log.info("=" * 60)
        log.info("  LUMINA BSC MIGRATION COLLECTOR")
        log.info("=" * 60)
        
        # Validate config
        if not QUICKNODE_WSS_URL:
            log.error("QUICKNODE_WSS_URL not set!")
            return
        if not QUICKNODE_RPC_URL:
            log.error("QUICKNODE_RPC_URL not set!")
            return
            
        # Connect to ClickHouse
        try:
            self.db.connect()
        except Exception as e:
            log.error(f"ClickHouse connection failed: {e}")
            log.warning("Running without ClickHouse - data will not be persisted")
            
        # Setup Web3
        self.w3 = Web3(Web3.HTTPProvider(QUICKNODE_RPC_URL))
        if not self.w3.is_connected():
            log.error("Web3 RPC connection failed!")
            return
        log.info(f"Web3 connected, current block: {self.w3.eth.block_number}")
        
        # Setup HTTP session
        self.session = aiohttp.ClientSession()
        self.enricher = DataEnricher(self.session, self.db)
        
        # Update BNB price
        await self.enricher.get_bnb_price()
        log.info(f"BNB price: ${self.enricher.bnb_price:.2f}")
        
        self.running = True
        self.stats["start_time"] = datetime.now(timezone.utc)
        
        # Start WebSocket listener
        await self.listen_for_pairs()
        
    async def stop(self):
        """Stop the collector"""
        self.running = False
        if self.session:
            await self.session.close()
        log.info("Collector stopped")
        
    async def listen_for_pairs(self):
        """Listen for PairCreated events via WebSocket"""
        import websockets
        
        subscribe_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "address": PANCAKE_FACTORY_V2,
                    "topics": [PAIR_CREATED_TOPIC]
                }
            ]
        })
        
        while self.running:
            try:
                async with websockets.connect(QUICKNODE_WSS_URL) as ws:
                    log.info(f"WebSocket connected to QuickNode")
                    await ws.send(subscribe_msg)
                    
                    # Get subscription confirmation
                    response = await ws.recv()
                    sub_data = json.loads(response)
                    if "result" in sub_data:
                        log.info(f"Subscribed to PairCreated events (sub_id: {sub_data['result']})")
                    
                    # Listen for events
                    while self.running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(msg)
                            
                            if "params" in data and "result" in data["params"]:
                                log_entry = data["params"]["result"]
                                await self.process_pair_created(log_entry)
                                
                        except asyncio.TimeoutError:
                            # Send ping to keep connection alive
                            await ws.ping()
                            
            except Exception as e:
                log.error(f"WebSocket error: {e}")
                self.stats["errors"] += 1
                await asyncio.sleep(5)  # Reconnect delay
                
    async def process_pair_created(self, log_entry: Dict):
        """Process a PairCreated event"""
        try:
            self.stats["pairs_detected"] += 1
            
            # Parse event data
            topics = log_entry.get("topics", [])
            data = log_entry.get("data", "")
            block_hex = log_entry.get("blockNumber", "0x0")
            tx_hash = log_entry.get("transactionHash", "")
            
            if len(topics) < 3:
                return
                
            # Extract token addresses from topics
            token0 = "0x" + topics[1][-40:]
            token1 = "0x" + topics[2][-40:]
            
            # Extract pair address from data
            pair_address = "0x" + data[-40:] if len(data) >= 42 else ""
            
            # Determine which is the new token (not WBNB)
            token0_lower = token0.lower()
            token1_lower = token1.lower()
            
            if token0_lower == WBNB.lower():
                token_address = token1
            elif token1_lower == WBNB.lower():
                token_address = token0
            else:
                # Neither is WBNB, skip
                return
                
            # Skip stablecoins
            if token_address.lower() in SKIP_TOKENS:
                return
                
            block_number = int(block_hex, 16)
            
            log.info(f"[NEW PAIR] {token_address[:10]}... | Block: {block_number}")
            
            # Create migration record
            migration = TokenMigration(
                token_address=token_address.lower(),
                pair_address=pair_address.lower(),
                block_number=block_number,
                block_timestamp=datetime.now(timezone.utc),
            )
            
            # Enrich data in parallel
            await self.enrich_migration(migration, tx_hash)
            
            # ML Scoring - apply primary tax filter and score
            ml_result = self.score_token(migration)
            migration.ml_score = ml_result.get("score", 0)
            migration.ml_action = ml_result.get("action", "SKIP")
            
            # Insert into ClickHouse
            try:
                self.db.insert_migration(migration)
                self.stats["pairs_processed"] += 1
                
                # Log with ML decision
                action_emoji = {"SNIPE": "🎯", "SNIPE_SMALL": "⚡", "REJECT": "❌", "SKIP": "⏭️"}.get(ml_result["action"], "")
                log.info(f"[{ml_result['action']}] {action_emoji} {migration.token_symbol} | Liq: ${migration.initial_liq_usd:,.0f} | Score: {ml_result['score']:.2f}")
                
                if ml_result.get("reject_reason"):
                    log.info(f"  └─ Reject: {ml_result['reject_reason']}")
                    
            except Exception as e:
                log.error(f"ClickHouse insert error: {e}")
                
        except Exception as e:
            log.error(f"Error processing PairCreated: {e}")
            self.stats["errors"] += 1
            
    async def enrich_migration(self, m: TokenMigration, tx_hash: str):
        """Enrich migration with data from multiple sources"""
        # Run enrichment tasks in parallel
        tasks = [
            self.enricher.get_goplus_security(m.token_address),
            self.enricher.get_dexscreener_data(m.token_address),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # GoPlus data
        if isinstance(results[0], dict):
            goplus = results[0]
            m.is_honeypot = goplus.get("is_honeypot", 0)
            m.buy_tax = goplus.get("buy_tax", 0)
            m.sell_tax = goplus.get("sell_tax", 0)
            m.is_mintable = goplus.get("is_mintable", 0)
            m.is_proxy = goplus.get("is_proxy", 0)
            m.has_blacklist = goplus.get("has_blacklist", 0)
            m.has_whitelist = goplus.get("has_whitelist", 0)
            m.can_take_ownership = goplus.get("can_take_ownership", 0)
            m.owner_can_change_balance = goplus.get("owner_can_change_balance", 0)
            m.hidden_owner = goplus.get("hidden_owner", 0)
            m.selfdestruct = goplus.get("selfdestruct", 0)
            m.external_call = goplus.get("external_call", 0)
            m.holder_count = goplus.get("holder_count", 0)
            m.creator_pct = goplus.get("creator_pct", 0)
            
        # DexScreener data
        if isinstance(results[1], dict):
            dex = results[1]
            m.initial_liq_usd = dex.get("liquidity_usd", 0)
            m.initial_liq_bnb = dex.get("liquidity_bnb", 0)
            m.initial_price_usd = dex.get("price_usd", 0)
            m.token_name = dex.get("token_name", "")
            m.token_symbol = dex.get("token_symbol", "")
            
        # Get deployer from transaction
        if tx_hash and self.w3:
            m.deployer_address = await self.enricher.get_deployer_from_tx(tx_hash, self.w3)
            
            # Get deployer reputation
            if m.deployer_address:
                rep = self.enricher.get_deployer_reputation(m.deployer_address)
                m.deployer_total_tokens = rep.get("deployer_total_tokens", 0)
                m.deployer_rug_count = rep.get("deployer_rug_count", 0)
                m.deployer_honeypot_count = rep.get("deployer_honeypot_count", 0)
                m.deployer_success_count = rep.get("deployer_success_count", 0)
                m.deployer_avg_lifespan_h = rep.get("deployer_avg_lifespan_h", 0)
                m.deployer_score = rep.get("deployer_score", 0)


# ============================================================
# Main Entry Point
# ============================================================
async def main():
    collector = MigrationCollector()
    
    try:
        await collector.start()
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        await collector.stop()
        
        # Print stats
        stats = collector.stats
        if stats["start_time"]:
            runtime = (datetime.now(timezone.utc) - stats["start_time"]).total_seconds()
            log.info("=" * 40)
            log.info(f"Runtime: {runtime/3600:.1f} hours")
            log.info(f"Pairs detected: {stats['pairs_detected']}")
            log.info(f"Pairs processed: {stats['pairs_processed']}")
            log.info(f"ML Snipes: {stats['snipes']}")
            log.info(f"ML Rejects: {stats['rejects']}")
            log.info(f"Errors: {stats['errors']}")


if __name__ == "__main__":
    asyncio.run(main())
