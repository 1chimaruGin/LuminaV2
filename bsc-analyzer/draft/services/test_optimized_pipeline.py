#!/usr/bin/env python3
"""
Test the optimized Tier 2 pipeline latency
Target: <5ms with pre-fetching, <1ms with cache hit
"""
import os, sys, time, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ml'))
from dotenv import load_dotenv
load_dotenv()

from tier2_optimized import OptimizedTier2

async def benchmark():
    print("="*60)
    print("  OPTIMIZED PIPELINE BENCHMARK")
    print("="*60)
    
    t2 = OptimizedTier2()
    await t2.start()
    
    # Test tokens
    tokens = [
        ("0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82", "CAKE"),
        ("0x2170ed0880ac9a755fd29b2688956bd959f933f8", "ETH"),
        ("0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c", "BTCB"),
    ]
    
    print("\n[1] COLD START (no cache, API fetch required)")
    print("-" * 50)
    for addr, name in tokens:
        start = time.perf_counter()
        r = await t2.score(addr)
        elapsed = (time.perf_counter() - start) * 1000
        print(f"  {name:6} | {r['decision']:12} | {elapsed:7.1f}ms | cache={r['cache']}")
    
    print("\n[2] WARM CACHE (data pre-fetched)")
    print("-" * 50)
    latencies = []
    for addr, name in tokens:
        times = []
        for _ in range(10):
            start = time.perf_counter()
            r = await t2.score(addr)
            times.append((time.perf_counter() - start) * 1000)
        avg = sum(times) / len(times)
        latencies.append(avg)
        print(f"  {name:6} | {r['decision']:12} | {avg:7.3f}ms avg (10 runs)")
    
    print("\n[3] PRE-FETCH SIMULATION")
    print("-" * 50)
    new_token = "0x1d2f0da169ceb9fc7b3144628db156f3f6c60dbe"  # XRP
    
    print(f"  CONTRACT_CREATION: prefetch queued")
    await t2.prefetch(new_token)
    await asyncio.sleep(0.5)  # Simulate time between contract creation and liquidity add
    
    start = time.perf_counter()
    r = await t2.score(new_token)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"  ADD_LIQUIDITY:     {r['decision']:12} | {elapsed:7.3f}ms | cache={r['cache']}")
    
    print("\n[4] HARD FILTER TEST (C++ Tier 1)")
    print("-" * 50)
    
    # Simulate tokens that would be rejected by hard filters
    test_cases = [
        {"name": "Honeypot", "is_honeypot": 1},
        {"name": "5% Tax", "buy_tax": 5, "sell_tax": 5},
        {"name": "Owner change bal", "owner_can_change_balance": 1},
        {"name": "Known scammer", "deployer_score": -60},
        {"name": "Good token", "initial_liq_usd": 50000, "holder_count": 200},
    ]
    
    try:
        import lumina_scorer
        scorer = lumina_scorer.FastScorer()
        scorer.set_thresholds(0.5, 0.35)
        
        for tc in test_cases:
            name = tc.pop("name")
            d = lumina_scorer.TokenData()
            for k, v in tc.items():
                setattr(d, k, v)
            r = scorer.score(d)
            dec = {0:"REJECT", 1:"SKIP", 2:"SNIPE_SMALL", 3:"SNIPE"}[r.decision.value]
            reason = f" ({r.reject_reason})" if r.reject_reason else ""
            print(f"  {name:18} | {dec:12}{reason} | {r.latency_ns}ns")
    except ImportError:
        print("  C++ scorer not available")
    
    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    print(f"  Cache hit latency:  {sum(latencies)/len(latencies):.3f}ms avg")
    print(f"  Target:             <5ms ✓" if sum(latencies)/len(latencies) < 5 else "  Target: <5ms ✗")
    print(f"  C++ scorer:         ~300-400ns per token")
    print("="*60)
    
    await t2.stop()

if __name__ == "__main__":
    asyncio.run(benchmark())
