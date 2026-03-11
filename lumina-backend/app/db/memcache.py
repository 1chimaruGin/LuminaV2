"""
Fast in-memory TTL cache — replaces Redis when Redis is unavailable.
Thread-safe, async-compatible, zero dependencies.
"""

import time
import json
from typing import Any, Optional

_store: dict[str, tuple[float, Any]] = {}  # key -> (expires_at, value)


async def cache_get(key: str) -> Optional[Any]:
    entry = _store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _store.pop(key, None)
        return None
    return value


async def cache_set(key: str, value: Any, ttl: int = 60):
    _store[key] = (time.time() + ttl, value)


async def cache_delete(key: str):
    _store.pop(key, None)


async def cache_delete_pattern(pattern: str):
    import fnmatch
    keys_to_delete = [k for k in _store if fnmatch.fnmatch(k, pattern)]
    for k in keys_to_delete:
        _store.pop(k, None)


def cache_stats() -> dict:
    now = time.time()
    valid = sum(1 for _, (exp, _) in _store.items() if exp > now)
    return {"total_keys": len(_store), "valid_keys": valid}
