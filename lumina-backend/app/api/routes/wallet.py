"""
Wallet analysis API routes — fetches real on-chain balances from
Solana / Ethereum public RPCs, augments with Grok AI for context,
and has pre-loaded profiles for famous wallets.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Query

from pydantic import BaseModel

from app.core.rate_limit import rate_limit

from app.core.config import get_settings
from app.db.redis import cache_get, cache_set
from app.schemas.wallet import WalletAnalysisRequest
from app.services.token_resolver import resolve_mint, resolve_mints_batch

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/wallet", tags=["Wallet"])

# ── RPCs ──────────────────────────────────────────────────────────────────────
_alchemy_key = settings.ALCHEMY_API_KEY
SOLANA_RPC = f"https://solana-mainnet.g.alchemy.com/v2/{_alchemy_key}" if _alchemy_key else "https://api.mainnet-beta.solana.com"
ETH_RPC = f"https://eth-mainnet.g.alchemy.com/v2/{_alchemy_key}" if _alchemy_key else "https://eth.llamarpc.com"

# EVM chain RPCs — public endpoints for each chain
EVM_RPCS: dict[str, str] = {
    "ETH": ETH_RPC,
    "BSC": "https://bsc-dataseed1.binance.org",
    "ARB": f"https://arb-mainnet.g.alchemy.com/v2/{_alchemy_key}" if _alchemy_key else "https://arb1.arbitrum.io/rpc",
    "BASE": f"https://base-mainnet.g.alchemy.com/v2/{_alchemy_key}" if _alchemy_key else "https://mainnet.base.org",
    "OP": f"https://opt-mainnet.g.alchemy.com/v2/{_alchemy_key}" if _alchemy_key else "https://mainnet.optimism.io",
    "AVAX": "https://api.avax.network/ext/bc/C/rpc",
    "MATIC": "https://polygon-rpc.com",
}

# Native token info per EVM chain
EVM_NATIVE: dict[str, dict] = {
    "ETH": {"symbol": "ETH", "name": "Ethereum", "coingecko": "ethereum", "logo": "https://assets.coingecko.com/coins/images/279/small/ethereum.png", "decimals": 18},
    "BSC": {"symbol": "BNB", "name": "BNB Chain", "coingecko": "binancecoin", "logo": "https://assets.coingecko.com/coins/images/825/small/bnb-icon2_2x.png", "decimals": 18},
    "ARB": {"symbol": "ETH", "name": "Ethereum (Arbitrum)", "coingecko": "ethereum", "logo": "https://assets.coingecko.com/coins/images/279/small/ethereum.png", "decimals": 18},
    "BASE": {"symbol": "ETH", "name": "Ethereum (Base)", "coingecko": "ethereum", "logo": "https://assets.coingecko.com/coins/images/279/small/ethereum.png", "decimals": 18},
    "OP": {"symbol": "ETH", "name": "Ethereum (Optimism)", "coingecko": "ethereum", "logo": "https://assets.coingecko.com/coins/images/279/small/ethereum.png", "decimals": 18},
    "AVAX": {"symbol": "AVAX", "name": "Avalanche", "coingecko": "avalanche-2", "logo": "https://assets.coingecko.com/coins/images/12559/small/Avalanche_Circle_RedWhite_Trans.png", "decimals": 18},
    "MATIC": {"symbol": "POL", "name": "Polygon", "coingecko": "matic-network", "logo": "https://assets.coingecko.com/coins/images/4713/small/polygon.png", "decimals": 18},
}

logger.info(f"Solana RPC: {'Alchemy' if _alchemy_key else 'public'} | ETH RPC: {'Alchemy' if _alchemy_key else 'llamarpc'} | EVM chains: {list(EVM_RPCS.keys())}")

# ── Token Registry (CoinGecko token lists + Trust Wallet CDN) ─────────────
# Maps chain -> CoinGecko token list URL
_TOKEN_LIST_URLS = {
    "ETH": "https://tokens.coingecko.com/ethereum/all.json",
    "BSC": "https://tokens.coingecko.com/binance-smart-chain/all.json",
    "ARB": "https://tokens.coingecko.com/arbitrum-one/all.json",
    "BASE": "https://tokens.coingecko.com/base/all.json",
    "OP": "https://tokens.coingecko.com/optimistic-ethereum/all.json",
    "AVAX": "https://tokens.coingecko.com/avalanche/all.json",
    "MATIC": "https://tokens.coingecko.com/polygon-pos/all.json",
}
# Trust Wallet asset CDN — chain slug per chain
_TW_CHAIN_SLUG = {
    "ETH": "ethereum",
    "BSC": "smartchain",
    "ARB": "arbitrum",
    "BASE": "base",
    "OP": "optimism",
    "AVAX": "avalanchec",
    "MATIC": "polygon",
}

# In-memory token registry cache: chain -> {addr_lower -> {symbol, name, logo}}
_token_registry: dict[str, dict[str, dict]] = {}
_token_registry_ts: dict[str, float] = {}
_TOKEN_REGISTRY_TTL = 86400  # 24h


async def _load_token_registry(chain: str) -> dict[str, dict]:
    """Load CoinGecko token list for a chain, cached in-memory for 24h + Redis."""
    now = time.time()
    if chain in _token_registry and (now - _token_registry_ts.get(chain, 0)) < _TOKEN_REGISTRY_TTL:
        return _token_registry[chain]

    # Try Redis first
    cache_key = f"token_registry:{chain}"
    cached = await cache_get(cache_key)
    if cached and isinstance(cached, dict):
        _token_registry[chain] = cached
        _token_registry_ts[chain] = now
        logger.info(f"Token registry {chain}: loaded {len(cached)} tokens from cache")
        return cached

    # Fetch from CoinGecko
    url = _TOKEN_LIST_URLS.get(chain)
    if not url:
        return {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code != 200:
                logger.warning(f"Token list fetch failed {chain}: {r.status_code}")
                return _token_registry.get(chain, {})
            data = r.json()
            tokens = data.get("tokens", [])
            registry: dict[str, dict] = {}
            for t in tokens:
                addr = t.get("address", "").lower()
                if addr:
                    registry[addr] = {
                        "symbol": t.get("symbol", ""),
                        "name": t.get("name", ""),
                        "logo": t.get("logoURI", ""),
                        "decimals": t.get("decimals", 18),
                    }
            _token_registry[chain] = registry
            _token_registry_ts[chain] = now
            await cache_set(cache_key, registry, ttl=_TOKEN_REGISTRY_TTL)
            logger.info(f"Token registry {chain}: loaded {len(registry)} tokens from CoinGecko")
            return registry
    except Exception as e:
        logger.warning(f"Token registry load error {chain}: {e}")
        return _token_registry.get(chain, {})


def _tw_logo_url(chain: str, contract_addr: str) -> str:
    """Build Trust Wallet CDN logo URL for a token. Needs checksum address."""
    slug = _TW_CHAIN_SLUG.get(chain)
    if not slug:
        return ""
    return f"https://assets-cdn.trustwallet.com/blockchains/{slug}/assets/{contract_addr}/logo.png"


def _detect_chain(address: str) -> str:
    if address.startswith("0x"):
        return "ETH"
    elif address.startswith("bc1") or address.startswith("1") or address.startswith("3"):
        return "BTC"
    else:
        return "SOL"


# ── Real on-chain balance fetchers ────────────────────────────────────────────

async def _fetch_sol_balance(address: str) -> Optional[dict]:
    """Fetch SOL balance + token accounts with resolved names from Solana mainnet RPC.
    All RPC calls run in parallel for speed."""
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            # ── Fire all 4 requests in parallel ──
            async def _get_balance():
                r = await client.post(SOLANA_RPC, json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getBalance", "params": [address],
                })
                return r.json().get("result", {}).get("value", 0) / 1e9

            async def _get_price():
                try:
                    r = await client.get(
                        "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
                        timeout=3,
                    )
                    return r.json().get("solana", {}).get("usd", 0)
                except Exception:
                    return 0

            async def _get_tokens():
                # Query both SPL Token and Token-2022 programs in parallel
                spl_req = client.post(SOLANA_RPC, json={
                    "jsonrpc": "2.0", "id": 2,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        address,
                        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                        {"encoding": "jsonParsed"},
                    ],
                })
                t22_req = client.post(SOLANA_RPC, json={
                    "jsonrpc": "2.0", "id": 22,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        address,
                        {"programId": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"},
                        {"encoding": "jsonParsed"},
                    ],
                })
                spl_r, t22_r = await asyncio.gather(spl_req, t22_req, return_exceptions=True)
                accounts = []
                if not isinstance(spl_r, Exception):
                    accounts.extend(spl_r.json().get("result", {}).get("value", []))
                if not isinstance(t22_r, Exception):
                    accounts.extend(t22_r.json().get("result", {}).get("value", []))
                return accounts

            async def _get_sigs():
                r = await client.post(SOLANA_RPC, json={
                    "jsonrpc": "2.0", "id": 3,
                    "method": "getSignaturesForAddress",
                    "params": [address, {"limit": 100}],
                })
                return r.json().get("result", [])

            sol_balance, sol_price, token_accounts, recent_sigs = await asyncio.gather(
                _get_balance(), _get_price(), _get_tokens(), _get_sigs()
            )

            sol_usd = sol_balance * sol_price
            token_count = len(token_accounts)
            txn_count = len(recent_sigs)

            # ── Parse ALL holdings ──
            holdings_raw = []
            for acct in token_accounts:
                info = acct.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                amt_info = info.get("tokenAmount", {})
                ui_amount = amt_info.get("uiAmount") or 0
                if ui_amount > 0:
                    holdings_raw.append({"mint": info.get("mint", ""), "amount": ui_amount})

            # ── Price ALL tokens via DexScreener BEFORE sorting ──
            # DexScreener allows 30 addresses per request; batch them
            all_mints = [h["mint"] for h in holdings_raw if h["mint"]]
            token_prices: dict[str, float] = {}
            dex_meta: dict[str, dict] = {}  # addr -> {symbol, name, logo}

            async def _fetch_dex_batch(batch_mints: list[str]):
                """Fetch prices + metadata for up to 30 mints from DexScreener."""
                if not batch_mints:
                    return
                try:
                    url = "https://api.dexscreener.com/tokens/v1/solana/" + ",".join(batch_mints)
                    resp = await client.get(url, timeout=10)
                    pairs = resp.json() if resp.status_code == 200 else []
                    if not isinstance(pairs, list):
                        return
                    for pair in pairs:
                        base = pair.get("baseToken", {})
                        addr = base.get("address", "")
                        if not addr:
                            continue
                        price_str = pair.get("priceUsd")
                        if addr not in token_prices and price_str:
                            try:
                                token_prices[addr] = float(price_str)
                            except (ValueError, TypeError):
                                pass
                        if addr not in dex_meta:
                            p_info = pair.get("info", {})
                            dex_meta[addr] = {
                                "symbol": base.get("symbol", ""),
                                "name": base.get("name", ""),
                                "logo": p_info.get("imageUrl", ""),
                            }
                except Exception as e:
                    logger.debug(f"DexScreener batch error: {e}")

            # Fire all DexScreener batches in parallel (30 per request)
            batches = [all_mints[i:i + 30] for i in range(0, len(all_mints), 30)]
            if batches:
                await asyncio.gather(*[_fetch_dex_batch(b) for b in batches], return_exceptions=True)

            # ── Resolve names for top mints via token_resolver (fallback for DexScreener misses) ──
            # Only resolve the ones DexScreener didn't identify
            unresolved_mints = [m for m in all_mints if m not in dex_meta][:30]
            resolved = {}
            if unresolved_mints:
                resolved = await resolve_mints_batch(unresolved_mints)

            # ── Build enriched holdings with USD values for ALL tokens ──
            all_holdings = []
            total_token_usd = 0.0
            for h in holdings_raw:
                mint = h["mint"]
                dex_info = dex_meta.get(mint, {})
                resolver_info = resolved.get(mint, {})
                symbol = dex_info.get("symbol") or resolver_info.get("symbol") or mint[:6]
                name = dex_info.get("name") or resolver_info.get("name") or "Unknown Token"
                logo = dex_info.get("logo") or resolver_info.get("logo") or ""
                if not logo and mint:
                    logo = f"https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/{mint}/logo.png"
                price = token_prices.get(mint, 0)
                usd_value = h["amount"] * price
                total_token_usd += usd_value
                all_holdings.append({
                    "mint": mint,
                    "symbol": symbol,
                    "name": name,
                    "logo": logo,
                    "amount": h["amount"],
                    "usd_value": round(usd_value, 6),
                    "price": price,
                })

            # Filter out dust (< $10) and sort by USD value descending
            all_holdings = [h for h in all_holdings if h["usd_value"] >= 10]
            all_holdings.sort(key=lambda h: h["usd_value"], reverse=True)

            # Return top 50 (UI paginates the rest)
            top_holdings = all_holdings[:50]
            total_portfolio_usd = sol_usd + total_token_usd

            # ── Parse sig timestamps ──
            sig_timestamps = [s.get("blockTime") for s in recent_sigs if s.get("blockTime")]

            return {
                "sol_balance": f"{sol_balance:,.4f} SOL",
                "sol_value": f"${sol_usd:,.2f}" if sol_price else "—",
                "sol_balance_raw": sol_balance,
                "sol_usd_raw": sol_usd,
                "sol_price": sol_price,
                "total_portfolio_usd": total_portfolio_usd,
                "total_token_usd": total_token_usd,
                "token_count": token_count,
                "recent_txn_count": txn_count,
                "top_token_accounts": top_holdings,
                "sig_timestamps": sig_timestamps,
                "recent_signatures": [s.get("signature", "") for s in recent_sigs],
            }
    except Exception as e:
        logger.error(f"Solana RPC error for {address}: {e}")
        return None


async def _fetch_eth_balance(address: str) -> Optional[dict]:
    """Fetch ETH balance from Ethereum mainnet RPC."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(ETH_RPC, json={
                "jsonrpc": "2.0", "id": 1,
                "method": "eth_getBalance",
                "params": [address, "latest"],
            })
            data = resp.json()
            wei = int(data.get("result", "0x0"), 16)
            eth_balance = wei / 1e18

            # ETH price
            try:
                price_resp = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
                    timeout=5,
                )
                eth_price = price_resp.json().get("ethereum", {}).get("usd", 0)
            except Exception:
                eth_price = 0

            eth_usd = eth_balance * eth_price

            # Transaction count (nonce)
            nonce_resp = await client.post(ETH_RPC, json={
                "jsonrpc": "2.0", "id": 2,
                "method": "eth_getTransactionCount",
                "params": [address, "latest"],
            })
            nonce_data = nonce_resp.json()
            txn_count = int(nonce_data.get("result", "0x0"), 16)

            return {
                "eth_balance": f"{eth_balance:,.4f} ETH",
                "eth_value": f"${eth_usd:,.2f}" if eth_price else "—",
                "eth_balance_raw": eth_balance,
                "eth_usd_raw": eth_usd,
                "eth_price": eth_price,
                "txn_count": txn_count,
            }
    except Exception as e:
        logger.error(f"Ethereum RPC error for {address}: {e}")
        return None


