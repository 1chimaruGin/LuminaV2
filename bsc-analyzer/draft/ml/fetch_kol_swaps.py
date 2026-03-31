"""
Phase 1: Fetch all BSC swap history for KOL wallets via Moralis → ClickHouse.

Usage:
    python ml/fetch_kol_swaps.py [--wallet 0x...] [--max-pages 500]

Reads wallets from top.json, fetches all DEX swaps from Moralis,
and inserts into lumina.kol_swaps ClickHouse table.
"""

import asyncio
import json
import os
import sys
import time
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from lumina-backend (has Moralis key)
def _load_env():
    for env_path in [PROJECT_ROOT / ".env", PROJECT_ROOT.parent / "lumina-backend" / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

MORALIS_API_KEY = os.environ.get("MORALIS_API_KEY", "")
CLICKHOUSE_BIN = str(PROJECT_ROOT / "clickhouse-bin")


def load_valid_kol_wallets_from_top_json(top_path: Path) -> list[str]:
    """Return unique lowercase 0x addresses from top.json; skip blanks and invalid entries."""
    with open(top_path) as f:
        wallets_data = json.load(f)
    out: list[str] = []
    for w in wallets_data:
        addr = (w.get("address") or "").strip().lower()
        if len(addr) == 42 and addr.startswith("0x"):
            out.append(addr)
    return list(dict.fromkeys(out))


# BSC native/stablecoin addresses to filter out
NATIVE_MINTS = {
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    "0x0000000000000000000000000000000000000000",
}
STABLECOIN_MINTS = {
    "0x55d398326f99059ff775485246999027b3197955",  # USDT
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
    "0xc5f0f7b66764f6ec8c8dff7ba683102295e16409",  # FDUSD
    "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d",  # USD1
}


def _parse_timestamp(block_ts) -> int:
    if isinstance(block_ts, str) and block_ts:
        try:
            dt = datetime.fromisoformat(block_ts.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except Exception:
            return 0
    elif isinstance(block_ts, (int, float)):
        return int(block_ts) if block_ts < 1e12 else int(block_ts / 1000)
    return 0


def _normalize_amount(amount: float, token_addr: str) -> float:
    """Fix raw wei amounts from Moralis."""
    addr = token_addr.lower()
    # Stablecoins with 18 decimals
    if addr in STABLECOIN_MINTS and amount > 1e15:
        return amount / 1e18
    # Native tokens
    if addr in NATIVE_MINTS and amount > 1e15:
        return amount / 1e18
    # Generic: if > 1e20, likely raw 18-decimal
    if amount > 1e20:
        return amount / 1e18
    return amount


def _parse_swap(sw: dict, native_price: float) -> list[dict]:
    """Parse a Moralis swap into normalized records."""
    results = []
    block_ts = sw.get("blockTimestamp") or sw.get("block_timestamp") or ""
    ts = _parse_timestamp(block_ts)
    tx_hash = sw.get("transactionHash", sw.get("transaction_hash", ""))
    tx_type = sw.get("transactionType", "")
    pair_label = sw.get("pairLabel", "")

    bought = sw.get("bought", {}) or {}
    sold = sw.get("sold", {}) or {}

    bought_addr = (bought.get("address") or "").lower()
    sold_addr = (sold.get("address") or "").lower()
    bought_sym = bought.get("symbol") or bought.get("name") or "?"
    sold_sym = sold.get("symbol") or sold.get("name") or "?"
    bought_name = bought.get("name") or bought_sym
    sold_name = sold.get("name") or sold_sym
    bought_logo = bought.get("logo") or ""
    sold_logo = sold.get("logo") or ""

    bought_amt = abs(float(bought.get("amount") or 0))
    sold_amt = abs(float(sold.get("amount") or 0))

    bought_is_quote = bought_addr in NATIVE_MINTS or bought_addr in STABLECOIN_MINTS
    sold_is_quote = sold_addr in NATIVE_MINTS or sold_addr in STABLECOIN_MINTS

    bought_usd = abs(float(bought.get("usdAmount") or 0))
    sold_usd = abs(float(sold.get("usdAmount") or 0))

    # Cross-validate Moralis USD against native estimate
    if native_price > 0:
        if bought_is_quote and bought_addr in NATIVE_MINTS and bought_amt > 0:
            est = _normalize_amount(bought_amt, bought_addr) * native_price
            if bought_usd > est * 10 and est > 1:
                bought_usd = est
        if sold_is_quote and sold_addr in NATIVE_MINTS and sold_amt > 0:
            est = _normalize_amount(sold_amt, sold_addr) * native_price
            if sold_usd > est * 10 and est > 1:
                sold_usd = est

    if sold_is_quote and sold_usd > 0:
        trade_usd = sold_usd
    elif bought_is_quote and bought_usd > 0:
        trade_usd = bought_usd
    else:
        trade_usd = 0.0
        if sold_is_quote and sold_amt > 0:
            norm = _normalize_amount(sold_amt, sold_addr)
            if sold_addr in NATIVE_MINTS:
                trade_usd = norm * native_price
            elif sold_addr in STABLECOIN_MINTS:
                trade_usd = norm
        if trade_usd == 0 and bought_is_quote and bought_amt > 0:
            norm = _normalize_amount(bought_amt, bought_addr)
            if bought_addr in NATIVE_MINTS:
                trade_usd = norm * native_price
            elif bought_addr in STABLECOIN_MINTS:
                trade_usd = norm

    def _make(token_addr, token_sym, token_name, token_logo, side, token_amt, quote_amt):
        if not token_addr or token_addr in NATIVE_MINTS or token_addr in STABLECOIN_MINTS:
            return None
        return {
            "token_address": token_addr,
            "token_symbol": token_sym[:32],
            "token_name": token_name[:128],
            "token_logo": token_logo,
            "side": side,
            "token_amount": _normalize_amount(token_amt, token_addr),
            "quote_amount": quote_amt,
            "usd_value": trade_usd,
            "tx_hash": tx_hash,
            "block_timestamp": ts,
            "pair_label": pair_label,
        }

    if tx_type == "buy":
        if not bought_is_quote:
            r = _make(bought_addr, bought_sym, bought_name, bought_logo, "buy", bought_amt, sold_amt if sold_is_quote else bought_amt)
        else:
            r = _make(sold_addr, sold_sym, sold_name, sold_logo, "buy", sold_amt, bought_amt)
        if r:
            results.append(r)
    elif tx_type == "sell":
        if not sold_is_quote:
            r = _make(sold_addr, sold_sym, sold_name, sold_logo, "sell", sold_amt, bought_amt if bought_is_quote else sold_amt)
        else:
            r = _make(bought_addr, bought_sym, bought_name, bought_logo, "sell", bought_amt, sold_amt)
        if r:
            results.append(r)
    elif not tx_type and bought_addr and sold_addr:
        r1 = _make(sold_addr, sold_sym, sold_name, sold_logo, "sell", sold_amt, bought_amt)
        r2 = _make(bought_addr, bought_sym, bought_name, bought_logo, "buy", bought_amt, sold_amt)
        if r1:
            results.append(r1)
        if r2:
            results.append(r2)

    return results


async def fetch_bnb_price(client: httpx.AsyncClient) -> float:
    """Get current BNB price for USD estimation."""
    try:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=binancecoin&vs_currencies=usd",
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("binancecoin", {}).get("usd", 600.0)
    except Exception:
        pass
    return 600.0  # Fallback


async def fetch_wallet_swaps(
    client: httpx.AsyncClient,
    wallet: str,
    max_pages: int = 500,
    native_price: float = 600.0,
) -> list[dict]:
    """Fetch all BSC DEX swaps for a wallet from Moralis."""
    headers = {"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}
    swaps = []
    cursor = None

    for page in range(max_pages):
        url = f"https://deep-index.moralis.io/api/v2.2/wallets/{wallet}/swaps"
        params = {"chain": "0x38", "order": "DESC", "limit": "100"}
        if cursor:
            params["cursor"] = cursor

        resp = await client.get(url, headers=headers, params=params)

        # Retry on rate limit
        for retry in range(3):
            if resp.status_code in (429, 502, 503):
                wait = min(2 ** (retry + 1), 15)
                logger.warning(f"  Moralis {resp.status_code}, retry {retry+1} in {wait}s")
                await asyncio.sleep(wait)
                resp = await client.get(url, headers=headers, params=params)
            else:
                break

        if resp.status_code != 200:
            logger.error(f"  Moralis {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        result = data.get("result", [])
        if not result:
            break

        for sw in result:
            parsed = _parse_swap(sw, native_price)
            swaps.extend(parsed)

        cursor = data.get("cursor")
        if not cursor:
            break

        if (page + 1) % 25 == 0:
            logger.info(f"  {wallet[:12]}... page {page+1}, {len(swaps)} swaps so far")
        await asyncio.sleep(0.15)

    logger.info(f"  {wallet[:12]}... total: {len(swaps)} swaps across {min(page+1, max_pages)} pages")
    return swaps


def insert_to_clickhouse(wallet: str, swaps: list[dict]):
    """Batch insert swaps into ClickHouse via clickhouse-bin client."""
    if not swaps:
        return 0

    import subprocess

    rows = []
    for s in swaps:
        # Escape strings for TSV
        def esc(v):
            return str(v).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")

        row = "\t".join([
            esc(wallet.lower()),
            esc(s["token_address"]),
            esc(s["token_symbol"]),
            esc(s["token_name"]),
            esc(s.get("token_logo", "")),
            esc(s["side"]),
            str(s["token_amount"]),
            str(s.get("quote_amount", 0)),
            str(s["usd_value"]),
            esc(s["tx_hash"]),
            str(s["block_timestamp"]),
            "BSC",
            esc(s.get("pair_label", "")),
        ])
        rows.append(row)

    tsv_data = "\n".join(rows) + "\n"

    cmd = [
        CLICKHOUSE_BIN, "client",
        "--query",
        "INSERT INTO lumina.kol_swaps (wallet_address, token_address, token_symbol, token_name, token_logo, side, token_amount, quote_amount, usd_value, tx_hash, block_timestamp, chain, pair_label) FORMAT TabSeparated"
    ]

    result = subprocess.run(cmd, input=tsv_data, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.error(f"ClickHouse insert error: {result.stderr[:500]}")
        return 0

    logger.info(f"  Inserted {len(rows)} swaps for {wallet[:12]}...")
    return len(rows)


async def main():
    parser = argparse.ArgumentParser(description="Fetch KOL wallet swaps → ClickHouse")
    parser.add_argument("--wallet", help="Single wallet to fetch (default: all from top.json)")
    parser.add_argument("--max-pages", type=int, default=500, help="Max Moralis pages per wallet")
    args = parser.parse_args()

    # Load wallets
    top_path = PROJECT_ROOT / "top.json"
    if args.wallet:
        wallets = [args.wallet.lower()]
    else:
        wallets = load_valid_kol_wallets_from_top_json(top_path)
        if not wallets:
            logger.error("No valid wallets in %s (need 0x + 40 hex chars per entry)", top_path)
            sys.exit(1)

    logger.info(f"Fetching swaps for {len(wallets)} wallets")

    async with httpx.AsyncClient(timeout=25) as client:
        bnb_price = await fetch_bnb_price(client)
        logger.info(f"BNB price: ${bnb_price:.2f}")

        total_swaps = 0
        total_inserted = 0

        for i, wallet in enumerate(wallets):
            logger.info(f"\n[{i+1}/{len(wallets)}] Fetching {wallet}")
            t0 = time.time()

            swaps = await fetch_wallet_swaps(client, wallet, max_pages=args.max_pages, native_price=bnb_price)
            total_swaps += len(swaps)

            # Deduplicate by (tx_hash, token_address, side)
            seen = set()
            unique = []
            for s in swaps:
                key = (s["tx_hash"], s["token_address"], s["side"])
                if key not in seen:
                    seen.add(key)
                    unique.append(s)

            inserted = insert_to_clickhouse(wallet, unique)
            total_inserted += inserted

            elapsed = time.time() - t0
            logger.info(f"  Done in {elapsed:.1f}s: {len(swaps)} fetched, {len(unique)} unique, {inserted} inserted")

    logger.info(f"\n{'='*60}")
    logger.info(f"COMPLETE: {total_swaps} total swaps, {total_inserted} inserted to ClickHouse")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
