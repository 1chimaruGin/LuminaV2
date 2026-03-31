#!/usr/bin/env python3
"""
Add block-aligned *holder proxy* fields using JSON-RPC `eth_getLogs` (ERC20 Transfer).

GMGN `holder_count` is a current snapshot only — it cannot answer "holders at block B".
This script counts **distinct Transfer `to` addresses** from `create_block` through an
end block (inclusive). That is a **proxy** for distribution breadth, not exact
on-chain holder count (sell/burn/mint semantics differ).

Writes per `kol_buys[]`:
  `rpc_unique_recipients_through_buy_block` — through that KOL buy's `buy_block`
Writes per `slot_delay` / delay cell:
  `rpc_unique_recipients_through_our_entry_block` — through `our_entry_block`

Env:
  QUICK_NODE_BSC_RPC or ALCHEMY_BSC_RPC (first non-empty wins)

Usage:
  export QUICK_NODE_BSC_RPC=https://...
  python3 scripts/enrich_recipients_at_entry.py backtest_results/kol.jsonl -o out.jsonl
  python3 scripts/enrich_recipients_at_entry.py kol.jsonl -o out.jsonl --max-rows 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from typing import Any, Optional

TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


def rpc_url() -> str:
    for k in ("QUICK_NODE_BSC_RPC", "ALCHEMY_BSC_RPC"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    raise RuntimeError("Set QUICK_NODE_BSC_RPC (or ALCHEMY_BSC_RPC)")


def eth_call(url: str, method: str, params: list[Any]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(
        "utf-8"
    )
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    if j.get("error"):
        raise RuntimeError(str(j["error"]))
    return j.get("result")


def topic_to_addr(topic: str) -> str:
    if not topic or len(topic) < 42:
        return ""
    return ("0x" + topic[-40:]).lower()


def count_recipients_chunked(
    url: str,
    token: str,
    from_block: int,
    to_block: int,
    chunk: int,
) -> int:
    """Unique `to` addresses in Transfer logs [from_block, to_block]."""
    if to_block < from_block:
        return 0
    recipients: set[str] = set()
    cur = from_block
    while cur <= to_block:
        sub_end = min(cur + max(1, chunk) - 1, to_block)
        flt = {
            "fromBlock": hex(cur),
            "toBlock": hex(sub_end),
            "address": token,
            "topics": [TRANSFER_TOPIC0],
        }
        logs = eth_call(url, "eth_getLogs", [flt])
        if isinstance(logs, list):
            for lg in logs:
                topics = lg.get("topics") or []
                if len(topics) >= 3:
                    addr = topic_to_addr(topics[2])
                    if addr:
                        recipients.add(addr)
        cur = sub_end + 1
    return len(recipients)


# Cache: (token lower, create_block, end_block) -> count
_cache: dict[tuple[str, int, int], int] = {}


def get_count(
    url: str,
    token: str,
    create_block: int,
    end_block: int,
    chunk: int,
) -> int:
    tok = token.lower()
    if end_block <= 0:
        return 0
    key = (tok, create_block, end_block)
    if key in _cache:
        return _cache[key]
    n = count_recipients_chunked(url, tok, create_block, end_block, chunk)
    _cache[key] = n
    return n


SLOT_KEYS = ("slot_1", "slot_2", "slot_3")
DELAY_KEYS = ("plus_1_block", "plus_2_block", "plus_2s")


def enrich_row(row: dict[str, Any], url: str, chunk: int) -> dict[str, Any]:
    token = (row.get("token") or "").strip()
    if not token:
        return row
    cb = int(row.get("create_block") or 0)
    if cb <= 0:
        return row

    kol_buys = row.get("kol_buys")
    if isinstance(kol_buys, list):
        for kb in kol_buys:
            if not isinstance(kb, dict):
                continue
            bb = int(kb.get("buy_block") or 0)
            if bb > 0:
                kb["rpc_unique_recipients_through_buy_block"] = get_count(url, token, cb, bb, chunk)

    sd = row.get("slot_delay")
    if isinstance(sd, dict):
        for sk in SLOT_KEYS:
            slot = sd.get(sk)
            if not isinstance(slot, dict):
                continue
            for dk in DELAY_KEYS:
                cell = slot.get(dk)
                if not isinstance(cell, dict):
                    continue
                ob = int(cell.get("our_entry_block") or 0)
                if ob > 0:
                    cell["rpc_unique_recipients_through_our_entry_block"] = get_count(
                        url, token, cb, ob, chunk
                    )
    return row


def load_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('{"summary'):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "token" in rec:
                rows.append(rec)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Enrich kol_monitor JSONL with unique Transfer recipient counts through entry blocks"
    )
    ap.add_argument("input_jsonl", help="kol_monitor JSONL")
    ap.add_argument("-o", "--output", required=True, help="Output JSONL path")
    ap.add_argument("--max-rows", type=int, default=0, help="Process only first N rows (0=all)")
    ap.add_argument(
        "--chunk-blocks",
        type=int,
        default=4000,
        help="Max block span per eth_getLogs call (split if provider limits)",
    )
    ap.add_argument("--sleep", type=float, default=0.0, help="Delay between tokens (rate limits)")
    args = ap.parse_args()

    url = rpc_url()
    rows = load_jsonl(args.input_jsonl)
    if args.max_rows and args.max_rows > 0:
        rows = rows[: args.max_rows]
    if not rows:
        print("No rows", file=sys.stderr)
        sys.exit(1)

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    for i, row in enumerate(rows):
        enrich_row(row, url, args.chunk_blocks)
        if args.sleep > 0:
            time.sleep(args.sleep)
        if (i + 1) % 50 == 0:
            print(f"... {i + 1}/{len(rows)} rows ({time.time() - t0:.0f}s)", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"Wrote {len(rows)} rows -> {args.output} ({len(_cache)} unique token×create×end ranges)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