async def _fetch_evm_balance(address: str, chain: str) -> Optional[dict]:
    """Fetch native balance + ERC-20/BEP-20 token balances for any EVM chain.

    Strategy (mirrors Arkham/GMGN):
      1. Load CoinGecko token registry (cached 24h) for instant symbol/name/logo/decimals
      2. Alchemy getTokenBalances (paginated) for raw balances
      3. Resolve known tokens from registry (instant), unknown via Alchemy metadata
      4. Price via DexScreener (registry tokens first) + Moralis fallback
      5. Logos: registry -> DexScreener -> Trust Wallet CDN fallback
    """
    rpc_url = EVM_RPCS.get(chain)
    native = EVM_NATIVE.get(chain)
    if not rpc_url or not native:
        logger.warning(f"No RPC configured for chain {chain}")
        return None

    _alchemy_rpcs = {
        "ETH": f"https://eth-mainnet.g.alchemy.com/v2/{_alchemy_key}",
        "BSC": f"https://bnb-mainnet.g.alchemy.com/v2/{_alchemy_key}",
        "ARB": f"https://arb-mainnet.g.alchemy.com/v2/{_alchemy_key}",
        "BASE": f"https://base-mainnet.g.alchemy.com/v2/{_alchemy_key}",
        "OP": f"https://opt-mainnet.g.alchemy.com/v2/{_alchemy_key}",
    } if _alchemy_key else {}
    _dex_chains = {"ETH": "ethereum", "BSC": "bsc", "ARB": "arbitrum", "BASE": "base", "OP": "optimism", "AVAX": "avalanche", "MATIC": "polygon"}
    _moralis_chains = {"ETH": "eth", "BSC": "bsc", "ARB": "arbitrum", "BASE": "base", "OP": "optimism", "AVAX": "avalanche", "MATIC": "polygon"}

    alchemy_rpc = _alchemy_rpcs.get(chain)
    dex_chain = _dex_chains.get(chain, "")
    moralis_chain = _moralis_chains.get(chain)
    moralis_key = settings.MORALIS_API_KEY

    try:
        async with httpx.AsyncClient(timeout=30) as client:

            # ── Phase 1: Parallel — native bal, price, nonce, Alchemy balances, token registry ──
            async def _get_native():
                resp = await client.post(rpc_url, json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "eth_getBalance",
                    "params": [address, "latest"],
                })
                wei = int(resp.json().get("result", "0x0"), 16)
                return wei / (10 ** native["decimals"])

            async def _get_native_price():
                try:
                    r = await client.get(
                        f"https://api.coingecko.com/api/v3/simple/price?ids={native['coingecko']}&vs_currencies=usd",
                        timeout=5,
                    )
                    return r.json().get(native["coingecko"], {}).get("usd", 0)
                except Exception:
                    return 0

            async def _get_nonce():
                r = await client.post(rpc_url, json={
                    "jsonrpc": "2.0", "id": 2,
                    "method": "eth_getTransactionCount",
                    "params": [address, "latest"],
                })
                return int(r.json().get("result", "0x0"), 16)

            async def _get_tokens_alchemy() -> list[dict]:
                if not alchemy_rpc:
                    return []
                try:
                    all_nonzero: list[dict] = []
                    page_key = None
                    for _ in range(10):
                        params: list = [address, "erc20"]
                        if page_key:
                            params = [address, "erc20", {"pageKey": page_key}]
                        r = await client.post(alchemy_rpc, json={
                            "jsonrpc": "2.0", "id": 10,
                            "method": "alchemy_getTokenBalances",
                            "params": params,
                        }, timeout=15)
                        data = r.json()
                        if "error" in data:
                            logger.warning(f"Alchemy getTokenBalances error {chain}: {data['error']}")
                            break
                        result = data.get("result", {})
                        for tb in result.get("tokenBalances", []):
                            hex_bal = tb.get("tokenBalance", "0x0")
                            if hex_bal and hex_bal != "0x0":
                                raw = int(hex_bal, 16)
                                if raw > 0:
                                    all_nonzero.append({"contract": tb["contractAddress"], "raw_balance": raw})
                        page_key = result.get("pageKey")
                        if not page_key:
                            break
                    logger.info(f"Alchemy {chain}: {len(all_nonzero)} non-zero tokens (paginated)")
                    return all_nonzero
                except Exception as e:
                    logger.warning(f"Alchemy getTokenBalances error {chain}: {e}")
                    return []

            native_bal, native_price, txn_count, raw_tokens, registry = await asyncio.gather(
                _get_native(), _get_native_price(), _get_nonce(),
                _get_tokens_alchemy(), _load_token_registry(chain),
                return_exceptions=True,
            )
            if isinstance(native_bal, Exception): native_bal = 0.0
            if isinstance(native_price, Exception): native_price = 0.0
            if isinstance(txn_count, Exception): txn_count = 0
            if isinstance(raw_tokens, Exception): raw_tokens = []
            if isinstance(registry, Exception): registry = {}

            native_usd = native_bal * native_price

            # ── Phase 2: Resolve metadata from registry (instant) ──
            # Split Alchemy tokens into registry-known vs unknown
            alchemy_found: set[str] = set()  # track addresses already found by Alchemy
            known_tokens: list[dict] = []
            unknown_addrs: list[str] = []
            for rt in raw_tokens:
                addr_lower = rt["contract"].lower()
                alchemy_found.add(addr_lower)
                reg = registry.get(addr_lower)
                if reg:
                    decimals = reg.get("decimals", 18) or 18
                    ui_amount = rt["raw_balance"] / (10 ** decimals)
                    if ui_amount > 0:
                        known_tokens.append({
                            "contract": rt["contract"],
                            "symbol": reg["symbol"] or "???",
                            "name": reg["name"] or "Unknown",
                            "logo": reg.get("logo", ""),
                            "amount": ui_amount,
                            "price": 0.0,
                            "usd_value": 0.0,
                        })
                else:
                    unknown_addrs.append(rt["contract"])

            # ── Phase 2b: Batch balanceOf for ALL registry tokens Alchemy missed ──
            # This catches USDT, USDC, DAI, CAKE etc. that Alchemy's index skips
            _balance_of_sig = "0x70a08231"  # balanceOf(address)
            _padded_addr = address[2:].lower().zfill(64)
            _call_data = _balance_of_sig + _padded_addr

            registry_addrs_to_check = [
                addr for addr in registry if addr not in alchemy_found
            ]
            if registry_addrs_to_check and alchemy_rpc:
                for batch_start in range(0, len(registry_addrs_to_check), 200):
                    batch_chunk = registry_addrs_to_check[batch_start:batch_start + 200]
                    # Build id -> address map for reliable response matching
                    id_to_addr: dict[int, str] = {}
                    rpc_batch = []
                    for i, ca in enumerate(batch_chunk):
                        rpc_id = batch_start + i
                        id_to_addr[rpc_id] = ca
                        rpc_batch.append({
                            "jsonrpc": "2.0", "id": rpc_id,
                            "method": "eth_call",
                            "params": [{"to": ca, "data": _call_data}, "latest"],
                        })
                    try:
                        r = await client.post(alchemy_rpc, json=rpc_batch, timeout=25)
                        results = r.json()
                        if isinstance(results, list):
                            for res in results:
                                if "error" in res:
                                    continue
                                rpc_id = res.get("id")
                                ca = id_to_addr.get(rpc_id)
                                if not ca:
                                    continue
                                hex_result = res.get("result", "0x0")
                                if not hex_result or hex_result in ("0x", "0x0"):
                                    continue
                                try:
                                    raw_bal = int(hex_result, 16)
                                except (ValueError, TypeError):
                                    continue
                                if raw_bal <= 0:
                                    continue
                                reg = registry.get(ca)
                                if not reg:
                                    continue
                                decimals = reg.get("decimals", 18) or 18
                                ui_amount = raw_bal / (10 ** decimals)
                                if ui_amount > 0:
                                    known_tokens.append({
                                        "contract": ca,
                                        "symbol": reg["symbol"] or "???",
                                        "name": reg["name"] or "Unknown",
                                        "logo": reg.get("logo", ""),
                                        "amount": ui_amount,
                                        "price": 0.0,
                                        "usd_value": 0.0,
                                    })
                    except Exception as e:
                        logger.debug(f"Batch balanceOf error {chain}: {e}")

            # Debug: log stablecoin presence
            _stable_syms = [t["symbol"] for t in known_tokens if t["symbol"].upper() in ("USDT","USDC","BSC-USD","DAI","BUSD")]
            logger.info(f"Registry {chain}: {len(known_tokens)} known (after balanceOf scan), {len(unknown_addrs)} unknown, stables={_stable_syms}")

            # ── Phase 3: Price known tokens via DexScreener ──
            price_map: dict[str, tuple[float, str]] = {}  # addr_lower -> (price, logo)
            known_addrs = [t["contract"] for t in known_tokens]
            if known_addrs and dex_chain:
                for batch_start in range(0, min(len(known_addrs), 600), 30):
                    batch_addrs = known_addrs[batch_start:batch_start + 30]
                    try:
                        r = await client.get(
                            f"https://api.dexscreener.com/tokens/v1/{dex_chain}/{','.join(batch_addrs)}",
                            timeout=10,
                        )
                        pairs = r.json() if r.status_code == 200 else []
                        if isinstance(pairs, list):
                            for p in pairs:
                                base = p.get("baseToken", {})
                                ba = base.get("address", "").lower()
                                if ba and ba not in price_map:
                                    try:
                                        pr = float(p.get("priceUsd", 0))
                                    except (ValueError, TypeError):
                                        pr = 0.0
                                    if pr > 0:
                                        ds_logo = p.get("info", {}).get("imageUrl", "")
                                        price_map[ba] = (pr, ds_logo)
                    except Exception as e:
                        logger.debug(f"DexScreener batch error {chain}: {e}")

            # Also price unknown tokens via DexScreener (they might be DEX-listed memes)
            if unknown_addrs and dex_chain:
                for batch_start in range(0, min(len(unknown_addrs), 300), 30):
                    batch_addrs = unknown_addrs[batch_start:batch_start + 30]
                    try:
                        r = await client.get(
                            f"https://api.dexscreener.com/tokens/v1/{dex_chain}/{','.join(batch_addrs)}",
                            timeout=10,
                        )
                        pairs = r.json() if r.status_code == 200 else []
                        if isinstance(pairs, list):
                            for p in pairs:
                                base = p.get("baseToken", {})
                                ba = base.get("address", "").lower()
                                if ba and ba not in price_map:
                                    try:
                                        pr = float(p.get("priceUsd", 0))
                                    except (ValueError, TypeError):
                                        pr = 0.0
                                    if pr > 0:
                                        ds_logo = p.get("info", {}).get("imageUrl", "")
                                        price_map[ba] = (pr, ds_logo)
                    except Exception as e:
                        logger.debug(f"DexScreener batch error {chain}: {e}")

            logger.info(f"DexScreener {chain}: {len(price_map)} tokens priced")

            # Apply DexScreener prices to known tokens
            for t in known_tokens:
                pm = price_map.get(t["contract"].lower())
                if pm:
                    t["price"] = pm[0]
                    t["usd_value"] = round(t["amount"] * pm[0], 6)
                    if pm[1] and not t["logo"]:
                        t["logo"] = pm[1]

            # Hardcoded stablecoin pricing (these are ~$1 and often missing from DEX data)
            _stablecoin_symbols = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD", "BSC-USD"}
            for t in known_tokens:
                if t["price"] <= 0 and t["symbol"].upper() in _stablecoin_symbols:
                    t["price"] = 1.0
                    t["usd_value"] = round(t["amount"], 2)
                    # Fix display symbol for BSC-USD → USDT
                    if t["symbol"] == "BSC-USD":
                        t["symbol"] = "USDT"

            # Moralis fallback for still-unpriced known tokens
            still_unpriced = [t for t in known_tokens if t["price"] <= 0]
            if still_unpriced and moralis_key and moralis_chain:
                async def _moralis_price(t: dict) -> None:
                    try:
                        r = await client.get(
                            f"https://deep-index.moralis.io/api/v2.2/erc20/{t['contract']}/price",
                            params={"chain": moralis_chain},
                            headers={"X-API-Key": moralis_key},
                            timeout=6,
                        )
                        if r.status_code == 200:
                            d = r.json()
                            p = float(d.get("usdPrice", 0) or 0)
                            if p > 0:
                                t["price"] = p
                                t["usd_value"] = round(t["amount"] * p, 6)
                    except Exception:
                        pass

                for bs in range(0, min(len(still_unpriced), 60), 10):
                    batch = still_unpriced[bs:bs + 10]
                    await asyncio.gather(*[_moralis_price(t) for t in batch], return_exceptions=True)

            logger.info(f"After Moralis {chain}: {sum(1 for t in known_tokens if t['price']>0)} known tokens priced")

            # ── Phase 4: Resolve unknown tokens that DexScreener priced ──
            # These are meme tokens not in CoinGecko registry but with DEX liquidity
            priced_unknown = [a for a in unknown_addrs if a.lower() in price_map]
            raw_map = {t["contract"].lower(): t["raw_balance"] for t in raw_tokens}
            if priced_unknown and alchemy_rpc:
                async def _get_meta(contract: str) -> Optional[dict]:
                    try:
                        r = await client.post(alchemy_rpc, json={
                            "jsonrpc": "2.0", "id": 20,
                            "method": "alchemy_getTokenMetadata",
                            "params": [contract],
                        }, timeout=8)
                        meta = r.json().get("result", {})
                        decimals = meta.get("decimals") or 18
                        raw_bal = raw_map.get(contract.lower(), 0)
                        ui_amount = raw_bal / (10 ** decimals)
                        if ui_amount <= 0:
                            return None
                        pm = price_map.get(contract.lower(), (0, ""))
                        usd_value = round(ui_amount * pm[0], 6)
                        return {
                            "contract": contract,
                            "symbol": meta.get("symbol") or "???",
                            "name": meta.get("name") or "Unknown",
                            "logo": meta.get("logo") or pm[1] or "",
                            "amount": ui_amount,
                            "price": pm[0],
                            "usd_value": usd_value,
                        }
                    except Exception:
                        return None

                for bs in range(0, min(len(priced_unknown), 60), 10):
                    batch = priced_unknown[bs:bs + 10]
                    results = await asyncio.gather(*[_get_meta(c) for c in batch], return_exceptions=True)
                    for r in results:
                        if isinstance(r, dict) and r["usd_value"] > 0:
                            known_tokens.append(r)

            # ── Phase 5: Logo fallback — Trust Wallet CDN for tokens without logos ──
            for t in known_tokens:
                if not t["logo"] and t["contract"]:
                    t["logo"] = _tw_logo_url(chain, t["contract"])

            # ── Phase 6: Filter dust, sort, build final holdings ──
            tokens = [t for t in known_tokens if t["usd_value"] >= 0.01]
            tokens.sort(key=lambda t: t["usd_value"], reverse=True)
            total_token_usd = sum(t["usd_value"] for t in tokens)
            total_portfolio_usd = native_usd + total_token_usd

            top_holdings = []
            for t in tokens[:50]:
                pct = round(t["usd_value"] / max(total_portfolio_usd, 0.01) * 100, 2)
                top_holdings.append({
                    "mint": t["contract"],
                    "symbol": t["symbol"],
                    "name": t["name"],
                    "logo": t["logo"],
                    "amount": t["amount"],
                    "usd_value": t["usd_value"],
                    "price": t["price"],
                    "pct": pct,
                })

            return {
                "chain": chain,
                "native_symbol": native["symbol"],
                "native_name": native["name"],
                "native_logo": native["logo"],
                "balance_raw": native_bal,
                "balance_fmt": f"{native_bal:,.4f} {native['symbol']}",
                "native_price": native_price,
                "native_usd": native_usd,
                "total_portfolio_usd": total_portfolio_usd,
                "total_token_usd": total_token_usd,
                "token_count": len(tokens) + (1 if native_bal > 0 else 0),
                "txn_count": txn_count,
                "top_token_accounts": top_holdings,
            }
    except Exception as e:
        logger.error(f"{chain} RPC error for {address}: {e}")
        return None


