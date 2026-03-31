#!/usr/bin/env python3
"""
Label live-captured tokens with outcome data (peak_mcap, graduated, peak_mult).

Reads kol_dataset_live.csv, fetches current/peak mcap for each token via RPC,
and writes labeled rows back.

Usage:
    python ml/label_live_data.py [--input backtest_results/kol_dataset_live.csv]
                                  [--output backtest_results/kol_dataset_live_labeled.csv]
                                  [--min-age-hours 4]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_rpc_url():
    url = os.environ.get("QUICK_NODE_BSC_RPC", "")
    if not url:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("QUICK_NODE_BSC_RPC="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return url


def eth_block_number(rpc_url: str) -> int:
    resp = requests.post(rpc_url, json={
        "jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []
    }, timeout=15)
    return int(resp.json()["result"], 16)


def eth_get_token_curve(rpc_url: str, token_addr: str) -> dict | None:
    """Fetch Four.meme token curve info via proxy manager getTokenInfo."""
    proxy = "0x5c952063c7fc8610FFDB798152D69F0B9550762b"
    # getTokenInfo(address) selector = 0xc45a0155
    data = "0xc45a0155" + token_addr[2:].lower().zfill(64)
    resp = requests.post(rpc_url, json={
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": proxy, "data": data}, "latest"]
    }, timeout=15)
    result = resp.json().get("result", "0x")
    if not result or result == "0x" or len(result) < 66:
        return None
    # Decode minimal: funds_bnb at offset 0x60 (word 3), max_funds at offset 0xa0 (word 5)
    try:
        hex_data = result[2:]
        if len(hex_data) < 256:
            return None
        funds_raw = int(hex_data[128:192], 16)
        max_raw = int(hex_data[192:256], 16)
        return {
            "funds_bnb": funds_raw / 1e18,
            "max_funds_bnb": max_raw / 1e18,
        }
    except (ValueError, IndexError):
        return None


def label_tokens(input_path: str, output_path: str, rpc_url: str,
                 min_age_hours: float, bnb_price: float):
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print("Empty CSV", file=sys.stderr)
            return
        rows = list(reader)

    print(f"Read {len(rows)} rows from {input_path}")

    current_block = eth_block_number(rpc_url)
    min_age_blocks = int(min_age_hours * 3600 / 3)

    labeled = 0
    for i, row in enumerate(rows):
        create_block = int(float(row.get("create_block", 0) or 0))
        if create_block <= 0:
            continue
        age_blocks = current_block - create_block
        if age_blocks < min_age_blocks:
            continue

        token = row.get("token_address", "")
        if not token:
            continue

        entry_mcap = float(row.get("entry_mcap_usd", 0) or 0)
        if entry_mcap <= 0:
            continue

        # Fetch current state
        curve = eth_get_token_curve(rpc_url, token)
        if curve is None:
            continue

        current_mcap_bnb = curve["funds_bnb"]
        current_mcap_usd = current_mcap_bnb * bnb_price
        graduated = curve["funds_bnb"] >= curve["max_funds_bnb"] * 0.99 if curve["max_funds_bnb"] > 0 else False

        # Use current mcap as proxy for peak (best we can do without historical tracking)
        peak_mcap = max(current_mcap_usd, entry_mcap)
        peak_mult = peak_mcap / entry_mcap if entry_mcap > 0 else 0

        row["peak_mcap_usd"] = f"{peak_mcap:.0f}"
        row["low_mcap_usd"] = f"{min(current_mcap_usd, entry_mcap):.0f}"
        row["graduated"] = str(graduated).lower()
        row["peak_mult_vs_slot2_entry"] = f"{peak_mult:.4f}"

        labeled += 1

        if (i + 1) % 10 == 0:
            print(f"  Processed {i+1}/{len(rows)}, labeled {labeled}", file=sys.stderr)

        time.sleep(0.1)  # Rate limit

    fieldnames = list(rows[0].keys()) if rows else []
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Labeled {labeled}/{len(rows)} tokens → {output_path}")


def main():
    p = argparse.ArgumentParser(description="Label live-captured tokens with outcomes")
    p.add_argument("--input", default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_live.csv"))
    p.add_argument("--output", default=str(PROJECT_ROOT / "backtest_results" / "kol_dataset_live_labeled.csv"))
    p.add_argument("--min-age-hours", type=float, default=4.0,
                    help="Only label tokens older than N hours")
    p.add_argument("--bnb-price", type=float, default=0.0,
                    help="BNB price in USD (0 = fetch from Binance)")
    args = p.parse_args()

    rpc_url = get_rpc_url()
    if not rpc_url:
        print("Set QUICK_NODE_BSC_RPC env or .env", file=sys.stderr)
        sys.exit(1)

    bnb_price = args.bnb_price
    if bnb_price <= 0:
        try:
            resp = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT", timeout=10)
            bnb_price = float(resp.json()["price"])
            print(f"BNB price: ${bnb_price:.2f}")
        except Exception as e:
            print(f"Cannot fetch BNB price: {e}. Use --bnb-price.", file=sys.stderr)
            sys.exit(1)

    label_tokens(args.input, args.output, rpc_url, args.min_age_hours, bnb_price)


if __name__ == "__main__":
    main()
