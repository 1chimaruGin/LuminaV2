"""
Token mint → symbol/name resolver.

Strategy (like BullX Neo):
1. Preload Jupiter /all token list at startup (~14K tokens, cached in-memory)
2. For Token-2022 mints: read embedded tokenMetadata extension (pump.fun, etc.)
3. For classic SPL mints: batch-fetch Metaplex metadata PDAs via getMultipleAccounts
4. Cache everything so repeated lookups are instant
"""

import asyncio
import base64
import hashlib
import logging
import struct
import time
from typing import Optional

import base58
import httpx
from nacl.bindings import crypto_sign_ed25519_pk_to_curve25519

logger = logging.getLogger(__name__)

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
METAPLEX_PROGRAM = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"

# ── Built-in map of popular tokens (instant, no network needed) ───────────────
_BUILTIN: dict[str, dict] = {
    "So11111111111111111111111111111111111111112": {"symbol": "SOL", "name": "Wrapped SOL", "logo": "", "decimals": 9},
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": {"symbol": "USDC", "name": "USD Coin", "logo": "", "decimals": 6},
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": {"symbol": "USDT", "name": "Tether USD", "logo": "", "decimals": 6},
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": {"symbol": "mSOL", "name": "Marinade Staked SOL", "logo": "", "decimals": 9},
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj": {"symbol": "stSOL", "name": "Lido Staked SOL", "logo": "", "decimals": 9},
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": {"symbol": "bSOL", "name": "BlazeStake Staked SOL", "logo": "", "decimals": 9},
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": {"symbol": "JitoSOL", "name": "Jito Staked SOL", "logo": "", "decimals": 9},
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": {"symbol": "JUP", "name": "Jupiter", "logo": "", "decimals": 6},
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": {"symbol": "BONK", "name": "Bonk", "logo": "", "decimals": 5},
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": {"symbol": "WIF", "name": "dogwifhat", "logo": "", "decimals": 6},
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": {"symbol": "POPCAT", "name": "Popcat", "logo": "", "decimals": 9},
    "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof": {"symbol": "RENDER", "name": "Render Token", "logo": "", "decimals": 8},
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3": {"symbol": "PYTH", "name": "Pyth Network", "logo": "", "decimals": 6},
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux": {"symbol": "HNT", "name": "Helium", "logo": "", "decimals": 8},
    "TNSRxcUxoT9xBG3de7PiJyTDYu7kskLqcpddxnEJAS6": {"symbol": "TNSR", "name": "Tensor", "logo": "", "decimals": 9},
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": {"symbol": "JTO", "name": "Jito", "logo": "", "decimals": 9},
    "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5": {"symbol": "MEW", "name": "cat in a dogs world", "logo": "", "decimals": 5},
    "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ": {"symbol": "W", "name": "Wormhole", "logo": "", "decimals": 6},
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": {"symbol": "RAY", "name": "Raydium", "logo": "", "decimals": 6},
    "SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt": {"symbol": "SRM", "name": "Serum", "logo": "", "decimals": 6},
    "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey": {"symbol": "MNDE", "name": "Marinade", "logo": "", "decimals": 9},
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": {"symbol": "ORCA", "name": "Orca", "logo": "", "decimals": 6},
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs": {"symbol": "ETH", "name": "Ethereum (Wormhole)", "logo": "", "decimals": 8},
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh": {"symbol": "WBTC", "name": "Wrapped BTC (Wormhole)", "logo": "", "decimals": 8},
    "DUSTawucrTsGU8hcqRdHDCbuYhCPADMLM2VcCb8VnFnQ": {"symbol": "DUST", "name": "DUST Protocol", "logo": "", "decimals": 9},
    "kinXdEcpDQeHPEuQnqmUgtYykqKGVFq6CeVX5iAHJq6": {"symbol": "KIN", "name": "Kin", "logo": "", "decimals": 5},
    "nosXBVoaCTtYdLvKY6Csb4AC8JCdQKKAaWYtx2ZMoo7": {"symbol": "NOS", "name": "Nosana", "logo": "", "decimals": 6},
    "GDfnEsia2WLAW5t8yx2tFEWDBxfEjRYGqMBHBwsTo5cm": {"symbol": "GORK", "name": "Gork", "logo": "", "decimals": 6},
    "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6": {"symbol": "MOBILE", "name": "Helium Mobile", "logo": "", "decimals": 6},
    "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns": {"symbol": "IOT", "name": "Helium IOT", "logo": "", "decimals": 6},
    "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7": {"symbol": "DRIFT", "name": "Drift", "logo": "", "decimals": 6},
    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": {"symbol": "jupSOL", "name": "Jupiter Staked SOL", "logo": "", "decimals": 9},
    "2FPyTwcZLUg1MDrwsyoP4D6s1tM6hAkTEQpoLfKGpfKP": {"symbol": "FIDA", "name": "Bonfida", "logo": "", "decimals": 6},
    "SHDWyBxihqiCj6YekG2GUr7wqKLeLAMK1gHZck9pL6y": {"symbol": "SHDW", "name": "Shadow Token", "logo": "", "decimals": 9},
    "MangoCzJ36AjZyKwVj3VnYU4GTonjfVEnJmvvWaxLac": {"symbol": "MNGO", "name": "Mango", "logo": "", "decimals": 6},
}

