#!/usr/bin/env python3
"""
Test: Verify Python spike detection matches scalper.pine EXACTLY.

KEY INSIGHT: Pine runs on the CHART timeframe. When the chart is 1m,
both ratios use 1m candle data:

  prevRatio = volume / volume[1]                     (cur 1m vol / prev 1m vol)
  maRatio   = volume / ta.sma(volume[1], ma_window)  (cur 1m vol / SMA of prev N 1m vols)
  isOverlap = prevRatio >= threshold AND maRatio >= threshold

  zone: high/low of the spike 1m candle, mid = (bodyHigh + bodyLow) / 2

Verification target: DEGO 2026-03-06 08:29 UTC → 5m:2603.3× 1m:516.5× on TradingView
"""
import asyncio
import ccxt.async_support as ccxt
from datetime import datetime, timedelta, timezone


def fmt_ts(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


async def test_pair(
    ex,
    symbol: str,
    threshold_prev: float,
    threshold_ma: float,
    ma_window: int = 10,
    days_back: int = 3,
):
    """
    Replicate scalper.pine overlap detection on historical 1m data.
    Both ratios computed from 1m candles — matches Pine on 1m chart.
    """
    print(f"\n{'═'*72}")
    print(f"  {symbol}  |  prev≥{threshold_prev}×  MA≥{threshold_ma}×  MA({ma_window})  |  {days_back}d")
    print(f"{'═'*72}")

    since = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp() * 1000)

    # ── Fetch ALL 1m candles ──
    all_1m = []
    cursor = since
    while True:
        batch = await ex.fetch_ohlcv(symbol, "1m", since=cursor, limit=1500)
        if not batch:
            break
        all_1m.extend(batch)
        if len(batch) < 1500:
            break
        cursor = batch[-1][0] + 1
        await asyncio.sleep(0.3)

    print(f"  Fetched {len(all_1m)} 1m candles")

    # ── Scan every 1m candle for overlap spike ──
    overlaps = []
    for i in range(ma_window + 1, len(all_1m)):
        c = all_1m[i]       # current 1m candle
        p = all_1m[i - 1]   # previous 1m candle = volume[1]
        vol_cur = c[5]
        vol_prev = p[5]

        if vol_cur <= 0 or vol_prev <= 0:
            continue

        # Pine: volume / volume[1]
        ratio_prev = vol_cur / vol_prev
        if ratio_prev < threshold_prev:
            continue

        # Pine: ta.sma(volume[1], ma_window)
        # volume[1]=all_1m[i-1], volume[2]=all_1m[i-2], ..., volume[ma_window]=all_1m[i-ma_window]
        sma_vols = [all_1m[i - k][5] for k in range(1, ma_window + 1)
                    if all_1m[i - k][5] > 0]
        if len(sma_vols) < max(3, ma_window // 2):
            continue

        ma_val = sum(sma_vols) / len(sma_vols)
        if ma_val <= 0:
            continue

        # Pine: volume / sma(volume[1], ma_window)
        ratio_ma = vol_cur / ma_val
        if ratio_ma < threshold_ma:
            continue

        # ── OVERLAP SPIKE ──
        body_high = max(c[1], c[4])
        body_low = min(c[1], c[4])
        overlaps.append({
            "ts": c[0],
            "o": c[1], "h": c[2], "l": c[3], "c": c[4],
            "vol": vol_cur,
            "vol_prev": vol_prev,
            "ratio_prev": ratio_prev,
            "ratio_ma": ratio_ma,
            "ma_val": ma_val,
            "zone_high": c[2],
            "zone_low": c[3],
            "zone_mid": (body_high + body_low) / 2,
            "bullish": c[4] >= c[1],
        })

    print(f"\n  ✅ OVERLAP SPIKES: {len(overlaps)}")
    print(f"  {'─'*68}")
    for o in overlaps:
        bull = "BULL ▲" if o["bullish"] else "BEAR ▼"
        print(f"  {fmt_ts(o['ts'])}  |  prev: {o['ratio_prev']:.1f}×  MA: {o['ratio_ma']:.1f}×  |  {bull}")
        print(f"    vol: {o['vol']:>12,.0f}  vol[1]: {o['vol_prev']:>12,.0f}  (vol/vol[1])")
        print(f"    vol: {o['vol']:>12,.0f}  MA{ma_window}:  {o['ma_val']:>12,.0f}  (vol/sma(vol[1],{ma_window}))")
        print(f"    O={o['o']}  H={o['h']}  L={o['l']}  C={o['c']}")
        print(f"    Zone: {o['zone_high']} / {o['zone_mid']} / {o['zone_low']}")
        print()

    return overlaps


async def main():
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "swap"}})

    pairs = ["DEGO/USDT:USDT", "ARIA/USDT:USDT"]

    # Test configs — both thresholds apply to 1m data
    configs = [
        ("Pine default (5×/5×)", 5.0, 5.0, 10),
        ("High (100×/20×)", 100.0, 20.0, 10),
    ]

    try:
        for pair in pairs:
            for label, tp, tm, ma in configs:
                print(f"\n  Config: {label}")
                await test_pair(ex, pair, tp, tm, ma, days_back=3)

        print(f"\n{'═'*72}")
        print("  VERIFY ON TRADINGVIEW:")
        print("  1. Open tradingview.com → DEGO/USDT Perp (or ARIA/USDT Perp)")
        print("  2. Set chart timeframe to 1m")
        print("  3. Add 'God of Scalper' indicator")
        print("  4. Multipliers: prev ≥ X, MA ≥ Y (same as above)")
        print("  5. Green ✕ markers should appear at the SAME timestamps")
        print(f"{'═'*72}")

    finally:
        await ex.close()


if __name__ == "__main__":
    asyncio.run(main())
