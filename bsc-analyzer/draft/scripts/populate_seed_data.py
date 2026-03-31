#!/usr/bin/env python3
"""
Lumina BSC Tier 1 — Seed Data Population Script

Populates:
1. deployers.csv — Deployer reputation from BSC contract creations
2. blacklist.txt — Known scam addresses from GoPlus API
3. bytecodes.csv — Scam bytecode hashes (placeholder, needs manual curation)

Usage:
    python scripts/populate_seed_data.py [--rpc URL] [--output-dir DIR]

Requirements:
    pip install aiohttp web3
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import aiohttp
except ImportError:
    print("ERROR: aiohttp not installed. Run: pip install aiohttp")
    sys.exit(1)

# ============================================================
# Configuration
# ============================================================

GOPLUS_API = "https://api.gopluslabs.io/api/v1"
BSC_CHAIN_ID = "56"

# Known scam patterns (addresses that are always blacklisted)
KNOWN_SCAM_PATTERNS = [
    # Tornado Cash related
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",
    # Known rug deployers (examples)
]

# Known locker contracts (for reference)
KNOWN_LOCKERS = {
    "0x407993575c91ce7643a4d4ccacc9a98c36ee1bbe": "PinkLock V2",
    "0x663a5c229c09b049e36dcc11a9b0d4a8eb9db214": "UNCX",
    "0x000000000000000000000000000000000000dead": "Burn Address",
}

# PancakeSwap addresses
PANCAKE_FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
PANCAKE_ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"


@dataclass
class DeployerStats:
    address: str
    total_deploys: int = 0
    rug_count: int = 0
    survival_count: int = 0
    flags: int = 0
    first_seen_block: int = 0
    last_seen_block: int = 0
    tokens: list = field(default_factory=list)

    # Flag constants
    KNOWN_SCAMMER = 1
    KNOWN_LEGIT = 2
    CEX_FUNDED = 4
    MIXER_FUNDED = 8
    SERIAL_DEPLOYER = 16


# ============================================================
# GoPlus API Client
# ============================================================

class GoPlusClient:
    """Client for GoPlus Security API (free tier)"""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.rate_limit_delay = 0.5  # 2 requests/sec for free tier

    async def check_token_security(self, token_address: str) -> Optional[dict]:
        """Check token security via GoPlus API"""
        url = f"{GOPLUS_API}/token_security/{BSC_CHAIN_ID}"
        params = {"contract_addresses": token_address.lower()}

        try:
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 1:
                        result = data.get("result", {})
                        return result.get(token_address.lower())
                await asyncio.sleep(self.rate_limit_delay)
        except Exception as e:
            print(f"  GoPlus error for {token_address[:10]}...: {e}")
        return None

    async def check_address_security(self, address: str) -> Optional[dict]:
        """Check address security (malicious address detection)"""
        url = f"{GOPLUS_API}/address_security/{address}"
        params = {"chain_id": BSC_CHAIN_ID}

        try:
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 1:
                        return data.get("result")
                await asyncio.sleep(self.rate_limit_delay)
        except Exception as e:
            print(f"  GoPlus address error for {address[:10]}...: {e}")
        return None

    async def batch_check_tokens(self, tokens: list[str], batch_size: int = 10) -> dict:
        """Check multiple tokens, returns {address: security_data}"""
        results = {}
        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i + batch_size]
            batch_str = ",".join(batch)
            url = f"{GOPLUS_API}/token_security/{BSC_CHAIN_ID}"
            params = {"contract_addresses": batch_str}

            try:
                async with self.session.get(url, params=params, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == 1:
                            results.update(data.get("result", {}))
                await asyncio.sleep(self.rate_limit_delay)
            except Exception as e:
                print(f"  GoPlus batch error: {e}")

            print(f"  Checked {min(i + batch_size, len(tokens))}/{len(tokens)} tokens...")
        return results


# ============================================================
# BSC RPC Client
# ============================================================

class BSCClient:
    """Simple BSC JSON-RPC client"""

    def __init__(self, session: aiohttp.ClientSession, rpc_url: str):
        self.session = session
        self.rpc_url = rpc_url
        self.request_id = 0

    async def _call(self, method: str, params: list) -> Optional[dict]:
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self.request_id
        }
        try:
            async with self.session.post(self.rpc_url, json=payload, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result")
        except Exception as e:
            print(f"  RPC error: {e}")
        return None

    async def get_block_number(self) -> int:
        result = await self._call("eth_blockNumber", [])
        return int(result, 16) if result else 0

    async def get_block(self, block_num: int, full_txs: bool = False) -> Optional[dict]:
        hex_block = hex(block_num)
        return await self._call("eth_getBlockByNumber", [hex_block, full_txs])

    async def get_code(self, address: str, block: str = "latest") -> Optional[str]:
        return await self._call("eth_getCode", [address, block])

    async def get_logs(self, from_block: int, to_block: int, topics: list) -> list:
        params = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": topics
        }
        result = await self._call("eth_getLogs", [params])
        return result or []


# ============================================================
# Data Population Functions
# ============================================================

async def fetch_recent_token_creations(bsc: BSCClient, blocks_back: int = 10000) -> list[dict]:
    """
    Fetch recent PairCreated events from PancakeSwap Factory.
    This gives us new token launches to analyze.
    """
    print(f"\n[1/4] Fetching recent token creations (last {blocks_back} blocks)...")

    current_block = await bsc.get_block_number()
    from_block = current_block - blocks_back

    # PairCreated(address indexed token0, address indexed token1, address pair, uint)
    PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

    tokens = []
    chunk_size = 2000  # BSC limits log queries

    for start in range(from_block, current_block, chunk_size):
        end = min(start + chunk_size - 1, current_block)
        logs = await bsc.get_logs(
            start, end,
            [PAIR_CREATED_TOPIC, None, None]  # Any token0, any token1
        )

        for log in logs:
            if len(log.get("topics", [])) >= 3:
                token0 = "0x" + log["topics"][1][-40:]
                token1 = "0x" + log["topics"][2][-40:]
                pair = "0x" + log["data"][26:66]
                block = int(log["blockNumber"], 16)

                # Skip WBNB pairs where WBNB is token0
                wbnb = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
                token = token1 if token0.lower() == wbnb else token0

                tokens.append({
                    "token": token.lower(),
                    "pair": pair.lower(),
                    "block": block
                })

        print(f"  Scanned blocks {start}-{end}, found {len(tokens)} pairs so far...")
        await asyncio.sleep(0.1)

    print(f"  Found {len(tokens)} token pairs")
    return tokens


async def analyze_tokens_with_goplus(goplus: GoPlusClient, tokens: list[dict]) -> tuple[dict, list]:
    """
    Analyze tokens with GoPlus to identify scams and build deployer stats.
    Returns (deployer_stats, blacklist_addresses)
    """
    print(f"\n[2/4] Analyzing {len(tokens)} tokens with GoPlus API...")

    deployers: dict[str, DeployerStats] = {}
    blacklist: list[str] = []

    # Batch check all tokens
    token_addrs = list(set(t["token"] for t in tokens))
    security_data = await goplus.batch_check_tokens(token_addrs)

    for token_info in tokens:
        token = token_info["token"]
        block = token_info["block"]
        security = security_data.get(token, {})

        if not security:
            continue

        # Extract deployer (creator/owner)
        creator = security.get("creator_address", "").lower()
        owner = security.get("owner_address", "").lower()
        deployer_addr = creator or owner

        if not deployer_addr or deployer_addr == "0x" + "0" * 40:
            continue

        # Initialize deployer stats
        if deployer_addr not in deployers:
            deployers[deployer_addr] = DeployerStats(address=deployer_addr)

        deployer = deployers[deployer_addr]
        deployer.total_deploys += 1
        deployer.tokens.append(token)

        if deployer.first_seen_block == 0 or block < deployer.first_seen_block:
            deployer.first_seen_block = block
        if block > deployer.last_seen_block:
            deployer.last_seen_block = block

        # Check if token is a scam
        is_scam = False
        scam_reasons = []

        if security.get("is_honeypot") == "1":
            is_scam = True
            scam_reasons.append("honeypot")
        if security.get("cannot_sell_all") == "1":
            is_scam = True
            scam_reasons.append("cannot_sell")
        if security.get("is_blacklisted") == "1":
            is_scam = True
            scam_reasons.append("blacklisted")
        if security.get("is_in_dex") == "0":
            # Not on DEX anymore = likely rugged
            is_scam = True
            scam_reasons.append("not_on_dex")

        # Check for dangerous permissions
        if security.get("can_take_back_ownership") == "1":
            scam_reasons.append("can_reclaim_ownership")
        if security.get("owner_change_balance") == "1":
            scam_reasons.append("owner_can_change_balance")
        if security.get("hidden_owner") == "1":
            scam_reasons.append("hidden_owner")

        # High sell tax = likely scam
        sell_tax = float(security.get("sell_tax", "0") or "0")
        if sell_tax > 0.5:  # >50% sell tax
            is_scam = True
            scam_reasons.append(f"high_sell_tax_{int(sell_tax*100)}%")

        if is_scam:
            deployer.rug_count += 1
            # Add token to blacklist
            blacklist.append(token)
            # If deployer has multiple rugs, blacklist them too
            if deployer.rug_count >= 2:
                blacklist.append(deployer_addr)
                deployer.flags |= DeployerStats.KNOWN_SCAMMER
        else:
            deployer.survival_count += 1

        # Serial deployer flag
        if deployer.total_deploys >= 5:
            deployer.flags |= DeployerStats.SERIAL_DEPLOYER

    print(f"  Analyzed {len(deployers)} unique deployers")
    print(f"  Found {len(blacklist)} addresses to blacklist")

    return deployers, blacklist


async def fetch_known_scam_addresses(goplus: GoPlusClient) -> list[str]:
    """Fetch additional known scam addresses from GoPlus"""
    print("\n[3/4] Fetching known scam addresses...")

    blacklist = list(KNOWN_SCAM_PATTERNS)

    # Add some known scam token addresses to check their deployers
    known_scam_tokens = [
        # Add known scam token addresses here
        # These will be checked and their deployers added to blacklist
    ]

    if known_scam_tokens:
        security_data = await goplus.batch_check_tokens(known_scam_tokens)
        for token, data in security_data.items():
            creator = data.get("creator_address", "").lower()
            if creator and creator != "0x" + "0" * 40:
                blacklist.append(creator)
            blacklist.append(token)

    print(f"  Added {len(blacklist)} known scam addresses")
    return blacklist


def write_output_files(
    output_dir: str,
    deployers: dict[str, DeployerStats],
    blacklist: list[str]
):
    """Write output CSV and TXT files"""
    print(f"\n[4/4] Writing output files to {output_dir}/...")

    os.makedirs(output_dir, exist_ok=True)

    # Write deployers.csv
    deployers_file = os.path.join(output_dir, "deployers.csv")
    with open(deployers_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["address", "total_deploys", "rug_count", "survival_count", "flags"])
        for addr, stats in sorted(deployers.items(), key=lambda x: -x[1].total_deploys):
            writer.writerow([
                addr,
                stats.total_deploys,
                stats.rug_count,
                stats.survival_count,
                stats.flags
            ])
    print(f"  Wrote {len(deployers)} deployers to deployers.csv")

    # Write blacklist.txt
    blacklist_file = os.path.join(output_dir, "blacklist.txt")
    unique_blacklist = sorted(set(addr.lower() for addr in blacklist if addr))
    with open(blacklist_file, "w") as f:
        f.write("# Lumina BSC Tier 1 Blacklist\n")
        f.write(f"# Generated: {datetime.now().isoformat()}\n")
        f.write(f"# Total: {len(unique_blacklist)} addresses\n\n")
        for addr in unique_blacklist:
            f.write(f"{addr}\n")
    print(f"  Wrote {len(unique_blacklist)} addresses to blacklist.txt")

    # Write bytecodes.csv (placeholder - needs manual curation)
    bytecodes_file = os.path.join(output_dir, "bytecodes.csv")
    with open(bytecodes_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["hash", "label", "risk_score"])
        # Placeholder entries - these need to be populated with actual scam bytecode hashes
        writer.writerow(["# Add keccak256 hashes of known scam contract bytecode here", "", ""])
        writer.writerow(["# Use: keccak256(eth_getCode(scam_token_address))", "", ""])
    print(f"  Wrote bytecodes.csv (placeholder - needs manual curation)")

    # Write summary
    summary_file = os.path.join(output_dir, "summary.json")
    summary = {
        "generated_at": datetime.now().isoformat(),
        "deployers_count": len(deployers),
        "blacklist_count": len(unique_blacklist),
        "scammer_deployers": sum(1 for d in deployers.values() if d.flags & DeployerStats.KNOWN_SCAMMER),
        "serial_deployers": sum(1 for d in deployers.values() if d.flags & DeployerStats.SERIAL_DEPLOYER),
        "total_rugs_detected": sum(d.rug_count for d in deployers.values()),
        "total_survivors": sum(d.survival_count for d in deployers.values()),
    }
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Wrote summary.json")


# ============================================================
# Main
# ============================================================

async def fetch_dexscreener_tokens(session: aiohttp.ClientSession, limit: int = 100) -> list[str]:
    """Fetch recent BSC tokens from DexScreener"""
    print("\n[ALT] Fetching tokens from DexScreener...")
    tokens = []
    
    try:
        # Get trending/new tokens on BSC
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                for item in data[:limit]:
                    if item.get("chainId") == "bsc":
                        tokens.append(item.get("tokenAddress", "").lower())
        
        # Also get from token boosts
        url2 = "https://api.dexscreener.com/token-boosts/latest/v1"
        async with session.get(url2, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                for item in data[:limit]:
                    if item.get("chainId") == "bsc":
                        addr = item.get("tokenAddress", "").lower()
                        if addr and addr not in tokens:
                            tokens.append(addr)
        
        print(f"  Found {len(tokens)} tokens from DexScreener")
    except Exception as e:
        print(f"  DexScreener error: {e}")
    
    return tokens


async def fetch_sample_bsc_tokens(session: aiohttp.ClientSession) -> list[str]:
    """Fetch a sample of BSC tokens to analyze - combines multiple sources"""
    tokens = set()
    
    # Source 1: DexScreener
    dex_tokens = await fetch_dexscreener_tokens(session, 200)
    tokens.update(dex_tokens)
    
    # Source 2: Known high-risk token patterns (for testing)
    # These are example addresses - in production, scrape from scam databases
    sample_tokens = [
        # Add some known BSC tokens to seed the analysis
        "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82",  # CAKE
        "0x2170ed0880ac9a755fd29b2688956bd959f933f8",  # ETH
        "0x55d398326f99059ff775485246999027b3197955",  # USDT
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    ]
    tokens.update(sample_tokens)
    
    return list(tokens)


async def main():
    parser = argparse.ArgumentParser(description="Populate Lumina BSC Tier 1 seed data")
    parser.add_argument("--rpc", default="https://bsc-dataseed.binance.org/",
                        help="BSC RPC URL")
    parser.add_argument("--output-dir", default="data",
                        help="Output directory for CSV/TXT files")
    parser.add_argument("--blocks", type=int, default=10000,
                        help="Number of blocks to scan back (default: 10000 = ~8 hours)")
    parser.add_argument("--use-dexscreener", action="store_true",
                        help="Use DexScreener as token source instead of BSC RPC")
    args = parser.parse_args()

    print("=" * 60)
    print("  Lumina BSC Tier 1 — Seed Data Population")
    print("=" * 60)
    print(f"  RPC: {args.rpc}")
    print(f"  Output: {args.output_dir}/")
    print(f"  Blocks to scan: {args.blocks}")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        bsc = BSCClient(session, args.rpc)
        goplus = GoPlusClient(session)

        # Step 1: Fetch tokens (try RPC first, fallback to DexScreener)
        tokens = []
        if not args.use_dexscreener:
            tokens = await fetch_recent_token_creations(bsc, args.blocks)
        
        if not tokens:
            print("\n[INFO] No tokens from RPC, using DexScreener + sample tokens...")
            token_addrs = await fetch_sample_bsc_tokens(session)
            tokens = [{"token": t, "pair": "", "block": 0} for t in token_addrs]

        if not tokens:
            print("\nNo tokens found from any source.")
            return

        # Step 2: Analyze with GoPlus
        deployers, blacklist = await analyze_tokens_with_goplus(goplus, tokens)

        # Step 3: Add known scam addresses
        known_scams = await fetch_known_scam_addresses(goplus)
        blacklist.extend(known_scams)

        # Step 4: Write output files
        write_output_files(args.output_dir, deployers, blacklist)

    print("\n" + "=" * 60)
    print("  ✓ Seed data population complete!")
    print("=" * 60)
    print(f"\nNext steps:")
    print(f"  1. Review {args.output_dir}/summary.json")
    print(f"  2. Run: ./lumina_hotpath --deployers {args.output_dir}/deployers.csv \\")
    print(f"                          --blacklist {args.output_dir}/blacklist.txt")
    print(f"  3. For bytecodes.csv, manually add keccak256 hashes of known scam bytecode")


if __name__ == "__main__":
    asyncio.run(main())
