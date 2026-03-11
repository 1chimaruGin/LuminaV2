"""
Test script: Verify overlap spike detection on DEGOUSDT and ARIAUSDT.
Fetches recent 5m + 1m OHLCV data and scans for spikes matching scalper.pine logic.
"""
import asyncio
import ccxt.async_support as ccxt
from datetime import datetime, timedelta


async def scan_pair(ex, symbol: str, threshold_5m: float, threshold_1m: float, ma_window: int, days_back: int = 7):
    """Scan historical 5m candles for overlap spikes."""
    print(f"\n{'='*70}")
    print(f"  Scanning {symbol} — last {days_back} days")
    print(f"  Thresholds: 5m ≥ {threshold_5m}×  |  1m ≥ {threshold_1m}×  |  MA window: {ma_window}")
    print(f"{'='*70}")

    # Fetch 5m candles (max ~2000 per request)
    since_ms = int((datetime.utcnow() - timedelta(days=days_back)).timestamp() * 1000)
    all_5m = []
    fetch_since = since_ms
    while True:
        batch = await ex.fetch_ohlcv(symbol, "5m", since=fetch_since, limit=1500)
        if not batch:
            break
        all_5m.extend(batch)
        if len(batch) < 1500:
            break
        fetch_since = batch[-1][0] + 1
        await asyncio.sleep(0.5)

    print(f"  Fetched {len(all_5m)} 5m candles")

    # Step 1: Find all 5m candles where vol / prev_vol ≥ threshold_5m
    candidates_5m = []
    for i in range(1, len(all_5m)):
        cur = all_5m[i]
        prev = all_5m[i - 1]
        cur_vol = cur[5]
        prev_vol = prev[5]
        if prev_vol <= 0 or cur_vol <= 0:
            continue
        ratio = cur_vol / prev_vol
        if ratio >= threshold_5m:
            candidates_5m.append({
                "index": i,
                "ts": cur[0],
                "open": cur[1],
                "high": cur[2],
                "low": cur[3],
                "close": cur[4],
                "vol": cur_vol,
                "prev_vol": prev_vol,
                "ratio_5m": ratio,
            })

    print(f"  5m spikes ≥ {threshold_5m}×: {len(candidates_5m)}")
    if candidates_5m:
        print(f"  Top 5m spikes:")
        for c in sorted(candidates_5m, key=lambda x: -x["ratio_5m"])[:10]:
            dt = datetime.utcfromtimestamp(c["ts"] / 1000).strftime("%Y-%m-%d %H:%M")
            print(f"    {dt} UTC | {c['ratio_5m']:>8.1f}× | vol={c['vol']:.0f} prev={c['prev_vol']:.0f} | O={c['open']} C={c['close']}")

    # Step 2: For each 5m spike, fetch surrounding 1m data and check overlap
    overlap_spikes = []
    for c in candidates_5m:
        ts_5m = c["ts"]
        # Fetch 1m candles around this 5m candle
        fetch_from = ts_5m - (ma_window + 5) * 60_000
        ohlcv_1m = await ex.fetch_ohlcv(symbol, "1m", since=fetch_from, limit=ma_window + 10)
        await asyncio.sleep(0.3)

        if not ohlcv_1m or len(ohlcv_1m) < ma_window + 1:
            continue

        # Find the 1m candle closest to the 5m candle timestamp
        # The 5m candle at ts covers ts..ts+300000, so 1m candles at ts, ts+60k, ts+120k, ts+180k, ts+240k
        # Check each 1m candle within the 5m window
        for j in range(len(ohlcv_1m)):
            ts_1m = ohlcv_1m[j][0]
            # Must be within the 5m candle window
            if ts_1m < ts_5m or ts_1m >= ts_5m + 300_000:
                continue

            cur_vol_1m = ohlcv_1m[j][5]
            if cur_vol_1m <= 0:
                continue

            # Get previous ma_window 1m candle volumes (before this 1m candle)
            prev_vols = []
            for k in range(j - ma_window, j):
                if 0 <= k < len(ohlcv_1m) and ohlcv_1m[k][5] > 0:
                    prev_vols.append(ohlcv_1m[k][5])

            if len(prev_vols) < 3:
                continue

            ma_1m = sum(prev_vols) / len(prev_vols)
            if ma_1m <= 0:
                continue

            ratio_1m = cur_vol_1m / ma_1m

            if ratio_1m >= threshold_1m:
                overlap_spikes.append({
                    **c,
                    "ts_1m": ts_1m,
                    "vol_1m": cur_vol_1m,
                    "ma_1m": ma_1m,
                    "ratio_1m": ratio_1m,
                })
                break  # One overlap per 5m candle is enough

    print(f"\n  ✅ OVERLAP SPIKES (5m ≥ {threshold_5m}× AND 1m ≥ {threshold_1m}×): {len(overlap_spikes)}")
    for s in overlap_spikes:
        dt = datetime.utcfromtimestamp(s["ts"] / 1000).strftime("%Y-%m-%d %H:%M")
        bull = "BULL" if s["close"] >= s["open"] else "BEAR"
        print(f"    🚨 {dt} UTC | 5m={s['ratio_5m']:.0f}× 1m={s['ratio_1m']:.0f}× | {bull}")
        print(f"       5m vol: {s['vol']:.0f} (prev {s['prev_vol']:.0f})")
        print(f"       1m vol: {s['vol_1m']:.0f} (MA{ma_window}={s['ma_1m']:.0f})")
        print(f"       Price: O={s['open']} H={s['high']} L={s['low']} C={s['close']}")

    # Also show with lower thresholds
    if not overlap_spikes:
        print(f"\n  Trying lower thresholds to find signals...")
        for t5, t1 in [(50, 10), (20, 5), (10, 3)]:
            count = 0
            for c in candidates_5m if t5 >= threshold_5m else []:
                pass
            # Re-scan all 5m candles with lower threshold
            lower_5m = []
            for i in range(1, len(all_5m)):
                cur = all_5m[i]
                prev = all_5m[i - 1]
                if prev[5] <= 0 or cur[5] <= 0:
                    continue
                ratio = cur[5] / prev[5]
                if ratio >= t5:
                    lower_5m.append({"ts": cur[0], "ratio_5m": ratio, "vol": cur[5], "prev_vol": prev[5], "open": cur[1], "close": cur[4], "high": cur[2], "low": cur[3]})

            print(f"    With 5m≥{t5}×: {len(lower_5m)} candidates")
            if lower_5m:
                top = sorted(lower_5m, key=lambda x: -x["ratio_5m"])[:3]
                for t in top:
                    dt = datetime.utcfromtimestamp(t["ts"] / 1000).strftime("%Y-%m-%d %H:%M")
                    print(f"      {dt} | 5m={t['ratio_5m']:.1f}× vol={t['vol']:.0f}")

    return overlap_spikes


async def main():
    ex = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })

    try:
        pairs = ["DEGO/USDT:USDT", "ARIA/USDT:USDT"]
        thresholds = [
            (100, 20, 10),  # Original: 5m≥100×, 1m≥20×, MA10
            (50, 10, 10),   # Lower
            (20, 5, 10),    # Much lower
        ]

        for pair in pairs:
            for t5, t1, ma in thresholds:
                await scan_pair(ex, pair, t5, t1, ma, days_back=7)

    finally:
        await ex.close()


if __name__ == "__main__":
    asyncio.run(main())
