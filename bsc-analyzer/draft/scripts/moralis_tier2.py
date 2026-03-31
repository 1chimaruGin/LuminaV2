#!/usr/bin/env python3
"""
Tier-2 enricher: read Four.meme JSONL lines from stdin, batch-call Moralis for deployer wallet
activity, print merged JSON (debounced, low call rate).

Requires: MORALIS_API_KEY in environment.
Optional: MORALIS_BASE_URL (default https://deep-index.moralis.io)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("MORALIS_BASE_URL", "https://deep-index.moralis.io").rstrip("/")
API_KEY = os.environ.get("MORALIS_API_KEY", "")
CACHE_TTL = float(os.environ.get("MORALIS_CACHE_TTL_SEC", "300"))
DEBOUNCE_SEC = float(os.environ.get("MORALIS_DEBOUNCE_SEC", "2.0"))

_cache: dict[str, tuple[float, Any]] = {}


def moralis_get(path: str) -> Any:
    if not API_KEY:
        return None
    url = f"{BASE}{path}"
    sep = "&" if "?" in url else "?"
    url += f"{sep}chain=bsc"
    req = urllib.request.Request(
        url,
        headers={"X-API-Key": API_KEY, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"moralis HTTP {e.code}: {e.read()[:500]!r}\n")
        return None
    except Exception as e:
        sys.stderr.write(f"moralis error: {e}\n")
        return None


def wallet_stats(address: str) -> dict[str, Any]:
    now = time.time()
    ck = address.lower()
    if ck in _cache and now - _cache[ck][0] < CACHE_TTL:
        return _cache[ck][1]
    # Native + token transfers count (single lightweight aggregate)
    out: dict[str, Any] = {"address": address}
    tr = moralis_get(f"/api/v2/{address}/erc20/transfers?limit=10")
    if isinstance(tr, dict):
        res = tr.get("result") or []
        out["recent_erc20_transfer_count"] = len(res) if isinstance(res, list) else 0
    _cache[ck] = (now, out)
    return out


def main() -> None:
    if not API_KEY:
        sys.stderr.write("MORALIS_API_KEY not set; passing through stdin unchanged.\n")
    pending: dict[str, dict] = {}
    last_flush = 0.0

    def flush_pending() -> None:
        nonlocal pending
        for c, o in list(pending.items()):
            stats = wallet_stats(o["creator"])
            o["moralis_deployer"] = stats
            print(json.dumps(o, separators=(",", ":")))
            del pending[c]

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            print(line)
            continue
        if obj.get("type") != "fourmeme_intel":
            print(line)
            continue
        creator = obj.get("creator")
        if not creator or not API_KEY:
            print(json.dumps(obj, separators=(",", ":")))
            continue
        pending[creator.lower()] = obj
        now = time.time()
        if now - last_flush < DEBOUNCE_SEC:
            continue
        last_flush = now
        flush_pending()

    flush_pending()


if __name__ == "__main__":
    main()