def _fmt_usd(val: float) -> str:
    if val >= 1_000_000:
        return f"${val / 1_000_000:,.2f}M"
    if val >= 1_000:
        return f"${val / 1_000:,.2f}K"
    return f"${val:,.2f}"


def _time_ago(ts: int) -> str:
    """Convert unix timestamp to human-readable age like '6s', '2m', '1h', '3d'."""
    diff = int(time.time()) - ts
    if diff < 60:
        return f"{max(diff, 1)}s"
    if diff < 3600:
        return f"{diff // 60}m"
    if diff < 86400:
        return f"{diff // 3600}h"
    return f"{diff // 86400}d"


def _build_activity_heatmap(timestamps: list[int]) -> list[list[int]]:
    """Build a 7x24 (days x hours) trading activity heatmap from timestamps.
    Returns 7 rows of 24 values each — counts of transactions per hour-slot
    for the last 7 days."""
    now = int(time.time())
    grid = [[0] * 24 for _ in range(7)]
    for ts in timestamps:
        age_hours = (now - ts) / 3600
        day_idx = int(age_hours / 24)
        hour_idx = int(age_hours % 24)
        if 0 <= day_idx < 7 and 0 <= hour_idx < 24:
            grid[day_idx][hour_idx] += 1
    return grid


_EXCLUDED_PROGRAMS = {
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "ComputeBudget111111111111111111111111111111",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
    "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s",
    "SysvarRent111111111111111111111111111111111",
    "SysvarC1ock11111111111111111111111111111111",
    "Vote111111111111111111111111111111111111111",
    "Stake11111111111111111111111111111111111111",
    "So11111111111111111111111111111111111111112",
    "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
    "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY",
}