# ── In-memory token cache (builtin + Jupiter + on-chain resolved) ─────────────
_TOKEN_CACHE: dict[str, dict] = {**_BUILTIN}
_JUPITER_LOADED = False
_JUPITER_LOADING = False
_LAST_JUPITER_ATTEMPT = 0.0


async def preload_jupiter():
    """Load Jupiter /all token list into memory. Call at startup."""
    global _JUPITER_LOADED, _JUPITER_LOADING, _LAST_JUPITER_ATTEMPT

    if _JUPITER_LOADED or _JUPITER_LOADING:
        return
    if time.time() - _LAST_JUPITER_ATTEMPT < 60:
        return

    _JUPITER_LOADING = True
    _LAST_JUPITER_ATTEMPT = time.time()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://token.jup.ag/all")
            if resp.status_code == 200:
                tokens = resp.json()
                for t in tokens:
                    addr = t.get("address", "")
                    if addr:
                        _TOKEN_CACHE[addr] = {
                            "symbol": t.get("symbol", ""),
                            "name": t.get("name", ""),
                            "logo": t.get("logoURI", ""),
                            "decimals": t.get("decimals", 0),
                        }
                _JUPITER_LOADED = True
                logger.info(f"✅ Jupiter token list loaded: {len(_TOKEN_CACHE)} tokens")
            else:
                logger.warning(f"Jupiter API returned {resp.status_code}")
    except Exception as e:
        logger.warning(f"Jupiter API unavailable: {e}")
    finally:
        _JUPITER_LOADING = False


# ── Token-2022 embedded metadata extraction ───────────────────────────────────

def extract_token2022_metadata(mint_address: str, account_info: dict) -> Optional[dict]:
    """Extract metadata from a Token-2022 mint's extensions (pump.fun tokens, etc.)."""
    try:
        parsed = account_info.get("data", {}).get("parsed", {}).get("info", {})
        extensions = parsed.get("extensions", [])
        for ext in extensions:
            if ext.get("extension") == "tokenMetadata":
                state = ext.get("state", {})
                name = state.get("name", "").strip()
                symbol = state.get("symbol", "").strip()
                if name or symbol:
                    result = {
                        "symbol": symbol or name[:10],
                        "name": name or symbol,
                        "logo": "",
                        "decimals": parsed.get("decimals", 0),
                    }
                    _TOKEN_CACHE[mint_address] = result
                    return result
    except Exception:
        pass
    return None


# ── Metaplex PDA metadata (classic SPL tokens) ───────────────────────────────

def _derive_metadata_pda(mint: str) -> Optional[str]:
    """Derive the Metaplex metadata PDA for a given mint address."""
    try:
        program_id = base58.b58decode(METAPLEX_PROGRAM)
        mint_bytes = base58.b58decode(mint)
        seeds = [b"metadata", program_id, mint_bytes]

        for bump in range(255, -1, -1):
            h = hashlib.sha256()
            for s in seeds:
                h.update(s)
            h.update(bytes([bump]))
            h.update(program_id)
            h.update(b"ProgramDerivedAddress")
            candidate = h.digest()
            try:
                crypto_sign_ed25519_pk_to_curve25519(candidate)
                continue  # on curve — not a valid PDA
            except Exception:
                return base58.b58encode(candidate).decode()
        return None
    except Exception:
        return None


def _parse_metaplex_metadata(data_bytes: bytes) -> Optional[dict]:
    """Parse Metaplex metadata account binary data to extract name/symbol."""
    try:
        if len(data_bytes) < 69:
            return None
        offset = 1 + 32 + 32  # key + update_authority + mint = 65
        name_len = struct.unpack_from("<I", data_bytes, offset)[0]
        offset += 4
        name = data_bytes[offset:offset + name_len].decode("utf-8", errors="ignore").rstrip("\x00").strip()
        offset += name_len
        symbol_len = struct.unpack_from("<I", data_bytes, offset)[0]
        offset += 4
        symbol = data_bytes[offset:offset + symbol_len].decode("utf-8", errors="ignore").rstrip("\x00").strip()
        if symbol and name:
            return {"symbol": symbol, "name": name, "logo": "", "decimals": 0}
    except Exception:
        pass
    return None


