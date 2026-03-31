"""
Phase 2b: Fetch GoPlus + Honeypot.is security features for all tokens → token_features.

Usage:
    python ml/fetch_features.py [--limit N] [--skip-existing]

Reads unique tokens from lumina.token_labels, fetches GoPlus security data
in batches of 20, plus Honeypot.is simulation, and inserts into lumina.token_features.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import argparse
import logging
from pathlib import Path
from collections import defaultdict

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load env
def _load_env():
    for env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT.parent / "lumina-backend" / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

GOPLUS_API_KEY = os.environ.get("GOPLUS_API_KEY", "")
CLICKHOUSE_BIN = str(PROJECT_ROOT / "clickhouse-bin")


def ch_query(query: str) -> list[dict]:
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"{query} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"CH error: {result.stderr[:500]}")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


def ch_insert(table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    data = "\n".join(json.dumps(r) for r in rows) + "\n"
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"INSERT INTO {table} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, input=data, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.error(f"CH insert error: {result.stderr[:500]}")
        return 0
    return len(rows)


async def fetch_goplus_batch(client: httpx.AsyncClient, tokens: list[str]) -> dict:
    """Fetch GoPlus security data for up to 20 tokens."""
    token_str = ",".join(tokens)
    url = f"https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={token_str}"
    if GOPLUS_API_KEY:
        url += f"&sign={GOPLUS_API_KEY}"

    try:
        resp = await client.get(url, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 1:
                return data.get("result", {})
    except Exception as e:
        logger.warning(f"GoPlus batch error: {e}")
    return {}


async def fetch_honeypot(client: httpx.AsyncClient, token: str) -> dict:
    """Fetch Honeypot.is simulation results."""
    try:
        url = f"https://api.honeypot.is/v2/IsHoneypot?address={token}&chainID=56"
        resp = await client.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            sim = data.get("simulationResult", {})
            return {
                "success": not data.get("honeypotResult", {}).get("isHoneypot", True),
                "buy_tax": sim.get("buyTax", 0),
                "sell_tax": sim.get("sellTax", 0),
            }
    except Exception:
        pass
    return {"success": False, "buy_tax": 0, "sell_tax": 0}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Limit number of tokens")
    parser.add_argument("--skip-existing", action="store_true", help="Skip tokens already in token_features")
    args = parser.parse_args()

    # Get all tokens that need features
    if args.skip_existing:
        tokens_query = """
            SELECT DISTINCT token_address 
            FROM lumina.token_labels 
            WHERE token_address NOT IN (SELECT token_address FROM lumina.token_features)
            ORDER BY token_address
        """
    else:
        tokens_query = "SELECT DISTINCT token_address FROM lumina.token_labels ORDER BY token_address"

    tokens_data = ch_query(tokens_query)
    tokens = [r["token_address"] for r in tokens_data]

    if args.limit > 0:
        tokens = tokens[:args.limit]

    logger.info(f"Fetching features for {len(tokens)} tokens")

    # Get KOL consensus data (how many KOLs bought each token)
    kol_data = ch_query("""
        SELECT 
            token_address,
            uniq(wallet_address) as kol_count,
            groupArray(wallet_address) as wallets,
            min(block_timestamp) as first_buy_ts
        FROM lumina.kol_swaps 
        WHERE side = 'buy'
        GROUP BY token_address
    """)
    kol_map = {}
    for r in kol_data:
        kol_map[r["token_address"]] = {
            "kol_count": r["kol_count"],
            "wallets": ",".join(r["wallets"][:10]),
            "first_buy_ts": r["first_buy_ts"],
        }

    # Get token symbols/names from swaps
    symbol_data = ch_query("""
        SELECT token_address, any(token_symbol) as sym, any(token_name) as name
        FROM lumina.kol_swaps
        GROUP BY token_address
    """)
    symbol_map = {r["token_address"]: (r["sym"], r["name"]) for r in symbol_data}

    # Fetch GoPlus in batches of 20
    BATCH_SIZE = 20
    goplus_results = {}
    goplus_hit = 0

    async with httpx.AsyncClient(timeout=25) as client:
        for i in range(0, len(tokens), BATCH_SIZE):
            batch = tokens[i:i + BATCH_SIZE]
            result = await fetch_goplus_batch(client, batch)

            for t in batch:
                g = result.get(t.lower()) or result.get(t) or {}
                if g:
                    goplus_results[t] = g
                    goplus_hit += 1

            done = min(i + BATCH_SIZE, len(tokens))
            if done % 200 == 0 or done == len(tokens):
                logger.info(f"  GoPlus: {done}/{len(tokens)} tokens processed, {goplus_hit} with data")
            await asyncio.sleep(0.5)

        logger.info(f"GoPlus: {goplus_hit}/{len(tokens)} tokens have data ({goplus_hit/max(len(tokens),1)*100:.1f}%)")

        # Retry missing tokens individually (GoPlus batch sometimes misses)
        missing = [t for t in tokens if t not in goplus_results]
        if missing:
            retry_count = min(len(missing), 500)  # Limit retries
            logger.info(f"Retrying {retry_count}/{len(missing)} missing tokens individually...")
            retried_hit = 0
            for j, token in enumerate(missing[:retry_count]):
                result = await fetch_goplus_batch(client, [token])
                g = result.get(token.lower()) or result.get(token) or {}
                if g:
                    goplus_results[token] = g
                    retried_hit += 1
                if (j + 1) % 100 == 0:
                    logger.info(f"  Retry: {j+1}/{retry_count}, found {retried_hit} more")
                await asyncio.sleep(0.3)
            logger.info(f"Retry found {retried_hit} more tokens. Total: {len(goplus_results)}/{len(tokens)}")

        # Fetch Honeypot.is for tokens that have GoPlus data (to not waste time on unknown tokens)
        honeypot_results = {}
        honeypot_tokens = list(goplus_results.keys())[:2000]  # Limit to 2000 for speed
        logger.info(f"\nFetching Honeypot.is for {len(honeypot_tokens)} tokens...")
        for j, token in enumerate(honeypot_tokens):
            hp = await fetch_honeypot(client, token)
            honeypot_results[token] = hp
            if (j + 1) % 200 == 0:
                logger.info(f"  Honeypot: {j+1}/{len(honeypot_tokens)}")
            await asyncio.sleep(0.15)

    # Build feature rows
    logger.info(f"\nBuilding feature rows...")
    feature_rows = []
    for token in tokens:
        g = goplus_results.get(token, {})
        hp = honeypot_results.get(token, {})
        kol = kol_map.get(token, {})
        sym, name = symbol_map.get(token, ("???", "???"))

        # GoPlus features
        holders_list = g.get("holders", [])
        top10_pct = 0.0
        creator_pct = 0.0
        if holders_list:
            top10_pct = sum(float(h.get("percent", 0) or 0) for h in holders_list[:10]) * 100
        creator_pct_raw = float(g.get("creator_percent", 0) or 0)
        creator_pct = creator_pct_raw * 100

        # LP lock info
        lp_holders = g.get("lp_holders", [])
        lp_locked = 0
        lp_lock_pct = 0.0
        for lph in lp_holders:
            if lph.get("is_locked"):
                lp_locked = 1
                lp_lock_pct += float(lph.get("percent", 0) or 0) * 100

        row = {
            "token_address": token,
            "token_symbol": sym[:32] if sym else "???",
            "token_name": name[:128] if name else "???",
            "chain": "BSC",
            "first_kol_buy_ts": kol.get("first_buy_ts", 0),
            "is_open_source": 1 if g.get("is_open_source") == "1" else 0,
            "is_proxy": 1 if g.get("is_proxy") == "1" else 0,
            "is_honeypot": 1 if g.get("is_honeypot") == "1" else 0,
            "buy_tax": round(float(g.get("buy_tax", 0) or 0) * 100, 2),
            "sell_tax": round(float(g.get("sell_tax", 0) or 0) * 100, 2),
            "is_mintable": 1 if g.get("is_mintable") == "1" else 0,
            "has_blacklist": 1 if g.get("is_blacklisted") == "1" else 0,
            "can_take_ownership": 1 if g.get("can_take_back_ownership") == "1" else 0,
            "owner_change_balance": 1 if g.get("owner_change_balance") == "1" else 0,
            "hidden_owner": 1 if g.get("hidden_owner") == "1" else 0,
            "selfdestruct": 1 if g.get("selfdestruct") == "1" else 0,
            "external_call": 1 if g.get("external_call") == "1" else 0,
            "is_renounced": 1 if g.get("owner_address") == "0x0000000000000000000000000000000000000000" else 0,
            "holder_count": int(g.get("holder_count", 0) or 0),
            "top10_holder_pct": round(top10_pct, 2),
            "creator_pct": round(creator_pct, 2),
            "lp_locked": lp_locked,
            "lp_lock_pct": round(lp_lock_pct, 2),
            "kol_buyer_count": kol.get("kol_count", 0),
            "kol_wallets": kol.get("wallets", ""),
            "honeypot_sim_success": 1 if hp.get("success") else 0,
            "honeypot_buy_tax": round(float(hp.get("buy_tax", 0) or 0), 2),
            "honeypot_sell_tax": round(float(hp.get("sell_tax", 0) or 0), 2),
        }
        feature_rows.append(row)

    # Insert in batches
    BATCH = 500
    total_inserted = 0
    for i in range(0, len(feature_rows), BATCH):
        batch = feature_rows[i:i + BATCH]
        inserted = ch_insert("lumina.token_features", batch)
        total_inserted += inserted
        if (i + BATCH) % 2000 == 0:
            logger.info(f"  Inserted {total_inserted}/{len(feature_rows)} features...")

    logger.info(f"Inserted {total_inserted} feature rows into token_features")

    # Stats
    has_goplus = sum(1 for t in tokens if t in goplus_results)
    has_honeypot = sum(1 for t in tokens if t in honeypot_results)
    logger.info(f"\n{'='*60}")
    logger.info(f"PHASE 2b COMPLETE")
    logger.info(f"  Total tokens:     {len(tokens)}")
    logger.info(f"  GoPlus data:      {has_goplus} ({has_goplus/max(len(tokens),1)*100:.1f}%)")
    logger.info(f"  Honeypot.is data: {has_honeypot} ({has_honeypot/max(len(tokens),1)*100:.1f}%)")
    logger.info(f"  Feature rows:     {total_inserted}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
