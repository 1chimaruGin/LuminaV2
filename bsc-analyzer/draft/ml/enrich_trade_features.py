"""
Phase 3 v2: Enrich token_features with trade-derived features from kol_swaps.

These features are available for ALL tokens (not dependent on GoPlus):
- KOL entry patterns: buy size, number of buys, DCA behavior
- Token trading patterns: total volume, unique traders, buy/sell ratio
- Timing features: how quickly KOLs entered after token creation
- Exit patterns: hold duration, sell strategy

Usage:
    python ml/enrich_trade_features.py
"""

import json
import subprocess
import logging
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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


def main():
    logger.info("Computing trade-derived features for all tokens...")

    # ── 1. Per-token aggregate trading data from kol_swaps ──
    token_stats = ch_query("""
        SELECT
            token_address,
            
            -- KOL consensus
            uniq(wallet_address) as kol_buyer_count,
            
            -- Volume stats
            count() as total_swaps,
            countIf(side = 'buy') as total_buys,
            countIf(side = 'sell') as total_sells,
            sum(usd_value) as total_volume_usd,
            sumIf(usd_value, side = 'buy') as total_buy_volume_usd,
            sumIf(usd_value, side = 'sell') as total_sell_volume_usd,
            
            -- Average trade sizes
            avgIf(usd_value, side = 'buy' AND usd_value > 0) as avg_buy_usd,
            avgIf(usd_value, side = 'sell' AND usd_value > 0) as avg_sell_usd,
            maxIf(usd_value, side = 'buy') as max_buy_usd,
            
            -- Timing
            min(block_timestamp) as first_trade_ts,
            max(block_timestamp) as last_trade_ts,
            minIf(block_timestamp, side = 'buy') as first_buy_ts,
            maxIf(block_timestamp, side = 'buy') as last_buy_ts,
            minIf(block_timestamp, side = 'sell') as first_sell_ts,
            maxIf(block_timestamp, side = 'sell') as last_sell_ts
            
        FROM lumina.kol_swaps
        GROUP BY token_address
    """)
    logger.info(f"Loaded trade stats for {len(token_stats)} tokens")

    # ── 2. Per-wallet-token trade patterns ──
    wallet_token_stats = ch_query("""
        SELECT
            token_address,
            wallet_address,
            countIf(side = 'buy') as buys,
            countIf(side = 'sell') as sells,
            sumIf(usd_value, side = 'buy') as buy_usd,
            sumIf(usd_value, side = 'sell') as sell_usd,
            minIf(block_timestamp, side = 'buy') as first_buy,
            maxIf(block_timestamp, side = 'sell') as last_sell
        FROM lumina.kol_swaps
        GROUP BY token_address, wallet_address
    """)

    # Group by token
    wallet_trades_by_token = defaultdict(list)
    for wt in wallet_token_stats:
        wallet_trades_by_token[wt["token_address"]].append(wt)

    # ── 3. Compute derived features ──
    feature_updates = {}
    for ts in token_stats:
        token = ts["token_address"]
        wt_list = wallet_trades_by_token.get(token, [])

        total_buys = ts["total_buys"]
        total_sells = ts["total_sells"]
        total_swaps = ts["total_swaps"]
        kol_count = ts["kol_buyer_count"]

        # Buy/sell ratio (higher = more buying pressure = good)
        buy_sell_ratio = total_buys / max(total_sells, 1)

        # Volume sell ratio (how much was sold vs bought)
        sell_volume_ratio = ts["total_sell_volume_usd"] / max(ts["total_buy_volume_usd"], 0.01)

        # DCA pattern: KOLs who bought multiple times
        dca_count = sum(1 for wt in wt_list if wt["buys"] > 1)
        dca_ratio = dca_count / max(kol_count, 1)

        # All-sold pattern: KOLs who fully exited
        fully_exited = sum(1 for wt in wt_list if wt["sells"] > 0 and wt["sell_usd"] >= wt["buy_usd"] * 0.5)
        exit_ratio = fully_exited / max(kol_count, 1)

        # Hold duration stats
        hold_durations = []
        for wt in wt_list:
            if wt["last_sell"] > 0 and wt["first_buy"] > 0:
                dur = wt["last_sell"] - wt["first_buy"]
                if dur > 0:
                    hold_durations.append(dur)

        avg_hold_sec = sum(hold_durations) / max(len(hold_durations), 1) if hold_durations else 0
        max_hold_sec = max(hold_durations) if hold_durations else 0

        # Time between first and last trade (token lifespan from KOL perspective)
        token_active_sec = ts["last_trade_ts"] - ts["first_trade_ts"] if ts["last_trade_ts"] > ts["first_trade_ts"] else 0

        # Average buy size relative to total volume
        avg_buy = ts["avg_buy_usd"] or 0
        max_buy = ts["max_buy_usd"] or 0

        # Profit indicators from trade data
        # If sell_volume > buy_volume, KOLs made money
        net_profit_ratio = (ts["total_sell_volume_usd"] - ts["total_buy_volume_usd"]) / max(ts["total_buy_volume_usd"], 0.01)

        feature_updates[token] = {
            # Trade pattern features
            "total_swaps": total_swaps,
            "total_buys": total_buys,
            "total_sells": total_sells,
            "buy_sell_ratio": round(buy_sell_ratio, 4),
            "sell_volume_ratio": round(sell_volume_ratio, 4),
            "total_volume_usd": round(ts["total_volume_usd"], 2),
            "avg_buy_usd": round(avg_buy, 2),
            "max_buy_usd": round(max_buy, 2),

            # KOL behavior features
            "kol_buyer_count": kol_count,
            "dca_ratio": round(dca_ratio, 4),
            "exit_ratio": round(exit_ratio, 4),

            # Timing features
            "avg_hold_sec": int(avg_hold_sec),
            "max_hold_sec": int(max_hold_sec),
            "token_active_sec": int(token_active_sec),

            # Profit indicator
            "net_profit_ratio": round(net_profit_ratio, 4),
        }

    logger.info(f"Computed trade features for {len(feature_updates)} tokens")

    # ── 4. Save to JSON for training ──
    output_path = PROJECT_ROOT / "ml" / "trade_features.json"
    with open(output_path, "w") as f:
        json.dump(feature_updates, f)
    logger.info(f"Saved trade features to {output_path}")

    # Print summary stats
    logger.info("\n" + "=" * 60)
    logger.info("TRADE FEATURE STATS")
    logger.info("=" * 60)

    kol_counts = [v["kol_buyer_count"] for v in feature_updates.values()]
    volumes = [v["total_volume_usd"] for v in feature_updates.values()]
    holds = [v["avg_hold_sec"] for v in feature_updates.values() if v["avg_hold_sec"] > 0]

    import statistics
    logger.info(f"  Tokens: {len(feature_updates)}")
    logger.info(f"  KOL buyers: median={statistics.median(kol_counts)}, max={max(kol_counts)}")
    logger.info(f"  Volume USD: median=${statistics.median(volumes):.2f}, max=${max(volumes):.2f}")
    if holds:
        logger.info(f"  Hold time: median={statistics.median(holds)/3600:.1f}h, max={max(holds)/3600:.1f}h")

    # Count multi-KOL tokens
    multi = sum(1 for v in feature_updates.values() if v["kol_buyer_count"] >= 2)
    logger.info(f"  Multi-KOL (≥2): {multi}")


if __name__ == "__main__":
    main()