async def _fetch_sol_parsed_txns(address: str, signatures: list[str], token_prices: dict[str, float] | None = None) -> tuple[list[dict], list[dict]]:
    """Fetch and parse recent Solana transactions.
    With Alchemy we can fire all requests in parallel (high rate limits).
    Falls back to batched sequential with delays for free-tier RPCs.
    Returns (trades, counterparties)."""
    if not signatures:
        return [], []

    price_map = token_prices or {}
    trades = []
    counterparty_counts: dict[str, int] = {}
    sigs_to_fetch = signatures[:50]  # Fetch up to 50 txns for richer trade history

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # ── Parallel getTransaction calls ──
            all_results: list[tuple[str, dict | None]] = []

            async def _fetch_one(sig: str) -> tuple[str, dict | None]:
                for attempt in range(3):
                    try:
                        resp = await client.post(SOLANA_RPC, json={
                            "jsonrpc": "2.0", "id": 1,
                            "method": "getTransaction",
                            "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                        }, timeout=12)
                        if resp.status_code == 429:
                            await asyncio.sleep(1.0 * (attempt + 1))
                            continue
                        return (sig, resp.json().get("result"))
                    except Exception:
                        if attempt < 2:
                            await asyncio.sleep(0.5)
                return (sig, None)

            # Fire in batches of 10 to avoid overwhelming even Alchemy
            for batch_start in range(0, len(sigs_to_fetch), 10):
                batch = sigs_to_fetch[batch_start:batch_start + 10]
                results = await asyncio.gather(*[_fetch_one(s) for s in batch], return_exceptions=True)
                for r in results:
                    if isinstance(r, Exception):
                        continue
                    all_results.append(r)

            ok_count = sum(1 for _, r in all_results if r)
            logger.info(f"getTransaction: {ok_count}/{len(all_results)} succeeded")

            for sig, tx_data in all_results:
                if isinstance(tx_data, Exception) or not tx_data:
                    continue

                block_time = tx_data.get("blockTime", 0)
                meta = tx_data.get("meta", {})
                tx_err = meta.get("err")

                # ── Extract counterparties from account keys ──
                msg = tx_data.get("transaction", {}).get("message", {})
                account_keys = msg.get("accountKeys", [])
                # Find the best counterparty: a signer/writable key that isn't us or a program
                tx_counterparty = ""
                for ak in account_keys:
                    pubkey = ak.get("pubkey", "") if isinstance(ak, dict) else str(ak)
                    if pubkey and pubkey != address and pubkey not in _EXCLUDED_PROGRAMS and len(pubkey) >= 32:
                        signer = ak.get("signer", False) if isinstance(ak, dict) else False
                        writable = ak.get("writable", False) if isinstance(ak, dict) else False
                        if signer or writable:
                            counterparty_counts[pubkey] = counterparty_counts.get(pubkey, 0) + 1
                            if not tx_counterparty and signer:
                                tx_counterparty = pubkey
                            elif not tx_counterparty and writable:
                                tx_counterparty = pubkey

                # ── Extract token balance changes (only for successful txns) ──
                if tx_err:
                    continue
                pre_balances = meta.get("preTokenBalances", [])
                post_balances = meta.get("postTokenBalances", [])

                # Also find counterparty from token balance owners
                for b in pre_balances + post_balances:
                    owner = b.get("owner", "")
                    if owner and owner != address and owner not in _EXCLUDED_PROGRAMS and len(owner) >= 32:
                        if not tx_counterparty:
                            tx_counterparty = owner

                pre_map: dict[str, float] = {}
                for b in pre_balances:
                    if b.get("owner") == address:
                        mint = b.get("mint", "")
                        pre_map[mint] = pre_map.get(mint, 0) + (b.get("uiTokenAmount", {}).get("uiAmount") or 0)

                post_map: dict[str, float] = {}
                for b in post_balances:
                    if b.get("owner") == address:
                        mint = b.get("mint", "")
                        post_map[mint] = post_map.get(mint, 0) + (b.get("uiTokenAmount", {}).get("uiAmount") or 0)

                changed_mints = set(list(pre_map.keys()) + list(post_map.keys()))
                for mint in changed_mints:
                    diff = post_map.get(mint, 0) - pre_map.get(mint, 0)
                    if abs(diff) < 0.000001:
                        continue
                    token_info = await resolve_mint(mint)
                    symbol = token_info.get("symbol", mint[:6])
                    price = price_map.get(mint, 0)
                    usd_val = abs(diff) * price
                    trades.append({
                        "signature": sig[:12] + "...",
                        "token": symbol,
                        "mint": mint,
                        "side": "Buy" if diff > 0 else "Sell",
                        "amount": abs(diff),
                        "price": price,
                        "total_usd": round(usd_val, 2),
                        "timestamp": block_time,
                        "age": _time_ago(block_time) if block_time else "—",
                        "maker": tx_counterparty or "",
                    })

    except Exception as e:
        logger.error(f"Error fetching parsed txns for {address}: {e}")

    trades.sort(key=lambda t: t.get("timestamp", 0), reverse=True)

    # Build counterparties list sorted by interaction count
    counterparties = []
    for addr, count in sorted(counterparty_counts.items(), key=lambda x: x[1], reverse=True)[:25]:
        counterparties.append({
            "address": addr,
            "short": f"{addr[:4]}…{addr[-4:]}",
            "txns": count,
        })

    return trades, counterparties


# ── Known Wallet Profiles (enriched pre-loaded data) ────────────────────────

KNOWN_WALLETS: dict[str, dict] = {
    "MfDuWeqSHEqTFVYZ7LoexgAK9dxk7cy4DFJWjWMGVWa": {
        "profile": {
            "label": "Wintermute Automated Liquidity Bot",
            "entity": "Wintermute",
            "role": "Market Maker — DeFi Liquidity Provider",
            "risk_level": "Low",
            "risk_note": "Legitimate market maker operated by Wintermute. No scams or malicious behavior. Activity can influence token prices through liquidity provision.",
            "tags": ["Market Maker", "Whale", "DeFi"],
            "is_smart_money": True,
            "chain": "SOL",
        },
        "sol_balance": "99.59 SOL",
        "sol_value": "$7,634",
        "token_count": "2,344",
        "total_txns": "1,656,740",
        "sends": "895,885",
        "receives": "760,855",
        "portfolio_value": "$24.57M",
        "portfolio_change": "-2.7%",
        "status": "Active",
        "funded_by": "OKX",
        "top_holdings": [
            {"token": "USDC", "amount": "5.59M", "value": "$5.59M", "pct": 22.7},
            {"token": "SOL", "amount": "99.59", "value": "$7,634", "pct": 0.03},
            {"token": "ARC", "amount": "~$300K", "value": "$300K", "pct": 1.2},
            {"token": "WOJAK", "amount": "2.5M–3.5M", "value": "~$180K", "pct": 0.7},
        ],
        "recent_activity": [
            {"tx_type": "Buy", "action": "Buying $ARC — $400K+ combined with secondary wallet", "date": "Feb 2026"},
            {"tx_type": "Burn", "action": "Burned 21,631 WSOL worth ~$5.39M", "date": "Jan 2025"},
            {"tx_type": "Accumulate", "action": "Accumulated $WOJAK 2.5M–3.5M units", "date": "Nov 2025"},
        ],
        "top_counterparties": [
            {"name": "Orca", "txns": 190491, "volume": "$469.65M"},
            {"name": "Tessera V", "txns": 1609, "volume": "$369.81M"},
            {"name": "Fluxbeam", "txns": 24102, "volume": "$82.4M"},
        ],
        "risk_flags": [
            {"label": "Scam Association", "value": "None", "color": "text-accent-success"},
            {"label": "Manipulation Risk", "value": "Low — Liquidity role", "color": "text-accent-success"},
            {"label": "Volatility Influence", "value": "High — Large trades", "color": "text-accent-warning"},
            {"label": "Centralization", "value": "N/A — Bot wallet", "color": "text-slate-400"},
        ],
        "social_mentions": [
            "Tracked for low-entry buys in memecoins like $ARC and $WOJAK",
            "Labeled as 'follow-worthy' address for spotting opportunities",
            "Tied to Wintermute's market-making moves on Solana DEXes",
        ],
    },
    "DfMxre4cKmvogbLrPigxmibVTTQDuzjdXojWzjCXXhzj": {
        "profile": {
            "label": "Arkham MEV Bot",
            "entity": "Arkham Intelligence",
            "role": "MEV Searcher — Sandwich & Arbitrage Bot",
            "risk_level": "Medium",
            "risk_note": "High-frequency MEV bot associated with Arkham Intelligence's research operations. Executes arbitrage and sandwich attacks. Profitable but controversial extraction strategy.",
            "tags": ["MEV Bot", "Arbitrage", "High Frequency"],
            "is_smart_money": True,
            "chain": "SOL",
        },
        "sol_balance": "2,847 SOL",
        "sol_value": "$218,204",
        "token_count": "156",
        "total_txns": "4,892,310",
        "sends": "2,446,155",
        "receives": "2,446,155",
        "portfolio_value": "$3.2M",
        "portfolio_change": "+8.4%",
        "status": "Active",
        "funded_by": "Binance",
        "top_holdings": [
            {"token": "SOL", "amount": "2,847", "value": "$218K", "pct": 6.8},
            {"token": "USDC", "amount": "1.8M", "value": "$1.8M", "pct": 56.2},
            {"token": "JTO", "amount": "245K", "value": "$612K", "pct": 19.1},
            {"token": "BONK", "amount": "48B", "value": "$384K", "pct": 12.0},
        ],
        "recent_activity": [
            {"tx_type": "Buy", "action": "Sandwich attack on JTO/SOL pair — $45K profit", "date": "2 hours ago"},
            {"tx_type": "Sell", "action": "Liquidated BONK position — $120K", "date": "6 hours ago"},
            {"tx_type": "Buy", "action": "Arbitrage: Raydium→Orca on WIF — $8.2K profit", "date": "12 hours ago"},
            {"tx_type": "Accumulate", "action": "Accumulated JTO over 48h — 245K tokens", "date": "2 days ago"},
        ],
        "top_counterparties": [
            {"name": "Raydium", "txns": 892431, "volume": "$2.1B"},
            {"name": "Orca", "txns": 654210, "volume": "$1.4B"},
            {"name": "Jupiter", "txns": 421890, "volume": "$890M"},
        ],
        "risk_flags": [
            {"label": "MEV Extraction", "value": "Very High", "color": "text-accent-error"},
            {"label": "Sandwich Attacks", "value": "Confirmed", "color": "text-accent-error"},
            {"label": "Scam Association", "value": "None", "color": "text-accent-success"},
            {"label": "Profitability", "value": "+$12.4M all-time", "color": "text-accent-success"},
        ],
        "social_mentions": [
            "Known MEV bot operated by Arkham — one of the most profitable on Solana",
            "Responsible for ~2.3% of all sandwich attacks on Raydium in Q4 2025",
            "Frequently front-runs large Jupiter aggregation routes",
        ],
    },
    "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045": {
        "profile": {
            "label": "vitalik.eth",
            "entity": "Vitalik Buterin",
            "role": "Ethereum Co-founder — Public Figure",
            "risk_level": "Low",
            "risk_note": "Personal wallet of Ethereum co-founder Vitalik Buterin. Frequently donates to public goods and charity. Extremely influential — any movement is tracked globally.",
            "tags": ["Public Figure", "Diamond Hands", "OG"],
            "is_smart_money": True,
            "chain": "ETH",
        },
        "sol_balance": "—",
        "sol_value": "—",
        "token_count": "842",
        "total_txns": "2,145,890",
        "sends": "1,245,000",
        "receives": "900,890",
        "portfolio_value": "$680M",
        "portfolio_change": "-4.1%",
        "status": "Active",
        "funded_by": "Genesis",
        "top_holdings": [
            {"token": "ETH", "amount": "240,687", "value": "$478M", "pct": 70.3},
            {"token": "USDC", "amount": "42M", "value": "$42M", "pct": 6.2},
            {"token": "MKR", "amount": "12,400", "value": "$18.6M", "pct": 2.7},
            {"token": "RPL", "amount": "890K", "value": "$15.2M", "pct": 2.2},
        ],
        "recent_activity": [
            {"tx_type": "Sell", "action": "Donated 100 ETH to Gitcoin Grants", "date": "1 week ago"},
            {"tx_type": "Buy", "action": "Received 500 ETH from staking rewards", "date": "3 days ago"},
            {"tx_type": "Burn", "action": "Burned meme tokens received unsolicited", "date": "2 weeks ago"},
        ],
        "top_counterparties": [
            {"name": "Uniswap V3", "txns": 3420, "volume": "$890M"},
            {"name": "Gitcoin", "txns": 245, "volume": "$120M"},
            {"name": "ENS", "txns": 89, "volume": "$2.4M"},
        ],
        "risk_flags": [
            {"label": "Scam Association", "value": "None", "color": "text-accent-success"},
            {"label": "Market Influence", "value": "Extreme", "color": "text-accent-error"},
            {"label": "Donation Activity", "value": "Very High", "color": "text-accent-success"},
            {"label": "Token Dumps", "value": "Burns unsolicited only", "color": "text-accent-success"},
        ],
        "social_mentions": [
            "Every transaction by vitalik.eth trends on crypto Twitter within minutes",
            "Known for burning meme tokens sent to him — does not endorse",
            "Largest individual ETH holder after the Ethereum Foundation",
        ],
    },
    "0x9B68BFaE21e88e4a9fBc935f94b0fEA016745494": {
        "profile": {
            "label": "Jump Trading",
            "entity": "Jump Crypto",
            "role": "Institutional Market Maker — Multi-chain",
            "risk_level": "Low",
            "risk_note": "Institutional-grade market maker operated by Jump Crypto. Provides deep liquidity across CEX and DEX. Backed by Jump Trading Group with $20B+ AUM.",
            "tags": ["Market Maker", "DeFi", "Institutional"],
            "is_smart_money": True,
            "chain": "ETH",
        },
        "sol_balance": "—",
        "sol_value": "—",
        "token_count": "1,284",
        "total_txns": "8,942,100",
        "sends": "4,890,000",
        "receives": "4,052,100",
        "portfolio_value": "$142M",
        "portfolio_change": "+1.2%",
        "status": "Active",
        "funded_by": "Jump Trading Group",
        "top_holdings": [
            {"token": "ETH", "amount": "32,400", "value": "$64.5M", "pct": 45.4},
            {"token": "USDC", "amount": "28M", "value": "$28M", "pct": 19.7},
            {"token": "WBTC", "amount": "420", "value": "$28.1M", "pct": 19.8},
            {"token": "stETH", "amount": "8,200", "value": "$16.3M", "pct": 11.5},
        ],
        "recent_activity": [
            {"tx_type": "Buy", "action": "Added $4.2M ETH liquidity to Uniswap V3", "date": "4 hours ago"},
            {"tx_type": "Sell", "action": "Rebalanced WBTC/ETH — sold 120 WBTC", "date": "1 day ago"},
            {"tx_type": "Accumulate", "action": "Accumulated stETH via Lido — 2,400 units", "date": "3 days ago"},
        ],
        "top_counterparties": [
            {"name": "Uniswap V3", "txns": 1245000, "volume": "$24.8B"},
            {"name": "Curve", "txns": 342000, "volume": "$8.9B"},
            {"name": "Aave V3", "txns": 89000, "volume": "$4.2B"},
        ],
        "risk_flags": [
            {"label": "Scam Association", "value": "None", "color": "text-accent-success"},
            {"label": "Manipulation Risk", "value": "Low — Regulated entity", "color": "text-accent-success"},
            {"label": "Concentration", "value": "Medium — ETH heavy", "color": "text-accent-warning"},
            {"label": "Counterparty Risk", "value": "Low", "color": "text-accent-success"},
        ],
        "social_mentions": [
            "One of the largest institutional LPs on Uniswap V3 and Curve",
            "Jump Crypto provides ~8% of all ETH/USDC liquidity on-chain",
            "Backed by Jump Trading Group — traditional finance powerhouse",
        ],
    },
    "4GQeEya6VDNBaYVFazVqSmAX8qHyYnYCMZrKoFu1azVqS": {
        "profile": {
            "label": "Alameda Research Remnant",
            "entity": "Alameda (Defunct)",
            "role": "Defunct Trading Firm — Asset Recovery",
            "risk_level": "High",
            "risk_note": "Residual wallet from Alameda Research. Now managed by FTX bankruptcy estate. Assets being liquidated systematically. High market impact risk on sells.",
            "tags": ["FTX Estate", "Whale", "Liquidation"],
            "is_smart_money": False,
            "chain": "SOL",
        },
        "sol_balance": "12.4M SOL",
        "sol_value": "$950M",
        "token_count": "89",
        "total_txns": "342,100",
        "sends": "180,000",
        "receives": "162,100",
        "portfolio_value": "$1.8B",
        "portfolio_change": "-12.8%",
        "status": "Liquidating",
        "funded_by": "FTX/Alameda",
        "top_holdings": [
            {"token": "SOL", "amount": "12.4M", "value": "$950M", "pct": 52.8},
            {"token": "BTC (wrapped)", "amount": "4,200", "value": "$281M", "pct": 15.6},
            {"token": "ETH (wrapped)", "amount": "84,000", "value": "$167M", "pct": 9.3},
            {"token": "SRM", "amount": "890M", "value": "$89M", "pct": 4.9},
        ],
        "recent_activity": [
            {"tx_type": "Sell", "action": "Estate sold 250K SOL via Galaxy Digital OTC", "date": "1 week ago"},
            {"tx_type": "Sell", "action": "Liquidated 1,200 BTC through Coinbase Prime", "date": "2 weeks ago"},
            {"tx_type": "Sell", "action": "Sold 45M SRM tokens on market", "date": "1 month ago"},
        ],
        "top_counterparties": [
            {"name": "Galaxy Digital", "txns": 42, "volume": "$4.2B"},
            {"name": "Coinbase Prime", "txns": 156, "volume": "$2.8B"},
            {"name": "Wintermute", "txns": 89, "volume": "$1.4B"},
        ],
        "risk_flags": [
            {"label": "Bankruptcy Estate", "value": "Yes — FTX", "color": "text-accent-error"},
            {"label": "Market Impact", "value": "Extreme — Large sells", "color": "text-accent-error"},
            {"label": "Scam Association", "value": "FTX Fraud", "color": "text-accent-error"},
            {"label": "Liquidation Schedule", "value": "Ongoing", "color": "text-accent-warning"},
        ],
        "social_mentions": [
            "FTX estate wallet — every sell causes market panic",
            "Galaxy Digital handling OTC liquidation to minimize market impact",
            "Estimated $1.8B remaining to be distributed to creditors",
        ],
    },
}


# ── Grok API integration ────────────────────────────────────────────────────

GROK_SYSTEM_PROMPT = """You are Lumina's wallet analyzer AI. Given a blockchain wallet address AND its real on-chain balance data, return a JSON analysis.

CRITICAL RULES:
- NEVER invent or fabricate portfolio values, balances, transaction counts, or holdings. The real on-chain data will be provided to you — use ONLY those numbers.
- If you recognise the address (e.g. a known entity), provide the label/entity/role. Otherwise say "Unknown Wallet" and "Independent".
- For fields you cannot determine, use null or empty arrays.
- You MUST return ONLY valid JSON (no markdown, no explanation).

Return this structure:
{
  "profile": {
    "label": "Human-readable name or 'Unknown Wallet'",
    "entity": "Organization name or 'Independent'",
    "role": "e.g. Trader, Market Maker, DeFi User, NFT Collector, or 'Unknown'",
    "risk_level": "Low|Medium|High",
    "risk_note": "1-2 sentence risk assessment based on the on-chain data provided",
    "tags": ["tag1", "tag2"],
    "is_smart_money": true/false
  },
  "recent_activity": [{"tx_type": "Buy|Sell|Transfer|Burn|Accumulate", "action": "description", "date": "relative time"}],
  "top_counterparties": [{"name": "Protocol", "txns": 0, "volume": "$X"}],
  "risk_flags": [{"label": "Risk Type", "value": "Assessment", "color": "text-accent-success|text-accent-warning|text-accent-error"}],
  "social_mentions": ["mention1", "mention2"]
}

Only include recent_activity, top_counterparties, and social_mentions if you have REAL knowledge about this address. Return empty arrays if unknown."""


async def _grok_analyze(address: str, chain: str, onchain_summary: str) -> Optional[dict]:
    """Ask Grok for identity/risk context. Provide real on-chain data so it doesn't fabricate."""
    if not settings.GROK_API_KEY:
        return None

    cache_key = f"grok:wallet:v2:{address}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    user_msg = (
        f"Analyze this {chain} wallet address: {address}\n\n"
        f"Here is the REAL on-chain data (do NOT change these numbers):\n{onchain_summary}"
    )

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                f"{settings.GROK_API_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.GROK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "grok-3-mini",
                    "messages": [
                        {"role": "system", "content": GROK_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1500,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # Strip markdown code fences if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            result = json.loads(content)
            await cache_set(cache_key, result, ttl=300)
            return result
    except Exception as e:
        logger.error(f"Grok API error for {address}: {e}")
        return None


# ── Wallet Analysis endpoint ─────────────────────────────────────────────────

@router.post("/analyze", dependencies=[Depends(rate_limit(max_requests=20, window_seconds=60))])
async def analyze_wallet(req: WalletAnalysisRequest):
    chain = req.chain or _detect_chain(req.address)
    short_addr = req.address[:8] + "..." + req.address[-4:] if len(req.address) > 16 else req.address

    # 1. Check known wallets first (curated profiles) — merge with required fields
    if req.address in KNOWN_WALLETS:
        known = KNOWN_WALLETS[req.address]
        profile = known["profile"].copy()
        profile["address"] = req.address
        profile["chain"] = profile.get("chain", chain)
        # Ensure all required frontend fields are present
        defaults = {
            "trade_history": [],
            "activity_heatmap": [[0]*24 for _ in range(7)],
            "pnl": {"realized": 0, "unrealized": 0, "total_revenue": 0, "total_spent": 0},
            "connected_wallets": [],
            "portfolio_value_raw": 0,
            "sol_balance_raw": 0,
            "sol_price": 0,
            "net_worth_sol": 0,
            "first_seen": 0,
            "last_seen": 0,
        }
        # Normalize top_holdings: amounts must be numbers, add missing keys
        holdings = known.get("top_holdings", [])
        for h in holdings:
            if isinstance(h.get("amount"), str):
                raw = h["amount"].replace(",", "").replace("~", "").replace("$", "")
                raw = raw.replace("M", "e6").replace("K", "e3").replace("B", "e9")
                try:
                    h["amount"] = float(eval(raw))
                except Exception:
                    h["amount"] = 0
            # Parse usd_value from "value" string like "$478M"
            if not h.get("usd_value") and isinstance(h.get("value"), str):
                vr = h["value"].replace(",", "").replace("$", "").replace("~", "").strip()
                vr = vr.replace("M", "e6").replace("K", "e3").replace("B", "e9")
                try:
                    h["usd_value"] = float(eval(vr))
                except Exception:
                    h["usd_value"] = 0
            h.setdefault("name", h.get("token", "Unknown"))
            h.setdefault("logo", "")
            h.setdefault("mint", "")
            h.setdefault("usd_value", 0)
            h.setdefault("price", 0)
        # Parse portfolio_value_raw from string like "$680M"
        pv_str = known.get("portfolio_value", "")
        if isinstance(pv_str, str) and "$" in pv_str:
            pv_raw = pv_str.replace(",", "").replace("$", "").strip()
            pv_raw = pv_raw.replace("M", "e6").replace("K", "e3").replace("B", "e9")
            try:
                defaults["portfolio_value_raw"] = float(eval(pv_raw))
            except Exception:
                pass
        result = {**defaults, **known, "top_holdings": holdings, "profile": profile}
        return result

    # 2. Fetch REAL on-chain data (with Redis cache for speed)
    t0 = time.time()
    is_evm = req.address.startswith("0x")

    # For EVM addresses: query ALL major chains in parallel (like Arkham)
    # The same 0x address exists on ETH, BSC, BASE, ARB, OP, etc.
    _EVM_CHAINS_TO_SCAN = ["ETH", "BSC", "ARB", "BASE", "OP"]

    evm_results: dict[str, dict] = {}  # chain -> onchain data
    onchain = None  # For SOL compatibility

    if is_evm:
        # Parallel fetch all EVM chains
        async def _fetch_chain_cached(ch: str) -> tuple[str, dict | None]:
            ck = f"wallet:onchain:{ch}:{req.address}"
            cached = await cache_get(ck)
            if cached:
                return (ch, cached)
            try:
                result = await _fetch_evm_balance(req.address, ch)
                if result:
                    await cache_set(ck, result, ttl=60)
                return (ch, result)
            except Exception as e:
                logger.warning(f"Multi-chain fetch {ch} error: {e}")
                return (ch, None)

        chain_results = await asyncio.gather(
            *[_fetch_chain_cached(ch) for ch in _EVM_CHAINS_TO_SCAN],
            return_exceptions=True,
        )
        for r in chain_results:
            if isinstance(r, Exception):
                continue
            ch, data = r
            if data and data.get("total_portfolio_usd", 0) > 0:
                evm_results[ch] = data
        logger.info(f"Multi-chain fetch for {req.address[:12]}: {list(evm_results.keys())} in {time.time()-t0:.2f}s")
    elif chain == "SOL":
        cache_key = f"wallet:onchain:SOL:{req.address}"
        onchain = await cache_get(cache_key)
        if not onchain:
            onchain = await _fetch_sol_balance(req.address)
            if onchain:
                await cache_set(cache_key, onchain, ttl=60)
        logger.info(f"On-chain fetch for {req.address[:12]} (SOL): {time.time()-t0:.2f}s")

    # Build on-chain summary for Grok and for the response
    trade_history = []
    activity_heatmap = []
    pnl = {"realized": 0, "unrealized": 0, "total_revenue": 0, "total_spent": 0}

    if is_evm and evm_results:
        # ── Unified multi-chain EVM response ──
        total_portfolio_usd = 0.0
        total_token_count = 0
        total_txn_count = 0
        all_holdings: list[dict] = []
        chain_portfolios: list[dict] = []

        for ch, data in evm_results.items():
            ch_native = EVM_NATIVE.get(ch, {})
            ch_portfolio = data.get("total_portfolio_usd", 0)
            ch_native_bal = data.get("balance_raw", 0)
            ch_native_usd = data.get("native_usd", 0)
            ch_native_price = data.get("native_price", 0)
            ch_token_count = data.get("token_count", 0)
            ch_txn_count = data.get("txn_count", 0)

            total_portfolio_usd += ch_portfolio
            total_token_count += ch_token_count
            total_txn_count += ch_txn_count

            chain_portfolios.append({
                "chain": ch,
                "chain_name": ch_native.get("name", ch),
                "native_symbol": ch_native.get("symbol", ch),
                "native_balance": ch_native_bal,
                "native_usd": ch_native_usd,
                "portfolio_usd": ch_portfolio,
                "token_count": ch_token_count,
                "txn_count": ch_txn_count,
            })

            # Add native token holding with chain tag
            if ch_native_bal > 0:
                all_holdings.append({
                    "token": ch_native.get("symbol", ch),
                    "name": ch_native.get("name", ch),
                    "logo": ch_native.get("logo", ""),
                    "mint": "",
                    "amount": ch_native_bal,
                    "amount_fmt": f"{ch_native_bal:,.4f}",
                    "value": f"${ch_native_usd:,.2f}" if ch_native_usd else "—",
                    "usd_value": round(ch_native_usd, 2),
                    "price": ch_native_price,
                    "pct": 0,  # recalc later
                    "chain": ch,
                })

            # Add ERC-20/BEP-20 token holdings with chain tag
            for h in data.get("top_token_accounts", []):
                usd_val = h.get("usd_value", 0)
                all_holdings.append({
                    "token": h.get("symbol", "???"),
                    "name": h.get("name", "Unknown"),
                    "logo": h.get("logo", ""),
                    "mint": h.get("mint", ""),
                    "amount": h["amount"],
                    "amount_fmt": f"{h['amount']:,.4f}",
                    "value": f"${usd_val:,.2f}" if usd_val > 0 else "—",
                    "usd_value": usd_val,
                    "price": h.get("price", 0),
                    "pct": 0,
                    "chain": ch,
                })

        # Sort all holdings by USD value, recalculate percentages
        all_holdings.sort(key=lambda h: h.get("usd_value", 0), reverse=True)
        for h in all_holdings:
            h["pct"] = round(h["usd_value"] / max(total_portfolio_usd, 0.01) * 100, 2) if h["usd_value"] > 0 else 0

        # Sort chain_portfolios by portfolio value descending
        chain_portfolios.sort(key=lambda c: c["portfolio_usd"], reverse=True)
        primary_chain = chain_portfolios[0]["chain"] if chain_portfolios else "ETH"

        portfolio_value = _fmt_usd(total_portfolio_usd) if total_portfolio_usd > 0 else "$0.00"

        # Build summary for AI
        top_symbols = [
            f"{h['token']}({h['amount']:,.2f}=${h.get('usd_value', 0):,.0f})[{h.get('chain','?')}]"
            for h in all_holdings[:8]
        ]
        chain_summary_parts = [
            f"{cp['chain']}: ${cp['portfolio_usd']:,.0f} ({cp['token_count']} tokens)"
            for cp in chain_portfolios
        ]
        onchain_summary = (
            f"Multi-chain EVM Portfolio\n"
            f"Chains: {', '.join(chain_summary_parts)}\n"
            f"Total Portfolio (USD): ${total_portfolio_usd:,.2f}\n"
            f"Total Tokens: {total_token_count}\n"
            f"Total Txns: {total_txn_count}\n"
            f"Top holdings: {', '.join(top_symbols)}"
        )

        base_result = {
            "sol_balance": "—",
            "sol_balance_raw": 0,
            "sol_value": "—",
            "sol_price": 0,
            "net_worth_sol": 0,
            "token_count": total_token_count,
            "total_txns": str(total_txn_count),
            "sends": str(total_txn_count),
            "receives": "—",
            "portfolio_value": portfolio_value,
            "portfolio_value_raw": round(total_portfolio_usd, 2),
            "portfolio_change": "—",
            "status": "Active" if total_txn_count > 0 else "Dormant",
            "funded_by": "Unknown",
            "top_holdings": all_holdings[:100],
            "chain_portfolios": chain_portfolios,
            "first_seen": 0,
            "last_seen": 0,
            "connected_wallets": [],
        }

    elif chain == "SOL" and onchain:
        sol_bal = onchain["sol_balance_raw"]
        sol_usd = onchain["sol_usd_raw"]
        sol_price = onchain.get("sol_price", 0)
        token_count = onchain["token_count"]
        txn_count = onchain["recent_txn_count"]
        total_portfolio_usd = onchain.get("total_portfolio_usd", sol_usd)
        portfolio_value = _fmt_usd(total_portfolio_usd) if total_portfolio_usd > 0 else "$0.00"

        # Build summary of top holdings with resolved names for Grok
        top_symbols = [
            f"{h.get('symbol', '?')}({h['amount']:,.0f}=${h.get('usd_value', 0):,.0f})"
            for h in onchain.get("top_token_accounts", [])[:6]
        ]
        onchain_summary = (
            f"Chain: Solana\n"
            f"SOL Balance: {sol_bal:,.4f} SOL (${sol_usd:,.2f})\n"
            f"Total Portfolio (USD): ${total_portfolio_usd:,.2f}\n"
            f"SPL Token Accounts: {token_count}\n"
            f"Recent Transactions (last 100 window): {txn_count}\n"
            f"Top tokens: {', '.join(top_symbols)}"
        )

        # Build top_holdings with real USD values and % allocation
        top_holdings = []
        for h in onchain.get("top_token_accounts", []):
            usd_val = h.get("usd_value", 0)
            pct = round(usd_val / max(total_portfolio_usd, 0.01) * 100, 2) if usd_val > 0 else 0
            top_holdings.append({
                "token": h.get("symbol", h["mint"][:6]),
                "name": h.get("name", "Unknown"),
                "logo": h.get("logo", ""),
                "mint": h.get("mint", ""),
                "amount": h["amount"],
                "amount_fmt": f"{h['amount']:,.2f}",
                "value": f"${usd_val:,.2f}" if usd_val > 0 else "—",
                "usd_value": usd_val,
                "price": h.get("price", 0),
                "pct": pct,
            })
        # Add SOL itself at top if balance > 0
        if sol_bal > 0:
            sol_pct = round(sol_usd / max(total_portfolio_usd, 0.01) * 100, 2) if sol_usd > 0 else 0
            top_holdings.insert(0, {
                "token": "SOL",
                "name": "Solana",
                "logo": "https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png",
                "mint": "So11111111111111111111111111111111111111112",
                "amount": sol_bal,
                "amount_fmt": f"{sol_bal:,.4f}",
                "value": f"${sol_usd:,.2f}" if sol_usd else "—",
                "usd_value": round(sol_usd, 2),
                "price": sol_price,
                "pct": sol_pct,
            })

        # Sort holdings by USD value descending (most valuable first)
        top_holdings.sort(key=lambda h: h.get("usd_value", 0), reverse=True)

        # Build price map from holdings for trade USD resolution
        _price_map: dict[str, float] = {}
        for h in onchain.get("top_token_accounts", []):
            if h.get("mint") and h.get("price", 0) > 0:
                _price_map[h["mint"]] = h["price"]
        # Add SOL price
        if sol_price > 0:
            _price_map["So11111111111111111111111111111111111111112"] = sol_price

        # Parse trade history + counterparties from recent signatures
        trade_history, connected_wallets = await _fetch_sol_parsed_txns(req.address, onchain.get("recent_signatures", []), token_prices=_price_map)

        # Activity heatmap from sig timestamps
        activity_heatmap = _build_activity_heatmap(onchain.get("sig_timestamps", []))

        # Wallet age from oldest signature
        sig_ts = onchain.get("sig_timestamps", [])
        first_seen = min(sig_ts) if sig_ts else 0
        last_seen = max(sig_ts) if sig_ts else 0

        # Net worth in SOL equivalent
        net_worth_sol = round(total_portfolio_usd / sol_price, 4) if sol_price > 0 else sol_bal

        base_result = {
            "sol_balance": onchain["sol_balance"],
            "sol_balance_raw": sol_bal,
            "sol_value": onchain["sol_value"],
            "sol_price": sol_price,
            "net_worth_sol": net_worth_sol,
            "token_count": token_count,
            "total_txns": str(txn_count) + "+",
            "sends": "—",
            "receives": "—",
            "portfolio_value": portfolio_value,
            "portfolio_value_raw": round(total_portfolio_usd, 2),
            "portfolio_change": "—",
            "status": "Active" if txn_count > 0 else "Dormant",
            "funded_by": "Unknown",
            "top_holdings": top_holdings,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "connected_wallets": connected_wallets,
        }

    else:
        # No on-chain data available (RPC failed or unsupported chain)
        onchain_summary = f"Chain: {chain}\nNo on-chain data could be fetched."
        base_result = {
            "sol_balance": "—",
            "sol_balance_raw": 0,
            "sol_value": "—",
            "sol_price": 0,
            "net_worth_sol": 0,
            "token_count": 0,
            "total_txns": "—",
            "sends": "—",
            "receives": "—",
            "portfolio_value": "—",
            "portfolio_value_raw": 0,
            "portfolio_change": "—",
            "status": "Unknown",
            "funded_by": "Unknown",
            "top_holdings": [],
            "first_seen": 0,
            "last_seen": 0,
            "connected_wallets": [],
        }

    # 3. Return on-chain data only (fast) — AI analysis is a separate endpoint
    has_data = bool(evm_results) if is_evm else bool(onchain)
    # For EVM: show primary chain + all active chains as tags
    if is_evm and evm_results:
        display_chain = primary_chain
        display_tags = list(evm_results.keys())
    else:
        display_chain = chain
        display_tags = [chain]

    return {
        **base_result,
        "profile": {
            "address": req.address,
            "chain": display_chain,
            "chains": display_tags,
            "label": f"Wallet {short_addr}",
            "entity": "—",
            "role": "—",
            "risk_level": "—",
            "risk_note": "Click 'Analyze with AI' for risk assessment.",
            "tags": display_tags,
            "is_smart_money": False,
        },
        "recent_activity": [],
        "top_counterparties": [],
        "risk_flags": [
            {"label": "On-chain Data", "value": "Real balances shown" if has_data else "Unavailable", "color": "text-accent-success" if has_data else "text-accent-warning"},
        ],
        "social_mentions": [],
        "trade_history": trade_history,
        "activity_heatmap": activity_heatmap,
        "pnl": pnl,
        "_onchain_summary": onchain_summary,
    }


@router.post("/ai-analyze", dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60))])
async def ai_analyze_wallet(req: WalletAnalysisRequest):
    """Run Grok AI analysis on a wallet. Expects on-chain data to already be fetched."""
    chain = _detect_chain(req.address)
    short_addr = req.address[:6] + "..." + req.address[-4:]

    # Reuse cached on-chain data (from the initial analyze call)
    onchain_summary = f"Chain: {chain}\nAddress: {req.address}"
    cache_key = f"wallet:onchain:{req.address}"
    onchain = await cache_get(cache_key)
    if not onchain and chain == "SOL":
        onchain = await _fetch_sol_balance(req.address)
        if onchain:
            await cache_set(cache_key, onchain, ttl=60)
    elif not onchain and chain == "ETH":
        onchain = await _fetch_eth_balance(req.address)
        if onchain:
            await cache_set(cache_key, onchain, ttl=60)
    if chain == "SOL" and onchain:
        sol_bal = onchain["sol_balance_raw"]
        sol_usd = onchain["sol_usd_raw"]
        top_symbols = [f"{h.get('symbol', '?')}({h['amount']:,.0f})" for h in onchain.get("top_token_accounts", [])[:4]]
        onchain_summary = (
            f"Chain: Solana\n"
            f"SOL Balance: {sol_bal:,.4f} SOL (${sol_usd:,.2f})\n"
            f"SPL Token Accounts: {onchain['token_count']}\n"
            f"Recent Transactions (last 100 window): {onchain['recent_txn_count']}\n"
            f"Top tokens: {', '.join(top_symbols)}"
        )
    elif chain == "ETH" and onchain:
        onchain_summary = (
            f"Chain: Ethereum\n"
            f"ETH Balance: {onchain['eth_balance_raw']:,.4f} ETH (${onchain['eth_usd_raw']:,.2f})\n"
            f"Nonce (outbound txns): {onchain['txn_count']}"
        )

    grok_result = await _grok_analyze(req.address, chain, onchain_summary)

    if not grok_result:
        return {
            "profile": {
                "address": req.address,
                "chain": chain,
                "label": f"Wallet {short_addr}",
                "entity": "Independent",
                "role": "Unknown",
                "risk_level": "Unknown",
                "risk_note": "AI analysis unavailable. Check API key or try again later.",
                "tags": [chain],
                "is_smart_money": False,
            },
            "recent_activity": [],
            "top_counterparties": [],
            "risk_flags": [{"label": "AI Analysis", "value": "Failed", "color": "text-accent-error"}],
            "social_mentions": [],
        }

    grok_profile = grok_result.get("profile", {})
    return {
        "profile": {
            "address": req.address,
            "chain": chain,
            "label": grok_profile.get("label") or f"Wallet {short_addr}",
            "entity": grok_profile.get("entity") or "Independent",
            "role": grok_profile.get("role") or "Unknown",
            "risk_level": grok_profile.get("risk_level") or "Medium",
            "risk_note": grok_profile.get("risk_note") or "No additional context available.",
            "tags": grok_profile.get("tags") or [chain],
            "is_smart_money": grok_profile.get("is_smart_money", False),
        },
        "recent_activity": grok_result.get("recent_activity") or [],
        "top_counterparties": grok_result.get("top_counterparties") or [],
        "risk_flags": grok_result.get("risk_flags") or [
            {"label": "Identity", "value": "Unverified", "color": "text-accent-warning"},
        ],
        "social_mentions": grok_result.get("social_mentions") or [],
    }


