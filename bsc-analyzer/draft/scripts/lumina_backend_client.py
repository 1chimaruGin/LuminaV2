"""
Thin HTTP client for lumina-backend token gate (BSC).
Used by scripts/enrich_candidates.py when LUMINA_BACKEND_URL is set.

Example:
  export LUMINA_BACKEND_URL=http://127.0.0.1:8000
  export LUMINA_API_PREFIX=/api/v1   # default
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def fetch_bsc_candidate_check(
    base_url: str,
    api_prefix: str,
    token_address: str,
    timeout_sec: float = 20.0,
) -> dict | None:
    """
    GET {base}{prefix}/token/bsc-candidate-check/{token}
    Returns parsed JSON or None on failure.
    """
    if not base_url:
        return None
    prefix = (api_prefix or "/api/v1").rstrip("/")
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    url = f"{base_url.rstrip('/')}{prefix}/token/bsc-candidate-check/{token_address.lower()}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "lumina-bsc-analyzer/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        return {"error": str(e), "url": url}


def main() -> None:
    import sys

    base = os.environ.get("LUMINA_BACKEND_URL", "http://127.0.0.1:8000")
    prefix = os.environ.get("LUMINA_API_PREFIX", "/api/v1")
    if len(sys.argv) < 2:
        print("Usage: python lumina_backend_client.py 0xToken...", file=sys.stderr)
        sys.exit(1)
    out = fetch_bsc_candidate_check(base, prefix, sys.argv[1].strip())
    if out:
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