async def _batch_fetch_metaplex(mints: list[str]) -> dict[str, dict]:
    """Batch-fetch Metaplex metadata for multiple mints via getMultipleAccounts."""
    if not mints:
        return {}

    # Derive PDAs
    pda_map: dict[str, str] = {}  # pda_address -> mint
    pdas: list[str] = []
    for mint in mints:
        pda = _derive_metadata_pda(mint)
        if pda:
            pda_map[pda] = mint
            pdas.append(pda)

    if not pdas:
        return {}

    results: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            # Solana allows up to 100 accounts per getMultipleAccounts call
            for i in range(0, len(pdas), 100):
                batch = pdas[i:i + 100]
                resp = await client.post(SOLANA_RPC, json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getMultipleAccounts",
                    "params": [batch, {"encoding": "base64"}],
                })
                values = resp.json().get("result", {}).get("value", [])
                for j, val in enumerate(values):
                    if val and val.get("data"):
                        pda_addr = batch[j]
                        mint = pda_map.get(pda_addr)
                        if mint:
                            raw = base64.b64decode(val["data"][0])
                            meta = _parse_metaplex_metadata(raw)
                            if meta:
                                results[mint] = meta
                                _TOKEN_CACHE[mint] = meta
    except Exception as e:
        logger.debug(f"Metaplex batch fetch error: {e}")

    return results


async def _batch_fetch_token2022(mints: list[str]) -> dict[str, dict]:
    """Batch-fetch Token-2022 mint accounts to extract embedded metadata."""
    if not mints:
        return {}

    results: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            for i in range(0, len(mints), 100):
                batch = mints[i:i + 100]
                resp = await client.post(SOLANA_RPC, json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getMultipleAccounts",
                    "params": [batch, {"encoding": "jsonParsed"}],
                })
                values = resp.json().get("result", {}).get("value", [])
                for j, val in enumerate(values):
                    if val:
                        mint = batch[j]
                        meta = extract_token2022_metadata(mint, val)
                        if meta:
                            results[mint] = meta
    except Exception as e:
        logger.debug(f"Token-2022 batch fetch error: {e}")

    return results


# ── Public API ────────────────────────────────────────────────────────────────

async def resolve_mint(mint_address: str) -> dict:
    """Resolve a Solana SPL mint address to symbol/name."""
    if mint_address in _TOKEN_CACHE:
        return _TOKEN_CACHE[mint_address]

    # Single-mint fallback: try Token-2022 first, then Metaplex
    resolved = await _batch_fetch_token2022([mint_address])
    if mint_address in resolved:
        return resolved[mint_address]

    resolved = await _batch_fetch_metaplex([mint_address])
    if mint_address in resolved:
        return resolved[mint_address]

    fallback = {
        "symbol": mint_address[:4] + "..." + mint_address[-4:] if len(mint_address) > 12 else mint_address,
        "name": "Unknown Token",
        "logo": "",
        "decimals": 0,
    }
    _TOKEN_CACHE[mint_address] = fallback
    return fallback


async def resolve_mints_batch(mints: list[str]) -> dict[str, dict]:
    """Resolve multiple mints at once. Uses cache + parallel on-chain lookups."""
    if not _JUPITER_LOADED:
        await preload_jupiter()

    unknown = [m for m in mints if m not in _TOKEN_CACHE]

    if unknown:
        # Fire Token-2022 and Metaplex lookups in parallel
        t22_result, mplex_result = await asyncio.gather(
            _batch_fetch_token2022(unknown),
            _batch_fetch_metaplex(unknown),
            return_exceptions=True,
        )
        # Merge results (Token-2022 takes priority since it's authoritative)
        if isinstance(mplex_result, dict):
            _TOKEN_CACHE.update(mplex_result)
        if isinstance(t22_result, dict):
            _TOKEN_CACHE.update(t22_result)

        # Set fallbacks for still-unknown mints
        for m in unknown:
            if m not in _TOKEN_CACHE:
                _TOKEN_CACHE[m] = {
                    "symbol": m[:4] + "..." + m[-4:] if len(m) > 12 else m,
                    "name": "Unknown Token",
                    "logo": "",
                    "decimals": 0,
                }

    return {m: _TOKEN_CACHE[m] for m in mints if m in _TOKEN_CACHE}


def get_symbol(mint: str) -> Optional[str]:
    """Synchronous lookup from cache."""
    info = _TOKEN_CACHE.get(mint)
    return info["symbol"] if info else None
