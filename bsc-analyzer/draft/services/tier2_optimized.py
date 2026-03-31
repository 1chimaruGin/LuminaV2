#!/usr/bin/env python3
"""Lumina BSC — Optimized Tier 2 Pipeline (<5ms latency)"""
import os, sys, time, asyncio, aiohttp, logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from collections import OrderedDict
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ml'))
from dotenv import load_dotenv
load_dotenv()

try:
    import lumina_scorer
    HAVE_CPP = True
except: HAVE_CPP = False

log = logging.getLogger(__name__)

class Decision(Enum):
    REJECT = 0
    SKIP = 1
    SNIPE_SMALL = 2
    SNIPE = 3

@dataclass
class TokenData:
    address: str
    fetch_time: float = 0.0
    is_honeypot: int = 0
    buy_tax: float = 0.0
    sell_tax: float = 0.0
    is_mintable: int = 0
    owner_can_change_balance: int = 0
    holder_count: int = 0
    liquidity_usd: float = 0.0
    buys_24h: int = 0
    sells_24h: int = 0

class LRUCache:
    def __init__(self, max_size=10000, ttl=300):
        self.max_size, self.ttl = max_size, ttl
        self.cache: OrderedDict = OrderedDict()
        self.hits = self.misses = 0
    
    def get(self, key: str) -> Optional[TokenData]:
        if key not in self.cache:
            self.misses += 1
            return None
        ts, data = self.cache[key]
        if time.time() - ts > self.ttl:
            del self.cache[key]
            self.misses += 1
            return None
        self.cache.move_to_end(key)
        self.hits += 1
        return data
    
    def set(self, key: str, data: TokenData):
        if key in self.cache: del self.cache[key]
        elif len(self.cache) >= self.max_size: self.cache.popitem(last=False)
        self.cache[key] = (time.time(), data)

class OptimizedTier2:
    def __init__(self, bnb_price=600.0):
        self.cache = LRUCache()
        self.bnb_price = bnb_price
        self.session = None
        self.prefetch_queue = asyncio.Queue()
        if HAVE_CPP:
            self.scorer = lumina_scorer.FastScorer()
            self.scorer.set_thresholds(0.5, 0.35)
    
    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        asyncio.create_task(self._prefetch_worker())
        log.info(f"Tier2 started | C++:{HAVE_CPP}")
    
    async def stop(self):
        if self.session: await self.session.close()
    
    async def _prefetch_worker(self):
        while True:
            try:
                token, deployer = await self.prefetch_queue.get()
                if not self.cache.get(token.lower()):
                    await self._fetch_and_cache(token)
            except asyncio.CancelledError: break
            except: pass
    
    async def prefetch(self, token: str, deployer: str = ""):
        await self.prefetch_queue.put((token, deployer))
    
    async def _fetch_and_cache(self, token: str) -> TokenData:
        token = token.lower()
        data = TokenData(address=token)
        
        # Parallel fetch
        gp, dx = await asyncio.gather(
            self._fetch_goplus(token), self._fetch_dex(token), return_exceptions=True)
        
        if isinstance(gp, dict):
            data.is_honeypot = int(gp.get("is_honeypot", "0") or "0")
            data.buy_tax = float(gp.get("buy_tax", "0") or "0") * 100
            data.sell_tax = float(gp.get("sell_tax", "0") or "0") * 100
            data.owner_can_change_balance = int(gp.get("owner_change_balance", "0") or "0")
            data.holder_count = int(gp.get("holder_count", "0") or "0")
        
        if isinstance(dx, dict):
            data.liquidity_usd = dx.get("liq", 0)
            data.buys_24h = dx.get("buys", 0)
            data.sells_24h = dx.get("sells", 0)
        
        data.fetch_time = time.time()
        self.cache.set(token, data)
        return data
    
    async def _fetch_goplus(self, token: str) -> Dict:
        try:
            async with self.session.get(f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={token}") as r:
                return (await r.json()).get("result", {}).get(token, {}) if r.status == 200 else {}
        except: return {}
    
    async def _fetch_dex(self, token: str) -> Dict:
        try:
            async with self.session.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}") as r:
                if r.status == 200:
                    p = (await r.json()).get("pairs", [{}])[0]
                    return {"liq": float((p.get("liquidity") or {}).get("usd") or 0),
                            "buys": p.get("txns",{}).get("h24",{}).get("buys") or 0,
                            "sells": p.get("txns",{}).get("h24",{}).get("sells") or 0}
        except: pass
        return {}
    
    async def score(self, token: str) -> Dict:
        start = time.perf_counter_ns()
        token = token.lower()
        
        data = self.cache.get(token)
        cache_hit = data is not None
        if not data: data = await self._fetch_and_cache(token)
        
        # Hard filters
        if data.is_honeypot:
            return {"score": 0, "decision": "REJECT", "reason": "honeypot", "latency_ms": (time.perf_counter_ns()-start)/1e6, "cache": cache_hit}
        if data.buy_tax > 0 or data.sell_tax > 0:
            return {"score": 0, "decision": "REJECT", "reason": f"tax:{data.buy_tax:.0f}/{data.sell_tax:.0f}", "latency_ms": (time.perf_counter_ns()-start)/1e6, "cache": cache_hit}
        
        # C++ score
        if HAVE_CPP:
            td = lumina_scorer.TokenData()
            td.initial_liq_usd = data.liquidity_usd
            td.is_honeypot = data.is_honeypot
            td.buy_tax = data.buy_tax
            td.sell_tax = data.sell_tax
            td.holder_count = data.holder_count
            td.buy_count_5m = data.buys_24h // 288
            td.sell_count_5m = data.sells_24h // 288
            r = self.scorer.score(td)
            score, dec = r.score, Decision(r.decision.value).name
        else:
            score, dec = 0.5, "SNIPE_SMALL"
        
        return {"score": score, "decision": dec, "reason": "", "latency_ms": (time.perf_counter_ns()-start)/1e6, "cache": cache_hit}

async def demo():
    t2 = OptimizedTier2()
    await t2.start()
    
    token = "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82"  # CAKE
    print(f"\n=== TIER 2 OPTIMIZED DEMO ===")
    print(f"[1] Prefetch (CONTRACT_CREATION)")
    await t2.prefetch(token)
    await asyncio.sleep(1)
    
    print(f"[2] Score (cache hit)")
    for _ in range(3):
        r = await t2.score(token)
        print(f"    {r['decision']}: {r['score']:.3f} | {r['latency_ms']:.3f}ms | cache={r['cache']}")
    
    print(f"\n[3] Score new token (cache miss)")
    r = await t2.score("0x2170ed0880ac9a755fd29b2688956bd959f933f8")  # ETH
    print(f"    {r['decision']}: {r['score']:.3f} | {r['latency_ms']:.1f}ms | cache={r['cache']}")
    
    await t2.stop()

if __name__ == "__main__":
    asyncio.run(demo())
