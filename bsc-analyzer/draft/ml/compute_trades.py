"""
Phase 2a: Compute per-token trade summaries from kol_swaps → kol_token_trades.
Also generates labels in token_labels based on KOL outcomes.

Usage:
    python ml/compute_trades.py

Reads from lumina.kol_swaps, computes PnL per token per wallet,
and inserts into lumina.kol_token_trades + lumina.token_labels.
"""

import subprocess
import json
import logging
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLICKHOUSE_BIN = str(PROJECT_ROOT / "clickhouse-bin")


def ch_query(query: str, fmt: str = "JSONEachRow") -> list[dict]:
    """Run a ClickHouse query and return results as list of dicts."""
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"{query} FORMAT {fmt}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.error(f"CH query error: {result.stderr[:500]}")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


def ch_insert(table: str, rows: list[dict]):
    """Insert rows into ClickHouse table via JSONEachRow format."""
    if not rows:
        return 0
    data = "\n".join(json.dumps(r) for r in rows) + "\n"
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"INSERT INTO {table} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, input=data, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        logger.error(f"CH insert error: {result.stderr[:500]}")
        return 0
    return len(rows)


def main():
    # Fetch all swaps ordered by wallet + token + timestamp
    logger.info("Fetching all swaps from ClickHouse...")
    swaps = ch_query("""
        SELECT 
            wallet_address, token_address, token_symbol, token_name,
            side, token_amount, quote_amount, usd_value, 
            block_timestamp, tx_hash, chain
        FROM lumina.kol_swaps 
        ORDER BY wallet_address, token_address, block_timestamp ASC
    """)
    logger.info(f"Loaded {len(swaps)} swaps")

    # Group by (wallet, token)
    wallet_token_swaps = defaultdict(list)
    for s in swaps:
        key = (s["wallet_address"], s["token_address"])
        wallet_token_swaps[key].append(s)

    logger.info(f"Processing {len(wallet_token_swaps)} wallet-token pairs...")

    # Compute per-token trade stats
    trade_rows = []
    for (wallet, token), token_swaps in wallet_token_swaps.items():
        buys = [s for s in token_swaps if s["side"] == "buy"]
        sells = [s for s in token_swaps if s["side"] == "sell"]

        if not buys and not sells:
            continue

        buy_count = len(buys)
        sell_count = len(sells)
        total_buy_usd = sum(s["usd_value"] for s in buys)
        total_sell_usd = sum(s["usd_value"] for s in sells)
        total_buy_tokens = sum(s["token_amount"] for s in buys)
        total_sell_tokens = sum(s["token_amount"] for s in sells)

        avg_buy_price = total_buy_usd / max(total_buy_tokens, 1e-18) if total_buy_tokens > 0 else 0
        avg_sell_price = total_sell_usd / max(total_sell_tokens, 1e-18) if total_sell_tokens > 0 else 0

        first_buy_ts = buys[0]["block_timestamp"] if buys else 0
        last_buy_ts = buys[-1]["block_timestamp"] if buys else 0
        first_sell_ts = sells[0]["block_timestamp"] if sells else 0
        last_sell_ts = sells[-1]["block_timestamp"] if sells else 0

        # Hold duration
        remaining_tokens = max(0, total_buy_tokens - total_sell_tokens)
        if sell_count > 0 and remaining_tokens < total_buy_tokens * 0.01:
            hold_sec = max(0, last_sell_ts - first_buy_ts) if first_buy_ts else 0
        else:
            hold_sec = 0  # Still holding or no sells

        # Realized PnL
        cost_basis_sold = avg_buy_price * total_sell_tokens if total_sell_tokens > 0 else 0
        realized_pnl = total_sell_usd - cost_basis_sold
        realized_pnl_pct = (realized_pnl / max(total_buy_usd, 0.01)) * 100 if total_buy_usd > 0.01 else 0

        # Exit type
        if sell_count == 0:
            exit_type = "none"
        elif sell_count == 1 and remaining_tokens < total_buy_tokens * 0.01:
            exit_type = "sell_all"
        elif sell_count > 1 and remaining_tokens < total_buy_tokens * 0.01:
            exit_type = "gradual_exit"
        elif sell_count > 0:
            exit_type = "partial_exit"
        else:
            exit_type = "unknown"

        first = token_swaps[0]
        trade_rows.append({
            "wallet_address": wallet,
            "token_address": token,
            "token_symbol": first["token_symbol"],
            "token_name": first["token_name"],
            "chain": first.get("chain", "BSC"),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_buy_usd": round(total_buy_usd, 4),
            "total_sell_usd": round(total_sell_usd, 4),
            "total_buy_tokens": total_buy_tokens,
            "total_sell_tokens": total_sell_tokens,
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "first_buy_ts": first_buy_ts,
            "last_buy_ts": last_buy_ts,
            "first_sell_ts": first_sell_ts,
            "last_sell_ts": last_sell_ts,
            "hold_duration_sec": hold_sec,
            "realized_pnl_usd": round(realized_pnl, 4),
            "realized_pnl_pct": round(realized_pnl_pct, 2),
            "exit_type": exit_type,
        })

    logger.info(f"Computed {len(trade_rows)} trade summaries")

    # Insert trade summaries in batches
    BATCH = 1000
    total_inserted = 0
    for i in range(0, len(trade_rows), BATCH):
        batch = trade_rows[i:i + BATCH]
        inserted = ch_insert("lumina.kol_token_trades", batch)
        total_inserted += inserted
        if (i + BATCH) % 5000 == 0:
            logger.info(f"  Inserted {total_inserted}/{len(trade_rows)} trade rows...")

    logger.info(f"Inserted {total_inserted} trade summaries into kol_token_trades")

    # ── Compute token labels ──
    # Group trades by token (across all KOLs)
    token_trades = defaultdict(list)
    for t in trade_rows:
        # Only include tokens with actual buy cost (not airdrops)
        if t["total_buy_usd"] > 0.01:
            token_trades[t["token_address"]].append(t)

    logger.info(f"\nComputing labels for {len(token_trades)} tokens (with buy cost > $0.01)...")

    label_rows = []
    label_dist = defaultdict(int)

    for token, trades in token_trades.items():
        kol_count = len(trades)
        pnl_pcts = [t["realized_pnl_pct"] for t in trades]
        hold_secs = [t["hold_duration_sec"] for t in trades if t["hold_duration_sec"] > 0]

        avg_pnl = sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0
        max_pnl = max(pnl_pcts) if pnl_pcts else 0
        min_pnl = min(pnl_pcts) if pnl_pcts else 0
        avg_hold = int(sum(hold_secs) / len(hold_secs)) if hold_secs else 0

        # Check for rug indicators
        all_zero_sells = all(t["total_sell_usd"] < 0.01 for t in trades)
        all_loss = all(t["realized_pnl_pct"] < -80 for t in trades if t["sell_count"] > 0)

        # Label assignment
        if all_zero_sells and all(t["sell_count"] == 0 for t in trades):
            label = "RUG"  # No one could sell = likely rug
        elif all_loss and min_pnl < -90:
            label = "RUG"
        elif avg_pnl > 100:
            label = "WIN_BIG"
        elif avg_pnl > 20:
            label = "WIN"
        elif avg_pnl > -20:
            label = "BREAKEVEN"
        else:
            label = "LOSS"

        is_profitable = 1 if label in ("WIN_BIG", "WIN") else 0
        label_dist[label] += 1

        label_rows.append({
            "token_address": token,
            "total_kol_buyers": kol_count,
            "avg_pnl_pct": round(avg_pnl, 2),
            "max_pnl_pct": round(max_pnl, 2),
            "min_pnl_pct": round(min_pnl, 2),
            "avg_hold_sec": avg_hold,
            "label": label,
            "is_profitable": is_profitable,
        })

    # Insert labels
    total_labels = 0
    for i in range(0, len(label_rows), BATCH):
        batch = label_rows[i:i + BATCH]
        inserted = ch_insert("lumina.token_labels", batch)
        total_labels += inserted

    logger.info(f"Inserted {total_labels} labels into token_labels")

    # Print distribution
    logger.info("\n" + "=" * 60)
    logger.info("LABEL DISTRIBUTION")
    logger.info("=" * 60)
    total = sum(label_dist.values())
    for label in ["WIN_BIG", "WIN", "BREAKEVEN", "LOSS", "RUG"]:
        count = label_dist.get(label, 0)
        pct = count / max(total, 1) * 100
        bar = "█" * int(pct / 2)
        logger.info(f"  {label:12s}: {count:6d} ({pct:5.1f}%) {bar}")
    logger.info(f"  {'TOTAL':12s}: {total:6d}")

    # Print summary stats
    profitable = sum(1 for r in label_rows if r["is_profitable"])
    logger.info(f"\n  Profitable tokens: {profitable}/{total} ({profitable/max(total,1)*100:.1f}%)")

    # Multi-KOL consensus tokens
    multi_kol = [r for r in label_rows if r["total_kol_buyers"] >= 2]
    multi_kol_profitable = [r for r in multi_kol if r["is_profitable"]]
    logger.info(f"  Multi-KOL tokens (≥2 buyers): {len(multi_kol)} ({len(multi_kol_profitable)} profitable)")

    logger.info(f"\n{'='*60}")
    logger.info("PHASE 2a COMPLETE")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