# ── Starred Wallets (in-memory for now) ──────────────────────────────────────

_starred: list[dict] = []


@router.get("/starred")
async def get_starred_wallets(user_id: str = Query("default")):
    user_wallets = [w for w in _starred if w.get("user_id") == user_id]
    return {"data": user_wallets, "total": len(user_wallets)}


@router.post("/starred")
async def add_starred_wallet(
    wallet_address: str,
    user_id: str = Query("default"),
    label: str = Query(""),
    chain: str = Query("SOL"),
):
    entry = {
        "id": len(_starred) + 1,
        "user_id": user_id,
        "wallet_address": wallet_address,
        "label": label or "Unknown Wallet",
        "chain": chain,
        "tags": ["Custom"],
        "value": "—",
    }
    _starred.append(entry)
    return entry


@router.delete("/starred/{wallet_id}")
async def remove_starred_wallet(wallet_id: int):
    global _starred
    _starred = [w for w in _starred if w.get("id") != wallet_id]
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  TRADER MODE — Per-token PnL, win rate, behaviour analysis
# ══════════════════════════════════════════════════════════════════════════════

_MORALIS_CHAINS = {"ETH": "eth", "BSC": "bsc", "ARB": "arbitrum", "BASE": "base", "OP": "optimism"}
_MORALIS_CHAIN_REV = {v: k for k, v in _MORALIS_CHAINS.items()}

