#!/usr/bin/env python3
"""
Lumina BSC — Deployer Reputation Database Builder

Builds a CSV database of deployer wallet reputations by:
1. Fetching PairCreated events from BSC (via QuickNode RPC)
2. Getting the deployer (tx sender) for each pair
3. Tracking token outcomes (rugged, honeypot, successful)
4. Computing reputation scores

Output: data/deployers.csv with columns:
  deployer,total_tokens,rugged,honeypots,successful,avg_lifespan_hours,score

Usage:
    python scripts/build_deployer_db.py --days 30
    python scripts/build_deployer_db.py --days 7 --output data/deployers_7d.csv
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import aiohttp

# BSC RPC
BSC_RPC = os.environ.get(
    "QUICK_NODE_BSC_RPC",
    "https://bsc-dataseed.binance.org/"
)

# PancakeSwap V2 Factory
PANCAKE_FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

# Event signatures
PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

# BSC block time ~3 seconds
BLOCKS_PER_HOUR = 1200
BLOCKS_PER_DAY = 28800

# Stablecoins to skip
STABLECOINS = {
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    "0x55d398326f99059ff775485246999027b3197955",  # USDT
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
    "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3",  # DAI
}


@dataclass
class TokenRecord:
    """Record for a single token deployment"""
    token_address: str
    pair_address: str
    deployer: str
    creation_block: int
    creation_timestamp: int = 0
    
    # Outcome tracking
    is_honeypot: bool = False
    is_rugged: bool = False
    is_successful: bool = False  # Hit 2x+
    peak_multiple: float = 1.0
    final_multiple: float = 1.0
    lifespan_hours: float = 0.0
    liquidity_bnb: float = 0.0


@dataclass
class DeployerStats:
    """Aggregated stats for a deployer wallet"""
    address: str
    total_tokens: int = 0
    rugged_tokens: int = 0
    honeypot_tokens: int = 0
    successful_tokens: int = 0
    total_lifespan_hours: float = 0.0
    first_seen_block: int = 0
    last_seen_block: int = 0
    tokens: List[TokenRecord] = field(default_factory=list)
    
    @property
    def avg_lifespan_hours(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return self.total_lifespan_hours / self.total_tokens
    
    @property
    def success_rate(self) -> float:
        valid = self.total_tokens - self.honeypot_tokens
        if valid <= 0:
            return 0.0
        return self.successful_tokens / valid
    
    @property
    def rug_rate(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return self.rugged_tokens / self.total_tokens
    
    @property
    def honeypot_rate(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return self.honeypot_tokens / self.total_tokens
    
    def compute_score(self) -> float:
        """
        Compute reputation score from -100 to +100
        
        Factors:
        - Success rate (positive)
        - Rug rate (negative, heavily weighted)
        - Honeypot rate (negative)
        - Experience bonus (more tokens = more reliable signal)
        - Longevity bonus (tokens that last longer)
        """
        score = 0.0
        
        # Base score from success rate (0 to 50 points)
        score += self.success_rate * 50
        
        # Penalty for rugs (-100 points max)
        score -= self.rug_rate * 100
        
        # Penalty for honeypots (-50 points max)
        score -= self.honeypot_rate * 50
        
        # Experience bonus (+10 if deployed 5+ tokens)
        if self.total_tokens >= 5:
            score += 10
        
        # Longevity bonus (+10 if avg lifespan > 24h)
        if self.avg_lifespan_hours > 24:
            score += 10
        
        # Clamp to [-100, 100]
        return max(-100, min(100, score))


class DeployerDBBuilder:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.deployers: Dict[str, DeployerStats] = defaultdict(lambda: DeployerStats(address=""))
        self.tokens: List[TokenRecord] = []
        self.request_count = 0
        self.last_request_time = 0
    
    async def rate_limit(self, delay: float = 0.1):
        """Rate limit RPC requests"""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self.last_request_time = time.time()
        self.request_count += 1
    
    async def get_latest_block(self) -> int:
        """Get current BSC block number"""
        params = {
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 1
        }
        async with self.session.post(BSC_RPC, json=params) as resp:
            data = await resp.json()
            return int(data.get("result", "0x0"), 16)
    
    async def get_tx_sender(self, tx_hash: str) -> Optional[str]:
        """Get the sender (deployer) of a transaction"""
        await self.rate_limit(0.05)
        params = {
            "jsonrpc": "2.0",
            "method": "eth_getTransactionByHash",
            "params": [tx_hash],
            "id": 1
        }
        try:
            async with self.session.post(BSC_RPC, json=params) as resp:
                data = await resp.json()
                tx = data.get("result")
                if tx:
                    return tx.get("from", "").lower()
        except:
            pass
        return None
    
    async def fetch_pair_created_events(
        self, start_block: int, end_block: int
    ) -> List[dict]:
        """Fetch PairCreated events from PancakeSwap Factory"""
        pairs = []
        chunk_size = 2000
        current = start_block
        total_chunks = (end_block - start_block) // chunk_size + 1
        chunk_num = 0
        
        print(f"  Fetching blocks {start_block:,} → {end_block:,}...")
        
        while current < end_block:
            chunk_end = min(current + chunk_size, end_block)
            chunk_num += 1
            
            try:
                await self.rate_limit(0.1)
                params = {
                    "jsonrpc": "2.0",
                    "method": "eth_getLogs",
                    "params": [{
                        "fromBlock": hex(current),
                        "toBlock": hex(chunk_end),
                        "address": PANCAKE_FACTORY_V2,
                        "topics": [PAIR_CREATED_TOPIC]
                    }],
                    "id": 1
                }
                
                async with self.session.post(BSC_RPC, json=params) as resp:
                    data = await resp.json()
                    
                    if "error" in data:
                        await asyncio.sleep(0.5)
                        current = chunk_end
                        continue
                    
                    logs = data.get("result", [])
                    
                    for log in logs:
                        try:
                            topics = log.get("topics", [])
                            if len(topics) < 3:
                                continue
                            
                            token0 = "0x" + topics[1][-40:]
                            token1 = "0x" + topics[2][-40:]
                            data_hex = log.get("data", "0x")
                            pair_address = "0x" + data_hex[26:66]
                            block_num = int(log.get("blockNumber", "0x0"), 16)
                            tx_hash = log.get("transactionHash", "")
                            
                            # Only BNB pairs
                            if token0.lower() == WBNB.lower():
                                token_address = token1.lower()
                            elif token1.lower() == WBNB.lower():
                                token_address = token0.lower()
                            else:
                                continue
                            
                            # Skip stablecoins
                            if token_address in STABLECOINS:
                                continue
                            
                            pairs.append({
                                "token": token_address,
                                "pair": pair_address.lower(),
                                "block": block_num,
                                "tx_hash": tx_hash,
                            })
                        except:
                            continue
                
                progress = chunk_num / total_chunks * 100
                print(f"\r  Progress: {progress:.1f}% ({len(pairs)} pairs found)", end="")
                
            except Exception as e:
                await asyncio.sleep(0.5)
            
            current = chunk_end
        
        print(f"\n  Found {len(pairs)} BNB pairs")
        return pairs
    
    async def get_deployers_for_pairs(self, pairs: List[dict]) -> List[TokenRecord]:
        """Get deployer wallet for each pair by fetching tx sender"""
        records = []
        
        print(f"  Fetching deployers for {len(pairs)} pairs...")
        
        for i, pair in enumerate(pairs):
            try:
                deployer = await self.get_tx_sender(pair["tx_hash"])
                if deployer:
                    record = TokenRecord(
                        token_address=pair["token"],
                        pair_address=pair["pair"],
                        deployer=deployer,
                        creation_block=pair["block"],
                    )
                    records.append(record)
                
                if (i + 1) % 50 == 0:
                    print(f"\r  Progress: {(i+1)/len(pairs)*100:.1f}% ({len(records)} deployers found)", end="")
                
            except:
                continue
        
        print(f"\n  Found deployers for {len(records)} pairs")
        return records
    
    async def enrich_token_outcomes(self, records: List[TokenRecord]):
        """Check token outcomes via DexScreener"""
        print(f"  Enriching {len(records)} tokens with DexScreener data...")
        
        for i, record in enumerate(records):
            try:
                await self.rate_limit(0.2)  # DexScreener rate limit
                url = f"https://api.dexscreener.com/latest/dex/pairs/bsc/{record.pair_address}"
                
                async with self.session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    
                    data = await resp.json()
                    pair_data = data.get("pair") or (data.get("pairs", [{}])[0] if data.get("pairs") else {})
                    
                    if not pair_data:
                        # No data = likely rugged or dead
                        record.is_rugged = True
                        record.lifespan_hours = 0
                        continue
                    
                    # Get liquidity
                    liq = pair_data.get("liquidity", {})
                    liq_usd = float(liq.get("usd", 0) or 0)
                    record.liquidity_bnb = liq_usd / 600  # Approximate BNB price
                    
                    # Get price changes
                    pc = pair_data.get("priceChange", {})
                    h1 = float(pc.get("h1", 0) or 0)
                    h24 = float(pc.get("h24", 0) or 0)
                    
                    # Validate (reject garbage data)
                    if abs(h1) > 10000:
                        h1 = 0
                    if abs(h24) > 10000:
                        h24 = 0
                    
                    # Calculate multiples
                    if h24 > -100:
                        record.final_multiple = (100 + h24) / 100
                    if h1 > -100:
                        record.peak_multiple = max((100 + h1) / 100, record.final_multiple)
                    
                    # Determine outcome
                    if record.final_multiple < 0.1:
                        record.is_rugged = True
                    elif record.peak_multiple >= 2.0:
                        record.is_successful = True
                    
                    # Estimate lifespan (if still trading, use 24h+)
                    txns = pair_data.get("txns", {}).get("h24", {})
                    total_txns = (txns.get("buys", 0) or 0) + (txns.get("sells", 0) or 0)
                    if total_txns > 0:
                        record.lifespan_hours = 24.0  # Still active
                    else:
                        record.lifespan_hours = 1.0  # Dead
                
                if (i + 1) % 50 == 0:
                    print(f"\r  Progress: {(i+1)/len(records)*100:.1f}%", end="")
                
            except:
                continue
        
        print(f"\n  Enrichment complete")
    
    async def check_honeypots(self, records: List[TokenRecord]):
        """Check honeypot status via GoPlus API"""
        print(f"  Checking honeypots for {len(records)} tokens...")
        
        for i, record in enumerate(records):
            try:
                await self.rate_limit(0.5)  # GoPlus rate limit
                url = f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={record.token_address}"
                
                async with self.session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    
                    data = await resp.json()
                    result = data.get("result", {}).get(record.token_address.lower(), {})
                    
                    is_honeypot = result.get("is_honeypot") == "1"
                    buy_tax = float(result.get("buy_tax", 0) or 0)
                    sell_tax = float(result.get("sell_tax", 0) or 0)
                    
                    if is_honeypot or sell_tax > 0.5:  # >50% sell tax = honeypot
                        record.is_honeypot = True
                
                if (i + 1) % 20 == 0:
                    print(f"\r  Progress: {(i+1)/len(records)*100:.1f}%", end="")
                
            except:
                continue
        
        print(f"\n  Honeypot check complete")
    
    def aggregate_deployer_stats(self, records: List[TokenRecord]):
        """Aggregate token records into deployer stats"""
        print(f"  Aggregating stats for {len(records)} tokens...")
        
        for record in records:
            deployer = record.deployer
            if not deployer:
                continue
            
            if deployer not in self.deployers:
                self.deployers[deployer] = DeployerStats(address=deployer)
            
            stats = self.deployers[deployer]
            stats.total_tokens += 1
            stats.tokens.append(record)
            
            if record.is_honeypot:
                stats.honeypot_tokens += 1
            if record.is_rugged:
                stats.rugged_tokens += 1
            if record.is_successful:
                stats.successful_tokens += 1
            
            stats.total_lifespan_hours += record.lifespan_hours
            
            if stats.first_seen_block == 0 or record.creation_block < stats.first_seen_block:
                stats.first_seen_block = record.creation_block
            if record.creation_block > stats.last_seen_block:
                stats.last_seen_block = record.creation_block
        
        print(f"  Found {len(self.deployers)} unique deployers")
    
    def export_csv(self, output_path: str):
        """Export deployer stats to CSV"""
        print(f"  Exporting to {output_path}...")
        
        # Sort by total tokens (most active first)
        sorted_deployers = sorted(
            self.deployers.values(),
            key=lambda x: x.total_tokens,
            reverse=True
        )
        
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "deployer",
                "total_tokens",
                "rugged",
                "honeypots",
                "successful",
                "avg_lifespan_hours",
                "success_rate",
                "rug_rate",
                "score",
                "first_seen_block",
                "last_seen_block"
            ])
            
            for stats in sorted_deployers:
                writer.writerow([
                    stats.address,
                    stats.total_tokens,
                    stats.rugged_tokens,
                    stats.honeypot_tokens,
                    stats.successful_tokens,
                    f"{stats.avg_lifespan_hours:.2f}",
                    f"{stats.success_rate:.4f}",
                    f"{stats.rug_rate:.4f}",
                    f"{stats.compute_score():.2f}",
                    stats.first_seen_block,
                    stats.last_seen_block
                ])
        
        print(f"  Exported {len(sorted_deployers)} deployers")
        
        # Print summary
        total_scammers = sum(1 for s in sorted_deployers if s.compute_score() < -50)
        total_suspicious = sum(1 for s in sorted_deployers if -50 <= s.compute_score() < 0)
        total_neutral = sum(1 for s in sorted_deployers if 0 <= s.compute_score() < 30)
        total_legit = sum(1 for s in sorted_deployers if s.compute_score() >= 30)
        
        print(f"\n  Summary:")
        print(f"  ├─ Known scammers (score < -50):  {total_scammers}")
        print(f"  ├─ Suspicious (score -50 to 0):   {total_suspicious}")
        print(f"  ├─ Neutral (score 0 to 30):       {total_neutral}")
        print(f"  └─ Legit (score >= 30):           {total_legit}")
        
        # Export token-to-deployer mapping for C++ backtester
        token_map_path = output_path.replace(".csv", "_tokens.csv")
        with open(token_map_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["token", "deployer", "score"])
            for stats in sorted_deployers:
                score = stats.compute_score()
                for token in stats.tokens:
                    writer.writerow([token.token_address, stats.address, f"{score:.2f}"])
        print(f"  Token mapping: {token_map_path}")
    
    async def run(self, days: int, output_path: str, skip_honeypot_check: bool = False):
        """Run the full pipeline"""
        self.session = aiohttp.ClientSession()
        
        try:
            print(f"\n{'='*60}")
            print(f"  DEPLOYER REPUTATION DATABASE BUILDER")
            print(f"{'='*60}")
            print(f"  Period: Last {days} days")
            print(f"  Output: {output_path}")
            print(f"{'='*60}\n")
            
            # Get block range
            current_block = await self.get_latest_block()
            start_block = current_block - (days * BLOCKS_PER_DAY)
            
            print(f"[1/5] Fetching PairCreated events...")
            pairs = await self.fetch_pair_created_events(start_block, current_block)
            
            if not pairs:
                print("No pairs found!")
                return
            
            print(f"\n[2/5] Getting deployer wallets...")
            records = await self.get_deployers_for_pairs(pairs)
            
            print(f"\n[3/5] Enriching token outcomes...")
            await self.enrich_token_outcomes(records)
            
            if not skip_honeypot_check:
                print(f"\n[4/5] Checking honeypots (this takes a while)...")
                await self.check_honeypots(records)
            else:
                print(f"\n[4/5] Skipping honeypot check (--skip-honeypot)")
            
            print(f"\n[5/5] Aggregating deployer stats...")
            self.aggregate_deployer_stats(records)
            
            print(f"\n[Done] Exporting CSV...")
            self.export_csv(output_path)
            
            print(f"\n{'='*60}")
            print(f"  BUILD COMPLETE")
            print(f"{'='*60}")
            print(f"  Total pairs processed:  {len(pairs)}")
            print(f"  Unique deployers:       {len(self.deployers)}")
            print(f"  Output file:            {output_path}")
            print(f"{'='*60}\n")
            
        finally:
            await self.session.close()


async def main():
    parser = argparse.ArgumentParser(description="Build deployer reputation database")
    parser.add_argument("--days", type=int, default=7, help="Number of days to analyze")
    parser.add_argument("--output", type=str, default="data/deployers.csv", help="Output CSV path")
    parser.add_argument("--skip-honeypot", action="store_true", help="Skip honeypot check (faster)")
    args = parser.parse_args()
    
    builder = DeployerDBBuilder()
    await builder.run(args.days, args.output, args.skip_honeypot)


if __name__ == "__main__":
    asyncio.run(main())
