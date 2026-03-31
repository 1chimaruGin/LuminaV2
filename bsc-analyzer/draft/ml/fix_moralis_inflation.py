"""
Fix Moralis USD inflation in kol_swaps.

Problem: Moralis reports inflated native amounts for four.meme DEX swaps (~1000x).
This causes buy_usd and sell_usd to be massively inflated (e.g. $500K for a $500 buy).

Fix approach:
1. Identify inflated swaps (usd_value > $10K on meme tokens)
2. Estimate real USD from quote_amount * BNB price (~$650)
3. Cap usd_value at the estimated real value
4. Recompute kol_token_trades (trade summaries)
5. Recompute token_labels

Note: ClickHouse ReplacingMergeTree allows re-inserting rows with same key to update.
"""

import json
import subprocess
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLICKHOUSE_BIN = str(PROJECT_ROOT / "clickhouse-bin")

# Reasonable BNB price range for the data period
BNB_PRICE_USD = 650.0
# Max reasonable single swap USD for a meme token
MAX_SWAP_USD = 5000.0


def ch_query(query: str, fmt="JSONEachRow") -> list[dict]:
    cmd = [CLICKHOUSE_BIN, "client", "--query", f"{query} FORMAT {fmt}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.error(f"CH error: {result.stderr[:500]}")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


def ch_exec(query: str):
    cmd = [CLICKHOUSE_BIN, "client", "--query", query]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.error(f"CH exec error: {result.stderr[:500]}")
        return False
    return True


def main():
    logger.info("=" * 70)
    logger.info("FIX MORALIS USD INFLATION IN KOL SWAPS")
    logger.info("=" * 70)

    # Step 1: Count inflated swaps
    stats = ch_query("""
        SELECT
            countIf(usd_value > 5000) as inflated,
            countIf(usd_value > 10000) as very_inflated,
            countIf(usd_value > 100000) as extreme,
            count() as total
        FROM lumina.kol_swaps
    """)
    if stats:
        s = stats[0]
        logger.info(f"Inflated swaps (>$5K): {s['inflated']}")
        logger.info(f"Very inflated (>$10K): {s['very_inflated']}")
        logger.info(f"Extreme (>$100K):      {s['extreme']}")
        logger.info(f"Total swaps:           {s['total']}")

    # Step 2: Fix by re-inserting with capped usd_value
    # For swaps where usd_value > MAX_SWAP_USD, cap it
    # Use quote_amount * BNB_PRICE as the corrected value if it's lower
    logger.info(f"\nCapping swaps > ${MAX_SWAP_USD:.0f} USD...")

    # ClickHouse approach: INSERT INTO ... SELECT with corrected values
    # The ReplacingMergeTree will keep the latest version
    fix_query = f"""
        INSERT INTO lumina.kol_swaps
        SELECT
            wallet_address,
            token_address,
            token_symbol,
            token_name,
            token_logo,
            side,
            token_amount,
            quote_amount,
            -- Fix: cap usd_value at MAX_SWAP_USD or estimate from quote_amount
            if(usd_value > {MAX_SWAP_USD},
               least(
                   {MAX_SWAP_USD},
                   if(quote_amount > 0, quote_amount * {BNB_PRICE_USD}, usd_value)
               ),
               usd_value
            ) as usd_value,
            tx_hash,
            block_timestamp,
            chain,
            pair_label,
            now64(3) as ingested_at
        FROM lumina.kol_swaps
        WHERE usd_value > {MAX_SWAP_USD}
    """

    logger.info("Inserting corrected rows...")
    if not ch_exec(fix_query):
        logger.error("Failed to insert corrected rows!")
        return

    # Force merge to apply ReplacingMergeTree dedup
    logger.info("Optimizing table (merging duplicates)...")
    ch_exec("OPTIMIZE TABLE lumina.kol_swaps FINAL")

    # Verify fix
    verify = ch_query(f"""
        SELECT
            countIf(usd_value > {MAX_SWAP_USD}) as still_inflated,
            max(usd_value) as max_usd,
            quantile(0.99)(usd_value) as p99,
            count() as total
        FROM lumina.kol_swaps
    """)
    if verify:
        v = verify[0]
        logger.info(f"After fix: still > ${MAX_SWAP_USD:.0f}: {v['still_inflated']}, max: ${v['max_usd']:.0f}, p99: ${v['p99']:.0f}")

    # Step 3: Recompute kol_token_trades
    logger.info("\n" + "=" * 70)
    logger.info("RECOMPUTING TRADE SUMMARIES (kol_token_trades)")
    logger.info("=" * 70)

    # Truncate and rebuild
    ch_exec("TRUNCATE TABLE lumina.kol_token_trades")

    recompute_trades = """
        INSERT INTO lumina.kol_token_trades
        SELECT
            wallet_address,
            token_address,
            argMinIf(token_symbol, block_timestamp, token_symbol != '') as token_symbol,
            argMinIf(token_name, block_timestamp, token_name != '') as token_name,
            'BSC' as chain,
            countIf(side = 'buy') as buy_count,
            countIf(side = 'sell') as sell_count,
            sumIf(usd_value, side = 'buy') as total_buy_usd,
            sumIf(usd_value, side = 'sell') as total_sell_usd,
            sumIf(token_amount, side = 'buy') as total_buy_tokens,
            sumIf(token_amount, side = 'sell') as total_sell_tokens,
            -- avg buy/sell price
            if(sumIf(token_amount, side = 'buy') > 0,
               sumIf(usd_value, side = 'buy') / sumIf(token_amount, side = 'buy'), 0) as avg_buy_price,
            if(sumIf(token_amount, side = 'sell') > 0,
               sumIf(usd_value, side = 'sell') / sumIf(token_amount, side = 'sell'), 0) as avg_sell_price,
            minIf(block_timestamp, side = 'buy') as first_buy_ts,
            maxIf(block_timestamp, side = 'buy') as last_buy_ts,
            minIf(block_timestamp, side = 'sell') as first_sell_ts,
            maxIf(block_timestamp, side = 'sell') as last_sell_ts,
            -- hold duration: last sell - first buy
            if(countIf(side = 'sell') > 0 AND countIf(side = 'buy') > 0,
               maxIf(block_timestamp, side = 'sell') - minIf(block_timestamp, side = 'buy'), 0) as hold_duration_sec,
            -- realized PnL: total_sell - total_buy (simplified)
            sumIf(usd_value, side = 'sell') - sumIf(usd_value, side = 'buy') as realized_pnl_usd,
            -- realized PnL %
            if(sumIf(usd_value, side = 'buy') > 0,
               (sumIf(usd_value, side = 'sell') - sumIf(usd_value, side = 'buy')) / sumIf(usd_value, side = 'buy') * 100, 0) as realized_pnl_pct,
            '' as exit_type,
            now64(3) as updated_at
        FROM lumina.kol_swaps
        GROUP BY wallet_address, token_address
    """
    if ch_exec(recompute_trades):
        count = ch_query("SELECT count() as c FROM lumina.kol_token_trades")
        logger.info(f"Recomputed {count[0]['c']} trade summaries")
    else:
        logger.error("Failed to recompute trades!")
        return

    # Verify: check the previously inflated wallet
    wallet_check = ch_query("""
        SELECT
            sum(realized_pnl_usd) as total_pnl,
            count() as trades,
            countIf(realized_pnl_usd > 0) as profitable,
            max(abs(realized_pnl_usd)) as max_abs_pnl
        FROM lumina.kol_token_trades
        WHERE wallet_address = '0x8d5624fa29526c879a1ca7560961e4c5a08089ae'
    """)
    if wallet_check:
        w = wallet_check[0]
        logger.info(f"\nWallet 0x8d56... after fix:")
        logger.info(f"  Total PnL: ${w['total_pnl']:,.0f}")
        logger.info(f"  Trades: {w['trades']}, Profitable: {w['profitable']}")
        logger.info(f"  Max |PnL|: ${w['max_abs_pnl']:,.0f}")

    # Step 4: Recompute token_labels
    logger.info("\n" + "=" * 70)
    logger.info("RECOMPUTING TOKEN LABELS")
    logger.info("=" * 70)

    ch_exec("TRUNCATE TABLE lumina.token_labels")

    recompute_labels = """
        INSERT INTO lumina.token_labels
        SELECT
            token_address,
            argMin(token_symbol, updated_at) as token_symbol,
            count() as kol_count,
            avg(realized_pnl_pct) as avg_pnl_pct,
            max(realized_pnl_pct) as max_pnl_pct,
            min(realized_pnl_pct) as min_pnl_pct,
            -- is_profitable: majority of KOLs made money
            if(countIf(realized_pnl_usd > 0) > countIf(realized_pnl_usd <= 0), 1, 0) as is_profitable,
            -- label based on avg PnL %
            multiIf(
                avg(realized_pnl_pct) >= 200, 'WIN_BIG',
                avg(realized_pnl_pct) >= 20,  'WIN',
                avg(realized_pnl_pct) >= -20,  'BREAKEVEN',
                avg(realized_pnl_pct) >= -80,  'LOSS',
                'RUG'
            ) as label,
            now64(3) as updated_at
        FROM lumina.kol_token_trades
        WHERE buy_count > 0
        GROUP BY token_address
    """
    if ch_exec(recompute_labels):
        label_stats = ch_query("""
            SELECT label, count() as cnt, 
                   round(avg(avg_pnl_pct), 1) as mean_pnl,
                   round(countIf(is_profitable = 1) / count() * 100, 1) as profit_pct
            FROM lumina.token_labels
            GROUP BY label
            ORDER BY label
        """)
        logger.info("Label distribution after fix:")
        for ls in label_stats:
            logger.info(f"  {ls['label']:12s}  {ls['cnt']:6d} tokens  avg_pnl={ls['mean_pnl']:>8.1f}%  profitable={ls['profit_pct']}%")

        total = ch_query("SELECT count() as c FROM lumina.token_labels")
        logger.info(f"Total labeled tokens: {total[0]['c']}")

    # Step 5: Verify all wallets look reasonable now
    logger.info("\n" + "=" * 70)
    logger.info("ALL WALLET STATS (after fix)")
    logger.info("=" * 70)
    wallets = ch_query("""
        SELECT
            wallet_address,
            count() as trades,
            countIf(realized_pnl_usd > 0) as profitable,
            round(sum(realized_pnl_usd), 0) as total_pnl,
            round(sum(total_buy_usd), 0) as total_bought,
            round(countIf(realized_pnl_usd > 0) / count() * 100, 1) as win_pct
        FROM lumina.kol_token_trades
        GROUP BY wallet_address
        ORDER BY total_pnl DESC
    """)
    logger.info(f"{'Wallet':<45s} {'Trades':>7s} {'PnL':>12s} {'Bought':>12s} {'Win%':>7s}")
    logger.info("-" * 85)
    for w in wallets:
        logger.info(f"{w['wallet_address']:<45s} {w['trades']:7d} ${w['total_pnl']:>10,.0f} ${w['total_bought']:>10,.0f} {w['win_pct']:6.1f}%")


if __name__ == "__main__":
    main()
