#!/usr/bin/env python3
"""
Lumina BSC — Migration Sniper Backtester

Backtest your sniper strategy on historical BSC data.

Usage:
    # Backtest last 24 hours
    python scripts/backtest_sniper.py --hours 24

    # Backtest specific date range
    python scripts/backtest_sniper.py --start 2024-03-01 --end 2024-03-07

    # Backtest with custom parameters
    python scripts/backtest_sniper.py --hours 48 --amount 0.05 --min-liq 1.0

    # Export detailed results
    python scripts/backtest_sniper.py --hours 24 --export results.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple
import aiohttp

# BSC RPC - prefer QuickNode from env, fallback to public
BSC_RPC = os.environ.get(
    "QUICK_NODE_BSC_RPC",
    "https://bsc-dataseed.binance.org/"
)

# DexScreener API (free, 60 req/min)
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"

# PancakeSwap addresses
PANCAKE_FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

# Event signatures
PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
SYNC_TOPIC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"

# BSC block time ~3 seconds
BLOCKS_PER_HOUR = 1200
BLOCKS_PER_DAY = 28800


class SnipeStatus(Enum):
    CONFIRMED = "CONFIRMED"
    HONEYPOT = "HONEYPOT"
    RUGGED = "RUGGED"
    PROFIT = "PROFIT"
    LOSS = "LOSS"
    HOLDING = "HOLDING"


@dataclass
class BacktestSnipe:
    """Single backtest snipe record"""
    token_address: str
    token_symbol: str = ""
    pair_address: str = ""
    
    # Block info
    creation_block: int = 0
    creation_timestamp: int = 0
    
    # Entry
    entry_bnb: float = 0.0
    entry_price_bnb: float = 0.0  # Price in BNB per token
    initial_liq_bnb: float = 0.0
    
    # Price tracking
    price_at_1h: float = 0.0
    price_at_4h: float = 0.0
    price_at_24h: float = 0.0
    peak_price: float = 0.0
    final_price: float = 0.0
    
    # Multiples
    multiple_1h: float = 0.0
    multiple_4h: float = 0.0
    multiple_24h: float = 0.0
    peak_multiple: float = 0.0
    
    # Status
    status: SnipeStatus = SnipeStatus.CONFIRMED
    is_honeypot: bool = False
    buy_tax: float = 0.0
    sell_tax: float = 0.0
    
    # P&L (assuming sell at peak or final)
    pnl_at_peak_bnb: float = 0.0
    pnl_at_1h_bnb: float = 0.0
    pnl_at_4h_bnb: float = 0.0
    pnl_at_24h_bnb: float = 0.0


@dataclass
class BacktestMetrics:
    """Aggregated backtest metrics"""
    total_pairs: int = 0
    filtered_pairs: int = 0  # After min liquidity filter
    honeypots: int = 0
    rugged: int = 0
    
    # Hit rates
    hit_2x_1h: int = 0
    hit_2x_4h: int = 0
    hit_2x_24h: int = 0
    hit_5x_1h: int = 0
    hit_5x_4h: int = 0
    hit_5x_24h: int = 0
    hit_10x_24h: int = 0
    
    # P&L scenarios
    total_invested_bnb: float = 0.0
    pnl_sell_at_2x_bnb: float = 0.0      # Sell when hit 2x, else hold
    pnl_sell_at_peak_bnb: float = 0.0    # Perfect timing (unrealistic)
    pnl_sell_at_1h_bnb: float = 0.0      # Sell after 1 hour
    pnl_sell_at_4h_bnb: float = 0.0      # Sell after 4 hours
    pnl_sell_at_24h_bnb: float = 0.0     # Sell after 24 hours
    
    # Best/worst
    best_multiple: float = 0.0
    best_token: str = ""
    worst_multiple: float = float('inf')
    worst_token: str = ""
    
    @property
    def success_rate(self) -> float:
        return (self.filtered_pairs - self.honeypots) / self.filtered_pairs if self.filtered_pairs > 0 else 0
    
    @property
    def honeypot_rate(self) -> float:
        return self.honeypots / self.filtered_pairs if self.filtered_pairs > 0 else 0
    
    @property
    def rug_rate(self) -> float:
        valid = self.filtered_pairs - self.honeypots
        return self.rugged / valid if valid > 0 else 0
    
    @property
    def hit_2x_1h_rate(self) -> float:
        valid = self.filtered_pairs - self.honeypots
        return self.hit_2x_1h / valid if valid > 0 else 0
    
    @property
    def hit_2x_4h_rate(self) -> float:
        valid = self.filtered_pairs - self.honeypots
        return self.hit_2x_4h / valid if valid > 0 else 0
    
    @property
    def hit_5x_24h_rate(self) -> float:
        valid = self.filtered_pairs - self.honeypots
        return self.hit_5x_24h / valid if valid > 0 else 0
    
    def roi(self, strategy: str) -> float:
        if self.total_invested_bnb == 0:
            return 0
        pnl = getattr(self, f"pnl_{strategy}_bnb", 0)
        return (pnl / self.total_invested_bnb) * 100


class MigrationBacktester:
    def __init__(
        self,
        snipe_amount_bnb: float = 0.01,
        min_liquidity_bnb: float = 0.5,
        max_buy_tax: float = 0.10,
        max_sell_tax: float = 0.15,
    ):
        self.snipe_amount_bnb = snipe_amount_bnb
        self.min_liquidity_bnb = min_liquidity_bnb
        self.max_buy_tax = max_buy_tax
        self.max_sell_tax = max_sell_tax
        
        self.snipes: List[BacktestSnipe] = []
        self.metrics = BacktestMetrics()
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Rate limiting
        self.request_count = 0
        self.last_request_time = 0
    
    async def run(
        self,
        start_block: Optional[int] = None,
        end_block: Optional[int] = None,
        hours: Optional[int] = None,
    ):
        """Run backtest for specified block range or hours"""
        self.session = aiohttp.ClientSession()
        
        try:
            # Determine block range
            current_block = await self.get_latest_block()
            
            if hours:
                end_block = current_block
                start_block = current_block - (hours * BLOCKS_PER_HOUR)
            elif start_block is None:
                # Default: last 24 hours
                end_block = current_block
                start_block = current_block - BLOCKS_PER_DAY
            
            total_blocks = end_block - start_block
            
            print(f"\n{'='*70}")
            print(f"  MIGRATION SNIPER BACKTESTER")
            print(f"{'='*70}")
            print(f"  Block Range: {start_block:,} → {end_block:,} ({total_blocks:,} blocks)")
            print(f"  Approx Time: {total_blocks / BLOCKS_PER_HOUR:.1f} hours")
            print(f"  Snipe Amount: {self.snipe_amount_bnb} BNB")
            print(f"  Min Liquidity: {self.min_liquidity_bnb} BNB")
            print(f"  Max Buy Tax: {self.max_buy_tax*100:.0f}%")
            print(f"  Max Sell Tax: {self.max_sell_tax*100:.0f}%")
            print(f"{'='*70}\n")
            
            # Step 1: Fetch all PairCreated events
            print("[1/3] Fetching new pairs from DexScreener...")
            pairs = await self.fetch_pair_created_events(start_block, end_block)
            self.metrics.total_pairs = len(pairs)
            print(f"      Found {len(pairs)} new pairs")
            
            if len(pairs) == 0:
                print("\n[!] No pairs found in this range. Try a longer time period.")
                return
            
            # Step 2: Filter by liquidity and get initial data
            print("\n[2/3] Analyzing pairs and filtering...")
            filtered_pairs = await self.analyze_pairs(pairs)
            self.metrics.filtered_pairs = len(filtered_pairs)
            print(f"      {len(filtered_pairs)} pairs passed filters")
            
            if len(filtered_pairs) == 0:
                print("\n[!] No pairs passed filters. Try lowering min_liquidity.")
                return
            
            # Step 3: Calculate metrics (DexScreener already gave us price history)
            print("\n[3/3] Calculating metrics...")
            self.calculate_metrics()
            
            # Print results
            self.print_results()
            
        finally:
            await self.session.close()
    
    async def fetch_pair_created_events(
        self, start_block: int, end_block: int
    ) -> List[dict]:
        """Fetch new BSC pairs - use QuickNode RPC for longer periods, DexScreener for short"""
        pairs = []
        
        # Calculate time range from blocks
        hours_back = (end_block - start_block) * 3 / 3600
        
        # For periods > 48h, use QuickNode RPC (more comprehensive)
        if hours_back > 48 and "quiknode" in BSC_RPC.lower():
            return await self.fetch_pairs_from_rpc(start_block, end_block, hours_back)
        
        print(f"      Using DexScreener API (last {hours_back:.1f}h of pairs)...")
        
        try:
            # DexScreener: Search for new BSC pairs on PancakeSwap
            # The search endpoint returns recently active pairs
            url = "https://api.dexscreener.com/latest/dex/search?q=pancakeswap"
            
            await self.rate_limit()
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    print(f"\n      DexScreener error: {resp.status}")
                    return pairs
                
                data = await resp.json()
                all_pairs = data.get("pairs", [])
                print(f"      Found {len(all_pairs)} total pairs from DexScreener")
                
                # Filter by chain and creation time
                now_ms = int(time.time() * 1000)
                cutoff_ms = now_ms - int(hours_back * 3600 * 1000)
                
                for pair in all_pairs:
                    try:
                        # Only BSC pairs
                        if pair.get("chainId") != "bsc":
                            continue
                        
                        # Check creation time (if available)
                        pair_created = pair.get("pairCreatedAt", 0)
                        if pair_created and pair_created < cutoff_ms:
                            continue
                        
                        # Get base and quote tokens
                        base_token = pair.get("baseToken", {})
                        quote_token = pair.get("quoteToken", {})
                        base_symbol = base_token.get("symbol", "").upper()
                        quote_symbol = quote_token.get("symbol", "").upper()
                        
                        # We want pairs where one side is WBNB/BNB
                        # The "new token" is the other side
                        if quote_symbol in ["WBNB", "BNB"]:
                            token_address = base_token.get("address", "")
                            token_symbol = base_symbol
                        elif base_symbol in ["WBNB", "BNB"]:
                            token_address = quote_token.get("address", "")
                            token_symbol = quote_symbol
                        else:
                            continue  # Not a BNB pair
                        
                        pair_address = pair.get("pairAddress", "")
                        if not token_address or not pair_address:
                            continue
                        
                        # Skip WBNB itself
                        if token_symbol in ["WBNB", "BNB"]:
                            continue
                        
                        # Get liquidity
                        liquidity = pair.get("liquidity", {})
                        liq_usd = float(liquidity.get("usd", 0) or 0)
                        
                        # Get price changes
                        price_change = pair.get("priceChange", {}) or {}
                        
                        pairs.append({
                            "token": token_address,
                            "pair": pair_address,
                            "block": 0,
                            "token0": WBNB,
                            "symbol": token_symbol,
                            "liquidity_usd": liq_usd,
                            "created_at": pair_created or now_ms,
                            "price_usd": float(pair.get("priceUsd") or 0),
                            "price_change_1h": float(price_change.get("h1") or 0),
                            "price_change_24h": float(price_change.get("h24") or 0),
                            "volume_24h": float((pair.get("volume") or {}).get("h24") or 0),
                            "txns_24h": ((pair.get("txns") or {}).get("h24") or {}).get("buys", 0) + 
                                       ((pair.get("txns") or {}).get("h24") or {}).get("sells", 0),
                        })
                        
                    except Exception as e:
                        continue
                
                print(f"      Filtered to {len(pairs)} BSC token/BNB pairs")
                
        except Exception as e:
            print(f"\n      Error: {e}")
        
        return pairs
    
    async def fetch_pairs_from_rpc(
        self, start_block: int, end_block: int, hours_back: float
    ) -> List[dict]:
        """Fetch PairCreated events directly from QuickNode RPC (for longer backtests)"""
        pairs = []
        seen_pairs = set()
        
        print(f"      Using QuickNode RPC (last {hours_back:.1f}h = {hours_back/24:.1f} days)...")
        print(f"      Fetching blocks {start_block:,} → {end_block:,}...")
        
        chunk_size = 2000
        current = start_block
        total_chunks = (end_block - start_block) // chunk_size + 1
        chunk_num = 0
        
        while current < end_block:
            chunk_end = min(current + chunk_size, end_block)
            chunk_num += 1
            
            try:
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
                
                await self.rate_limit()
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
                            
                            if pair_address in seen_pairs:
                                continue
                            seen_pairs.add(pair_address)
                            
                            # Only BNB pairs
                            if token0.lower() == WBNB.lower():
                                token_address = token1
                            elif token1.lower() == WBNB.lower():
                                token_address = token0
                            else:
                                continue
                            
                            pairs.append({
                                "token": token_address,
                                "pair": pair_address,
                                "block": block_num,
                                "token0": token0,
                                "symbol": "???",
                                "liquidity_usd": 0,
                                "created_at": 0,
                                "price_usd": 0,
                                "price_change_1h": 0,
                                "price_change_24h": 0,
                                "from_rpc": True,
                            })
                        except:
                            continue
                
                progress = chunk_num / total_chunks * 100
                print(f"\r      Progress: {progress:.1f}% ({len(pairs)} BNB pairs found)", end="")
                
            except Exception as e:
                await asyncio.sleep(0.5)
            
            current = chunk_end
        
        print(f"\n      Found {len(pairs)} new BNB pairs from RPC")
        
        # Enrich with DexScreener data
        if pairs:
            print("      Enriching with DexScreener price data...")
            await self.enrich_pairs_with_dexscreener(pairs)
        
        return pairs
    
    async def enrich_pairs_with_dexscreener(self, pairs: List[dict]):
        """Add price data from DexScreener for RPC-fetched pairs"""
        # Stablecoins and known tokens to skip
        SKIP_TOKENS = {
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
            "0x55d398326f99059ff775485246999027b3197955",  # USDT
            "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
            "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
            "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3",  # DAI
        }
        
        to_remove = []
        for i, pair in enumerate(pairs):
            # Filter stablecoins
            if pair["token"].lower() in SKIP_TOKENS:
                to_remove.append(i)
                continue
            
            try:
                url = f"https://api.dexscreener.com/latest/dex/pairs/bsc/{pair['pair']}"
                await self.rate_limit()
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pair_data = data.get("pair") or (data.get("pairs", [{}])[0] if data.get("pairs") else {})
                        if pair_data:
                            pair["symbol"] = pair_data.get("baseToken", {}).get("symbol", "???")
                            pair["liquidity_usd"] = float((pair_data.get("liquidity") or {}).get("usd") or 0)
                            pair["price_usd"] = float(pair_data.get("priceUsd") or 0)
                            pc = pair_data.get("priceChange") or {}
                            
                            # Validate price change values — DexScreener returns
                            # garbage for new tokens (e.g. 15 quadrillion %)
                            raw_1h = float(pc.get("h1") or 0)
                            raw_24h = float(pc.get("h24") or 0)
                            pair["price_change_1h"] = raw_1h if abs(raw_1h) <= 10000 else 0
                            pair["price_change_24h"] = raw_24h if abs(raw_24h) <= 10000 else 0
                            
                            # Volume and age for additional validation
                            pair["volume_24h"] = float((pair_data.get("volume") or {}).get("h24") or 0)
                            pair["created_at"] = pair_data.get("pairCreatedAt", 0)
                            txns = pair_data.get("txns", {}).get("h24", {})
                            pair["txns_24h"] = (txns.get("buys", 0) or 0) + (txns.get("sells", 0) or 0)
                            # Store raw buy/sell counts for buy pressure calculation
                            pair["txns_raw"] = {
                                "buys": txns.get("buys", 0) or 0,
                                "sells": txns.get("sells", 0) or 0
                            }
                
                if (i + 1) % 10 == 0:
                    print(f"\r      Enriched {i+1}/{len(pairs)} pairs", end="")
                
                await asyncio.sleep(0.2)  # Rate limit DexScreener
            except:
                continue
        
        # Remove stablecoins (reverse order to preserve indices)
        for idx in reversed(to_remove):
            pairs.pop(idx)
        
        print(f"\r      Enriched {len(pairs)}/{len(pairs)} pairs")
    
    async def analyze_pairs(self, pairs: List[dict]) -> List[BacktestSnipe]:
        """Analyze pairs and filter by criteria (using DexScreener data)"""
        filtered = []
        bnb_price = await self.get_bnb_price()
        now_ms = int(time.time() * 1000)
        
        for i, pair_data in enumerate(pairs):
            try:
                # DexScreener already gives us most data
                liq_usd = pair_data.get("liquidity_usd", 0)
                liq_bnb = liq_usd / bnb_price if bnb_price > 0 else 0
                
                # Filter by minimum liquidity
                if liq_bnb < self.min_liquidity_bnb:
                    continue
                
                # Skip tokens with no DexScreener data
                price_usd = pair_data.get("price_usd", 0)
                if price_usd <= 0:
                    continue
                
                # Minimum transactions (at least some activity)
                txns_24h = pair_data.get("txns_24h", 0)
                if txns_24h < 5:
                    continue
                
                snipe = BacktestSnipe(
                    token_address=pair_data["token"],
                    pair_address=pair_data["pair"],
                    creation_block=pair_data.get("block", 0),
                    creation_timestamp=pair_data.get("created_at", 0),
                    token_symbol=pair_data.get("symbol", "???"),
                    initial_liq_bnb=liq_bnb,
                )
                
                snipe.entry_price_bnb = price_usd / bnb_price
                snipe.entry_bnb = self.snipe_amount_bnb
                
                # Use DexScreener price changes as proxy for historical performance
                # price_change_1h and price_change_24h are percentages
                price_change_1h = pair_data.get("price_change_1h", 0)
                price_change_24h = pair_data.get("price_change_24h", 0)
                
                # Check token age — if created less than 24h ago, the "24h change"
                # is actually "change since creation" which is unreliable
                created_at = pair_data.get("created_at", 0)
                token_age_hours = (now_ms - created_at) / (3600 * 1000) if created_at > 0 else 999
                
                # If token is less than 1h old, h1 data is unreliable
                if token_age_hours < 1:
                    price_change_1h = 0
                # If token is less than 24h old, h24 data is unreliable
                if token_age_hours < 24:
                    price_change_24h = price_change_1h  # Use 1h as best estimate
                
                # Calculate what entry price would have been
                # If current price is P and 24h change is +100%, entry was P/2
                if price_change_24h != 0 and price_change_24h > -100:
                    entry_multiplier = 100 / (100 + price_change_24h)
                    snipe.entry_price_bnb = snipe.entry_price_bnb * entry_multiplier
                
                # Current price is the "final" price for backtesting
                snipe.final_price = price_usd / bnb_price
                snipe.price_at_24h = snipe.final_price
                
                # Calculate multiples from price changes
                # Cap at 100x — anything higher is almost certainly a data error
                # Real BSC tokens rarely sustain >100x in 24h
                MAX_MULTIPLE = 100.0
                
                if price_change_24h > -100:
                    snipe.multiple_24h = min((100 + price_change_24h) / 100, MAX_MULTIPLE)
                if price_change_1h > -100:
                    snipe.multiple_1h = min((100 + price_change_1h) / 100, MAX_MULTIPLE)
                
                # Sanity check: if multiple is negative or zero, set to 1
                if snipe.multiple_24h <= 0:
                    snipe.multiple_24h = 1.0
                if snipe.multiple_1h <= 0:
                    snipe.multiple_1h = 1.0
                
                # 4h estimate: weighted interpolation between 1h and 24h
                # Weight 1h more heavily since 4h is closer to 1h than 24h
                snipe.multiple_4h = snipe.multiple_1h * 0.6 + snipe.multiple_24h * 0.4
                
                snipe.peak_multiple = max(snipe.multiple_24h, snipe.multiple_1h, 1.0)
                snipe.peak_price = snipe.entry_price_bnb * snipe.peak_multiple
                
                # Check honeypot via GoPlus
                honeypot_data = await self.check_honeypot(pair_data["token"])
                snipe.is_honeypot = honeypot_data.get("is_honeypot", False)
                snipe.buy_tax = honeypot_data.get("buy_tax", 0)
                snipe.sell_tax = honeypot_data.get("sell_tax", 0)
                
                if snipe.is_honeypot:
                    snipe.status = SnipeStatus.HONEYPOT
                    self.metrics.honeypots += 1
                elif snipe.buy_tax > self.max_buy_tax or snipe.sell_tax > self.max_sell_tax:
                    continue
                
                # Check for rug (>90% drop)
                if snipe.multiple_24h < 0.1:
                    snipe.status = SnipeStatus.RUGGED
                    self.metrics.rugged += 1
                
                # Calculate P&L
                snipe.pnl_at_peak_bnb = snipe.entry_bnb * (snipe.peak_multiple - 1)
                snipe.pnl_at_24h_bnb = snipe.entry_bnb * (snipe.multiple_24h - 1)
                snipe.pnl_at_1h_bnb = snipe.entry_bnb * (snipe.multiple_1h - 1) if snipe.multiple_1h > 0 else -snipe.entry_bnb
                snipe.pnl_at_4h_bnb = snipe.entry_bnb * (snipe.multiple_4h - 1) if snipe.multiple_4h > 0 else -snipe.entry_bnb
                
                filtered.append(snipe)
                self.snipes.append(snipe)
                
                # Progress
                if (i + 1) % 10 == 0:
                    print(f"\r      Analyzed {i+1}/{len(pairs)} pairs, {len(filtered)} passed", end="")
                
                # Rate limit GoPlus API
                await asyncio.sleep(0.5)
                
            except Exception as e:
                pass
        
        print(f"\r      Analyzed {len(pairs)}/{len(pairs)} pairs, {len(filtered)} passed")
        return filtered
    
    async def get_bnb_price(self) -> float:
        """Get current BNB price in USD"""
        try:
            url = "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT"
            async with self.session.get(url) as resp:
                data = await resp.json()
                return float(data.get("price", 600))
        except:
            return 600.0  # Fallback
    
    async def track_price_history(
        self, snipes: List[BacktestSnipe], end_block: int
    ):
        """Track price at 1h, 4h, 24h after creation"""
        for i, snipe in enumerate(snipes):
            if snipe.is_honeypot:
                continue
            
            try:
                creation_block = snipe.creation_block
                
                # Get prices at different times
                blocks_1h = creation_block + BLOCKS_PER_HOUR
                blocks_4h = creation_block + (4 * BLOCKS_PER_HOUR)
                blocks_24h = creation_block + BLOCKS_PER_DAY
                
                # Track peak price (sample every 10 minutes)
                peak_price = snipe.entry_price_bnb
                sample_interval = 200  # ~10 minutes
                
                current_block = creation_block
                while current_block <= min(blocks_24h, end_block):
                    reserves = await self.get_reserves_at_block(
                        snipe.pair_address, current_block, 
                        WBNB if snipe.token_address.lower() != WBNB.lower() else snipe.token_address
                    )
                    
                    if reserves:
                        bnb_reserve, token_reserve = reserves
                        if token_reserve > 0:
                            price = bnb_reserve / token_reserve
                            
                            # Check for rug (liquidity dropped >90%)
                            if bnb_reserve < snipe.initial_liq_bnb * 0.1:
                                snipe.status = SnipeStatus.RUGGED
                                self.metrics.rugged += 1
                                break
                            
                            if price > peak_price:
                                peak_price = price
                            
                            # Record at milestones
                            if current_block >= blocks_1h and snipe.price_at_1h == 0:
                                snipe.price_at_1h = price
                            if current_block >= blocks_4h and snipe.price_at_4h == 0:
                                snipe.price_at_4h = price
                            if current_block >= blocks_24h and snipe.price_at_24h == 0:
                                snipe.price_at_24h = price
                    
                    current_block += sample_interval
                
                snipe.peak_price = peak_price
                snipe.final_price = snipe.price_at_24h if snipe.price_at_24h > 0 else peak_price
                
                # Calculate multiples
                if snipe.entry_price_bnb > 0:
                    snipe.peak_multiple = peak_price / snipe.entry_price_bnb
                    if snipe.price_at_1h > 0:
                        snipe.multiple_1h = snipe.price_at_1h / snipe.entry_price_bnb
                    if snipe.price_at_4h > 0:
                        snipe.multiple_4h = snipe.price_at_4h / snipe.entry_price_bnb
                    if snipe.price_at_24h > 0:
                        snipe.multiple_24h = snipe.price_at_24h / snipe.entry_price_bnb
                
                # Calculate P&L
                snipe.pnl_at_peak_bnb = snipe.entry_bnb * (snipe.peak_multiple - 1)
                snipe.pnl_at_1h_bnb = snipe.entry_bnb * (snipe.multiple_1h - 1) if snipe.multiple_1h > 0 else -snipe.entry_bnb
                snipe.pnl_at_4h_bnb = snipe.entry_bnb * (snipe.multiple_4h - 1) if snipe.multiple_4h > 0 else -snipe.entry_bnb
                snipe.pnl_at_24h_bnb = snipe.entry_bnb * (snipe.multiple_24h - 1) if snipe.multiple_24h > 0 else -snipe.entry_bnb
                
                self.snipes.append(snipe)
                
            except Exception as e:
                pass
            
            # Progress
            if (i + 1) % 5 == 0:
                print(f"\r      Tracked {i+1}/{len(snipes)} tokens", end="")
        
        print(f"\r      Tracked {len(snipes)}/{len(snipes)} tokens")
    
    def calculate_metrics(self):
        """Calculate final metrics from all snipes"""
        for snipe in self.snipes:
            if snipe.is_honeypot:
                continue
            
            self.metrics.total_invested_bnb += snipe.entry_bnb
            
            # Hit rates
            if snipe.multiple_1h >= 2.0:
                self.metrics.hit_2x_1h += 1
            if snipe.multiple_4h >= 2.0:
                self.metrics.hit_2x_4h += 1
            if snipe.multiple_24h >= 2.0:
                self.metrics.hit_2x_24h += 1
            
            if snipe.multiple_1h >= 5.0:
                self.metrics.hit_5x_1h += 1
            if snipe.multiple_4h >= 5.0:
                self.metrics.hit_5x_4h += 1
            if snipe.multiple_24h >= 5.0:
                self.metrics.hit_5x_24h += 1
            
            if snipe.multiple_24h >= 10.0:
                self.metrics.hit_10x_24h += 1
            
            # P&L scenarios
            self.metrics.pnl_sell_at_peak_bnb += snipe.pnl_at_peak_bnb
            self.metrics.pnl_sell_at_1h_bnb += snipe.pnl_at_1h_bnb
            self.metrics.pnl_sell_at_4h_bnb += snipe.pnl_at_4h_bnb
            self.metrics.pnl_sell_at_24h_bnb += snipe.pnl_at_24h_bnb
            
            # Sell at 2x strategy
            if snipe.peak_multiple >= 2.0:
                self.metrics.pnl_sell_at_2x_bnb += snipe.entry_bnb  # 2x = 100% profit
            else:
                self.metrics.pnl_sell_at_2x_bnb += snipe.pnl_at_24h_bnb  # Hold if no 2x
            
            # Best/worst
            if snipe.peak_multiple > self.metrics.best_multiple:
                self.metrics.best_multiple = snipe.peak_multiple
                self.metrics.best_token = f"{snipe.token_symbol} ({snipe.token_address[:10]}...)"
            if snipe.peak_multiple < self.metrics.worst_multiple:
                self.metrics.worst_multiple = snipe.peak_multiple
                self.metrics.worst_token = f"{snipe.token_symbol} ({snipe.token_address[:10]}...)"
    
    def print_results(self):
        """Print backtest results"""
        m = self.metrics
        valid = m.filtered_pairs - m.honeypots
        
        print(f"\n{'='*70}")
        print(f"  BACKTEST RESULTS")
        print(f"{'='*70}")
        
        print(f"\n  PAIRS ANALYZED:")
        print(f"  ├─ Total pairs found:     {m.total_pairs}")
        print(f"  ├─ Passed filters:        {m.filtered_pairs}")
        print(f"  ├─ Honeypots:             {m.honeypots} ({m.honeypot_rate*100:.1f}%)")
        print(f"  └─ Rugged:                {m.rugged} ({m.rug_rate*100:.1f}%)")
        
        print(f"\n  HIT RATES (of {valid} valid snipes):")
        print(f"  ┌─────────────┬──────────┬──────────┬──────────┐")
        print(f"  │  Multiple   │   1 Hour │  4 Hours │ 24 Hours │")
        print(f"  ├─────────────┼──────────┼──────────┼──────────┤")
        print(f"  │  2x hit     │ {m.hit_2x_1h:>4} ({m.hit_2x_1h_rate*100:>4.1f}%) │ {m.hit_2x_4h:>4} ({m.hit_2x_4h_rate*100:>4.1f}%) │ {m.hit_2x_24h:>4} ({m.hit_2x_24h/valid*100 if valid else 0:>4.1f}%) │")
        print(f"  │  5x hit     │ {m.hit_5x_1h:>4}        │ {m.hit_5x_4h:>4}        │ {m.hit_5x_24h:>4} ({m.hit_5x_24h_rate*100:>4.1f}%) │")
        print(f"  │  10x hit    │     -    │     -    │ {m.hit_10x_24h:>4}        │")
        print(f"  └─────────────┴──────────┴──────────┴──────────┘")
        
        print(f"\n  P&L BY EXIT STRATEGY (invested {m.total_invested_bnb:.4f} BNB):")
        print(f"  ┌─────────────────────┬─────────────┬──────────┐")
        print(f"  │  Strategy           │  P&L (BNB)  │   ROI    │")
        print(f"  ├─────────────────────┼─────────────┼──────────┤")
        print(f"  │  Sell at 2x         │ {m.pnl_sell_at_2x_bnb:>+10.4f}  │ {m.roi('sell_at_2x'):>+7.1f}% │")
        print(f"  │  Sell at 1h         │ {m.pnl_sell_at_1h_bnb:>+10.4f}  │ {m.roi('sell_at_1h'):>+7.1f}% │")
        print(f"  │  Sell at 4h         │ {m.pnl_sell_at_4h_bnb:>+10.4f}  │ {m.roi('sell_at_4h'):>+7.1f}% │")
        print(f"  │  Sell at 24h        │ {m.pnl_sell_at_24h_bnb:>+10.4f}  │ {m.roi('sell_at_24h'):>+7.1f}% │")
        print(f"  │  Perfect timing*    │ {m.pnl_sell_at_peak_bnb:>+10.4f}  │ {m.roi('sell_at_peak'):>+7.1f}% │")
        print(f"  └─────────────────────┴─────────────┴──────────┘")
        print(f"  * Perfect timing = sell at peak (unrealistic)")
        
        print(f"\n  NOTABLE TRADES:")
        print(f"  ├─ Best:  {m.best_token} → {m.best_multiple:.1f}x")
        print(f"  └─ Worst: {m.worst_token} → {m.worst_multiple:.2f}x")
        
        # Top performers
        top_snipes = sorted(
            [s for s in self.snipes if not s.is_honeypot],
            key=lambda x: x.peak_multiple,
            reverse=True
        )[:5]
        
        if top_snipes:
            print(f"\n  TOP 5 PERFORMERS:")
            for i, s in enumerate(top_snipes, 1):
                print(f"  {i}. {s.token_symbol:>10} │ {s.peak_multiple:>6.1f}x peak │ "
                      f"{s.multiple_1h:>5.1f}x @1h │ Liq: {s.initial_liq_bnb:.2f} BNB")
        
        print(f"\n{'='*70}\n")
    
    def export_results(self, filepath: str):
        """Export results to JSON"""
        data = {
            "backtest_params": {
                "snipe_amount_bnb": self.snipe_amount_bnb,
                "min_liquidity_bnb": self.min_liquidity_bnb,
                "max_buy_tax": self.max_buy_tax,
                "max_sell_tax": self.max_sell_tax,
            },
            "metrics": {
                "total_pairs": self.metrics.total_pairs,
                "filtered_pairs": self.metrics.filtered_pairs,
                "honeypots": self.metrics.honeypots,
                "honeypot_rate": self.metrics.honeypot_rate,
                "rugged": self.metrics.rugged,
                "rug_rate": self.metrics.rug_rate,
                "hit_2x_1h": self.metrics.hit_2x_1h,
                "hit_2x_1h_rate": self.metrics.hit_2x_1h_rate,
                "hit_2x_4h": self.metrics.hit_2x_4h,
                "hit_2x_4h_rate": self.metrics.hit_2x_4h_rate,
                "hit_5x_24h": self.metrics.hit_5x_24h,
                "hit_5x_24h_rate": self.metrics.hit_5x_24h_rate,
                "hit_10x_24h": self.metrics.hit_10x_24h,
                "total_invested_bnb": self.metrics.total_invested_bnb,
                "pnl_sell_at_2x": self.metrics.pnl_sell_at_2x_bnb,
                "pnl_sell_at_1h": self.metrics.pnl_sell_at_1h_bnb,
                "pnl_sell_at_4h": self.metrics.pnl_sell_at_4h_bnb,
                "pnl_sell_at_24h": self.metrics.pnl_sell_at_24h_bnb,
                "roi_sell_at_2x": self.metrics.roi("sell_at_2x"),
                "roi_sell_at_1h": self.metrics.roi("sell_at_1h"),
                "best_multiple": self.metrics.best_multiple,
                "best_token": self.metrics.best_token,
            },
            "snipes": [
                {
                    "token": s.token_address,
                    "symbol": s.token_symbol,
                    "pair": s.pair_address,
                    "block": s.creation_block,
                    "initial_liq_bnb": s.initial_liq_bnb,
                    "entry_price": s.entry_price_bnb,
                    "peak_multiple": s.peak_multiple,
                    "multiple_1h": s.multiple_1h,
                    "multiple_4h": s.multiple_4h,
                    "multiple_24h": s.multiple_24h,
                    "is_honeypot": s.is_honeypot,
                    "status": s.status.value,
                }
                for s in self.snipes
            ]
        }
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        # Export token results .txt
        txt_path = filepath.replace(".json", "_tokens.txt")
        with open(txt_path, "w") as f:
            f.write("token_name, address, result\n")
            for s in self.snipes:
                if s.is_honeypot:
                    result = "HONEYPOT"
                elif s.status == SnipeStatus.RUGGED:
                    result = "RUG"
                else:
                    result = f"{s.peak_multiple:.1f}x"
                f.write(f"{s.token_symbol}, {s.token_address}, {result}\n")
        
        print(f"[Results exported to {filepath}]")
        print(f"[Tokens → {txt_path}]")
    
    # ========== Helper Methods ==========
    
    async def rate_limit(self):
        """Simple rate limiting"""
        self.request_count += 1
        if self.request_count % 10 == 0:
            await asyncio.sleep(0.1)  # 100ms pause every 10 requests
    
    async def get_latest_block(self) -> int:
        """Get latest block number"""
        params = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
        async with self.session.post(BSC_RPC, json=params) as resp:
            data = await resp.json()
            return int(data["result"], 16)
    
    async def get_token_symbol(self, token_address: str) -> str:
        """Get token symbol"""
        try:
            await self.rate_limit()
            params = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": token_address, "data": "0x95d89b41"}, "latest"],
                "id": 1
            }
            async with self.session.post(BSC_RPC, json=params) as resp:
                data = await resp.json()
                result = data.get("result", "0x")
                if len(result) > 130:
                    hex_str = result[130:]
                    return bytes.fromhex(hex_str).decode("utf-8", errors="ignore").strip("\x00")[:10]
        except:
            pass
        return "???"
    
    async def get_reserves_at_block(
        self, pair_address: str, block: int, token0: str
    ) -> Optional[Tuple[float, float]]:
        """Get reserves at specific block"""
        try:
            await self.rate_limit()
            params = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [
                    {"to": pair_address, "data": "0x0902f1ac"},
                    hex(block)
                ],
                "id": 1
            }
            async with self.session.post(BSC_RPC, json=params) as resp:
                data = await resp.json()
                result = data.get("result", "0x")
                if len(result) >= 130:
                    reserve0 = int(result[2:66], 16) / 1e18
                    reserve1 = int(result[66:130], 16) / 1e18
                    
                    # Determine which is BNB
                    if token0.lower() == WBNB.lower():
                        return (reserve0, reserve1)  # (BNB, token)
                    else:
                        return (reserve1, reserve0)  # (BNB, token)
        except:
            pass
        return None
    
    async def check_honeypot(self, token_address: str) -> dict:
        """Check if token is honeypot"""
        try:
            await self.rate_limit()
            url = f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={token_address}"
            async with self.session.get(url) as resp:
                data = await resp.json()
                result = data.get("result", {}).get(token_address.lower(), {})
                return {
                    "is_honeypot": result.get("is_honeypot") == "1",
                    "buy_tax": float(result.get("buy_tax", 0)),
                    "sell_tax": float(result.get("sell_tax", 0)),
                }
        except:
            return {"is_honeypot": False, "buy_tax": 0, "sell_tax": 0}


async def main():
    parser = argparse.ArgumentParser(description="Migration Sniper Backtester")
    parser.add_argument("--hours", type=int, help="Backtest last N hours")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--amount", type=float, default=0.01, help="Snipe amount in BNB")
    parser.add_argument("--min-liq", type=float, default=0.5, help="Min liquidity in BNB")
    parser.add_argument("--max-buy-tax", type=float, default=0.10, help="Max buy tax (0.10 = 10%)")
    parser.add_argument("--max-sell-tax", type=float, default=0.15, help="Max sell tax")
    parser.add_argument("--export", type=str, help="Export results to JSON file")
    args = parser.parse_args()
    
    backtester = MigrationBacktester(
        snipe_amount_bnb=args.amount,
        min_liquidity_bnb=args.min_liq,
        max_buy_tax=args.max_buy_tax,
        max_sell_tax=args.max_sell_tax,
    )
    
    # Determine time range
    hours = args.hours or 24  # Default 24 hours
    
    await backtester.run(hours=hours)
    
    if args.export:
        backtester.export_results(args.export)
    else:
        # Auto-export
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("backtest_results", exist_ok=True)
        backtester.export_results(f"backtest_results/backtest_{timestamp}.json")


if __name__ == "__main__":
    asyncio.run(main())
