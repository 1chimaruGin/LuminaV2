"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import AppShell from "@/components/DashboardShell";
import {
  fetchSpikeAlerts,
  fetchWatchlist,
  addToWatchlist,
  removeFromWatchlist,
  fetchScannerStatus,
  fetchStrategyOHLCV,
  updateScannerConfig,
  type OverlapSpikeAlert,
  type ScannerConfig,
  type ScannerStatus,
  type StrategyCandle,
} from "@/lib/api";
import { createChart, ColorType, type IChartApi, type ISeriesApi, type UTCTimestamp, CandlestickSeries, HistogramSeries, LineSeries } from "lightweight-charts";

/* ── Helpers ─────────────────────────────────────────────────────────────── */

const fU = (v: number) => {
  if (v >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  return "$" + v.toFixed(2);
};

const fVol = (v: number) => {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(0);
};

const fPct = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";

function timeAgo(ts: number): string {
  if (!ts) return "—";
  const diff = Date.now() - ts * 1000;
  if (diff < 0) return "now";
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s`;
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h`;
  return `${Math.floor(diff / 86400_000)}d`;
}

/* ── Lightweight Chart ───────────────────────────────────────────────────── */

function OHLCVChart({ symbol, timeframe, alert }: {
  symbol: string; timeframe: string; alert?: OverlapSpikeAlert | null;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const zoneRefs = useRef<ISeriesApi<"Line">[]>([]);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Step 1: init chart once container is mounted
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;

    // Use rAF to let the browser finish layout so getBoundingClientRect is accurate
    const raf = requestAnimationFrame(() => {
      const rect = el.getBoundingClientRect();
      const chart = createChart(el, {
        width: Math.max(rect.width, 300),
        height: Math.max(rect.height, 400),
        layout: { background: { type: ColorType.Solid, color: "#080808" }, textColor: "#525866", fontFamily: "monospace", fontSize: 10 },
        grid: { vertLines: { color: "#ffffff06" }, horzLines: { color: "#ffffff06" } },
        crosshair: { mode: 0, vertLine: { color: "#ffffff15", labelBackgroundColor: "#1a1a2e" }, horzLine: { color: "#ffffff15", labelBackgroundColor: "#1a1a2e" } },
        rightPriceScale: { borderColor: "#ffffff0a", scaleMargins: { top: 0.02, bottom: 0.2 } },
        timeScale: { borderColor: "#ffffff0a", timeVisible: true, secondsVisible: false },
      });
      chartRef.current = chart;
      candleRef.current = chart.addSeries(CandlestickSeries, {
        upColor: "#22c55e", downColor: "#ef4444", borderUpColor: "#22c55e", borderDownColor: "#ef4444",
        wickUpColor: "#22c55e60", wickDownColor: "#ef444460",
      });
      volumeRef.current = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

      const ro = new ResizeObserver(([e]) => {
        chart.applyOptions({ width: Math.max(e.contentRect.width, 300), height: Math.max(e.contentRect.height, 200) });
      });
      ro.observe(el);

      // Store cleanup
      (el as any).__chartCleanup = () => { ro.disconnect(); chart.remove(); };
      setReady(true);
    });

    return () => {
      cancelAnimationFrame(raf);
      (el as any).__chartCleanup?.();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      setReady(false);
    };
  }, []);

  // Step 2: load data — only runs after chart is ready
  useEffect(() => {
    if (!ready) return;
    let dead = false;
    setLoading(true); setError("");
    fetchStrategyOHLCV(symbol, timeframe, 500).then(r => {
      if (dead || !candleRef.current || !volumeRef.current) return;
      const d = r.data || [];
      if (!d.length) { setError("No data"); setLoading(false); return; }
      candleRef.current.setData(d.map((c: StrategyCandle) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
      volumeRef.current.setData(d.map((c: StrategyCandle) => ({ time: c.time as UTCTimestamp, value: c.volume, color: c.close >= c.open ? "#22c55e18" : "#ef444418" })));
      chartRef.current?.timeScale().fitContent();
      setLoading(false);
    }).catch(e => { if (!dead) { setError(e?.message || "Load failed"); setLoading(false); } });
    return () => { dead = true; };
  }, [ready, symbol, timeframe]);

  // Step 3: zone overlay lines
  useEffect(() => {
    if (!ready) return;
    const chart = chartRef.current;
    if (!chart) return;
    zoneRefs.current.forEach(s => { try { chart.removeSeries(s); } catch {} });
    zoneRefs.current = [];
    if (!alert) return;

    const mkLine = (color: string) => chart.addSeries(LineSeries, { color, lineWidth: 1, lineStyle: 2, priceLineVisible: false, crosshairMarkerVisible: false, lastValueVisible: false });
    const h = mkLine("rgba(34,197,94,0.6)");
    const m = mkLine("rgba(250,204,21,0.4)");
    const l = mkLine("rgba(239,68,68,0.6)");
    const t0 = Math.floor(alert.timestamp / 1000) as UTCTimestamp;
    const t1 = (t0 + 7200) as UTCTimestamp;
    h.setData([{ time: t0, value: alert.zone_high }, { time: t1, value: alert.zone_high }]);
    m.setData([{ time: t0, value: alert.zone_mid }, { time: t1, value: alert.zone_mid }]);
    l.setData([{ time: t0, value: alert.zone_low }, { time: t1, value: alert.zone_low }]);
    zoneRefs.current = [h, m, l];
  }, [ready, alert]);

  return (
    <div className="relative w-full" style={{ height: "100%", minHeight: 400 }}>
      <div ref={wrapRef} style={{ width: "100%", height: "100%", position: "absolute", inset: 0 }} />
      {loading && <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#080808]/70"><span className="material-symbols-outlined text-neon-cyan animate-spin text-xl">progress_activity</span></div>}
      {error && <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#080808]/70"><span className="text-rose-400 text-xs">{error}</span></div>}
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function TradingStrategyPage() {
  const [alerts, setAlerts] = useState<OverlapSpikeAlert[]>([]);
  const [watchlist, setWatchlist] = useState<OverlapSpikeAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState<OverlapSpikeAlert | null>(null);
  const [sortBy, setSortBy] = useState<"time" | "5m" | "1m">("time");
  const [saving, setSaving] = useState(false);
  const [sym, setSym] = useState("BTC/USDT:USDT");
  const [symInput, setSymInput] = useState("BTCUSDT");
  const [tf, setTf] = useState("5m");
  const [status, setStatus] = useState<ScannerStatus | null>(null);
  const [cfg, setCfg] = useState<ScannerConfig>({ vol_1h_min: 10_000, vol_1h_max: 2_000_000, spike_5m: 100, spike_1m: 20, ma_window: 10 });
  const [lc, setLc] = useState(cfg);
  useEffect(() => setLc(cfg), [cfg]);

  const loadStatus = useCallback(async () => { try { const s = await fetchScannerStatus(); setStatus(s); if (s.config) setCfg(s.config); } catch {} }, []);
  const loadAlerts = useCallback(async () => { try { setAlerts((await fetchSpikeAlerts(100)).data || []); } catch {} setLoading(false); }, []);
  useEffect(() => { fetchWatchlist().then(r => setWatchlist(r.data || [])).catch(() => {}); }, []);
  useEffect(() => { setLoading(true); loadAlerts(); loadStatus(); const a = setInterval(loadAlerts, 15_000); const b = setInterval(loadStatus, 10_000); return () => { clearInterval(a); clearInterval(b); }; }, [loadAlerts, loadStatus]);

  const pick = (a: OverlapSpikeAlert) => { setSel(a); setSym(a.symbol); setSymInput(a.base + "USDT"); };
  const applySym = () => {
    const raw = symInput.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!raw || raw.length < 3) return;
    // Parse: BTCUSDT → BTC/USDT:USDT
    const usdtIdx = raw.lastIndexOf("USDT");
    if (usdtIdx > 0) {
      const base = raw.slice(0, usdtIdx);
      setSym(`${base}/USDT:USDT`);
    } else {
      setSym(`${raw}/USDT:USDT`);
    }
    setSel(null);
  };
  const togWl = async (s: string) => { try { const r = watchlist.some(w => w.symbol === s) ? await removeFromWatchlist(s) : await addToWatchlist(s); setWatchlist(r.data || []); } catch {} };
  const save = async () => { setSaving(true); try { setCfg(await updateScannerConfig(lc)); } catch {} setSaving(false); };

  const sorted = useMemo(() => {
    const l = [...alerts];
    if (sortBy === "5m") l.sort((a, b) => b.ratio_5m - a.ratio_5m);
    else if (sortBy === "1m") l.sort((a, b) => b.ratio_1m - a.ratio_1m);
    else l.sort((a, b) => b.scan_ts - a.scan_ts);
    return l;
  }, [alerts, sortBy]);

  const live = status && status.last_scan_ts > 0;
  const sc = (k: keyof ScannerConfig, v: number) => setLc(p => ({ ...p, [k]: v }));
  const dd = "h-7 bg-[#0c0c14] border border-white/[0.06] rounded-md px-2 text-[11px] text-white/80 font-mono cursor-pointer outline-none focus:border-neon-cyan/30 hover:border-white/10 transition-colors";

  return (
    <AppShell header={
      <div className="flex items-center justify-between w-full">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-neon-lime/20 to-neon-cyan/20 flex items-center justify-center border border-neon-lime/20">
            <span className="material-symbols-outlined text-neon-lime text-lg">stacked_line_chart</span>
          </div>
          <div>
            <h1 className="text-white text-sm font-bold flex items-center gap-2">
              Trading Strategy
              <span className={`text-[9px] font-bold px-1.5 py-px rounded-full border ${live ? "bg-neon-lime/10 text-neon-lime border-neon-lime/20 animate-pulse" : "bg-amber-500/10 text-amber-400 border-amber-500/15"}`}>
                {live ? "LIVE" : "STARTING"}
              </span>
            </h1>
            <p className="text-slate-500 text-[11px]">God of Scalper · Binance Futures USDT-M</p>
          </div>
        </div>
        <button onClick={() => { loadAlerts(); loadStatus(); }} className="h-7 px-2.5 rounded-md bg-white/[0.03] border border-white/[0.06] text-slate-400 hover:text-white text-[11px] cursor-pointer transition-colors">
          <span className="material-symbols-outlined text-[14px]">refresh</span>
        </button>
      </div>
    }>

      {/* ── Top bar: scanner status + config ── */}
      <div className="glass-panel rounded-xl mb-2 overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 gap-4 flex-wrap">
          {/* left: status */}
          <div className="flex items-center gap-2.5 text-[11px] min-w-0">
            <div className="flex items-center gap-1.5 shrink-0">
              <span className={`w-2 h-2 rounded-full shrink-0 ${live ? "bg-neon-lime shadow-[0_0_6px_rgba(163,230,53,0.4)] animate-pulse" : "bg-slate-700"}`} />
              <span className={`font-bold ${live ? "text-white" : "text-slate-500"}`}>{live ? "Active" : "Starting..."}</span>
            </div>
            {live && (
              <>
                <span className="text-slate-600">|</span>
                <span className="text-slate-500"><span className="text-white font-bold">{status.pairs_filtered}</span>/{status.pairs_total} pairs</span>
                <span className="text-slate-600">|</span>
                <span className={`font-bold ${status.spikes_found > 0 ? "text-neon-lime" : "text-slate-500"}`}>{status.spikes_found} spike{status.spikes_found !== 1 ? "s" : ""}</span>
                <span className="text-slate-600">|</span>
                <span className="text-slate-500">{(status.scan_duration_ms / 1000).toFixed(0)}s · {timeAgo(status.last_scan_ts)} ago</span>
                {status.errors > 0 && <><span className="text-slate-600">|</span><span className="text-rose-400 font-bold">{status.errors} err</span></>}
              </>
            )}
          </div>

          {/* right: config */}
          <div className="flex items-center gap-1.5 shrink-0">
            <select value={lc.vol_1h_min} onChange={e => sc("vol_1h_min", +e.target.value)} className={dd}>
              <option value={1000}>$1K</option><option value={5000}>$5K</option><option value={10000}>$10K</option><option value={50000}>$50K</option><option value={100000}>$100K</option>
            </select>
            <span className="text-slate-700 text-[10px]">–</span>
            <select value={lc.vol_1h_max} onChange={e => sc("vol_1h_max", +e.target.value)} className={dd}>
              <option value={500000}>$500K</option><option value={1000000}>$1M</option><option value={2000000}>$2M</option><option value={5000000}>$5M</option><option value={10000000}>$10M</option>
            </select>
            <span className="text-slate-700 text-[10px] ml-1">Prev≥</span>
            <select value={lc.spike_5m} onChange={e => sc("spike_5m", +e.target.value)} className={dd}>
              <option value={5}>5×</option><option value={10}>10×</option><option value={20}>20×</option><option value={50}>50×</option><option value={100}>100×</option><option value={200}>200×</option>
            </select>
            <span className="text-slate-700 text-[10px]">MA≥</span>
            <select value={lc.spike_1m} onChange={e => sc("spike_1m", +e.target.value)} className={dd}>
              <option value={3}>3×</option><option value={5}>5×</option><option value={10}>10×</option><option value={20}>20×</option><option value={30}>30×</option><option value={50}>50×</option>
            </select>
            <select value={lc.ma_window} onChange={e => sc("ma_window", +e.target.value)} className={dd}>
              <option value={5}>MA5</option><option value={10}>MA10</option><option value={20}>MA20</option>
            </select>
            <button onClick={save} disabled={saving} className="h-7 px-3 rounded-md bg-neon-cyan/10 border border-neon-cyan/20 text-neon-cyan text-[11px] font-bold cursor-pointer hover:bg-neon-cyan/15 disabled:opacity-50 transition-colors">
              {saving ? "..." : "Apply"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Main layout ── */}
      <div className="flex gap-2" style={{ height: "calc(100vh - 170px)" }}>

        {/* ── Left sidebar: alerts ── */}
        <div className="w-[280px] xl:w-[320px] shrink-0 flex flex-col gap-2 overflow-hidden">

          {/* Watchlist */}
          {watchlist.length > 0 && (
            <div className="glass-panel rounded-xl overflow-hidden shrink-0">
              <div className="px-3 py-1.5 border-b border-white/[0.04] flex items-center gap-1.5 bg-amber-400/[0.03]">
                <span className="material-symbols-outlined text-amber-400 text-xs">star</span>
                <span className="text-amber-400 text-[11px] font-bold">Watchlist</span>
                <span className="text-slate-600 text-[10px] font-mono ml-auto">{watchlist.length}</span>
              </div>
              <div className="max-h-28 overflow-y-auto">
                {watchlist.map((w, i) => (
                  <div key={`wl-${i}`} onClick={() => pick(w)} className="px-3 py-1.5 flex items-center justify-between border-b border-white/[0.02] cursor-pointer hover:bg-white/[0.03] transition-colors">
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className={`w-1.5 h-1.5 rounded-full ${w.is_bullish ? "bg-emerald-400" : "bg-rose-400"}`} />
                      <span className="text-white font-bold">{w.base}</span>
                      <span className="text-amber-400 font-mono">{w.ratio_5m.toFixed(0)}×</span>
                      <span className="text-violet-400/70 font-mono">{w.ratio_1m.toFixed(0)}×</span>
                    </div>
                    <button onClick={e => { e.stopPropagation(); togWl(w.symbol); }} className="text-slate-600 hover:text-rose-400 cursor-pointer transition-colors">
                      <span className="material-symbols-outlined text-xs">close</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Alert list */}
          <div className="glass-panel rounded-xl flex flex-col flex-1 overflow-hidden min-h-0">
            <div className="px-3 py-2 border-b border-white/[0.04] bg-white/[0.01] shrink-0">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-amber-400 text-sm animate-pulse">radar</span>
                  <span className="text-white text-[11px] font-bold">Overlap Alerts</span>
                </div>
                <span className="text-slate-600 text-[10px] font-mono">{sorted.length}</span>
              </div>
              <div className="flex bg-[#0a0a12] rounded-md p-0.5 border border-white/[0.04]">
                {(["time", "5m", "1m"] as const).map(s => (
                  <button key={s} onClick={() => setSortBy(s)} className={`flex-1 py-0.5 rounded text-[10px] font-bold cursor-pointer transition-all ${sortBy === s ? "bg-white/[0.08] text-white shadow-sm" : "text-slate-600 hover:text-slate-300"}`}>
                    {s === "time" ? "Recent" : `${s}×`}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0">
              {loading ? (
                <div className="flex flex-col items-center justify-center py-12 gap-2">
                  <span className="material-symbols-outlined text-neon-cyan text-2xl animate-spin">progress_activity</span>
                  <span className="text-slate-600 text-[11px]">Loading alerts...</span>
                </div>
              ) : sorted.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 gap-2 px-4">
                  <span className="material-symbols-outlined text-slate-800 text-3xl">search_off</span>
                  <p className="text-slate-500 text-[11px] font-bold">No overlap spikes detected</p>
                  <p className="text-slate-600 text-[10px] text-center leading-relaxed">
                    Scanning <span className="text-white/70 font-bold">{status?.pairs_filtered ?? "..."}</span> futures pairs every ~45s.
                    Both prev ≥ <span className="text-amber-400">{cfg.spike_5m}×</span> and
                    MA ≥ <span className="text-violet-400">{cfg.spike_1m}×</span> must fire simultaneously.
                    Try lowering thresholds.
                  </p>
                </div>
              ) : sorted.map((a, i) => {
                const on = sel?.symbol === a.symbol && sel?.scan_ts === a.scan_ts;
                const wl = watchlist.some(w => w.symbol === a.symbol);
                return (
                  <div key={`${a.symbol}-${a.scan_ts}-${i}`} onClick={() => pick(a)}
                    className={`px-3 py-2 border-b border-white/[0.03] cursor-pointer transition-all ${on ? "bg-neon-cyan/[0.05] border-l-2 border-l-neon-cyan" : "hover:bg-white/[0.02]"}`}
                  >
                    <div className="flex items-center justify-between mb-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className={`text-[10px] ${a.is_bullish ? "text-emerald-400" : "text-rose-400"}`}>{a.is_bullish ? "▲" : "▼"}</span>
                        <span className="text-white text-[11px] font-bold">{a.base}</span>
                        <span className="text-slate-700 text-[10px]">PERP</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-amber-400 text-[11px] font-mono font-bold">{a.ratio_5m.toFixed(0)}×</span>
                        <span className="text-slate-600 text-[9px]">prev</span>
                        <span className="text-violet-400 text-[10px] font-mono">{a.ratio_1m.toFixed(0)}×</span>
                        <span className="text-slate-600 text-[9px]">MA</span>
                        <button onClick={e => { e.stopPropagation(); togWl(a.symbol); }} className={`ml-1 cursor-pointer transition-colors ${wl ? "text-amber-400" : "text-slate-800 hover:text-amber-400"}`}>
                          <span className="material-symbols-outlined text-[12px]">{wl ? "star" : "star_outline"}</span>
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px] text-slate-600">
                      <span className="text-emerald-400/60 font-bold">OVERLAP</span>
                      <span>{fU(a.price)}</span>
                      <span>·</span>
                      <span>{fU(a.vol_1h_est)}/h</span>
                      <span>·</span>
                      <span className={a.change_24h >= 0 ? "text-emerald-400/50" : "text-rose-400/50"}>{fPct(a.change_24h)}</span>
                      <span className="ml-auto">{timeAgo(a.scan_ts)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── Right: chart area ── */}
        <div className="flex-1 flex flex-col gap-2 min-w-0 overflow-hidden">
          {/* chart */}
          <div className="glass-panel rounded-xl flex-1 flex flex-col overflow-hidden min-h-0">
            <div className="px-3 py-1.5 border-b border-white/[0.04] bg-white/[0.01] flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-neon-cyan text-sm">candlestick_chart</span>
                  <input
                    value={symInput}
                    onChange={e => setSymInput(e.target.value.toUpperCase())}
                    onKeyDown={e => e.key === "Enter" && applySym()}
                    className="w-24 bg-[#0c0c14] border border-white/[0.06] rounded-md px-2 py-0.5 text-[11px] text-white font-bold font-mono outline-none focus:border-neon-cyan/30 transition-colors"
                    placeholder="BTCUSDT"
                  />
                  <button onClick={applySym} className="text-slate-500 hover:text-neon-cyan cursor-pointer transition-colors">
                    <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                  </button>
                  <span className="text-slate-700 text-[10px]">PERP</span>
                </div>
                <div className="flex bg-[#0a0a12] rounded-md p-0.5 border border-white/[0.04]">
                  {["1m", "5m", "15m", "1h", "4h"].map(t => (
                    <button key={t} onClick={() => setTf(t)} className={`px-2 py-0.5 rounded text-[10px] font-bold cursor-pointer transition-all ${tf === t ? "bg-neon-cyan/10 text-neon-cyan shadow-sm" : "text-slate-600 hover:text-white"}`}>{t}</button>
                  ))}
                </div>
              </div>
              {sel && (
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="text-amber-400 font-mono font-bold">{sel.ratio_5m.toFixed(0)}×</span>
                  <span className="text-slate-700 text-[10px]">prev</span>
                  <span className="text-violet-400 font-mono font-bold">{sel.ratio_1m.toFixed(0)}×</span>
                  <span className="text-slate-700 text-[10px]">MA</span>
                  <span className={`font-bold text-[10px] px-1.5 py-px rounded ${sel.is_bullish ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"}`}>
                    {sel.is_bullish ? "LONG" : "SHORT"}
                  </span>
                </div>
              )}
            </div>
            <div className="flex-1 relative min-h-0">
              <OHLCVChart symbol={sym} timeframe={tf} alert={sel} />
            </div>
          </div>

          {/* zone detail strip */}
          {sel && (
            <div className="glass-panel rounded-xl px-3 py-2 shrink-0">
              <div className="flex items-center gap-4 flex-wrap text-[11px]">
                <div className="flex items-center gap-4">
                  <div><span className="text-slate-600 text-[10px]">Zone </span><span className="text-emerald-400 font-mono font-bold">{fU(sel.zone_high)}</span><span className="text-slate-700 mx-1">/</span><span className="text-amber-400 font-mono">{fU(sel.zone_mid)}</span><span className="text-slate-700 mx-1">/</span><span className="text-rose-400 font-mono font-bold">{fU(sel.zone_low)}</span></div>
                </div>
                <span className="text-slate-800">|</span>
                <div><span className="text-slate-600 text-[10px]">Vol </span><span className="text-white font-mono">{fVol(sel.vol_5m_cur)}</span><span className="text-slate-700 mx-1">vol[1]</span><span className="text-slate-400 font-mono">{fVol(sel.vol_5m_prev)}</span></div>
                <span className="text-slate-800">|</span>
                <div><span className="text-slate-600 text-[10px]">Vol </span><span className="text-white font-mono">{fVol(sel.vol_1m_cur)}</span><span className="text-slate-700 mx-1">MA{cfg.ma_window}</span><span className="text-slate-400 font-mono">{fVol(sel.vol_1m_ma)}</span></div>
                <span className="text-slate-800">|</span>
                <div><span className="text-slate-600 text-[10px]">1h </span><span className="text-white font-mono">{fU(sel.vol_1h_est)}</span></div>
                <span className="text-slate-800">|</span>
                <span className={`font-bold ${sel.is_bullish ? "text-emerald-400" : "text-rose-400"}`}>{sel.is_bullish ? "▲ LONG" : "▼ SHORT"}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