# Native / wrapped tokens to exclude from token-level PnL (they are the "quote" currency)
_NATIVE_MINTS = {
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
    "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",  # WETH (ARB)
    "0x4200000000000000000000000000000000000006",  # WETH (BASE/OP)
    "So11111111111111111111111111111111111111112",  # WSOL
}

# Stablecoins used as quote currency
_STABLECOIN_MINTS = {
    "0x55d398326f99059ff775485246999027b3197955",  # USDT BSC
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC BSC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT ETH
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC ETH
    "0xaf88d065e77c8cc2239327c5edb3a432268e5831",  # USDC ARB
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC BASE
}


async def _fetch_wallet_swaps_moralis(address: str, chain_key: str, max_pages: int = 10) -> list[dict]:
    """Fetch all DEX swaps for a wallet on a specific chain via Moralis.
    Returns raw swap list with: token_address, side, usd, amount, timestamp, tx_hash, pair_label."""
    moralis_chain = _MORALIS_CHAINS.get(chain_key)
    if not moralis_chain:
        return []
    moralis_key = settings.MORALIS_API_KEY
    if not moralis_key:
        return []

    swaps: list[dict] = []
    cursor: str | None = None

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            headers = {"X-API-Key": moralis_key, "Accept": "application/json"}

            for page in range(max_pages):
                url = f"https://deep-index.moralis.io/api/v2.2/wallets/{address}/swaps"
                params: dict = {"chain": moralis_chain, "order": "DESC", "limit": "100"}
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 429:
                    await asyncio.sleep(1.5)
                    resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    logger.warning(f"Moralis wallet swaps {chain_key} {resp.status_code}: {resp.text[:200]}")
                    break

                data = resp.json()
                result = data.get("result", [])
                if not result:
                    break

                for sw in result:
                    # Parse Moralis wallet swap format
                    # Fields: transactionHash, transactionType (buy/sell), blockTimestamp,
                    #   bought: {address, amount, usdAmount, symbol, logo, name}
                    #   sold:   {address, amount, usdAmount, symbol, logo, name}
                    #   pairLabel, subCategory, baseToken, quoteToken
                    block_ts = sw.get("blockTimestamp") or sw.get("block_timestamp") or ""
                    ts = 0
                    if isinstance(block_ts, str) and block_ts:
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(block_ts.replace("Z", "+00:00"))
                            ts = int(dt.timestamp())
                        except Exception:
                            pass
                    elif isinstance(block_ts, (int, float)):
                        ts = int(block_ts) if block_ts < 1e12 else int(block_ts / 1000)

                    tx_hash = sw.get("transactionHash", sw.get("transaction_hash", ""))
                    tx_type = sw.get("transactionType", "")  # "buy" or "sell"
                    pair_label = sw.get("pairLabel", "")
                    sub_category = sw.get("subCategory", "")  # "accumulation", "partialSell", etc.

                    bought = sw.get("bought", {}) or {}
                    sold = sw.get("sold", {}) or {}

                    bought_addr = (bought.get("address") or "").lower()
                    sold_addr = (sold.get("address") or "").lower()
                    bought_sym = bought.get("symbol") or bought.get("name") or "?"
                    sold_sym = sold.get("symbol") or sold.get("name") or "?"
                    bought_logo = bought.get("logo") or ""
                    sold_logo = sold.get("logo") or ""
                    bought_name = bought.get("name") or bought_sym
                    sold_name = sold.get("name") or sold_sym

                    bought_amt = abs(float(bought.get("amount") or 0))
                    sold_amt = abs(float(sold.get("amount") or 0))
                    bought_usd = abs(float(bought.get("usdAmount") or 0))
                    sold_usd = abs(float(sold.get("usdAmount") or 0))

                    # Determine which token is "the token" and which is quote
                    bought_is_quote = bought_addr in _NATIVE_MINTS or bought_addr in _STABLECOIN_MINTS
                    sold_is_quote = sold_addr in _NATIVE_MINTS or sold_addr in _STABLECOIN_MINTS

                    if tx_type == "buy":
                        # Wallet bought a token (received bought, sent sold)
                        # The "bought" object is the token we're interested in
                        token_addr = bought_addr if not bought_is_quote else sold_addr
                        token_sym = bought_sym if not bought_is_quote else sold_sym
                        token_name = bought_name if not bought_is_quote else sold_name
                        token_logo = bought_logo if not bought_is_quote else sold_logo
                        token_amt = bought_amt if not bought_is_quote else sold_amt
                        usd = max(bought_usd, sold_usd)
                        if token_addr and token_addr not in _NATIVE_MINTS and token_addr not in _STABLECOIN_MINTS:
                            swaps.append({
                                "token_address": token_addr,
                                "token_symbol": token_sym,
                                "token_name": token_name,
                                "token_logo": token_logo,
                                "side": "buy",
                                "token_amount": token_amt,
                                "quote_amount": sold_amt if sold_is_quote else bought_amt,
                                "usd_value": usd,
                                "timestamp": ts,
                                "tx_hash": tx_hash,
                                "chain": chain_key,
                                "pair_label": pair_label,
                                "sub_category": sub_category,
                            })
                    elif tx_type == "sell":
                        # Wallet sold a token (sent sold, received bought)
                        # The "sold" object is the token we're interested in
                        token_addr = sold_addr if not sold_is_quote else bought_addr
                        token_sym = sold_sym if not sold_is_quote else bought_sym
                        token_name = sold_name if not sold_is_quote else bought_name
                        token_logo = sold_logo if not sold_is_quote else bought_logo
                        token_amt = sold_amt if not sold_is_quote else bought_amt
                        usd = max(bought_usd, sold_usd)
                        if token_addr and token_addr not in _NATIVE_MINTS and token_addr not in _STABLECOIN_MINTS:
                            swaps.append({
                                "token_address": token_addr,
                                "token_symbol": token_sym,
                                "token_name": token_name,
                                "token_logo": token_logo,
                                "side": "sell",
                                "token_amount": token_amt,
                                "quote_amount": bought_amt if bought_is_quote else sold_amt,
                                "usd_value": usd,
                                "timestamp": ts,
                                "tx_hash": tx_hash,
                                "chain": chain_key,
                                "pair_label": pair_label,
                                "sub_category": sub_category,
                            })

                cursor = data.get("cursor")
                if not cursor:
                    break
                await asyncio.sleep(0.15)  # Rate-limit courtesy

    except Exception as e:
        logger.error(f"Moralis wallet swaps error ({chain_key}): {e}")

    logger.info(f"Moralis wallet swaps {chain_key} for {address[:12]}: {len(swaps)} swaps across {min(page + 1, max_pages)} pages")
    return swaps


