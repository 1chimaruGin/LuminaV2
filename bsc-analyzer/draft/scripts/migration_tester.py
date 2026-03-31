#!/usr/bin/env python3
"""
Lumina BSC — Migration Sniper Tester

Tests the sniper on real migrations and tracks performance metrics.

Usage:
    # Dry run mode (no real trades, just track what WOULD happen)
    python scripts/migration_tester.py --dry-run --duration 1h

    # Paper trading mode (track real prices, simulated entries)
    python scripts/migration_tester.py --paper --duration 4h

    # Live mode (actual trades - BE CAREFUL)
    python scripts/migration_tester.py --live --amount 0.01

    # Backtest on historical data
    python scripts/migration_tester.py --backtest --start 2024-01-01 --end 2024-01-07
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable
import aiohttp

# BSC RPC endpoints
BSC_RPC = "https://bsc-dataseed.binance.org/"
BSC_WS = "wss://bsc-ws-node.nariox.org:443"

# PancakeSwap addresses
PANCAKE_ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
PANCAKE_FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

# Event signatures
PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
SYNC_TOPIC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"
MINT_TOPIC = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"


class SnipeStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REVERTED = "REVERTED"
    FRONTRUN = "FRONTRUN"
    HONEYPOT = "HONEYPOT"
    RUGGED = "RUGGED"
    SOLD_PROFIT = "SOLD_PROFIT"
    SOLD_LOSS = "SOLD_LOSS"
    HOLDING = "HOLDING"


@dataclass
class SnipeRecord:
    token_address: str
    token_symbol: str = ""
    pair_address: str = ""
    tx_hash: str = ""
    
    # Timing
    migration_detected_ms: int = 0
    snipe_submitted_ms: int = 0
    snipe_confirmed_ms: int = 0
    block_number: int = 0
    
    # Entry
    entry_bnb: float = 0.0
    entry_tokens: float = 0.0
    entry_price_usd: float = 0.0
    initial_liq_bnb: float = 0.0
    
    # State
    status: SnipeStatus = SnipeStatus.PENDING
    current_price_usd: float = 0.0
    peak_price_usd: float = 0.0
    peak_multiple: float = 0.0
    
    # Exit
    exit_bnb: float = 0.0
    exit_price_usd: float = 0.0
    pnl_bnb: float = 0.0
    pnl_percent: float = 0.0
    
    # Flags
    is_honeypot: bool = False
    buy_tax: float = 0.0
    sell_tax: float = 0.0
    tier1_score: float = 0.0
    
    # Milestones
    time_to_2x_ms: int = 0
    time_to_5x_ms: int = 0
    time_to_10x_ms: int = 0
    
    # Price history for charting
    price_history: List[tuple] = field(default_factory=list)  # [(timestamp_ms, price_usd)]


@dataclass
class PerformanceMetrics:
    total_snipes: int = 0
    confirmed: int = 0
    reverted: int = 0
    frontrun: int = 0
    honeypots: int = 0
    rugged: int = 0
    sold_profit: int = 0
    sold_loss: int = 0
    holding: int = 0
    
    hit_2x: int = 0
    hit_5x: int = 0
    hit_10x: int = 0
    hit_2x_1h: int = 0
    hit_2x_4h: int = 0
    hit_2x_24h: int = 0
    
    total_invested_bnb: float = 0.0
    total_returned_bnb: float = 0.0
    total_pnl_bnb: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    
    @property
    def success_rate(self) -> float:
        return self.confirmed / self.total_snipes if self.total_snipes > 0 else 0
    
    @property
    def honeypot_rate(self) -> float:
        return self.honeypots / self.confirmed if self.confirmed > 0 else 0
    
    @property
    def hit_2x_rate(self) -> float:
        return self.hit_2x / self.confirmed if self.confirmed > 0 else 0
    
    @property
    def hit_5x_rate(self) -> float:
        return self.hit_5x / self.confirmed if self.confirmed > 0 else 0
    
    @property
    def win_rate(self) -> float:
        closed = self.sold_profit + self.sold_loss
        return self.sold_profit / closed if closed > 0 else 0
    
    @property
    def roi(self) -> float:
        return (self.total_pnl_bnb / self.total_invested_bnb * 100) if self.total_invested_bnb > 0 else 0


class MigrationTester:
    def __init__(self, mode: str = "dry-run", snipe_amount_bnb: float = 0.01):
        self.mode = mode
        self.snipe_amount_bnb = snipe_amount_bnb
        self.records: Dict[str, SnipeRecord] = {}
        self.metrics = PerformanceMetrics()
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.bnb_price_usd = 600.0  # Will be updated
        
        # Callbacks
        self.on_migration_detected: Optional[Callable] = None
        self.on_snipe_result: Optional[Callable] = None
        self.on_price_update: Optional[Callable] = None
    
    async def start(self, duration_seconds: int = 3600):
        """Start monitoring for migrations"""
        self.running = True
        self.session = aiohttp.ClientSession()
        
        print(f"\n{'='*60}")
        print(f"  MIGRATION SNIPER TESTER - {self.mode.upper()} MODE")
        print(f"  Duration: {duration_seconds // 3600}h {(duration_seconds % 3600) // 60}m")
        print(f"  Snipe Amount: {self.snipe_amount_bnb} BNB")
        print(f"{'='*60}\n")
        
        # Update BNB price
        await self.update_bnb_price()
        
        # Start tasks
        tasks = [
            asyncio.create_task(self.monitor_new_pairs()),
            asyncio.create_task(self.price_updater()),
            asyncio.create_task(self.stats_printer()),
        ]
        
        # Run for duration
        try:
            await asyncio.sleep(duration_seconds)
        except asyncio.CancelledError:
            pass
        
        self.running = False
        for task in tasks:
            task.cancel()
        
        await self.session.close()
        self.print_final_summary()
    
    async def monitor_new_pairs(self):
        """Monitor for new PancakeSwap pair creations (migrations)"""
        print("[Monitor] Watching for new pair creations...")
        
        last_block = await self.get_latest_block()
        
        while self.running:
            try:
                current_block = await self.get_latest_block()
                
                if current_block > last_block:
                    # Check for PairCreated events
                    for block_num in range(last_block + 1, current_block + 1):
                        await self.check_block_for_migrations(block_num)
                    last_block = current_block
                
                await asyncio.sleep(1)  # BSC block time ~3s, check every 1s
                
            except Exception as e:
                print(f"[Monitor] Error: {e}")
                await asyncio.sleep(5)
    
    async def check_block_for_migrations(self, block_number: int):
        """Check a block for PairCreated events"""
        try:
            # Get logs for PairCreated events
            params = {
                "jsonrpc": "2.0",
                "method": "eth_getLogs",
                "params": [{
                    "fromBlock": hex(block_number),
                    "toBlock": hex(block_number),
                    "address": PANCAKE_FACTORY_V2,
                    "topics": [PAIR_CREATED_TOPIC]
                }],
                "id": 1
            }
            
            async with self.session.post(BSC_RPC, json=params) as resp:
                data = await resp.json()
                logs = data.get("result", [])
                
                for log in logs:
                    await self.handle_pair_created(log, block_number)
                    
        except Exception as e:
            print(f"[Block {block_number}] Error: {e}")
    
    async def handle_pair_created(self, log: dict, block_number: int):
        """Handle a PairCreated event - potential migration"""
        try:
            # Decode PairCreated event
            # topics[1] = token0, topics[2] = token1
            token0 = "0x" + log["topics"][1][-40:]
            token1 = "0x" + log["topics"][2][-40:]
            pair_address = "0x" + log["data"][26:66]
            
            # Determine which is the new token (not WBNB)
            if token0.lower() == WBNB.lower():
                token_address = token1
            elif token1.lower() == WBNB.lower():
                token_address = token0
            else:
                return  # Not a BNB pair, skip
            
            detection_time = int(time.time() * 1000)
            
            print(f"\n[MIGRATION DETECTED] Block {block_number}")
            print(f"  Token: {token_address}")
            print(f"  Pair:  {pair_address}")
            
            # Create snipe record
            record = SnipeRecord(
                token_address=token_address,
                pair_address=pair_address,
                migration_detected_ms=detection_time,
                block_number=block_number,
            )
            
            # Get token info
            record.token_symbol = await self.get_token_symbol(token_address)
            
            # Check initial liquidity
            record.initial_liq_bnb = await self.get_pair_bnb_reserve(pair_address)
            print(f"  Symbol: {record.token_symbol}")
            print(f"  Initial Liq: {record.initial_liq_bnb:.4f} BNB")
            
            # Filter: minimum liquidity
            if record.initial_liq_bnb < 0.5:
                print(f"  [SKIP] Liquidity too low (<0.5 BNB)")
                return
            
            # Honeypot check
            honeypot_result = await self.check_honeypot(token_address)
            record.is_honeypot = honeypot_result.get("is_honeypot", False)
            record.buy_tax = honeypot_result.get("buy_tax", 0)
            record.sell_tax = honeypot_result.get("sell_tax", 0)
            
            if record.is_honeypot:
                print(f"  [SKIP] Honeypot detected!")
                record.status = SnipeStatus.HONEYPOT
                self.records[token_address] = record
                self.metrics.total_snipes += 1
                self.metrics.honeypots += 1
                return
            
            if record.sell_tax > 0.15:
                print(f"  [SKIP] High sell tax: {record.sell_tax*100:.1f}%")
                return
            
            # Simulate snipe
            record.entry_bnb = self.snipe_amount_bnb
            record.entry_price_usd = await self.get_token_price_usd(token_address, pair_address)
            record.current_price_usd = record.entry_price_usd
            record.peak_price_usd = record.entry_price_usd
            
            if record.entry_price_usd > 0:
                record.entry_tokens = (record.entry_bnb * self.bnb_price_usd) / record.entry_price_usd
            
            record.snipe_submitted_ms = int(time.time() * 1000)
            record.snipe_confirmed_ms = record.snipe_submitted_ms + 500  # Simulated confirmation
            record.status = SnipeStatus.HOLDING
            
            self.records[token_address] = record
            self.metrics.total_snipes += 1
            self.metrics.confirmed += 1
            self.metrics.holding += 1
            self.metrics.total_invested_bnb += record.entry_bnb
            
            print(f"  [SNIPED] Entry price: ${record.entry_price_usd:.10f}")
            print(f"  [SNIPED] Tokens: {record.entry_tokens:.2f} {record.token_symbol}")
            
            if self.on_migration_detected:
                self.on_migration_detected(record)
                
        except Exception as e:
            print(f"[PairCreated] Error: {e}")
    
    async def price_updater(self):
        """Update prices for all held tokens"""
        while self.running:
            try:
                await asyncio.sleep(30)  # Update every 30 seconds
                
                for token_address, record in list(self.records.items()):
                    if record.status != SnipeStatus.HOLDING:
                        continue
                    
                    # Get current price
                    new_price = await self.get_token_price_usd(token_address, record.pair_address)
                    if new_price <= 0:
                        continue
                    
                    record.current_price_usd = new_price
                    record.price_history.append((int(time.time() * 1000), new_price))
                    
                    # Update peak
                    if new_price > record.peak_price_usd:
                        record.peak_price_usd = new_price
                    
                    # Calculate multiple
                    if record.entry_price_usd > 0:
                        multiple = new_price / record.entry_price_usd
                        record.peak_multiple = max(record.peak_multiple, multiple)
                        
                        # Track milestones
                        elapsed_ms = int(time.time() * 1000) - record.snipe_confirmed_ms
                        
                        if multiple >= 2.0 and record.time_to_2x_ms == 0:
                            record.time_to_2x_ms = elapsed_ms
                            self.metrics.hit_2x += 1
                            if elapsed_ms <= 3600000:
                                self.metrics.hit_2x_1h += 1
                            if elapsed_ms <= 14400000:
                                self.metrics.hit_2x_4h += 1
                            print(f"  [2X HIT] {record.token_symbol} in {elapsed_ms/1000:.0f}s!")
                        
                        if multiple >= 5.0 and record.time_to_5x_ms == 0:
                            record.time_to_5x_ms = elapsed_ms
                            self.metrics.hit_5x += 1
                            print(f"  [5X HIT] {record.token_symbol}!")
                        
                        if multiple >= 10.0 and record.time_to_10x_ms == 0:
                            record.time_to_10x_ms = elapsed_ms
                            self.metrics.hit_10x += 1
                            print(f"  [10X HIT] {record.token_symbol}!")
                        
                        # Check for rug (price dropped >90%)
                        if multiple < 0.1 and record.status == SnipeStatus.HOLDING:
                            record.status = SnipeStatus.RUGGED
                            self.metrics.holding -= 1
                            self.metrics.rugged += 1
                            record.pnl_bnb = -record.entry_bnb
                            self.metrics.total_pnl_bnb += record.pnl_bnb
                            print(f"  [RUGGED] {record.token_symbol} - Lost {record.entry_bnb} BNB")
                    
                    if self.on_price_update:
                        self.on_price_update(record)
                        
            except Exception as e:
                print(f"[PriceUpdater] Error: {e}")
    
    async def stats_printer(self):
        """Print periodic stats"""
        while self.running:
            await asyncio.sleep(60)  # Every minute
            self.print_live_stats()
    
    def print_live_stats(self):
        """Print current stats"""
        m = self.metrics
        print(f"\n[STATS] Snipes: {m.total_snipes} | Confirmed: {m.confirmed} | "
              f"Holding: {m.holding} | 2x: {m.hit_2x} | 5x: {m.hit_5x} | "
              f"P&L: {m.total_pnl_bnb:+.4f} BNB")
    
    def print_final_summary(self):
        """Print final performance summary"""
        m = self.metrics
        
        print("\n")
        print("╔" + "═"*62 + "╗")
        print("║" + " "*15 + "FINAL PERFORMANCE SUMMARY" + " "*22 + "║")
        print("╠" + "═"*62 + "╣")
        print(f"║  Total Snipes:     {m.total_snipes:<6}" + " "*36 + "║")
        print(f"║  ├─ Confirmed:     {m.confirmed:<6} ({m.success_rate*100:.1f}%)" + " "*26 + "║")
        print(f"║  ├─ Honeypots:     {m.honeypots:<6} ({m.honeypot_rate*100:.1f}% of confirmed)" + " "*10 + "║")
        print(f"║  └─ Rugged:        {m.rugged:<6}" + " "*36 + "║")
        print("╠" + "═"*62 + "╣")
        print("║  HIT RATES:" + " "*50 + "║")
        print(f"║  ├─ 2x hit:        {m.hit_2x:<6} ({m.hit_2x_rate*100:.1f}%)" + " "*26 + "║")
        print(f"║  ├─ 5x hit:        {m.hit_5x:<6} ({m.hit_5x_rate*100:.1f}%)" + " "*26 + "║")
        print(f"║  └─ 10x hit:       {m.hit_10x:<6}" + " "*36 + "║")
        print("║" + " "*62 + "║")
        print("║  2x TIMING:" + " "*50 + "║")
        print(f"║  ├─ Within 1h:     {m.hit_2x_1h:<6}" + " "*36 + "║")
        print(f"║  └─ Within 4h:     {m.hit_2x_4h:<6}" + " "*36 + "║")
        print("╠" + "═"*62 + "╣")
        print("║  P&L SUMMARY:" + " "*48 + "║")
        print(f"║  ├─ Invested:      {m.total_invested_bnb:.4f} BNB" + " "*30 + "║")
        print(f"║  ├─ Total P&L:     {m.total_pnl_bnb:+.4f} BNB" + " "*29 + "║")
        print(f"║  └─ ROI:           {m.roi:+.1f}%" + " "*37 + "║")
        print("╚" + "═"*62 + "╝")
        
        # Export results
        self.export_results()
    
    def export_results(self):
        """Export results to JSON"""
        output_dir = "sniper_logs"
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"{output_dir}/test_results_{timestamp}.json"
        
        data = {
            "test_info": {
                "mode": self.mode,
                "snipe_amount_bnb": self.snipe_amount_bnb,
                "timestamp": timestamp,
            },
            "metrics": {
                "total_snipes": self.metrics.total_snipes,
                "confirmed": self.metrics.confirmed,
                "success_rate": self.metrics.success_rate,
                "honeypot_rate": self.metrics.honeypot_rate,
                "hit_2x": self.metrics.hit_2x,
                "hit_2x_rate": self.metrics.hit_2x_rate,
                "hit_5x": self.metrics.hit_5x,
                "hit_5x_rate": self.metrics.hit_5x_rate,
                "hit_10x": self.metrics.hit_10x,
                "total_pnl_bnb": self.metrics.total_pnl_bnb,
                "roi_percent": self.metrics.roi,
            },
            "records": [
                {
                    "token": r.token_address,
                    "symbol": r.token_symbol,
                    "status": r.status.value,
                    "entry_bnb": r.entry_bnb,
                    "entry_price": r.entry_price_usd,
                    "peak_multiple": r.peak_multiple,
                    "pnl_bnb": r.pnl_bnb,
                    "is_honeypot": r.is_honeypot,
                    "time_to_2x_ms": r.time_to_2x_ms,
                    "initial_liq_bnb": r.initial_liq_bnb,
                }
                for r in self.records.values()
            ]
        }
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"\n[Results exported to {filepath}]")
    
    # ========== Helper Methods ==========
    
    async def get_latest_block(self) -> int:
        """Get latest block number"""
        params = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
        async with self.session.post(BSC_RPC, json=params) as resp:
            data = await resp.json()
            return int(data["result"], 16)
    
    async def get_token_symbol(self, token_address: str) -> str:
        """Get token symbol"""
        try:
            # symbol() = 0x95d89b41
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
                    # Decode string from ABI
                    hex_str = result[130:]
                    return bytes.fromhex(hex_str).decode("utf-8", errors="ignore").strip("\x00")
        except:
            pass
        return "UNKNOWN"
    
    async def get_pair_bnb_reserve(self, pair_address: str) -> float:
        """Get BNB reserve in pair"""
        try:
            # getReserves() = 0x0902f1ac
            params = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": pair_address, "data": "0x0902f1ac"}, "latest"],
                "id": 1
            }
            async with self.session.post(BSC_RPC, json=params) as resp:
                data = await resp.json()
                result = data.get("result", "0x")
                if len(result) >= 130:
                    reserve0 = int(result[2:66], 16) / 1e18
                    reserve1 = int(result[66:130], 16) / 1e18
                    # Return the larger one (likely BNB)
                    return max(reserve0, reserve1)
        except:
            pass
        return 0.0
    
    async def get_token_price_usd(self, token_address: str, pair_address: str) -> float:
        """Get token price in USD"""
        try:
            # Get reserves
            params = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": pair_address, "data": "0x0902f1ac"}, "latest"],
                "id": 1
            }
            async with self.session.post(BSC_RPC, json=params) as resp:
                data = await resp.json()
                result = data.get("result", "0x")
                if len(result) >= 130:
                    reserve0 = int(result[2:66], 16)
                    reserve1 = int(result[66:130], 16)
                    
                    # Get token0 to determine order
                    params2 = {
                        "jsonrpc": "2.0",
                        "method": "eth_call",
                        "params": [{"to": pair_address, "data": "0x0dfe1681"}, "latest"],  # token0()
                        "id": 1
                    }
                    async with self.session.post(BSC_RPC, json=params2) as resp2:
                        data2 = await resp2.json()
                        token0 = "0x" + data2.get("result", "")[26:66]
                        
                        if token0.lower() == WBNB.lower():
                            # BNB is token0, token is token1
                            bnb_reserve = reserve0 / 1e18
                            token_reserve = reserve1 / 1e18
                        else:
                            # Token is token0, BNB is token1
                            token_reserve = reserve0 / 1e18
                            bnb_reserve = reserve1 / 1e18
                        
                        if token_reserve > 0:
                            price_in_bnb = bnb_reserve / token_reserve
                            return price_in_bnb * self.bnb_price_usd
        except:
            pass
        return 0.0
    
    async def check_honeypot(self, token_address: str) -> dict:
        """Check if token is honeypot using GoPlus API"""
        try:
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
    
    async def update_bnb_price(self):
        """Update BNB/USD price"""
        try:
            url = "https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT"
            async with self.session.get(url) as resp:
                data = await resp.json()
                self.bnb_price_usd = float(data["price"])
                print(f"[BNB Price] ${self.bnb_price_usd:.2f}")
        except:
            pass


def parse_duration(s: str) -> int:
    """Parse duration string like '1h', '30m', '2h30m' to seconds"""
    total = 0
    current = ""
    for c in s:
        if c.isdigit():
            current += c
        elif c == 'h':
            total += int(current) * 3600
            current = ""
        elif c == 'm':
            total += int(current) * 60
            current = ""
        elif c == 's':
            total += int(current)
            current = ""
    return total if total > 0 else 3600


async def main():
    parser = argparse.ArgumentParser(description="Migration Sniper Tester")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (no trades)")
    parser.add_argument("--paper", action="store_true", help="Paper trading mode")
    parser.add_argument("--live", action="store_true", help="Live trading mode (CAREFUL!)")
    parser.add_argument("--duration", default="1h", help="Test duration (e.g., 1h, 30m, 4h)")
    parser.add_argument("--amount", type=float, default=0.01, help="Snipe amount in BNB")
    args = parser.parse_args()
    
    mode = "live" if args.live else ("paper" if args.paper else "dry-run")
    duration = parse_duration(args.duration)
    
    tester = MigrationTester(mode=mode, snipe_amount_bnb=args.amount)
    
    # Handle Ctrl+C
    def signal_handler(sig, frame):
        print("\n[Stopping...]")
        tester.running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    
    await tester.start(duration_seconds=duration)


if __name__ == "__main__":
    asyncio.run(main())
