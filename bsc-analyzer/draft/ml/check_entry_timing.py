"""
Check REAL KOL entry timing by comparing:
  - Token's first Transfer event block/timestamp (from BSC RPC)
  - KOL's first buy TX block/timestamp (from BSC RPC via tx receipt)

Correct approach:
  1. Get KOL buy TX receipt → real block number + timestamp
  2. Search backwards from that block for token's first Transfer event
  3. Compute block_diff and time_diff
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLICKHOUSE_BIN = str(PROJECT_ROOT / "clickhouse-bin")

sys.path.insert(0, str(PROJECT_ROOT.parent / "lumina-backend"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT.parent / "lumina-backend" / ".env")

BSC_RPC = os.environ.get("QUICK_NODE_BSC_RPC", "https://bsc-dataseed.binance.org/")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def ch_query(query: str) -> list[dict]:
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"{query} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"CH error: {result.stderr[:500]}")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


async def rpc_call(session, method, params):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    async with session.post(BSC_RPC, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        data = await resp.json()
        if "error" in data:
            return None
        return data.get("result")


async def get_real_timing(session, token_address, kol_buy_tx):
    """Get real entry timing by comparing on-chain data."""
    # Step 1: Get KOL buy TX receipt → block number
    receipt = await rpc_call(session, "eth_getTransactionReceipt", [kol_buy_tx])
    if not receipt:
        return None
    kol_block = int(receipt["blockNumber"], 16)

    # Step 2: Get KOL block timestamp
    block_data = await rpc_call(session, "eth_getBlockByNumber", [hex(kol_block), False])
    if not block_data:
        return None
    kol_ts = int(block_data["timestamp"], 16)

    # Step 3: Search for token's first Transfer event
    # Search 5000 blocks before KOL buy (≈25 min on BSC)
    from_block = max(kol_block - 5000, 0)
    logs = await rpc_call(session, "eth_getLogs", [{
        "address": token_address,
        "fromBlock": hex(from_block),
        "toBlock": hex(kol_block + 5),
        "topics": [TRANSFER_TOPIC],
    }])
    if not logs or len(logs) == 0:
        return None

    first_block = int(logs[0]["blockNumber"], 16)
    first_tx = logs[0]["transactionHash"]

    # Step 4: Get first Transfer block timestamp
    first_block_data = await rpc_call(session, "eth_getBlockByNumber", [hex(first_block), False])
    if not first_block_data:
        return None
    first_ts = int(first_block_data["timestamp"], 16)

    return {
        "kol_block": kol_block,
        "kol_ts": kol_ts,
        "creation_block": first_block,
        "creation_ts": first_ts,
        "creation_tx": first_tx,
        "block_diff": kol_block - first_block,
        "time_diff": kol_ts - first_ts,
    }


async def main():
    print("=" * 90)
    print("REAL KOL ENTRY TIMING (on-chain verified)")
    print("Token creation (first Transfer) vs KOL first buy (TX receipt)")
    print("=" * 90)

    # Get sample tokens with their first buy TX hashes
    tokens = ch_query("""
        SELECT
            token_address,
            token_symbol,
            argMin(tx_hash, block_timestamp) as first_buy_tx,
            min(block_timestamp) as first_buy_ts,
            argMin(wallet_address, block_timestamp) as first_buyer
        FROM lumina.kol_swaps
        WHERE side = 'buy'
        GROUP BY token_address, token_symbol
        ORDER BY rand()
        LIMIT 100
    """)

    print(f"\nChecking {len(tokens)} random tokens...\n")
    header = f"{'#':>3s} {'Symbol':<16s} {'CreationBlk':>12s} {'KOLBuyBlk':>12s} {'BlkDiff':>8s} {'Delay':>8s} {'Wallet':<14s}"
    print(header)
    print("-" * len(header))

    delays = []
    block_diffs = []

    async with aiohttp.ClientSession() as session:
        for i, t in enumerate(tokens):
            try:
                result = await get_real_timing(session, t["token_address"], t["first_buy_tx"])
            except Exception as e:
                print(f"  Error: {e}")
                continue

            if result is None:
                continue

            delays.append(result["time_diff"])
            block_diffs.append(result["block_diff"])

            sym = t["token_symbol"][:14]
            wallet_short = t["first_buyer"][:12] + ".."
            print(f"{len(delays):3d} {sym:<16s} {result['creation_block']:12d} {result['kol_block']:12d} {result['block_diff']:>8d} {result['time_diff']:>7d}s {wallet_short:<14s}")

            await asyncio.sleep(0.25)  # Rate limit

    # Summary
    if not delays:
        print("\nNo results!")
        return

    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    valid = [d for d in delays if d >= 0]
    print(f"  Tokens checked:  {len(delays)}")
    print(f"  Valid (delay≥0): {len(valid)}")
    if valid:
        print(f"  Min delay:       {min(valid)}s")
        print(f"  Max delay:       {max(valid)}s")
        print(f"  Avg delay:       {sum(valid)/len(valid):.1f}s")
        print(f"  Median delay:    {sorted(valid)[len(valid)//2]}s")
        print(f"  Avg block diff:  {sum(block_diffs)/len(block_diffs):.1f}")

    print()
    buckets = [
        ("0-2s",     0, 2),
        ("3-5s",     3, 5),
        ("6-10s",    6, 10),
        ("11-20s",   11, 20),
        ("21-30s",   21, 30),
        ("31-60s",   31, 60),
        ("1-5min",   61, 300),
        ("5-30min",  301, 1800),
        ("> 30min",  1801, 999999),
    ]
    neg = sum(1 for d in delays if d < 0)
    if neg:
        print(f"  {'< 0s (data issue)':<20s} {neg:4d} ({neg/len(delays)*100:5.1f}%)")

    print("  Distribution (valid only):")
    for label, lo, hi in buckets:
        count = sum(1 for d in valid if lo <= d <= hi)
        pct = count / len(valid) * 100 if valid else 0
        bar = "#" * int(pct / 2)
        print(f"    {label:<20s} {count:4d} ({pct:5.1f}%) {bar}")


if __name__ == "__main__":
    asyncio.run(main())