def _compute_trader_profile(swaps: list[dict], current_holdings: list[dict] | None = None) -> dict:
    """Compute per-token PnL, win rate, trading style, MC distribution from raw swaps.
    current_holdings: optional list of current token balances for unrealized PnL."""

    # Group swaps by token
    token_swaps: dict[str, list[dict]] = {}
    for s in swaps:
        addr = s["token_address"]
        if not addr or addr in _NATIVE_MINTS or addr in _STABLECOIN_MINTS:
            continue
        if addr not in token_swaps:
            token_swaps[addr] = []
        token_swaps[addr].append(s)

    # Build current holdings lookup for unrealized PnL
    holdings_map: dict[str, dict] = {}
    if current_holdings:
        for h in current_holdings:
            mint = (h.get("mint") or "").lower()
            if mint:
                holdings_map[mint] = h

    # Compute per-token stats
    token_stats: list[dict] = []
    total_realized = 0.0
    total_unrealized = 0.0
    total_cost = 0.0
    total_revenue = 0.0
    wins = 0
    losses = 0
    total_tokens_traded = 0

    for token_addr, tsw in token_swaps.items():
        tsw.sort(key=lambda x: x.get("timestamp", 0))
        first = tsw[0]
        symbol = first.get("token_symbol", "?")
        name = first.get("token_name", symbol)
        logo = first.get("token_logo", "")
        chain = first.get("chain", "?")

        buys = [s for s in tsw if s["side"] == "buy"]
        sells = [s for s in tsw if s["side"] == "sell"]

        buy_count = len(buys)
        sell_count = len(sells)
        total_buy_usd = sum(s["usd_value"] for s in buys)
        total_sell_usd = sum(s["usd_value"] for s in sells)
        total_buy_tokens = sum(s["token_amount"] for s in buys)
        total_sell_tokens = sum(s["token_amount"] for s in sells)

        avg_buy_price = total_buy_usd / max(total_buy_tokens, 1e-18)
        avg_sell_price = total_sell_usd / max(total_sell_tokens, 1e-18)

        realized_pnl = total_sell_usd - (total_buy_usd * (total_sell_tokens / max(total_buy_tokens, 1e-18)))
        realized_pnl = round(realized_pnl, 2)

        # Unrealized PnL: remaining tokens × (current_price - avg_buy_price)
        remaining_tokens = max(0, total_buy_tokens - total_sell_tokens)
        unrealized_pnl = 0.0
        current_price = 0.0
        current_balance_usd = 0.0
        holding = holdings_map.get(token_addr)
        if holding and remaining_tokens > 0:
            current_price = holding.get("price", 0) or 0
            current_balance_usd = holding.get("usd_value", 0) or 0
            cost_basis = avg_buy_price * remaining_tokens
            unrealized_pnl = round(current_balance_usd - cost_basis, 2)

        total_pnl = realized_pnl + unrealized_pnl

        # Holding duration
        first_buy_ts = buys[0]["timestamp"] if buys else 0
        last_sell_ts = sells[-1]["timestamp"] if sells else 0
        last_active_ts = tsw[-1]["timestamp"]
        if sell_count > 0 and remaining_tokens < 0.01:
            # Fully exited — duration is first buy to last sell
            hold_seconds = last_sell_ts - first_buy_ts if first_buy_ts else 0
        else:
            # Still holding — duration is first buy to now
            hold_seconds = int(time.time()) - first_buy_ts if first_buy_ts else 0

        # Win/loss determination
        is_win = total_pnl > 0
        if total_pnl > 1:
            wins += 1
        elif total_pnl < -1:
            losses += 1

        total_realized += realized_pnl
        total_unrealized += unrealized_pnl
        total_cost += total_buy_usd
        total_revenue += total_sell_usd
        total_tokens_traded += 1

        # Determine status
        if remaining_tokens > 0.01 and current_balance_usd > 0.01:
            status = "holding"
        elif sell_count > 0 and remaining_tokens < 0.01:
            status = "closed"
        elif buy_count > 0 and sell_count == 0:
            status = "holding"
        else:
            status = "closed"

        # Exit strategy detection
        if sell_count == 0:
            exit_type = "none"
        elif sell_count == 1 and remaining_tokens < 0.01:
            exit_type = "sell_all"
        elif sell_count > 1 and remaining_tokens < 0.01:
            exit_type = "gradual_exit"
        elif sell_count > 0 and remaining_tokens > 0.01:
            exit_type = "partial_exit"
        else:
            exit_type = "unknown"

        token_stats.append({
            "token_address": token_addr,
            "token_symbol": symbol,
            "token_name": name,
            "token_logo": logo,
            "chain": chain,
            "buys": buy_count,
            "sells": sell_count,
            "total_buy_usd": round(total_buy_usd, 2),
            "total_sell_usd": round(total_sell_usd, 2),
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price if sell_count > 0 else 0,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / max(total_buy_usd, 0.01) * 100, 2),
            "remaining_tokens": remaining_tokens,
            "current_price": current_price,
            "current_balance_usd": round(current_balance_usd, 2),
            "hold_duration_seconds": hold_seconds,
            "first_buy_ts": first_buy_ts,
            "last_active_ts": last_active_ts,
            "status": status,
            "exit_type": exit_type,
            "is_win": is_win,
            "pair_label": first.get("pair_label", ""),
        })

    # Sort by total PnL descending
    token_stats.sort(key=lambda x: x["total_pnl"], reverse=True)

    # Compute aggregate stats
    win_rate = round(wins / max(wins + losses, 1) * 100, 1)

    # Avg holding duration (closed positions only)
    closed = [t for t in token_stats if t["status"] == "closed"]
    avg_hold_sec = sum(t["hold_duration_seconds"] for t in closed) / max(len(closed), 1)

    # Trading style classification
    if len(token_stats) == 0:
        style = "Unknown"
    else:
        quick_exits = sum(1 for t in closed if t["hold_duration_seconds"] < 3600)  # < 1 hour
        long_holds = sum(1 for t in token_stats if t["hold_duration_seconds"] > 86400 * 7)  # > 7 days
        sell_all_count = sum(1 for t in token_stats if t["exit_type"] == "sell_all")
        gradual_count = sum(1 for t in token_stats if t["exit_type"] == "gradual_exit")

        if quick_exits > len(closed) * 0.6:
            style = "Scalper"
        elif long_holds > len(token_stats) * 0.4:
            style = "Diamond Hand"
        elif gradual_count > sell_all_count:
            style = "Strategic Trader"
        elif win_rate > 65:
            style = "Alpha Hunter"
        elif total_tokens_traded > 50:
            style = "Degen"
        else:
            style = "Active Trader"

    # Best / worst trade
    best = max(token_stats, key=lambda x: x["total_pnl"]) if token_stats else None
    worst = min(token_stats, key=lambda x: x["total_pnl"]) if token_stats else None

    # Cumulative PnL timeline (for chart)
    # Build from all swaps sorted by time
    all_sorted = sorted(swaps, key=lambda x: x.get("timestamp", 0))
    cumulative_pnl: list[dict] = []
    running = 0.0
    # Track cost basis per token for running PnL
    cost_tracker: dict[str, float] = {}  # token_addr -> total_cost
    revenue_tracker: dict[str, float] = {}  # token_addr -> total_revenue
    tokens_bought: dict[str, float] = {}
    tokens_sold: dict[str, float] = {}
    for s in all_sorted:
        ta = s["token_address"]
        if ta in _NATIVE_MINTS or ta in _STABLECOIN_MINTS:
            continue
        if s["side"] == "buy":
            cost_tracker[ta] = cost_tracker.get(ta, 0) + s["usd_value"]
            tokens_bought[ta] = tokens_bought.get(ta, 0) + s["token_amount"]
        else:
            revenue_tracker[ta] = revenue_tracker.get(ta, 0) + s["usd_value"]
            tokens_sold[ta] = tokens_sold.get(ta, 0) + s["token_amount"]
            # Calc running realized
            sold_ratio = tokens_sold[ta] / max(tokens_bought.get(ta, 0), 1e-18)
            sold_ratio = min(sold_ratio, 1.0)
            cost_of_sold = cost_tracker.get(ta, 0) * sold_ratio
            running = sum(revenue_tracker.values()) - sum(
                cost_tracker.get(t, 0) * min(tokens_sold.get(t, 0) / max(tokens_bought.get(t, 0), 1e-18), 1.0)
                for t in revenue_tracker
            )
        if s.get("timestamp", 0) > 0:
            cumulative_pnl.append({"ts": s["timestamp"], "pnl": round(running, 2)})

    return {
        "total_tokens_traded": total_tokens_traded,
        "total_realized_pnl": round(total_realized, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_pnl": round(total_realized + total_unrealized, 2),
        "total_cost": round(total_cost, 2),
        "total_revenue": round(total_revenue, 2),
        "win_rate": win_rate,
        "wins": wins,
        "losses": losses,
        "avg_hold_duration_seconds": int(avg_hold_sec),
        "trading_style": style,
        "best_trade": {
            "token": best["token_symbol"],
            "pnl": best["total_pnl"],
            "pnl_pct": best["total_pnl_pct"],
        } if best else None,
        "worst_trade": {
            "token": worst["token_symbol"],
            "pnl": worst["total_pnl"],
            "pnl_pct": worst["total_pnl_pct"],
        } if worst else None,
        "token_stats": token_stats[:200],  # Cap at 200 tokens
        "cumulative_pnl": cumulative_pnl[-500:],  # Last 500 data points
        "total_swaps": len(swaps),
    }


class TraderProfileRequest(BaseModel):
    address: str
    chains: list[str] | None = None  # Optional: specific chains, default all EVM
    time_range: str = "all"  # "7d", "30d", "90d", "all"


@router.post("/trader-profile", dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60))])
async def get_trader_profile(req: TraderProfileRequest):
    """Fetch full trading history for a wallet and compute per-token PnL,
    win rate, trading style, and behavior analysis. Works for both EVM and SOL."""
    t0 = time.time()
    address = req.address.strip()
    is_evm = address.startswith("0x")

    if is_evm:
        chains_to_scan = req.chains or ["ETH", "BSC", "ARB", "BASE", "OP"]
    else:
        chains_to_scan = ["SOL"]

    # Check cache
    cache_key = f"trader:profile:{address}:{','.join(chains_to_scan)}:{req.time_range}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # Fetch swaps from all chains in parallel
    all_swaps: list[dict] = []

    if is_evm:
        async def _fetch_chain(ch: str):
            return await _fetch_wallet_swaps_moralis(address, ch, max_pages=10)

        chain_results = await asyncio.gather(
            *[_fetch_chain(ch) for ch in chains_to_scan],
            return_exceptions=True,
        )
        for r in chain_results:
            if isinstance(r, Exception):
                logger.warning(f"Trader profile chain error: {r}")
                continue
            all_swaps.extend(r)
    else:
        # SOL: Use existing Solana swap parsing
        # For now, SOL trader mode uses Moralis Solana wallet swaps
        try:
            moralis_key = settings.MORALIS_API_KEY
            if moralis_key:
                async with httpx.AsyncClient(timeout=25) as client:
                    headers = {"X-API-Key": moralis_key, "Accept": "application/json"}
                    cursor = None
                    for page in range(10):
                        url = f"https://solana-gateway.moralis.io/account/mainnet/{address}/swaps"
                        params: dict = {"order": "DESC", "limit": "100"}
                        if cursor:
                            params["cursor"] = cursor
                        resp = await client.get(url, headers=headers, params=params)
                        if resp.status_code != 200:
                            break
                        data = resp.json()
                        result = data if isinstance(data, list) else data.get("result", [])
                        if not result:
                            break
                        for sw in result:
                            # Parse SOL swap format
                            bought = sw.get("bought", {}) or {}
                            sold = sw.get("sold", {}) or {}
                            block_ts = 0
                            for k in ("blockTimestamp", "block_timestamp", "timestamp"):
                                v = sw.get(k)
                                if v:
                                    if isinstance(v, str):
                                        try:
                                            from datetime import datetime
                                            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                                            block_ts = int(dt.timestamp())
                                        except Exception:
                                            pass
                                    elif isinstance(v, (int, float)):
                                        block_ts = int(v) if v < 1e12 else int(v / 1000)
                                    if block_ts:
                                        break

                            bought_addr = (bought.get("address") or bought.get("mint") or "").lower()
                            sold_addr = (sold.get("address") or sold.get("mint") or "").lower()
                            bought_sym = bought.get("symbol") or "?"
                            sold_sym = sold.get("symbol") or "?"
                            bought_usd = float(bought.get("usdAmount") or bought.get("valueUsd") or 0)
                            sold_usd = float(sold.get("usdAmount") or sold.get("valueUsd") or 0)
                            bought_amt = float(bought.get("amount") or bought.get("amountFormatted") or 0)
                            sold_amt = float(sold.get("amount") or sold.get("amountFormatted") or 0)

                            # SOL/stable is quote → the other is the traded token
                            sold_is_quote = sold_addr in _NATIVE_MINTS or "usd" in sold_sym.lower()
                            bought_is_quote = bought_addr in _NATIVE_MINTS or "usd" in bought_sym.lower()

                            if sold_is_quote and not bought_is_quote and bought_addr:
                                all_swaps.append({
                                    "token_address": bought_addr, "token_symbol": bought_sym,
                                    "token_name": bought.get("name", bought_sym),
                                    "token_logo": bought.get("logo", ""),
                                    "side": "buy", "token_amount": bought_amt,
                                    "quote_amount": sold_amt,
                                    "usd_value": sold_usd if sold_usd > 0 else bought_usd,
                                    "timestamp": block_ts, "tx_hash": sw.get("transactionHash", ""),
                                    "chain": "SOL", "pair_label": f"{bought_sym}/{sold_sym}",
                                })
                            elif bought_is_quote and not sold_is_quote and sold_addr:
                                all_swaps.append({
                                    "token_address": sold_addr, "token_symbol": sold_sym,
                                    "token_name": sold.get("name", sold_sym),
                                    "token_logo": sold.get("logo", ""),
                                    "side": "sell", "token_amount": sold_amt,
                                    "quote_amount": bought_amt,
                                    "usd_value": bought_usd if bought_usd > 0 else sold_usd,
                                    "timestamp": block_ts, "tx_hash": sw.get("transactionHash", ""),
                                    "chain": "SOL", "pair_label": f"{sold_sym}/{bought_sym}",
                                })

                        cursor = data.get("cursor") if isinstance(data, dict) else None
                        if not cursor:
                            break
                        await asyncio.sleep(0.15)
        except Exception as e:
            logger.error(f"SOL trader profile error: {e}")

    # Filter by time range
    if req.time_range != "all":
        now = int(time.time())
        ranges = {"7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400}
        cutoff = now - ranges.get(req.time_range, 0)
        if cutoff > 0:
            all_swaps = [s for s in all_swaps if s.get("timestamp", 0) >= cutoff]

    # Get current holdings for unrealized PnL computation
    current_holdings: list[dict] = []
    if is_evm:
        # Reuse cached portfolio data if available
        for ch in chains_to_scan:
            ck = f"wallet:onchain:{ch}:{address}"
            cached_chain = await cache_get(ck)
            if cached_chain:
                for h in cached_chain.get("top_token_accounts", []):
                    current_holdings.append({
                        "mint": (h.get("mint") or "").lower(),
                        "price": h.get("price", 0),
                        "usd_value": h.get("usd_value", 0),
                        "amount": h.get("amount", 0),
                    })

    profile = _compute_trader_profile(all_swaps, current_holdings)

    # Add metadata
    profile["address"] = address
    profile["chains_scanned"] = chains_to_scan
    profile["time_range"] = req.time_range
    profile["fetch_time_ms"] = int((time.time() - t0) * 1000)

    await cache_set(cache_key, profile, ttl=120)
    logger.info(f"Trader profile for {address[:12]}: {profile['total_swaps']} swaps, {profile['total_tokens_traded']} tokens in {profile['fetch_time_ms']}ms")
    return profile
