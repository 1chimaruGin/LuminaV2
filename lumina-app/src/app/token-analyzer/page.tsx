"use client";

import {
  useState,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  Suspense,
} from "react";
import { useSearchParams, useRouter } from "next/navigation";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import {
  analyzeToken,
  fetchInvestigateOHLCV,
  scanTokenActivity,
  fetchAIAnalysis,
  fetchWalletTokenTrades,
  type TokenAnalysis,
  type TokenPair,
  type InvestigateCandle,
  type InvestigateWallet,
  type CandleFlow,
  type RawSwap,
  type BigMove,
  type AIAnalysis,
  type WalletTokenTrade,
} from "@/lib/api";

/* ═══════════════════════════════════════════════════════════════
   CONSTANTS & HELPERS
   ═══════════════════════════════════════════════════════════════ */

const CHAINS = [
  { id: "solana", label: "SOL" },
  { id: "ethereum", label: "ETH" },
  { id: "bsc", label: "BSC" },
  { id: "base", label: "BASE" },
  { id: "arbitrum", label: "ARB" },
];
const TF_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1D", "1W", "1M"] as const;
const TF_SEC: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1D": 86400, "1W": 604800, "1M": 2592000 };

const fU = (v: number) => {
  if (Math.abs(v) >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (Math.abs(v) >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (Math.abs(v) >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  if (Math.abs(v) >= 1) return "$" + v.toFixed(2);
  if (Math.abs(v) > 0) return "$" + v.toFixed(6);
  return "$0";
};
const fP = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
const fN = (v: number) => v.toLocaleString("en-US");
const sh = (a: string) => (a.length > 16 ? a.slice(0, 6) + "…" + a.slice(-4) : a);

const TAG: Record<string, { color: string; bg: string; border: string }> = {
  whale: { color: "text-emerald-400", bg: "bg-emerald-500/8", border: "border-emerald-500/20" },
  smart: { color: "text-violet-400", bg: "bg-violet-500/8", border: "border-violet-500/20" },
  sell: { color: "text-rose-400", bg: "bg-rose-500/8", border: "border-rose-500/20" },
  bot: { color: "text-sky-400", bg: "bg-sky-500/8", border: "border-sky-500/20" },
  degen: { color: "text-amber-400", bg: "bg-amber-500/8", border: "border-amber-500/20" },
};

interface WhaleEvent {
  ts: number;
  wallet: string;
  label: string;
  tag: string;
  side: "buy" | "sell";
  usd: number;
  priceAtTime: number;
  pctChange: number;
}

/* ═══════════════════════════════════════════════════════════════
   TRADINGVIEW LIGHTWEIGHT CHART
   zero flickering — chart is imperatively managed via refs
   ═══════════════════════════════════════════════════════════════ */

function TVChart({
  candles,
  flowMap,
  symbol,
  wallets,
  whaleEvents,
  rawSwaps,
  bigMoves,
  onWalletClick,
  walletTrades,
  trackedWalletLabel,
}: {
  candles: InvestigateCandle[];
  flowMap: Record<string, CandleFlow>;
  symbol: string;
  wallets: InvestigateWallet[];
  whaleEvents: WhaleEvent[];
  rawSwaps: RawSwap[];
  bigMoves: BigMove[];
  onWalletClick: (addr: string) => void;
  walletTrades?: WalletTokenTrade[];
  trackedWalletLabel?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const whaleSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const markersRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const lcRef = useRef<any>(null);
  const roRef = useRef<ResizeObserver | null>(null);
  const [chartReady, setChartReady] = useState(false);

  // Tooltip state for interactive marker click
  type MarkerInfo = {
    type: "swap" | "big_move";
    side: "buy" | "sell";
    swaps?: RawSwap[];
    totalUsd?: number;
    pctMove?: number;
    volume?: number;
    ts: number;
  };
  const [tooltip, setTooltip] = useState<{ x: number; y: number; info: MarkerInfo } | null>(null);
  // Store marker data by candle ts for click lookup
  const markerDataRef = useRef<Map<number, MarkerInfo>>(new Map());

  // Create chart once — dynamic import to avoid SSR issues
  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;

    import("lightweight-charts").then((lc) => {
      if (disposed || !containerRef.current) return;

      const chart = lc.createChart(containerRef.current, {
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: "rgba(255,255,255,0.4)",
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: 10,
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.03)" },
          horzLines: { color: "rgba(255,255,255,0.03)" },
        },
        crosshair: {
          mode: lc.CrosshairMode.Normal,
          vertLine: { color: "rgba(139,92,246,0.4)", width: 1, style: 3, labelBackgroundColor: "#1a1a2e" },
          horzLine: { color: "rgba(139,92,246,0.4)", width: 1, style: 3, labelBackgroundColor: "#1a1a2e" },
        },
        rightPriceScale: {
          borderColor: "rgba(255,255,255,0.06)",
          scaleMargins: { top: 0.05, bottom: 0.25 },
        },
        timeScale: {
          borderColor: "rgba(255,255,255,0.06)",
          timeVisible: true,
          secondsVisible: false,
        },
        handleScroll: { vertTouchDrag: false },
      });

      const candleSeries = chart.addSeries(lc.CandlestickSeries, {
        upColor: "#10b981",
        downColor: "#ef4444",
        borderUpColor: "#10b981",
        borderDownColor: "#ef4444",
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
        priceFormat: {
          type: "custom",
          formatter: (price: number) => {
            if (price === 0) return "$0";
            const abs = Math.abs(price);
            if (abs >= 1000) return "$" + price.toFixed(2);
            if (abs >= 1) return "$" + price.toFixed(4);
            if (abs >= 0.001) return "$" + price.toFixed(6);
            if (abs >= 0.000001) return "$" + price.toFixed(9);
            return "$" + price.toExponential(3);
          },
          minMove: 0.000000001,
        },
      });

      const volSeries = chart.addSeries(lc.HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
      });
      chart.priceScale("vol").applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
      });

      const whaleSeries = chart.addSeries(lc.HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "whale",
      });
      chart.priceScale("whale").applyOptions({
        scaleMargins: { top: 0.72, bottom: 0.12 },
      });

      // Click handler for interactive markers
      chart.subscribeClick((param) => {
        if (!param.time) { setTooltip(null); return; }
        const ts = param.time as number;
        const info = markerDataRef.current.get(ts);
        if (info && param.point) {
          setTooltip({ x: param.point.x, y: param.point.y, info });
        } else {
          setTooltip(null);
        }
      });

      chartRef.current = chart;
      candleSeriesRef.current = candleSeries;
      volSeriesRef.current = volSeries;
      whaleSeriesRef.current = whaleSeries;
      lcRef.current = lc;

      const ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const { width, height } = entry.contentRect;
          chart.applyOptions({ width, height });
        }
      });
      ro.observe(containerRef.current!);
      roRef.current = ro;
      setChartReady(true);
    });

    return () => {
      disposed = true;
      setChartReady(false);
      roRef.current?.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
    };
  }, []);

  // Update data when candles/flowMap change — waits for chart to be ready
  useEffect(() => {
    if (!chartReady || !candleSeriesRef.current || candles.length === 0) return;
    setTooltip(null);

    // Deduplicate candles by timestamp (lightweight-charts requires unique asc times)
    const seen = new Map<number, typeof candles[0]>();
    for (const c of candles) { seen.set(c.ts, c); }
    const uniqueCandles = [...seen.values()].sort((a, b) => a.ts - b.ts);

    // Candle data
    const cData = uniqueCandles.map((c) => ({
      time: c.ts as number,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candleSeriesRef.current.setData(cData as any);

    // Volume data
    const vData = uniqueCandles.map((c) => ({
      time: c.ts as number,
      value: c.volume,
      color: c.close >= c.open ? "rgba(16,185,129,0.18)" : "rgba(239,68,68,0.18)",
    }));
    volSeriesRef.current?.setData(vData as any);

    // Whale flow data (net flow as histogram)
    const wData = uniqueCandles.map((c) => {
      const f = flowMap[String(c.ts)];
      if (!f) return { time: c.ts as number, value: 0, color: "transparent" };
      const net = f.buy_usd - f.sell_usd;
      const hasWhale = f.whale_buy + f.whale_sell > 0;
      let color: string;
      if (hasWhale) {
        color = net >= 0 ? "rgba(139,92,246,0.7)" : "rgba(236,72,153,0.7)";
      } else {
        color = net >= 0 ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)";
      }
      return { time: c.ts as number, value: Math.abs(net), color };
    });
    whaleSeriesRef.current?.setData(wData as any);

    // ── Markers: clean circles + diamonds, NO text, interactive ──
    if (markersRef.current) {
      markersRef.current.setMarkers([]);
    }

    const candleTsList = uniqueCandles.map((c) => c.ts).sort((a, b) => a - b);
    const half = candleTsList.length > 1 ? Math.floor((candleTsList[1] - candleTsList[0]) / 2) : 150;

    const snapToCandle = (ts: number) => {
      let lo = 0, hi = candleTsList.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (candleTsList[mid] < ts - half) lo = mid + 1; else hi = mid;
      }
      if (lo > 0 && Math.abs(candleTsList[lo - 1] - ts) < Math.abs(candleTsList[lo] - ts)) lo--;
      return candleTsList[lo];
    };

    const markerByCandle = new Map<number, { time: number; position: string; color: string; shape: string; text: string }>();
    const markerData = new Map<number, MarkerInfo>();

    // 1) Big-move markers (covers entire chart)
    for (const bm of bigMoves) {
      const ct = snapToCandle(bm.ts);
      if (!markerByCandle.has(ct)) {
        markerByCandle.set(ct, {
          time: ct,
          position: bm.side === "buy" ? "belowBar" : "aboveBar",
          color: bm.side === "buy" ? "#facc15" : "#f97316",
          shape: "diamond",
          text: "",
        });
        markerData.set(ct, { type: "big_move", side: bm.side, pctMove: bm.pct_move, volume: bm.volume, ts: ct });
      }
    }

    // 2) Swap markers override big-moves
    const swapsByCandle = new Map<number, RawSwap[]>();
    for (const s of rawSwaps) {
      if (!s.ts || s.usd <= 0) continue;
      const ct = snapToCandle(s.ts);
      if (!swapsByCandle.has(ct)) swapsByCandle.set(ct, []);
      swapsByCandle.get(ct)!.push(s);
    }

    // Dynamic thresholds for swap markers based on actual data
    const candleTotals = [...swapsByCandle.values()].map(ss => ss.reduce((a, s) => a + s.usd, 0)).filter(v => v > 0).sort((a, b) => a - b);
    const swapNoiseFloor = candleTotals.length >= 5 ? candleTotals[Math.floor(candleTotals.length * 0.3)] : 0; // bottom 30% is noise
    const swapWhaleFloor = candleTotals.length >= 5 ? candleTotals[Math.floor(candleTotals.length * 0.85)] : Infinity; // top 15% is whale-level
    const allSwapSizes = rawSwaps.map(s => s.usd).filter(v => v > 0).sort((a, b) => a - b);
    const swapTxFloor = allSwapSizes.length >= 5 ? allSwapSizes[Math.floor(allSwapSizes.length * 0.4)] : 0; // show top 60% in tooltip

    for (const [ct, swaps] of swapsByCandle) {
      const buyUsd = swaps.filter((s) => s.side === "buy").reduce((a, s) => a + s.usd, 0);
      const sellUsd = swaps.filter((s) => s.side === "sell").reduce((a, s) => a + s.usd, 0);
      const totalCandle = buyUsd + sellUsd;
      if (totalCandle < swapNoiseFloor) continue; // skip noise
      const isBuy = buyUsd >= sellUsd;
      const totalUsd = isBuy ? buyUsd : sellUsd;
      const side = isBuy ? "buy" as const : "sell" as const;

      markerByCandle.set(ct, {
        time: ct,
        position: isBuy ? "belowBar" : "aboveBar",
        color: isBuy
          ? (totalUsd >= swapWhaleFloor ? "#00f0ff" : "#10b981")
          : (totalUsd >= swapWhaleFloor ? "#f472b6" : "#ef4444"),
        shape: "circle",
        text: "",
      });
      markerData.set(ct, { type: "swap", side, swaps: swaps.filter(s => s.usd >= swapTxFloor), totalUsd, ts: ct });
    }

    // 3) Tracked wallet trade markers — gold arrows, always shown on top
    if (walletTrades && walletTrades.length > 0) {
      for (const wt of walletTrades) {
        if (!wt.ts || wt.usd <= 0) continue;
        const ct = snapToCandle(wt.ts);
        // Wallet trades get a unique key to avoid overwriting other markers on same candle
        // We use a separate map pass so they don't conflict
        const existing = markerByCandle.get(ct);
        // Only override if wallet trade is significant or no existing marker
        if (!existing || wt.usd > 50) {
          markerByCandle.set(ct, {
            time: ct,
            position: wt.side === "buy" ? "belowBar" : "aboveBar",
            color: wt.side === "buy" ? "#fbbf24" : "#f472b6",
            shape: wt.side === "buy" ? "arrowUp" : "arrowDown",
            text: "",
          });
          markerData.set(ct, {
            type: "swap",
            side: wt.side,
            swaps: [{ wallet: trackedWalletLabel || "Tracked", side: wt.side, usd: wt.usd, ts: wt.ts, tx: wt.tx_hash }],
            totalUsd: wt.usd,
            ts: ct,
          });
        }
      }
    }

    markerDataRef.current = markerData;
    const markers = [...markerByCandle.values()].sort((a, b) => a.time - b.time);

    if (markers.length > 0 && candleSeriesRef.current && lcRef.current) {
      markersRef.current = lcRef.current.createSeriesMarkers(candleSeriesRef.current, markers);
    }

    chartRef.current?.timeScale().fitContent();
  }, [candles, flowMap, wallets, whaleEvents, rawSwaps, bigMoves, chartReady, walletTrades, trackedWalletLabel]);

  // Build address→label lookup for tooltip
  const addrLabel: Record<string, string> = {};
  for (const w of wallets) addrLabel[w.address] = w.label;

  return (
    <div className="relative" onClick={() => setTooltip(null)}>
      <div ref={containerRef} className="w-full" style={{ height: 480 }} />

      {/* Chart legend */}
      <div className="absolute top-2 left-3 flex items-center gap-3 pointer-events-none z-10 flex-wrap">
        <span className="font-display text-[11px] font-bold text-white/50">{symbol}/USD</span>
        <span className="flex items-center gap-1 text-[11px] font-mono text-[#00f0ff]/80">
          <span className="inline-block w-2 h-2 rounded-full bg-[#00f0ff]" /> Buy
        </span>
        <span className="flex items-center gap-1 text-[11px] font-mono text-[#f472b6]/80">
          <span className="inline-block w-2 h-2 rounded-full bg-[#f472b6]" /> Sell
        </span>
        <span className="flex items-center gap-1 text-[11px] font-mono text-[#facc15]/80">
          <span className="inline-block w-2 h-2 rotate-45 bg-[#facc15]" /> Pump
        </span>
        <span className="flex items-center gap-1 text-[11px] font-mono text-[#f97316]/80">
          <span className="inline-block w-2 h-2 rotate-45 bg-[#f97316]" /> Dump
        </span>
        {walletTrades && walletTrades.length > 0 && (
          <>
            <span className="flex items-center gap-1 text-[11px] font-mono text-[#fbbf24]/80">
              <span className="material-symbols-outlined text-[10px]">arrow_upward</span> {trackedWalletLabel || "Tracked"} Buy
            </span>
            <span className="flex items-center gap-1 text-[11px] font-mono text-[#f472b6]/80">
              <span className="material-symbols-outlined text-[10px]">arrow_downward</span> {trackedWalletLabel || "Tracked"} Sell
            </span>
          </>
        )}
        <span className="text-[11px] font-mono text-white/50">click marker for details</span>
      </div>

      {/* Interactive tooltip panel */}
      {tooltip && (
        <div
          className="absolute z-50 pointer-events-auto"
          style={{
            left: Math.min(tooltip.x, (containerRef.current?.clientWidth || 600) - 260),
            top: Math.max(8, tooltip.y - 120),
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="bg-[#0d0d1a]/95 border border-white/10 rounded-lg shadow-xl backdrop-blur-md p-3 min-w-[230px] max-w-[280px]">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] text-white/60 font-mono">
                {new Date(tooltip.info.ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
              </span>
              <button onClick={() => setTooltip(null)} className="text-white/50 hover:text-white cursor-pointer">
                <span className="material-symbols-outlined text-[14px]">close</span>
              </button>
            </div>

            {tooltip.info.type === "big_move" && (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className={`inline-block w-2.5 h-2.5 rotate-45 ${tooltip.info.side === "buy" ? "bg-[#facc15]" : "bg-[#f97316]"}`} />
                  <span className="text-white text-xs font-bold">
                    {tooltip.info.side === "buy" ? "Big Pump" : "Big Dump"}
                  </span>
                  <span className={`text-xs font-bold font-mono ${tooltip.info.side === "buy" ? "text-emerald-400" : "text-rose-400"}`}>
                    {tooltip.info.side === "buy" ? "+" : "-"}{tooltip.info.pctMove?.toFixed(2)}%
                  </span>
                </div>
                {tooltip.info.volume ? (
                  <span className="text-[11px] text-white/60 font-mono">Vol: {fU(tooltip.info.volume)}</span>
                ) : null}
              </div>
            )}

            {tooltip.info.type === "swap" && tooltip.info.swaps && (
              <div className="space-y-1.5">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-bold ${tooltip.info.side === "buy" ? "text-[#00f0ff]" : "text-[#f472b6]"}`}>
                    {tooltip.info.side === "buy" ? "Net Buy" : "Net Sell"}
                  </span>
                  <span className="text-white text-xs font-bold font-mono">{fU(tooltip.info.totalUsd || 0)}</span>
                  <span className="text-[11px] text-white/50">{tooltip.info.swaps.length} txns</span>
                </div>
                <div className="max-h-[140px] overflow-y-auto space-y-1 pr-1">
                  {tooltip.info.swaps
                    .sort((a, b) => b.usd - a.usd)
                    .slice(0, 10)
                    .map((s, i) => (
                    <div key={i} className="flex items-center gap-2 text-[11px]">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${s.side === "buy" ? "bg-[#00f0ff]" : "bg-[#f472b6]"}`} />
                      <span className="text-white/60 font-mono truncate w-[80px] hover:text-violet-400 cursor-pointer transition-colors" title={s.wallet} onClick={() => onWalletClick(s.wallet)}>
                        {addrLabel[s.wallet] || sh(s.wallet)}
                      </span>
                      <span className={`font-bold font-mono ${s.side === "buy" ? "text-emerald-400" : "text-rose-400"}`}>
                        {fU(s.usd)}
                      </span>
                      {s.tx && (
                        <span className="text-white/50 font-mono text-[11px]">{s.tx.slice(0, 8)}</span>
                      )}
                    </div>
                  ))}
                  {tooltip.info.swaps.length > 10 && (
                    <span className="text-[11px] text-white/50">+{tooltip.info.swaps.length - 10} more</span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   WHALE ACTIVITY TIMELINE
   Shows exactly when each whale traded, mapped to candle times
   ═══════════════════════════════════════════════════════════════ */

function buildWhaleEvents(
  wallets: InvestigateWallet[],
  candles: InvestigateCandle[],
  flowMap: Record<string, CandleFlow>
): WhaleEvent[] {
  if (candles.length === 0) return [];
  const firstPrice = candles[0].open;
  // Build candle lookup by ts
  const candleByTs: Record<number, InvestigateCandle> = {};
  for (const c of candles) candleByTs[c.ts] = c;

  // Dynamic thresholds based on actual wallet data
  const allVols = wallets.map(w => w.total_volume).filter(v => v > 0).sort((a, b) => a - b);
  const allTxVals = wallets.flatMap(w => w.txns.map(tx => tx.usd_value)).filter(v => v > 0).sort((a, b) => a - b);
  const volThreshold = allVols.length >= 3 ? allVols[Math.floor(allVols.length * 0.5)] : 0; // top 50% of wallets
  const txThreshold = allTxVals.length >= 3 ? allTxVals[Math.floor(allTxVals.length * 0.6)] : 0; // top 40% of txns

  const events: WhaleEvent[] = [];
  // Get whale events from per-candle flow + wallet txns
  for (const w of wallets) {
    if (w.tag !== "whale" && w.tag !== "smart" && w.tag !== "sell" && w.total_volume < volThreshold) continue;
    for (const tx of w.txns) {
      if (!tx.timestamp || tx.usd_value < txThreshold) continue;
      // Find which candle this tx belongs to
      let bestTs = candles[0].ts;
      let bestDist = Infinity;
      for (const c of candles) {
        const dist = Math.abs(tx.timestamp - c.ts);
        if (dist < bestDist) { bestDist = dist; bestTs = c.ts; }
      }
      const candle = candleByTs[bestTs];
      const pctChange = candle ? ((candle.close - firstPrice) / firstPrice) * 100 : 0;
      events.push({
        ts: tx.timestamp,
        wallet: w.address,
        label: w.label,
        tag: w.tag,
        side: tx.side,
        usd: tx.usd_value,
        priceAtTime: candle?.close || 0,
        pctChange,
      });
    }
  }
  // Sort by time
  events.sort((a, b) => a.ts - b.ts);
  return events;
}

function WhaleTimeline({ events, onWalletClick }: { events: WhaleEvent[]; onWalletClick: (addr: string) => void }) {
  const [hoveredBucket, setHoveredBucket] = useState<number | null>(null);

  if (events.length === 0) return null;

  // Group by time buckets (1-minute) to avoid overlapping
  const buckets: Map<number, WhaleEvent[]> = new Map();
  for (const e of events) {
    const bucket = Math.floor(e.ts / 60) * 60;
    if (!buckets.has(bucket)) buckets.set(bucket, []);
    buckets.get(bucket)!.push(e);
  }

  const sorted = [...buckets.entries()].sort((a, b) => a[0] - b[0]);

  return (
    <div className="space-y-0.5 max-h-[320px] overflow-y-auto">
      {sorted.map(([bucket, evts]) => {
        const time = new Date(bucket * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const netUsd = evts.reduce((s, e) => s + (e.side === "buy" ? e.usd : -e.usd), 0);
        const isHovered = hoveredBucket === bucket;
        return (
          <div
            key={bucket}
            className={`flex items-start gap-2.5 px-2.5 py-2 rounded-lg transition-all cursor-pointer ${isHovered ? "bg-white/[0.04] scale-[1.01]" : "hover:bg-white/[0.02]"}`}
            onMouseEnter={() => setHoveredBucket(bucket)}
            onMouseLeave={() => setHoveredBucket(null)}
          >
            {/* Time */}
            <span className="font-mono text-[11px] text-white/50 w-14 shrink-0 pt-0.5">{time}</span>
            {/* Connector */}
            <div className="flex flex-col items-center shrink-0 pt-1">
              <div className={`w-2.5 h-2.5 rounded-full border ${netUsd >= 0 ? "bg-emerald-500 border-emerald-400/30" : "bg-rose-500 border-rose-400/30"} ${isHovered ? "scale-125" : ""} transition-transform`} />
              <div className="w-px h-full bg-white/[0.06]" />
            </div>
            {/* Events */}
            <div className="flex-1 space-y-1">
              {evts.map((e, i) => {
                const tag = TAG[e.tag] || TAG.degen;
                return (
                  <div key={i} className="flex items-center gap-2 flex-wrap group/wt">
                    <span className={`font-display text-[11px] font-bold px-1.5 py-0.5 rounded-full border cursor-pointer hover:brightness-125 ${tag.bg} ${tag.color} ${tag.border}`} onClick={() => onWalletClick(e.wallet)} title="Analyze wallet">{e.label}</span>
                    <button onClick={() => navigator.clipboard?.writeText(e.wallet)} className="material-symbols-outlined text-[11px] text-white/10 hover:text-neon-cyan cursor-pointer opacity-0 group-hover/wt:opacity-100 transition-all" title="Copy address">content_copy</button>
                    <span className={`font-mono text-[11px] font-semibold ${e.side === "buy" ? "text-emerald-400" : "text-rose-400"}`}>
                      {e.side === "buy" ? "▲ BUY" : "▼ SELL"} {fU(e.usd)}
                    </span>
                    {e.priceAtTime > 0 && (
                      <span className="font-mono text-[11px] text-white/50">
                        @ {e.priceAtTime < 0.01 ? "$" + e.priceAtTime.toExponential(2) : fU(e.priceAtTime)}
                      </span>
                    )}
                    <span className={`font-mono text-[11px] ${e.pctChange >= 0 ? "text-emerald-400/50" : "text-rose-400/50"}`}>
                      {e.pctChange >= 0 ? "+" : ""}{e.pctChange.toFixed(1)}%
                    </span>
                    <span className="material-symbols-outlined text-[11px] text-white/10 group-hover/wt:text-violet-400 cursor-pointer opacity-0 group-hover/wt:opacity-100 transition-all" onClick={() => onWalletClick(e.wallet)} title="Analyze wallet">open_in_new</span>
                  </div>
                );
              })}
            </div>
            {/* Net */}
            <span className={`font-mono text-[12px] font-bold shrink-0 ${netUsd >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              {netUsd >= 0 ? "+" : ""}{fU(netUsd)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   WHALE BUBBLE MAP — bubblemaps.io inspired
   Circles sized by volume, colored by tag, positioned by role
   ═══════════════════════════════════════════════════════════════ */

function WhaleBubbleMap({ wallets, onWalletClick }: { wallets: InvestigateWallet[]; onWalletClick: (addr: string) => void }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const svgW = 420;
  const svgH = 320;
  const centerX = svgW / 2;
  const centerY = svgH / 2;

  if (wallets.length === 0) return null;

  const maxVol = Math.max(...wallets.map((w) => w.total_volume), 1);

  // Position wallets in a spiral/radial layout
  // Buyers on left, sellers on right, size by volume
  const positioned = wallets.slice(0, 20).map((w, i) => {
    const angle = (i / Math.min(wallets.length, 20)) * Math.PI * 2 - Math.PI / 2;
    const isBuyer = w.net_usd >= 0;
    const biasX = isBuyer ? -35 : 35;
    const radius = 65 + i * 6;
    const x = centerX + Math.cos(angle) * radius + biasX;
    const y = centerY + Math.sin(angle) * radius;
    const r = Math.max(10, Math.sqrt(w.total_volume / maxVol) * 44);
    return { ...w, x, y, r, idx: i };
  });

  const tagColor: Record<string, string> = {
    whale: "#10b981",
    smart: "#8b5cf6",
    sell: "#f43f5e",
    bot: "#38bdf8",
    degen: "#f59e0b",
  };

  const hoveredW = hovered !== null ? positioned[hovered] : null;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${svgW} ${svgH}`} className="w-full select-none" style={{ maxHeight: 320 }}>
        {/* Center label */}
        <text x={centerX} y={centerY - 10} textAnchor="middle" fill="rgba(255,255,255,0.1)" fontSize="10" fontFamily="'Space Grotesk', sans-serif" fontWeight="bold">TOKEN</text>
        <circle cx={centerX} cy={centerY} r="5" fill="rgba(0,240,255,0.3)" stroke="rgba(0,240,255,0.3)" strokeWidth="1.5" />

        {/* Connection lines to center */}
        {positioned.map((w, i) => (
          <line key={`l${i}`} x1={centerX} y1={centerY} x2={w.x} y2={w.y} stroke={hovered === i ? "rgba(255,255,255,0.1)" : "rgba(255,255,255,0.03)"} strokeWidth={hovered === i ? "1" : "0.5"} />
        ))}

        {/* Bubbles */}
        {positioned.map((w, i) => {
          const color = tagColor[w.tag] || tagColor.degen;
          const isBuy = w.net_usd >= 0;
          const isActive = hovered === i;
          const scale = isActive ? 1.15 : 1;
          return (
            <g
              key={i}
              style={{ transform: `scale(${scale})`, transformOrigin: `${w.x}px ${w.y}px`, transition: "transform 0.15s ease" }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              className="cursor-pointer"
              onClick={() => onWalletClick(w.address)}
            >
              {/* Glow ring */}
              <circle cx={w.x} cy={w.y} r={w.r + 3} fill="none" stroke={color} strokeWidth={isActive ? "1.5" : "0.5"} opacity={isActive ? 0.5 : 0.15} />
              {/* Main bubble */}
              <circle cx={w.x} cy={w.y} r={w.r} fill={color} opacity={isActive ? 0.3 : 0.15} stroke={color} strokeWidth={isActive ? "1.5" : "1"} />
              {/* Direction indicator */}
              <circle cx={w.x} cy={w.y} r={Math.max(w.r * 0.3, 4)} fill={isBuy ? "#10b981" : "#f43f5e"} opacity={isActive ? 0.9 : 0.6} />
              {/* Label */}
              {w.r > 12 && (
                <>
                  <text x={w.x} y={w.y - w.r - 5} textAnchor="middle" fill={isActive ? "rgba(255,255,255,0.8)" : "rgba(255,255,255,0.5)"} fontSize="9" fontFamily="'Space Grotesk', sans-serif" fontWeight="bold">
                    {w.label}
                  </text>
                  <text x={w.x} y={w.y + w.r + 10} textAnchor="middle" fill={isActive ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.25)"} fontSize="8" fontFamily="'IBM Plex Mono', monospace">
                    {fU(w.total_volume)}
                  </text>
                </>
              )}
            </g>
          );
        })}

        {/* Legend */}
        <g transform={`translate(8, ${svgH - 60})`}>
          <rect x="-4" y="-4" width="85" height="55" rx="4" fill="rgba(10,10,18,0.8)" stroke="rgba(255,255,255,0.06)" />
          {Object.entries(tagColor).slice(0, 5).map(([tag, color], i) => (
            <g key={tag} transform={`translate(4, ${i * 10 + 2})`}>
              <circle cx="4" cy="4" r="3" fill={color} opacity="0.6" />
              <text x="14" y="7" fill="rgba(255,255,255,0.4)" fontSize="8" fontFamily="'Space Grotesk', sans-serif">{tag}</text>
            </g>
          ))}
        </g>

        {/* Buy/Sell sides */}
        <text x="32" y="16" fill="rgba(16,185,129,0.25)" fontSize="10" fontFamily="'Space Grotesk', sans-serif" fontWeight="bold">← BUYERS</text>
        <text x={svgW - 32} y="16" textAnchor="end" fill="rgba(244,63,94,0.25)" fontSize="10" fontFamily="'Space Grotesk', sans-serif" fontWeight="bold">SELLERS →</text>
      </svg>

      {/* Hover tooltip */}
      {hoveredW && (
        <div className="absolute bottom-2 left-2 right-2 bg-obsidian/95 backdrop-blur-md border border-white/10 rounded-lg p-2.5 z-10 pointer-events-none">
          <div className="flex items-center gap-2 mb-1">
            <span className={`font-display text-[11px] font-bold px-2 py-0.5 rounded-full border ${(TAG[hoveredW.tag] || TAG.degen).bg} ${(TAG[hoveredW.tag] || TAG.degen).color} ${(TAG[hoveredW.tag] || TAG.degen).border}`}>
              {hoveredW.label}
            </span>
            <span className="font-mono text-[11px] text-white/60">{sh(hoveredW.address)}</span>
          </div>
          <div className="flex items-center gap-3 font-mono text-[11px]">
            <span className="text-emerald-400">Buy {fU(hoveredW.buy_usd)}</span>
            <span className="text-rose-400">Sell {fU(hoveredW.sell_usd)}</span>
            <span className={`font-bold ${hoveredW.net_usd >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
              Net {hoveredW.net_usd >= 0 ? "+" : ""}{fU(hoveredW.net_usd)}
            </span>
            <span className="text-white/50">{hoveredW.buys}B / {hoveredW.sells}S</span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   WHALE INSIGHT ENGINE
   Determines which cluster caused pump/dump + long/short signal
   ═══════════════════════════════════════════════════════════════ */

interface WhaleInsight {
  direction: "long" | "short" | "neutral";
  confidence: number;
  reason: string;
  keyWallets: { address: string; label: string; tag: string; net: number }[];
  clusterAction: string;
  priceImpact: string;
}

function computeWhaleInsight(
  wallets: InvestigateWallet[],
  candles: InvestigateCandle[],
  flowMap: Record<string, CandleFlow>
): WhaleInsight {
  if (wallets.length === 0 || candles.length === 0) {
    return {
      direction: "neutral",
      confidence: 0,
      reason: "No whale data available",
      keyWallets: [],
      clusterAction: "—",
      priceImpact: "—",
    };
  }

  // Net flow from all wallets
  const totalBuy = wallets.reduce((s, w) => s + w.buy_usd, 0);
  const totalSell = wallets.reduce((s, w) => s + w.sell_usd, 0);
  const netFlow = totalBuy - totalSell;

  // Price change over the candle window
  const firstPrice = candles[0].open;
  const lastPrice = candles[candles.length - 1].close;
  const priceChangePct = ((lastPrice - firstPrice) / firstPrice) * 100;

  // Whale-specific flow
  const whaleWallets = wallets.filter((w) => w.tag === "whale" || w.tag === "smart");
  const whaleBuy = whaleWallets.reduce((s, w) => s + w.buy_usd, 0);
  const whaleSell = whaleWallets.reduce((s, w) => s + w.sell_usd, 0);
  const whaleNet = whaleBuy - whaleSell;

  // Recency — check last 1/4 of candles for recent whale activity
  const recentCandles = candles.slice(-Math.ceil(candles.length / 4));
  let recentWhaleNet = 0;
  for (const c of recentCandles) {
    const f = flowMap[String(c.ts)];
    if (f && (f.whale_buy + f.whale_sell) > 0) {
      recentWhaleNet += f.buy_usd - f.sell_usd;
    }
  }

  // Sort key wallets by absolute impact
  const keyWallets = [...wallets]
    .sort((a, b) => b.abs_impact - a.abs_impact)
    .slice(0, 5)
    .map((w) => ({ address: w.address, label: w.label, tag: w.tag, net: w.net_usd }));

  // Determine signal
  let direction: "long" | "short" | "neutral" = "neutral";
  let confidence = 0;
  let reason = "";
  let clusterAction = "";

  const buyPressure = totalBuy / Math.max(totalBuy + totalSell, 1);

  if (whaleNet > 0 && recentWhaleNet > 0 && buyPressure > 0.55) {
    direction = "long";
    confidence = Math.min(95, Math.round(buyPressure * 100 + (whaleNet > 10000 ? 10 : 0)));
    const topBuyer = whaleWallets.filter((w) => w.net_usd > 0).sort((a, b) => b.net_usd - a.net_usd)[0];
    clusterAction = `${whaleWallets.filter((w) => w.net_usd > 0).length} whales accumulating`;
    reason = topBuyer
      ? `${topBuyer.label} leading with +${fU(topBuyer.net_usd)} net buy. Recent whale flow is bullish. ${buyPressure > 0.65 ? "Strong " : ""}buy pressure at ${(buyPressure * 100).toFixed(0)}%.`
      : `Whale cluster net buying ${fU(whaleNet)}. Buy pressure ${(buyPressure * 100).toFixed(0)}%.`;
  } else if (whaleNet < 0 && recentWhaleNet < 0 && buyPressure < 0.45) {
    direction = "short";
    confidence = Math.min(95, Math.round((1 - buyPressure) * 100 + (Math.abs(whaleNet) > 10000 ? 10 : 0)));
    const topSeller = whaleWallets.filter((w) => w.net_usd < 0).sort((a, b) => a.net_usd - b.net_usd)[0];
    clusterAction = `${whaleWallets.filter((w) => w.net_usd < 0).length} whales distributing`;
    reason = topSeller
      ? `${topSeller.label} leading with ${fU(topSeller.net_usd)} net sell. Recent whale flow is bearish. Sell pressure at ${((1 - buyPressure) * 100).toFixed(0)}%.`
      : `Whale cluster net selling ${fU(Math.abs(whaleNet))}. Sell pressure ${((1 - buyPressure) * 100).toFixed(0)}%.`;
  } else {
    direction = "neutral";
    confidence = Math.round(50 - Math.abs(buyPressure - 0.5) * 60);
    clusterAction = "Mixed signals from whale cluster";
    reason = `Whales split: net flow ${whaleNet >= 0 ? "+" : ""}${fU(whaleNet)}. Buy pressure ${(buyPressure * 100).toFixed(0)}%. No clear directional bias.`;
  }

  const priceImpact =
    priceChangePct >= 0
      ? `+${priceChangePct.toFixed(2)}% over window`
      : `${priceChangePct.toFixed(2)}% over window`;

  return { direction, confidence, reason, keyWallets, clusterAction, priceImpact };
}

/* ═══════════════════════════════════════════════════════════════
   INSIGHT PANEL COMPONENT
   ═══════════════════════════════════════════════════════════════ */

function InsightPanel({ insight, chain, onWalletClick }: { insight: WhaleInsight; chain: string; onWalletClick: (addr: string) => void }) {
  const isLong = insight.direction === "long";
  const isShort = insight.direction === "short";
  const isNeutral = insight.direction === "neutral";

  const dirColor = isLong ? "text-emerald-400" : isShort ? "text-rose-400" : "text-slate-400";
  const dirBg = isLong ? "bg-emerald-500/8 border-emerald-500/20" : isShort ? "bg-rose-500/8 border-rose-500/20" : "bg-white/[0.03] border-white/[0.08]";
  const dirIcon = isLong ? "trending_up" : isShort ? "trending_down" : "trending_flat";

  return (
    <div className={`rounded-xl border p-4 ${dirBg}`}>
      {/* Signal header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${isLong ? "bg-emerald-500/15" : isShort ? "bg-rose-500/15" : "bg-white/5"}`}>
            <span className={`material-symbols-outlined text-[26px] ${dirColor}`}>{dirIcon}</span>
          </div>
          <div>
            <div className={`font-display text-base font-bold uppercase tracking-wide ${dirColor}`}>
              {insight.direction} Signal
            </div>
            <div className="font-mono text-xs text-white/60">
              {insight.confidence}% confidence · {insight.priceImpact}
            </div>
          </div>
        </div>
        <div className={`font-display text-3xl font-bold ${dirColor}`}>
          {isLong ? "▲" : isShort ? "▼" : "—"}
        </div>
      </div>

      {/* Reason */}
      <p className="font-body text-[13px] text-white/60 leading-relaxed mb-3">
        {insight.reason}
      </p>

      {/* Cluster action */}
      <div className="flex items-center gap-2 mb-3">
        <span className="material-symbols-outlined text-violet-400 text-[16px]">groups</span>
        <span className="font-display text-xs font-semibold text-violet-400">{insight.clusterAction}</span>
      </div>

      {/* Key wallets causing the move */}
      {insight.keyWallets.length > 0 && (
        <div className="space-y-1.5">
          <div className="font-display text-[11px] text-white/50 uppercase tracking-wider font-bold">Key Wallets Driving Price</div>
          {insight.keyWallets.map((w) => {
            const t = TAG[w.tag] || TAG.degen;
            return (
              <div key={w.address} className="group/kw rounded-lg border border-white/[0.04] hover:border-violet-500/25 bg-white/[0.015] hover:bg-gradient-to-r hover:from-violet-500/[0.06] hover:to-transparent transition-all duration-200">
                <div className="flex items-center gap-2 px-2.5 py-2">
                  <span className={`text-[11px] font-bold font-display px-2 py-0.5 rounded-full border shrink-0 ${t.bg} ${t.color} ${t.border}`}>
                    {w.label}
                  </span>
                  <div className="flex items-center gap-1 min-w-0">
                    <span className="font-mono text-[11px] text-white/35 truncate">{sh(w.address)}</span>
                    <button onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(w.address); }} className="material-symbols-outlined text-[11px] text-white/15 hover:text-neon-cyan cursor-pointer opacity-0 group-hover/kw:opacity-100 transition-all shrink-0" title="Copy address">content_copy</button>
                  </div>
                  <span className="flex-1" />
                  <span className={`font-mono text-[12px] font-bold shrink-0 ${w.net >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                    {w.net >= 0 ? "+" : ""}{fU(w.net)}
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); onWalletClick(w.address); }}
                    className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-display font-bold bg-violet-500/10 text-violet-400 border border-violet-500/20 hover:bg-violet-500/20 hover:border-violet-500/40 hover:shadow-[0_0_12px_rgba(139,92,246,0.15)] transition-all duration-200 cursor-pointer opacity-0 group-hover/kw:opacity-100 shrink-0"
                  >
                    <span className="material-symbols-outlined text-[11px]">query_stats</span>
                    Analyze
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   HEADER
   ═══════════════════════════════════════════════════════════════ */

function Header({
  query, setQuery, onAnalyze, loading, detectedChain,
}: {
  query: string; setQuery: (q: string) => void;
  onAnalyze: () => void; loading: boolean;
  detectedChain?: string;
}) {
  const { wallet, setWallet } = useWallet();
  const chainLabel = CHAINS.find(c => c.id === detectedChain)?.label || detectedChain?.toUpperCase();
  return (
    <div className="flex flex-col gap-2.5 w-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <h2 className="font-display text-white text-sm font-bold tracking-tight shrink-0 flex items-center gap-1.5">
            <span className="material-symbols-outlined text-neon-cyan text-[16px]">token</span>
            Token Analyzer
          </h2>
          <div className="h-4 w-px bg-white/8 hidden lg:block" />
          <div className="relative group hidden lg:block flex-1 max-w-[520px]">
            <span className={"absolute left-2.5 top-1/2 -translate-y-1/2 material-symbols-outlined text-[16px] " + (loading ? "text-neon-cyan animate-spin" : "text-white/50 group-focus-within:text-neon-cyan")}>
              {loading ? "progress_activity" : "search"}
            </span>
            <input
              className="w-full bg-white/[0.03] border border-white/[0.06] text-white rounded-lg pl-8 pr-3 py-1.5 focus:ring-1 focus:ring-neon-cyan/50 focus:border-neon-cyan/30 placeholder-white/20 transition-all outline-none font-mono text-[11px]"
              placeholder="Paste any token address (auto-detects chain)…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") onAnalyze(); }}
            />
          </div>
          {detectedChain && chainLabel && (
            <span className="font-display text-[11px] font-bold px-2 py-1 rounded-md bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/15 shrink-0 hidden lg:flex items-center gap-1">
              <span className="material-symbols-outlined text-[12px]">check_circle</span>{chainLabel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button onClick={onAnalyze} className="flex items-center gap-1.5 px-3 py-1.5 bg-neon-cyan hover:bg-cyan-400 text-black font-display text-[11px] font-bold rounded-lg transition-all shadow-neon-glow cursor-pointer active:scale-[0.97]">
            <span className="material-symbols-outlined text-[16px]">search</span>
            <span className="hidden sm:inline">Analyze</span>
          </button>
          <NotificationPanel />
          <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
        </div>
      </div>
      <div className="relative group lg:hidden">
        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/50 group-focus-within:text-neon-cyan material-symbols-outlined text-[16px]">search</span>
        <input className="w-full bg-white/[0.03] border border-white/[0.06] text-white rounded-lg pl-8 pr-3 py-1.5 focus:ring-1 focus:ring-neon-cyan/50 placeholder-white/20 transition-all outline-none font-mono text-[11px]" placeholder="Paste any token address…" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") onAnalyze(); }} />
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   WALLET ROW
   ═══════════════════════════════════════════════════════════════ */

function WalletRow({ w, rank, onView }: { w: InvestigateWallet; rank: number; onView: () => void }) {
  const [open, setOpen] = useState(false);
  const tag = TAG[w.tag] || TAG.degen;
  const buyPct = w.total_volume > 0 ? (w.buy_usd / w.total_volume) * 100 : 50;

  return (
    <div className={`transition-all ${open ? "bg-white/[0.015]" : ""}`}>
      <div className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-white/[0.02] transition-colors" onClick={() => setOpen(!open)}>
        <span className={`w-5 text-center font-mono text-[11px] font-bold ${rank <= 3 ? "text-violet-400" : "text-white/50"}`}>{rank}</span>
        <span className={`font-display text-[11px] font-bold px-2 py-0.5 rounded-full border ${tag.bg} ${tag.color} ${tag.border}`}>{w.label}</span>
        <button onClick={(e) => { e.stopPropagation(); onView(); }} className="font-mono text-[11px] text-white/50 hover:text-violet-400 transition-colors truncate" title={w.address}>{w.short_addr}</button>
        <span className="flex-1" />
        <div className="w-12 h-1.5 rounded-full bg-white/[0.04] overflow-hidden hidden sm:block">
          <div className="h-full bg-emerald-500" style={{ width: `${buyPct}%` }} />
        </div>
        <span className="font-mono text-[11px] text-emerald-400 w-6 text-right">{w.buys}</span>
        <span className="font-mono text-[11px] text-rose-400 w-6 text-right">{w.sells}</span>
        <span className="font-mono text-[12px] text-white/60 w-16 text-right">{fU(w.total_volume)}</span>
        <span className={`font-mono text-[12px] font-semibold w-16 text-right ${w.net_usd >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
          {w.net_usd >= 0 ? "+" : ""}{fU(w.net_usd)}
        </span>
        <span className={`material-symbols-outlined text-[12px] transition-transform text-white/50 ${open ? "rotate-180" : ""}`}>expand_more</span>
      </div>

      {open && (
        <div className="px-4 pb-3 space-y-2 border-t border-white/[0.03]">
          <div className="grid grid-cols-4 gap-1.5 pt-2">
            {[
              { l: "Buy", v: fU(w.buy_usd), c: "text-emerald-400" },
              { l: "Sell", v: fU(w.sell_usd), c: "text-rose-400" },
              { l: "Impact", v: fU(w.abs_impact), c: w.net_usd >= 0 ? "text-emerald-400" : "text-rose-400" },
              { l: "Ratio", v: buyPct.toFixed(0) + "% buy", c: "text-white/60" },
            ].map((s) => (
              <div key={s.l} className="bg-white/[0.02] rounded-lg px-2.5 py-2">
                <div className="font-display text-[11px] text-white/50 uppercase tracking-wider">{s.l}</div>
                <div className={`font-mono text-[13px] font-semibold ${s.c}`}>{s.v}</div>
              </div>
            ))}
          </div>
          <div className="h-1.5 rounded-full bg-white/[0.04] overflow-hidden flex">
            <div className="h-full bg-emerald-500/70" style={{ width: `${buyPct}%` }} />
            <div className="h-full bg-rose-500/70" style={{ width: `${100 - buyPct}%` }} />
          </div>
          {w.txns.length > 0 && (
            <div className="space-y-0.5">
              <div className="font-display text-[11px] text-white/50 uppercase tracking-wider">Recent</div>
              {w.txns.slice(0, 3).map((tx, i) => (
                <div key={i} className="flex items-center gap-2 font-mono text-[11px]">
                  <span className={tx.side === "buy" ? "text-emerald-400" : "text-rose-400"}>{tx.side.toUpperCase()}</span>
                  <span className="text-white/50">{fU(tx.usd_value)}</span>
                  {tx.timestamp && <span className="text-white/50 flex-1 text-right">{new Date(tx.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>}
                </div>
              ))}
            </div>
          )}
          <button onClick={onView} className="w-full py-1.5 font-display text-[11px] font-bold text-violet-400 hover:text-violet-300 bg-violet-500/5 hover:bg-violet-500/10 border border-violet-500/10 rounded-lg transition-all cursor-pointer flex items-center justify-center gap-1">
            <span className="material-symbols-outlined text-[12px]">open_in_new</span>Full Analysis
          </button>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   MAIN PAGE COMPONENT
   ═══════════════════════════════════════════════════════════════ */

const SESSION_KEY = "lumina_token_analyzer_cache";

function TokenAnalyzerInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [chain, setChain] = useState("auto");
  const [loading, setLoading] = useState(false);
  const [token, setToken] = useState<TokenAnalysis | null>(null);
  const [pairs, setPairs] = useState<TokenPair[]>([]);
  const [totalPairs, setTotalPairs] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Whale state
  const [scanning, setScanning] = useState(false);
  const [candles, setCandles] = useState<InvestigateCandle[]>([]);
  const [flowMap, setFlowMap] = useState<Record<string, CandleFlow>>({});
  const [wallets, setWallets] = useState<InvestigateWallet[]>([]);
  const [totalSwaps, setTotalSwaps] = useState(0);
  const [rawSwaps, setRawSwaps] = useState<RawSwap[]>([]);
  const [bigMoves, setBigMoves] = useState<BigMove[]>([]);
  const [whaleTf, setWhaleTf] = useState("5m");
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiTimestamp, setAiTimestamp] = useState<Date | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const restoredRef = useRef(false);
  const inactivityRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Wallet tracking state
  const [trackedWallet, setTrackedWallet] = useState("0xbf004bff64725914ee36d03b87d6965b0ced4903");
  const [trackedWalletLabel, setTrackedWalletLabel] = useState("Afeng");
  const [walletTrades, setWalletTrades] = useState<WalletTokenTrade[]>([]);
  const [walletTradesLoading, setWalletTradesLoading] = useState(false);
  const [showTrackPanel, setShowTrackPanel] = useState(false);

  const triggerAI = useCallback(async (tData: TokenAnalysis, wList: InvestigateWallet[], cList: InvestigateCandle[], fMap: Record<string, CandleFlow>) => {
    setAiLoading(true);
    try {
      // Build summaries for Claude
      const first = cList[0], last = cList[cList.length - 1];
      const vols = cList.map(c => c.volume);
      const avgVol = vols.reduce((a, b) => a + b, 0) / (vols.length || 1);
      const recentAvg = vols.slice(-10).reduce((a, b) => a + b, 0) / Math.min(vols.length, 10);
      const biggestPctMove = cList.reduce((mx, c) => { const m = Math.abs((c.close - c.open) / (c.open || 1) * 100); return m > mx ? m : mx; }, 0);
      const candle_summary = {
        count: cList.length,
        price_range: first && last ? `$${Math.min(first.low, last.low).toPrecision(4)} — $${Math.max(first.high, last.high).toPrecision(4)}` : "",
        vol_trend: recentAvg > avgVol * 1.3 ? "Increasing" : recentAvg < avgVol * 0.7 ? "Decreasing" : "Stable",
        biggest_move: `${biggestPctMove.toFixed(1)}% single candle`,
      };
      const flowVals = Object.values(fMap);
      const totalBuy = flowVals.reduce((a, f) => a + (f.buy_usd || 0), 0);
      const totalSell = flowVals.reduce((a, f) => a + (f.sell_usd || 0), 0);
      const flow_summary = {
        net_usd: totalBuy - totalSell,
        buy_pressure_pct: (totalBuy + totalSell) > 0 ? (totalBuy / (totalBuy + totalSell)) * 100 : 50,
      };
      // Send only top 5 wallets (by impact) to keep payload small + fast
      const topW = [...wList].sort((a, b) => b.abs_impact - a.abs_impact).slice(0, 5).map(w => ({
        address: w.short_addr, tag: w.tag, label: w.label,
        buy_usd: w.buy_usd, sell_usd: w.sell_usd, net_usd: w.net_usd,
      }));
      const res = await fetchAIAnalysis(tData as unknown as Record<string, unknown>, topW as unknown as Record<string, unknown>[], candle_summary, flow_summary);
      console.log("[Lumina AI] response:", res);
      if (res.analysis) { setAiAnalysis(res.analysis); setAiTimestamp(new Date()); }
      else console.warn("[Lumina AI] No analysis in response:", res);
    } catch (err) { console.error("[Lumina AI] triggerAI failed:", err); } finally { setAiLoading(false); }
  }, []);

  const runWhaleScan = useCallback(async (tokenAddr: string, pairAddr: string, ch: string, tf: string, tData?: TokenAnalysis) => {
    setScanning(true);
    try {
      const ohlcvRes = await fetchInvestigateOHLCV(pairAddr, ch, tf);
      if (ohlcvRes.candles?.length) {
        setCandles(ohlcvRes.candles);
        const scanRes = await scanTokenActivity({
          token_address: tokenAddr,
          pair_address: pairAddr,
          chain: ch,
          candle_timestamps: ohlcvRes.candles.map((c) => c.ts),
          timeframe_seconds: TF_SEC[tf] || 300,
          timeframe: tf,
        });
        if (scanRes.candle_flow) setFlowMap(scanRes.candle_flow);
        if (scanRes.wallets) setWallets(scanRes.wallets);
        setRawSwaps(scanRes.raw_swaps || []);
        setBigMoves(scanRes.big_moves || []);
        setTotalSwaps(scanRes.total_swaps || 0);
        // Trigger AI analysis in background after data is ready
        if (tData && scanRes.wallets?.length) {
          triggerAI(tData, scanRes.wallets, ohlcvRes.candles, scanRes.candle_flow || {});
        }
      }
    } catch { /* silent */ } finally { setScanning(false); }
  }, [triggerAI]);

  // Load wallet trades for a token
  const loadWalletTrades = useCallback(async (tokenAddr: string, ch: string) => {
    if (!trackedWallet) return;
    setWalletTradesLoading(true);
    try {
      const res = await fetchWalletTokenTrades(trackedWallet, tokenAddr, ch);
      setWalletTrades(res.trades || []);
    } catch { setWalletTrades([]); }
    finally { setWalletTradesLoading(false); }
  }, [trackedWallet]);

  const doAnalyze = useCallback(async (addr: string, ch?: string, silent = false) => {
    if (!addr.trim()) return;
    if (!silent) {
      setLoading(true); setError(null); setAiAnalysis(null);
      setCandles([]); setFlowMap({}); setWallets([]); setRawSwaps([]); setBigMoves([]); setTotalSwaps(0);
      setWalletTrades([]);
    }
    try {
      // Use 'auto' to let backend detect chain, or explicit chain for refreshes
      const res = await analyzeToken(addr.trim(), ch || "auto");
      if (res.error && !res.token) { if (!silent) { setError(res.error); setToken(null); setPairs([]); } }
      else {
        setToken(res.token); setPairs(res.pairs); setTotalPairs(res.total_pairs);
        // Update chain from detected chain_id
        const detectedChain = res.token?.chain_id || "auto";
        setChain(detectedChain);
        // Show token data immediately — loading done here
        setLoading(false);
        // Fire whale scan in background (don't await)
        if (res.token?.pair_address) {
          runWhaleScan(res.token.address, res.token.pair_address, detectedChain, whaleTf, res.token);
          // Also load tracked wallet trades
          loadWalletTrades(res.token.address, detectedChain);
        }
        return; // skip the finally setLoading since we already set it
      }
    } catch (e) { if (!silent) setError(e instanceof Error ? e.message : "Failed"); }
    finally { setLoading(false); }
  }, [whaleTf, runWhaleScan, loadWalletTrades]);

  // Auto-refresh: re-fetch token price every 30s, full rescan every 90s
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const scanCountRef = useRef(0);
  useEffect(() => {
    if (refreshRef.current) clearInterval(refreshRef.current);
    if (!token?.address) return;
    refreshRef.current = setInterval(() => {
      scanCountRef.current++;
      setIsRefreshing(true);
      if (scanCountRef.current % 3 === 0) {
        // Full rescan every 90s (3 × 30s)
        doAnalyze(token.address, chain, true).finally(() => {
          setIsRefreshing(false);
          setLastRefresh(new Date());
        });
      } else {
        // Price-only refresh every 30s
        analyzeToken(token.address, chain).then(res => {
          if (res.token) setToken(res.token);
        }).catch(() => {}).finally(() => {
          setIsRefreshing(false);
          setLastRefresh(new Date());
        });
      }
    }, 30_000);
    return () => { if (refreshRef.current) clearInterval(refreshRef.current); };
  }, [token?.address, chain]); // eslint-disable-line react-hooks/exhaustive-deps

  // 10-minute inactivity auto-reset: clear AI analysis since market data goes stale
  useEffect(() => {
    if (!aiAnalysis) return;
    if (inactivityRef.current) clearTimeout(inactivityRef.current);
    inactivityRef.current = setTimeout(() => {
      setAiAnalysis(null);
      setAiTimestamp(null);
    }, 10 * 60 * 1000); // 10 minutes
    return () => { if (inactivityRef.current) clearTimeout(inactivityRef.current); };
  }, [aiAnalysis]);

  // Manual AI refresh function
  const refreshAI = useCallback(() => {
    if (!token || !wallets.length || !candles.length) return;
    setAiAnalysis(null);
    triggerAI(token, wallets, candles, flowMap);
  }, [token, wallets, candles, flowMap, triggerAI]);

  // Restore from sessionStorage on mount (before URL param check)
  useEffect(() => {
    const addr = searchParams.get("address");
    if (addr && addr.length > 10) { setQuery(addr); doAnalyze(addr); return; }
    // Try to restore cached state
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (raw) {
        const cached = JSON.parse(raw);
        if (cached.token) { setToken(cached.token); setQuery(cached.query || ""); setChain(cached.chain || "solana"); setPairs(cached.pairs || []); setTotalPairs(cached.totalPairs || 0); setCandles(cached.candles || []); setFlowMap(cached.flowMap || {}); setWallets(cached.wallets || []); setRawSwaps(cached.rawSwaps || []); setBigMoves(cached.bigMoves || []); setTotalSwaps(cached.totalSwaps || 0); setWhaleTf(cached.whaleTf || "5m"); restoredRef.current = true; }
      }
    } catch { /* ignore */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Save state to sessionStorage whenever token data changes
  useEffect(() => {
    if (!token) return;
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ token, query, chain, pairs, totalPairs, candles, flowMap, wallets, rawSwaps, bigMoves, totalSwaps, whaleTf }));
    } catch { /* quota exceeded, ignore */ }
  }, [token, candles, flowMap, wallets, rawSwaps, bigMoves, totalSwaps, whaleTf, query, chain, pairs, totalPairs]);

  // Navigate to wallet analyzer with state preservation
  const handleWalletClick = useCallback((address: string) => {
    router.push(`/wallet-analyzer?address=${encodeURIComponent(address)}&chain=${chain}`);
  }, [router, chain]);

  const handleAnalyze = () => { if (query.trim()) doAnalyze(query.trim()); };

  const handleChangeTf = useCallback((tf: string) => {
    setWhaleTf(tf);
    if (!token?.pair_address) return;
    setCandles([]); setFlowMap({}); setWallets([]); setRawSwaps([]); setBigMoves([]);
    runWhaleScan(token.address, token.pair_address, chain, tf);
  }, [token, chain, runWhaleScan]);

  const t = token;

  // Signals
  const signals = useMemo(() => {
    if (!t) return [];
    const s: { label: string; signal: "bullish" | "bearish" | "neutral"; reason: string }[] = [];
    if (t.volume_24h > t.liquidity_usd * 2) s.push({ label: "Volume", signal: "bullish", reason: "24h vol > 2x liq" });
    else if (t.volume_24h < t.liquidity_usd * 0.1) s.push({ label: "Volume", signal: "bearish", reason: "Very low" });
    else s.push({ label: "Volume", signal: "neutral", reason: "Normal" });
    const ratio = t.txns_24h_buys / Math.max(t.txns_24h_sells, 1);
    if (ratio > 1.5) s.push({ label: "Pressure", signal: "bullish", reason: `${ratio.toFixed(1)}x buys` });
    else if (ratio < 0.7) s.push({ label: "Pressure", signal: "bearish", reason: `${(1 / ratio).toFixed(1)}x sells` });
    else s.push({ label: "Pressure", signal: "neutral", reason: "Balanced" });
    if (t.price_change_1h > 5 && t.price_change_5m > 0) s.push({ label: "Momentum", signal: "bullish", reason: "Uptrend" });
    else if (t.price_change_1h < -5 && t.price_change_5m < 0) s.push({ label: "Momentum", signal: "bearish", reason: "Downtrend" });
    else s.push({ label: "Momentum", signal: "neutral", reason: "Sideways" });
    return s;
  }, [t]);

  const pairAge = useMemo(() => {
    if (!t || !t.pair_created_at) return "—";
    const ms = Date.now() - t.pair_created_at;
    const d = Math.floor(ms / 86400000);
    if (d > 365) return Math.floor(d / 365) + "y";
    if (d > 30) return Math.floor(d / 30) + "mo";
    if (d > 0) return d + "d";
    return Math.floor(ms / 3600000) + "h";
  }, [t]);

  const sigColor = (s: string) => s === "bullish" ? "text-emerald-400" : s === "bearish" ? "text-rose-400" : "text-white/60";
  const sigIcon = (s: string) => s === "bullish" ? "north_east" : s === "bearish" ? "south_east" : "east";

  // Whale insight computation
  const insight = useMemo(() => computeWhaleInsight(wallets, candles, flowMap), [wallets, candles, flowMap]);

  // Whale timeline events
  const whaleEvents = useMemo(() => buildWhaleEvents(wallets, candles, flowMap), [wallets, candles, flowMap]);

  // Whale aggregates
  const whaleBuyUsd = wallets.reduce((s, w) => s + w.buy_usd, 0);
  const whaleSellUsd = wallets.reduce((s, w) => s + w.sell_usd, 0);
  const whaleNetFlow = whaleBuyUsd - whaleSellUsd;

  return (
    <AppShell header={<Header query={query} setQuery={setQuery} onAnalyze={handleAnalyze} loading={loading} detectedChain={token?.chain_id || undefined} />}>
      <div className="space-y-3">

        {/* Loading */}
        {loading && (
          <div className="glass-panel rounded-xl p-12 flex flex-col items-center justify-center gap-3">
            <div className="w-10 h-10 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" />
            <p className="font-display text-white/60 text-xs font-semibold">Analyzing token…</p>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div className="rounded-xl p-3 border border-rose-500/20 bg-rose-500/5 flex items-center gap-2">
            <span className="material-symbols-outlined text-rose-400 text-[16px]">error</span>
            <span className="font-mono text-rose-400 text-xs">{error}</span>
          </div>
        )}

        {/* ═══════ TOKEN LOADED ═══════ */}
        {t && !loading && (
          <>
            {/* ── Identity Row ── */}
            <div className="glass-panel rounded-xl p-3">
              <div className="flex items-center gap-3">
                {t.logo ? (
                  <img src={t.logo} alt="" className="w-9 h-9 rounded-full border border-white/8 object-cover shrink-0" onError={(e) => (e.currentTarget.style.display = "none")} />
                ) : (
                  <div className="w-9 h-9 rounded-full bg-neon-cyan/8 border border-neon-cyan/15 flex items-center justify-center shrink-0">
                    <span className="font-display text-neon-cyan font-bold text-xs">{t.symbol.slice(0, 2)}</span>
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="font-display text-white font-bold text-[15px]">{t.name}</span>
                    <span className="font-mono text-white/50 text-[13px]">${t.symbol}</span>
                    <span className="font-display text-[11px] font-bold px-1.5 py-0.5 rounded bg-neon-cyan/8 text-neon-cyan border border-neon-cyan/15">{t.chain_id}</span>
                    <span className="font-display text-[11px] font-bold px-1.5 py-0.5 rounded bg-white/[0.03] text-white/50 border border-white/[0.06]">{t.dex_id}</span>
                    <span className="font-display text-[11px] font-bold px-1.5 py-0.5 rounded bg-violet-500/8 text-violet-400 border border-violet-500/15">{pairAge}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="font-mono text-[11px] text-white/50 select-all">{sh(t.address)}</span>
                    <button onClick={() => navigator.clipboard?.writeText(t.address)} className="material-symbols-outlined text-white/15 hover:text-neon-cyan text-[12px] cursor-pointer transition-colors">content_copy</button>
                    {t.dex_url && <a href={t.dex_url} target="_blank" rel="noopener noreferrer" className="font-mono text-[11px] text-white/50 hover:text-neon-cyan transition-colors">DexScreener ↗</a>}
                  </div>
                </div>
                <div className="text-right shrink-0 flex flex-col items-end gap-0.5">
                  <p className="font-mono text-white text-xl font-bold leading-tight">
                    {t.price_usd < 0.001 ? "$" + t.price_usd.toExponential(3) : fU(t.price_usd)}
                  </p>
                  <p className={`font-mono text-xs font-semibold ${t.price_change_24h >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                    {fP(t.price_change_24h)}
                  </p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    {isRefreshing && (
                      <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span>
                        <span className="text-[11px] text-amber-400 font-bold">REFRESHING</span>
                      </span>
                    )}
                    {!isRefreshing && lastRefresh && (
                      <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/8 border border-emerald-500/15">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                        <span className="text-[11px] text-emerald-400 font-bold">LIVE</span>
                      </span>
                    )}
                    {scanning && (
                      <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-violet-500/10 border border-violet-500/20">
                        <span className="w-1.5 h-1.5 rounded-full border border-violet-400 border-t-transparent animate-spin"></span>
                        <span className="text-[11px] text-violet-400 font-bold">SCANNING</span>
                      </span>
                    )}
                    {lastRefresh && !isRefreshing && (
                      <span className="text-[11px] text-white/50 font-mono">
                        {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* ── Stats Row ── */}
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-1.5 items-stretch">
              {[
                { l: "MCap", v: t.market_cap > 0 ? fU(t.market_cap) : "—" },
                { l: "Liq", v: fU(t.liquidity_usd), c: t.liquidity_usd > 100000 ? "text-emerald-400" : t.liquidity_usd < 10000 ? "text-rose-400" : undefined },
                { l: "24h Vol", v: fU(t.volume_24h) },
                { l: "Holders", v: t.holder_count ? fN(t.holder_count) : "—", c: t.holder_count && t.holder_count > 1000 ? "text-emerald-400" : t.holder_count && t.holder_count < 100 ? "text-rose-400" : undefined },
                { l: "V/L", v: (t.liquidity_usd > 0 ? (t.volume_24h / t.liquidity_usd).toFixed(1) : "0") + "x" },
                { l: "Age", v: pairAge, c: "text-violet-400" },
              ].map((s) => (
                <div key={s.l} className="bg-white/[0.02] rounded-lg px-2.5 py-2 border border-white/[0.04]">
                  <div className="font-display text-[11px] text-white/50 uppercase tracking-wider font-bold">{s.l}</div>
                  <div className={`font-mono text-[14px] font-semibold ${s.c || "text-white/70"}`}>{s.v}</div>
                </div>
              ))}
            </div>

            {/* ── Price Changes + Signals ── */}
            <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-2 items-stretch">
              <div className="flex gap-1.5">
                {[
                  { l: "5m", v: t.price_change_5m },
                  { l: "1h", v: t.price_change_1h },
                  { l: "6h", v: t.price_change_6h },
                  { l: "24h", v: t.price_change_24h },
                ].map((p) => (
                  <div key={p.l} className={`flex-1 flex flex-col items-center py-1.5 rounded-lg border ${p.v >= 0 ? "bg-emerald-500/5 border-emerald-500/12" : "bg-rose-500/5 border-rose-500/12"}`}>
                    <span className="font-display text-[11px] text-white/50 uppercase font-bold">{p.l}</span>
                    <span className={`font-mono text-[13px] font-semibold ${p.v >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{fP(p.v)}</span>
                  </div>
                ))}
              </div>
              <div className="flex gap-1.5">
                {signals.map((s, i) => (
                  <div key={i} className="flex items-center gap-1.5 px-2.5 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                    <span className={`material-symbols-outlined text-[18px] ${sigColor(s.signal)}`}>{sigIcon(s.signal)}</span>
                    <div>
                      <div className={`font-display text-[11px] font-bold ${sigColor(s.signal)}`}>{s.label}</div>
                      <div className="font-mono text-[11px] text-white/50">{s.reason}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* ═══════════════════════════════════════
                CHART + WHALE SECTION
                ═══════════════════════════════════════ */}
            <div className="glass-panel rounded-xl overflow-hidden">
              {/* Chart header */}
              <div className="px-3 py-2 border-b border-white/[0.04] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-cyan text-[16px]">candlestick_chart</span>
                  <span className="font-display text-[13px] font-bold text-white/70">{t.symbol}/USDT</span>
                  {scanning && (
                    <span className="flex items-center gap-1 font-mono text-[11px] text-violet-400">
                      <span className="w-2 h-2 rounded-full border border-violet-400/30 border-t-violet-400 animate-spin" />
                      scanning…
                    </span>
                  )}
                  {!scanning && totalSwaps > 0 && (
                    <span className="font-mono text-[11px] text-white/50 bg-white/[0.03] px-1.5 py-0.5 rounded">
                      {totalSwaps} swaps · {wallets.length} wallets
                    </span>
                  )}
                  {!scanning && candles.length > 0 && (() => {
                    const lastTs = candles[candles.length - 1].ts;
                    const ago = Math.floor((Date.now() / 1000 - lastTs) / 60);
                    const isLive = ago < 10;
                    return (
                      <span className={`flex items-center gap-1 font-mono text-[11px] ${isLive ? "text-emerald-400/60" : "text-amber-400/60"}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${isLive ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
                        {isLive ? "Live" : `${ago}m ago`}
                      </span>
                    );
                  })()}
                </div>
                <div className="flex items-center gap-1 overflow-x-auto">
                  <div className="flex gap-0.5 bg-white/[0.02] rounded p-0.5 shrink-0">
                    {TF_OPTIONS.map((tf) => (
                      <button key={tf} onClick={() => handleChangeTf(tf)} className={`px-2 py-0.5 rounded font-display text-[11px] font-bold cursor-pointer transition-all ${whaleTf === tf ? "bg-violet-500/15 text-violet-400" : "text-white/50 hover:text-white/50"}`}>
                        {tf}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Wallet Tracking Bar */}
              <div className="px-3 py-1.5 border-b border-white/[0.04] bg-amber-500/[0.03] flex items-center gap-2 flex-wrap">
                <span className="material-symbols-outlined text-amber-400 text-[14px]">person_pin</span>
                <span className="font-display text-[11px] font-bold text-amber-400">Track Wallet</span>
                {!showTrackPanel ? (
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {trackedWallet ? (
                      <>
                        <span className="font-mono text-[11px] text-white/60 truncate">{trackedWalletLabel || sh(trackedWallet)}</span>
                        {walletTrades.length > 0 && (
                          <span className="font-mono text-[11px] text-amber-400/80 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                            {walletTrades.length} trades · {walletTrades.filter(t => t.side === "buy").length}B/{walletTrades.filter(t => t.side === "sell").length}S
                          </span>
                        )}
                        {walletTradesLoading && <span className="w-3 h-3 rounded-full border border-amber-400/30 border-t-amber-400 animate-spin" />}
                      </>
                    ) : (
                      <span className="font-mono text-[11px] text-white/30">No wallet tracked</span>
                    )}
                    <button onClick={() => setShowTrackPanel(!showTrackPanel)} className="ml-auto font-display text-[11px] font-bold text-amber-400 hover:text-amber-300 cursor-pointer px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/20 transition-all shrink-0">
                      {trackedWallet ? "Change" : "Add"}
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <input className="flex-1 min-w-0 bg-black/30 border border-white/10 text-white font-mono text-[11px] rounded px-2 py-1 outline-none focus:ring-1 focus:ring-amber-400/50 placeholder-white/20" placeholder="Wallet address…" value={trackedWallet} onChange={e => setTrackedWallet(e.target.value)} />
                    <input className="w-20 bg-black/30 border border-white/10 text-white text-[11px] rounded px-2 py-1 outline-none placeholder-white/20" placeholder="Label" value={trackedWalletLabel} onChange={e => setTrackedWalletLabel(e.target.value)} />
                    <button onClick={() => { setShowTrackPanel(false); if (token) loadWalletTrades(token.address, chain); }} className="font-display text-[11px] font-bold text-black bg-amber-400 hover:bg-amber-300 cursor-pointer px-2.5 py-1 rounded transition-all shrink-0">Track</button>
                    <button onClick={() => { setShowTrackPanel(false); setTrackedWallet(""); setTrackedWalletLabel(""); setWalletTrades([]); }} className="font-display text-[11px] text-white/50 hover:text-white cursor-pointer">
                      <span className="material-symbols-outlined text-[14px]">close</span>
                    </button>
                  </div>
                )}
              </div>

              {/* TradingView Chart */}
              {candles.length > 0 ? (
                <TVChart candles={candles} flowMap={flowMap} symbol={t.symbol} wallets={wallets} whaleEvents={whaleEvents} rawSwaps={rawSwaps} bigMoves={bigMoves} onWalletClick={handleWalletClick} walletTrades={walletTrades} trackedWalletLabel={trackedWalletLabel} />
              ) : scanning ? (
                <div className="h-[480px] flex flex-col items-center justify-center gap-3">
                  <div className="w-8 h-8 rounded-full border-2 border-violet-500/20 border-t-violet-400 animate-spin" />
                  <span className="font-display text-white/50 text-xs">Loading chart & scanning whale activity…</span>
                </div>
              ) : (
                <div className="h-[480px] flex items-center justify-center">
                  <span className="font-display text-white/40 text-xs">No chart data</span>
                </div>
              )}

              {/* Whale summary strip */}
              {wallets.length > 0 && (
                <div className="px-4 py-2.5 border-t border-white/[0.04] bg-white/[0.01] grid grid-cols-5 gap-3 text-center">
                  <div>
                    <div className="font-display text-[11px] text-white/50 uppercase font-bold">Net Flow</div>
                    <div className={`font-mono text-sm font-bold ${whaleNetFlow >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {whaleNetFlow >= 0 ? "+" : ""}{fU(whaleNetFlow)}
                    </div>
                  </div>
                  <div>
                    <div className="font-display text-[11px] text-white/50 uppercase font-bold">Buy</div>
                    <div className="font-mono text-sm font-bold text-emerald-400">{fU(whaleBuyUsd)}</div>
                  </div>
                  <div>
                    <div className="font-display text-[11px] text-white/50 uppercase font-bold">Sell</div>
                    <div className="font-mono text-sm font-bold text-rose-400">{fU(whaleSellUsd)}</div>
                  </div>
                  <div>
                    <div className="font-display text-[11px] text-white/50 uppercase font-bold">Whales</div>
                    <div className="font-mono text-sm font-bold text-violet-400">{wallets.filter((w) => w.tag === "whale" || w.tag === "smart").length}</div>
                  </div>
                  <div>
                    <div className="font-display text-[11px] text-white/50 uppercase font-bold">Pressure</div>
                    <div className="font-mono text-sm font-bold text-white/60">
                      {(whaleBuyUsd + whaleSellUsd) > 0 ? ((whaleBuyUsd / (whaleBuyUsd + whaleSellUsd)) * 100).toFixed(0) : "50"}%
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ═══ WHALE ANALYSIS — 3 panels ═══ */}
            {wallets.length > 0 && (
              <>
                {/* Row 1: Insight + Whale Timeline + Bubble Map */}
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 items-stretch">
                  {/* Signal + Key Wallets */}
                  <InsightPanel insight={insight} chain={chain} onWalletClick={handleWalletClick} />

                  {/* Whale Activity Timeline — when did each whale trade */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.015] overflow-hidden">
                    <div className="px-3 py-2.5 border-b border-white/[0.04] flex items-center gap-2">
                      <span className="material-symbols-outlined text-amber-400 text-[16px]">timeline</span>
                      <span className="font-display text-[13px] font-bold text-white/60">Whale Timeline</span>
                      <span className="font-mono text-[11px] text-white/50">{whaleEvents.length} events</span>
                    </div>
                    <div className="p-1">
                      {whaleEvents.length > 0 ? (
                        <WhaleTimeline events={whaleEvents} onWalletClick={handleWalletClick} />
                      ) : (
                        <div className="py-8 text-center">
                          <span className="font-display text-[11px] text-white/40">No whale events detected</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Bubble Map */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.015] overflow-hidden">
                    <div className="px-3 py-2.5 border-b border-white/[0.04] flex items-center gap-2">
                      <span className="material-symbols-outlined text-neon-cyan text-[16px]">bubble_chart</span>
                      <span className="font-display text-[13px] font-bold text-white/60">Wallet Cluster</span>
                      <span className="font-mono text-[11px] text-white/50">{wallets.length} wallets</span>
                    </div>
                    <div className="p-2">
                      <WhaleBubbleMap wallets={wallets} onWalletClick={handleWalletClick} />
                    </div>
                  </div>
                </div>

                {/* ═══ AI Trigger Button — shown when data ready but AI not triggered ═══ */}
                {!aiAnalysis && !aiLoading && wallets.length > 0 && candles.length > 0 && token && (
                  <button onClick={refreshAI}
                    className="w-full rounded-2xl border border-violet-500/20 bg-gradient-to-r from-violet-600/[0.06] to-neon-cyan/[0.04] p-4 flex items-center justify-center gap-3 cursor-pointer hover:border-violet-500/40 hover:shadow-[0_0_30px_rgba(139,92,246,0.1)] transition-all group">
                    <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-500 to-violet-700 flex items-center justify-center shadow-lg shadow-violet-500/20 group-hover:scale-110 transition-transform">
                      <span className="material-symbols-outlined text-white text-[20px]">auto_awesome</span>
                    </div>
                    <div className="text-left">
                      <div className="font-display text-[14px] font-bold text-white/80">Run AI Analysis</div>
                      <div className="font-mono text-[11px] text-violet-400/50">Claude will analyze whale activity, chart & market structure</div>
                    </div>
                    <span className="material-symbols-outlined text-violet-400 text-[20px] ml-auto group-hover:translate-x-1 transition-transform">arrow_forward</span>
                  </button>
                )}

                {/* ═══ LUMINA AI ANALYSIS — Premium Panel ═══ */}
                {(aiAnalysis || aiLoading) && (
                  <div className="rounded-2xl border border-violet-500/25 bg-gradient-to-br from-violet-600/[0.06] via-black/20 to-neon-cyan/[0.04] overflow-hidden shadow-[0_0_40px_rgba(139,92,246,0.08)]">
                    {/* Header bar */}
                    <div className="px-4 py-3 border-b border-violet-500/15 bg-gradient-to-r from-violet-500/[0.08] to-transparent flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-violet-700 flex items-center justify-center shadow-lg shadow-violet-500/20">
                        <span className="material-symbols-outlined text-white text-[18px]">auto_awesome</span>
                      </div>
                      <div>
                        <div className="font-display text-[15px] font-bold text-white tracking-tight">Lumina AI Analysis</div>
                        <div className="font-mono text-[11px] text-violet-400/50">powered by Claude · data-grounded</div>
                      </div>
                      {aiLoading && (
                        <span className="ml-auto flex items-center gap-2 font-mono text-[11px] text-violet-400/70">
                          <span className="w-3 h-3 rounded-full border-2 border-violet-400/30 border-t-violet-400 animate-spin" />
                          analyzing…
                        </span>
                      )}
                      {aiAnalysis && !aiLoading && token && (
                        <div className="ml-auto flex items-center gap-2">
                          {token.holder_count && (
                            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/[0.04] border border-white/[0.06]">
                              <span className="material-symbols-outlined text-[14px] text-amber-400">group</span>
                              <span className="font-mono text-[12px] text-amber-400 font-bold">{token.holder_count.toLocaleString()}</span>
                              <span className="font-display text-[11px] text-white/50">holders</span>
                            </div>
                          )}
                          {aiTimestamp && (
                            <span className="font-mono text-[11px] text-white/50">
                              {aiTimestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                            </span>
                          )}
                          <button onClick={refreshAI}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg bg-violet-500/10 border border-violet-500/20 hover:bg-violet-500/20 transition-all cursor-pointer group"
                            title="Refresh AI analysis with latest data">
                            <span className="material-symbols-outlined text-[14px] text-violet-400 group-hover:rotate-180 transition-transform duration-300">refresh</span>
                            <span className="font-display text-[11px] text-violet-400 font-bold">Refresh AI</span>
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Loading state */}
                    {aiLoading && !aiAnalysis && (
                      <div className="p-8 flex flex-col items-center justify-center gap-4">
                        <div className="relative">
                          <div className="w-10 h-10 rounded-full border-2 border-violet-500/20 border-t-violet-400 animate-spin" />
                          <div className="absolute inset-0 w-10 h-10 rounded-full border-2 border-transparent border-b-neon-cyan/30 animate-spin" style={{ animationDirection: "reverse", animationDuration: "1.5s" }} />
                        </div>
                        <span className="font-display text-sm text-white/60">Analyzing whale activity, chart data & market structure…</span>
                      </div>
                    )}

                    {/* Main content */}
                    {aiAnalysis && (
                      <div className="p-4 space-y-4">
                        {/* TLDR hero + Risk badge */}
                        <div className="flex items-start gap-4">
                          <div className="flex-1">
                            <h3 className="font-display text-base font-bold text-white/90 leading-snug">{aiAnalysis.tldr}</h3>
                            <p className="font-body text-[13px] text-white/50 leading-relaxed mt-2">{aiAnalysis.narrative}</p>
                          </div>
                          <div className={`shrink-0 px-3 py-1.5 rounded-xl border-2 font-display text-[12px] font-extrabold tracking-wide ${
                            aiAnalysis.risk_level === "LOW" ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" :
                            aiAnalysis.risk_level === "MEDIUM" ? "text-amber-400 bg-amber-500/10 border-amber-500/30" :
                            aiAnalysis.risk_level === "HIGH" ? "text-rose-400 bg-rose-500/10 border-rose-500/30" :
                            "text-red-400 bg-red-500/15 border-red-500/40"
                          }`}>
                            {aiAnalysis.risk_level} RISK
                          </div>
                        </div>

                        {/* Whale verdict — accent card */}
                        <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-gradient-to-r from-neon-cyan/[0.06] to-transparent border border-neon-cyan/15">
                          <span className="material-symbols-outlined text-neon-cyan text-[20px] mt-0.5">psychology</span>
                          <div>
                            <div className="font-display text-[12px] font-bold text-neon-cyan mb-0.5">Whale Verdict</div>
                            <div className="font-body text-[13px] text-white/60 leading-relaxed">{aiAnalysis.whale_verdict}</div>
                          </div>
                        </div>

                        {/* Spot + Perp signals — premium cards */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-stretch">
                          {[
                            { label: "Spot Signal", sig: aiAnalysis.spot_signal, icon: "currency_exchange" },
                            { label: "Perp Signal", sig: aiAnalysis.perp_signal, icon: "swap_vert" },
                          ].map(({ label, sig, icon }) => {
                            const isLong = sig.direction === "LONG";
                            const isShort = sig.direction === "SHORT";
                            const dirC = isLong ? "text-emerald-400" : isShort ? "text-rose-400" : "text-white/50";
                            const borderC = isLong ? "border-emerald-500/20" : isShort ? "border-rose-500/20" : "border-white/[0.06]";
                            const bgC = isLong ? "from-emerald-500/[0.06]" : isShort ? "from-rose-500/[0.06]" : "from-white/[0.02]";
                            return (
                              <div key={label} className={`rounded-xl border ${borderC} bg-gradient-to-br ${bgC} to-transparent p-3.5 space-y-3`}>
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2">
                                    <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${isLong ? "bg-emerald-500/15" : isShort ? "bg-rose-500/15" : "bg-white/[0.04]"}`}>
                                      <span className={`material-symbols-outlined text-[16px] ${dirC}`}>{icon}</span>
                                    </div>
                                    <span className="font-display text-[13px] font-bold text-white/50">{label}</span>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <span className={`font-display text-[15px] font-extrabold ${dirC}`}>{sig.direction}</span>
                                    {/* Confidence gauge */}
                                    <div className="flex items-center gap-1">
                                      <div className="w-12 h-2 rounded-full bg-white/[0.06] overflow-hidden">
                                        <div className={`h-full rounded-full transition-all ${isLong ? "bg-emerald-400" : isShort ? "bg-rose-400" : "bg-white/20"}`} style={{ width: `${sig.confidence}%` }} />
                                      </div>
                                      <span className="font-mono text-[11px] text-white/35">{sig.confidence}%</span>
                                    </div>
                                  </div>
                                </div>
                                <div className="grid grid-cols-3 gap-2 text-center">
                                  <div className="rounded-lg bg-black/20 p-2">
                                    <div className="font-display text-[11px] text-white/50 uppercase tracking-wider mb-0.5">Entry</div>
                                    <div className="font-mono text-[12px] text-white/70 font-bold">{sig.entry_zone}</div>
                                  </div>
                                  <div className="rounded-lg bg-black/20 p-2">
                                    <div className="font-display text-[11px] text-emerald-400/50 uppercase tracking-wider mb-0.5">Target</div>
                                    <div className="font-mono text-[12px] text-emerald-400 font-bold">{sig.targets?.[0] || "—"}</div>
                                  </div>
                                  <div className="rounded-lg bg-black/20 p-2">
                                    <div className="font-display text-[11px] text-rose-400/50 uppercase tracking-wider mb-0.5">Stop</div>
                                    <div className="font-mono text-[12px] text-rose-400 font-bold">{sig.stop_loss}</div>
                                  </div>
                                </div>
                                {sig.leverage_suggestion && (
                                  <div className="flex items-center gap-1.5">
                                    <span className="material-symbols-outlined text-[12px] text-violet-400/60">speed</span>
                                    <span className="font-mono text-[11px] text-violet-400/60">Leverage: {sig.leverage_suggestion}</span>
                                  </div>
                                )}
                                <p className="font-body text-[12px] text-white/60 leading-relaxed italic">{sig.reasoning}</p>
                              </div>
                            );
                          })}
                        </div>

                        {/* Key Levels + Risk Factors — bottom row */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-stretch">
                          <div className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-3.5">
                            <div className="font-display text-[11px] text-white/35 uppercase tracking-wider font-bold mb-2.5 flex items-center gap-1.5">
                              <span className="material-symbols-outlined text-[14px] text-violet-400/60">straighten</span>
                              Key Levels
                            </div>
                            <div className="space-y-2">
                              {aiAnalysis.key_levels.support?.map((s, i) => (
                                <div key={`s${i}`} className="flex items-center gap-3">
                                  <span className="font-display text-[11px] text-emerald-400/70 w-14 font-bold">Support</span>
                                  <span className="font-mono text-[13px] text-emerald-400 font-bold">{s}</span>
                                </div>
                              ))}
                              {aiAnalysis.key_levels.resistance?.map((r, i) => (
                                <div key={`r${i}`} className="flex items-center gap-3">
                                  <span className="font-display text-[11px] text-rose-400/70 w-14 font-bold">Resist</span>
                                  <span className="font-mono text-[13px] text-rose-400 font-bold">{r}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                          <div className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-3.5">
                            <div className="font-display text-[11px] text-white/35 uppercase tracking-wider font-bold mb-2.5 flex items-center gap-1.5">
                              <span className="material-symbols-outlined text-[14px] text-amber-400/60">shield</span>
                              Risk Factors
                            </div>
                            <div className="space-y-2">
                              {aiAnalysis.risk_factors?.map((f, i) => (
                                <div key={i} className="flex items-start gap-2">
                                  <span className="material-symbols-outlined text-[13px] text-amber-400/60 mt-0.5">warning</span>
                                  <span className="font-body text-[12px] text-white/50 leading-relaxed">{f}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Row 2: Pressure + Liquidity + Pairs (compact) */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-stretch">
                  {/* Buy/sell pressure */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 space-y-2">
                    <div className="font-display text-[11px] text-white/50 uppercase tracking-wider font-bold">Buy / Sell Pressure</div>
                    {[
                      { l: "24h", b: t.txns_24h_buys, s: t.txns_24h_sells },
                      { l: "1h", b: t.txns_1h_buys, s: t.txns_1h_sells },
                    ].map((r) => {
                      const total = r.b + r.s || 1;
                      const pct = (r.b / total) * 100;
                      return (
                        <div key={r.l}>
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="font-display text-[11px] text-white/50 uppercase font-bold">{r.l}</span>
                            <span className="font-mono text-[11px]">
                              <span className="text-emerald-400">{fN(r.b)}</span>
                              <span className="text-white/40"> / </span>
                              <span className="text-rose-400">{fN(r.s)}</span>
                            </span>
                          </div>
                          <div className="h-1 bg-white/[0.04] rounded-full overflow-hidden flex">
                            <div className="h-full bg-emerald-500/60 rounded-l-full" style={{ width: pct + "%" }} />
                            <div className="h-full bg-rose-500/60 rounded-r-full" style={{ width: 100 - pct + "%" }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Liquidity */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="font-display text-[11px] text-white/50 uppercase tracking-wider font-bold mb-2">Liquidity</div>
                    <div className="grid grid-cols-3 gap-1.5">
                      <div className="bg-white/[0.02] rounded-lg p-2.5">
                        <div className="font-display text-[11px] text-white/50 uppercase">USD</div>
                        <div className={`font-mono text-[13px] font-semibold ${t.liquidity_usd > 100000 ? "text-emerald-400" : "text-amber-400"}`}>{fU(t.liquidity_usd)}</div>
                      </div>
                      <div className="bg-white/[0.02] rounded-lg p-2.5">
                        <div className="font-display text-[11px] text-white/50 uppercase">Base</div>
                        <div className="font-mono text-[13px] font-semibold text-neon-cyan">{fU(t.liquidity_base)}</div>
                      </div>
                      <div className="bg-white/[0.02] rounded-lg p-2.5">
                        <div className="font-display text-[11px] text-white/50 uppercase">Quote</div>
                        <div className="font-mono text-[13px] font-semibold text-violet-400">{fU(t.liquidity_quote)}</div>
                      </div>
                    </div>
                  </div>

                  {/* Pairs — compact */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="font-display text-[11px] text-white/50 uppercase tracking-wider font-bold mb-2">
                      Pairs <span className="font-mono text-white/50">{totalPairs}</span>
                    </div>
                    <div className="space-y-1">
                      {pairs.slice(0, 3).map((p, i) => (
                        <a key={i} href={`https://dexscreener.com/${chain}/${p.pair_address}`} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 py-1.5 hover:bg-white/[0.03] rounded px-1.5 transition-colors">
                          <span className={`font-display text-[12px] font-bold ${i === 0 ? "text-neon-cyan" : "text-white/60"}`}>{p.base_symbol}/{p.quote_symbol}</span>
                          <span className="font-mono text-[11px] text-white/50">{p.dex}</span>
                          <span className="flex-1" />
                          <span className="font-mono text-[11px] text-white/50">{fU(p.volume_24h)}</span>
                        </a>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Row 2.5: Top Clusters + Top Traders */}
                {(() => {
                  const accumulators = wallets.filter(w => (w.tag === "whale" || w.tag === "smart") && w.net_usd > 0).sort((a, b) => b.net_usd - a.net_usd);
                  const dumpers = wallets.filter(w => (w.tag === "whale" || w.tag === "sell") && w.net_usd < 0).sort((a, b) => a.net_usd - b.net_usd);
                  const activeTraders = wallets.filter(w => w.buys + w.sells >= 5).sort((a, b) => b.total_volume - a.total_volume);
                  const totalAccBuy = accumulators.reduce((s, w) => s + w.buy_usd, 0);
                  const totalDumpSell = dumpers.reduce((s, w) => s + w.sell_usd, 0);
                  return (accumulators.length > 0 || dumpers.length > 0 || activeTraders.length > 0) ? (
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-stretch">
                      {/* Accumulator Cluster */}
                      <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/[0.03] p-3 space-y-2">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="material-symbols-outlined text-emerald-400 text-[16px]">trending_up</span>
                          <span className="font-display text-[12px] font-bold text-emerald-400">Top Accumulator Cluster</span>
                          <span className="font-mono text-[11px] text-emerald-400/40">{accumulators.length}</span>
                        </div>
                        {accumulators.length > 0 ? (
                          <>
                            <div className="font-mono text-[11px] text-emerald-400/60 mb-1">Combined buying: {fU(totalAccBuy)}</div>
                            {accumulators.slice(0, 4).map((w) => (
                              <div key={w.address} className="flex items-center gap-2 py-1 px-1 rounded hover:bg-white/[0.03] cursor-pointer group/ac transition-colors" onClick={() => handleWalletClick(w.address)}>
                                <span className={`font-display text-[11px] font-bold px-1.5 py-0.5 rounded-full border ${(TAG[w.tag] || TAG.degen).bg} ${(TAG[w.tag] || TAG.degen).color} ${(TAG[w.tag] || TAG.degen).border}`}>{w.label}</span>
                                <span className="font-mono text-[11px] text-white/50">{sh(w.address)}</span>
                                <button onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(w.address); }} className="material-symbols-outlined text-[11px] text-white/10 hover:text-neon-cyan cursor-pointer opacity-0 group-hover/ac:opacity-100 transition-all">content_copy</button>
                                <span className="flex-1" />
                                <span className="font-mono text-[11px] font-bold text-emerald-400">+{fU(w.net_usd)}</span>
                                <span className="material-symbols-outlined text-[11px] text-white/10 group-hover/ac:text-violet-400 transition-colors opacity-0 group-hover/ac:opacity-100">open_in_new</span>
                              </div>
                            ))}
                          </>
                        ) : (
                          <span className="font-display text-[11px] text-white/40">No accumulator cluster detected</span>
                        )}
                      </div>

                      {/* Dumper Cluster */}
                      <div className="rounded-xl border border-rose-500/15 bg-rose-500/[0.03] p-3 space-y-2">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="material-symbols-outlined text-rose-400 text-[16px]">trending_down</span>
                          <span className="font-display text-[12px] font-bold text-rose-400">Top Dumper Cluster</span>
                          <span className="font-mono text-[11px] text-rose-400/40">{dumpers.length}</span>
                        </div>
                        {dumpers.length > 0 ? (
                          <>
                            <div className="font-mono text-[11px] text-rose-400/60 mb-1">Combined selling: {fU(totalDumpSell)}</div>
                            {dumpers.slice(0, 4).map((w) => (
                              <div key={w.address} className="flex items-center gap-2 py-1 px-1 rounded hover:bg-white/[0.03] cursor-pointer group/dm transition-colors" onClick={() => handleWalletClick(w.address)}>
                                <span className={`font-display text-[11px] font-bold px-1.5 py-0.5 rounded-full border ${(TAG[w.tag] || TAG.degen).bg} ${(TAG[w.tag] || TAG.degen).color} ${(TAG[w.tag] || TAG.degen).border}`}>{w.label}</span>
                                <span className="font-mono text-[11px] text-white/50">{sh(w.address)}</span>
                                <button onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(w.address); }} className="material-symbols-outlined text-[11px] text-white/10 hover:text-neon-cyan cursor-pointer opacity-0 group-hover/dm:opacity-100 transition-all">content_copy</button>
                                <span className="flex-1" />
                                <span className="font-mono text-[11px] font-bold text-rose-400">{fU(w.net_usd)}</span>
                                <span className="material-symbols-outlined text-[11px] text-white/10 group-hover/dm:text-violet-400 transition-colors opacity-0 group-hover/dm:opacity-100">open_in_new</span>
                              </div>
                            ))}
                          </>
                        ) : (
                          <span className="font-display text-[11px] text-white/40">No dumper cluster detected</span>
                        )}
                      </div>

                      {/* Top Active Traders */}
                      <div className="rounded-xl border border-violet-500/15 bg-violet-500/[0.03] p-3 space-y-2">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="material-symbols-outlined text-violet-400 text-[16px]">swap_horiz</span>
                          <span className="font-display text-[12px] font-bold text-violet-400">Top Active Traders</span>
                          <span className="font-mono text-[11px] text-violet-400/40">{activeTraders.length}</span>
                        </div>
                        {activeTraders.length > 0 ? (
                          <>
                            <div className="font-mono text-[11px] text-violet-400/60 mb-1">5+ trades in window</div>
                            {activeTraders.slice(0, 4).map((w) => (
                              <div key={w.address} className="flex items-center gap-2 py-1 px-1 rounded hover:bg-white/[0.03] cursor-pointer group/at transition-colors" onClick={() => handleWalletClick(w.address)}>
                                <span className={`font-display text-[11px] font-bold px-1.5 py-0.5 rounded-full border ${(TAG[w.tag] || TAG.degen).bg} ${(TAG[w.tag] || TAG.degen).color} ${(TAG[w.tag] || TAG.degen).border}`}>{w.label}</span>
                                <span className="font-mono text-[11px] text-white/50">{sh(w.address)}</span>
                                <button onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(w.address); }} className="material-symbols-outlined text-[11px] text-white/10 hover:text-neon-cyan cursor-pointer opacity-0 group-hover/at:opacity-100 transition-all">content_copy</button>
                                <span className="flex-1" />
                                <span className="font-mono text-[11px] text-white/50">{w.buys}B/{w.sells}S</span>
                                <span className="font-mono text-[11px] font-bold text-white/60">{fU(w.total_volume)}</span>
                                <span className="material-symbols-outlined text-[11px] text-white/10 group-hover/at:text-violet-400 transition-colors opacity-0 group-hover/at:opacity-100">open_in_new</span>
                              </div>
                            ))}
                          </>
                        ) : (
                          <span className="font-display text-[11px] text-white/40">No active traders detected</span>
                        )}
                      </div>
                    </div>
                  ) : null;
                })()}

                {/* Row 3: Wallet list */}
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.015] overflow-hidden">
                  <div className="px-3 py-2.5 border-b border-white/[0.04] flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-violet-400 text-[16px]">group</span>
                      <span className="font-display text-[13px] font-bold text-white/60">Top Wallets</span>
                      <span className="font-mono text-[11px] text-white/50">{wallets.length}</span>
                    </div>
                    <div className="flex gap-1.5">
                      {Object.entries(
                        wallets.reduce<Record<string, number>>((acc, w) => { acc[w.tag] = (acc[w.tag] || 0) + 1; return acc; }, {})
                      ).map(([tag, count]) => {
                        const c = TAG[tag] || TAG.degen;
                        return <span key={tag} className={`font-mono text-[11px] ${c.color}`}>{count} {tag}</span>;
                      })}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1.5 text-[11px] font-display text-white/50 uppercase tracking-wider font-bold bg-white/[0.01] border-b border-white/[0.03]">
                    <span className="w-5 text-center">#</span>
                    <span className="w-16">Type</span>
                    <span className="flex-1">Address</span>
                    <span className="w-12 hidden sm:block" />
                    <span className="w-6 text-right">B</span>
                    <span className="w-6 text-right">S</span>
                    <span className="w-16 text-right">Vol</span>
                    <span className="w-16 text-right">Net</span>
                    <span className="w-4" />
                  </div>
                  <div className="max-h-[400px] overflow-y-auto divide-y divide-white/[0.02]">
                    {wallets.map((w, i) => (
                      <WalletRow key={w.address} w={w} rank={i + 1} onView={() => handleWalletClick(w.address)} />
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* Footer */}
            <div className="flex items-center justify-center gap-3 py-1">
              <div className="flex items-center gap-1 font-mono text-[11px] text-white/40">
                <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />Live
              </div>
              <span className="font-mono text-[11px] text-white/10">DexScreener · GeckoTerminal · Moralis</span>
            </div>
          </>
        )}

        {/* ── Empty State ── */}
        {!t && !loading && !error && (
          <div className="glass-panel rounded-xl p-8 flex flex-col items-center justify-center gap-5 text-center relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-neon-cyan/[0.02] via-transparent to-violet-500/[0.02] pointer-events-none" />
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-neon-cyan/8 to-violet-500/8 flex items-center justify-center border border-neon-cyan/12 relative z-10">
              <span className="material-symbols-outlined text-neon-cyan text-[24px]">token</span>
            </div>
            <div className="relative z-10">
              <h3 className="font-display text-white text-base font-bold mb-1">Analyze Any Token</h3>
              <p className="font-body text-white/50 text-xs max-w-md leading-relaxed">
                Paste a contract address for TradingView chart with <strong className="text-violet-400">whale movement markers</strong>, cluster analysis, and <strong className="text-emerald-400">long/short signals</strong>.
              </p>
            </div>
            <div className="relative z-10 grid grid-cols-4 gap-4 mt-1">
              {[
                { icon: "candlestick_chart", label: "TradingView Chart", c: "text-neon-cyan" },
                { icon: "diamond", label: "Whale Markers", c: "text-violet-400" },
                { icon: "trending_up", label: "Long/Short Signal", c: "text-emerald-400" },
                { icon: "groups", label: "Cluster Analysis", c: "text-amber-400" },
              ].map((f) => (
                <div key={f.label} className="flex flex-col items-center gap-1">
                  <span className={`material-symbols-outlined text-[16px] ${f.c}`}>{f.icon}</span>
                  <span className="font-display text-[11px] text-white/50">{f.label}</span>
                </div>
              ))}
            </div>
            <div className="relative z-10 mt-3 space-y-2 w-full max-w-sm">
              <div className="font-display text-[11px] text-white/40 uppercase tracking-wider font-bold">Quick Start</div>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {[
                  { label: "BONK", addr: "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263" },
                  { label: "WIF", addr: "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm" },
                  { label: "JUP", addr: "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN" },
                  { label: "TRUMP", addr: "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN" },
                ].map((ex) => (
                  <button key={ex.addr} onClick={() => { setQuery(ex.addr); doAnalyze(ex.addr); }} className="px-3 py-1 bg-white/[0.03] border border-white/[0.06] rounded-lg font-display text-[11px] text-white/50 font-bold hover:bg-neon-cyan/8 hover:border-neon-cyan/15 hover:text-neon-cyan transition-all cursor-pointer">
                    {ex.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

export default function TokenAnalyzerPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-obsidian flex items-center justify-center"><div className="w-10 h-10 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" /></div>}>
      <TokenAnalyzerInner />
    </Suspense>
  );
}
