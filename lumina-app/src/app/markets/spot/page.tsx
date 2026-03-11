"use client";

import { useState, useEffect, useRef, memo, useCallback } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import { fetchAllTickers, fetchOrderFlow, type Ticker, type OrderFlowData } from "@/lib/api";

const EXCHANGES = ["binance", "bybit", "okx", "gate", "kucoin", "mexc", "bitget", "hyperliquid"] as const;

// Maker/taker fees per exchange (taker used for market orders)
const EX_FEES: Record<string, { maker: number; taker: number }> = {
  binance:     { maker: 0.10, taker: 0.10 },
  bybit:       { maker: 0.10, taker: 0.10 },
  okx:         { maker: 0.08, taker: 0.10 },
  gate:        { maker: 0.15, taker: 0.15 },
  kucoin:      { maker: 0.10, taker: 0.10 },
  mexc:        { maker: 0.00, taker: 0.10 },
  bitget:      { maker: 0.10, taker: 0.10 },
  hyperliquid: { maker: 0.01, taker: 0.035 },
};

const fU = (v: number) => {
  if (Math.abs(v) >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (Math.abs(v) >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (Math.abs(v) >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  if (Math.abs(v) >= 1) return "$" + v.toFixed(2);
  if (Math.abs(v) > 0) return "$" + v.toFixed(6);
  return "$0";
};
const fP = (v: number | null) => v == null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";

function TradingViewWidget({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = "";
    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    widgetDiv.style.width = "100%";
    widgetDiv.style.height = "100%";
    containerRef.current.appendChild(widgetDiv);
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true, symbol, interval: "D", timezone: "Etc/UTC", theme: "dark", style: "1", locale: "en",
      backgroundColor: "rgba(10, 10, 10, 1)", gridColor: "rgba(255, 255, 255, 0.03)",
      hide_top_toolbar: false, hide_legend: false, allow_symbol_change: true, save_image: false, calendar: false, hide_volume: false,
      support_host: "https://www.tradingview.com",
    });
    containerRef.current.appendChild(script);
  }, [symbol]);
  return <div className="tradingview-widget-container w-full h-full" ref={containerRef} />;
}
const MemoizedWidget = memo(TradingViewWidget);

function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Spot Markets</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">Live data · Binance · Bybit · OKX</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function SpotChartsPage() {
  const [selectedSymbol, setSelectedSymbol] = useState("BINANCE:BTCUSDT");
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [exFilter, setExFilter] = useState<string>("all");
  const [orderFlow, setOrderFlow] = useState<OrderFlowData | null>(null);
  const [ofSymbol, setOfSymbol] = useState("BTC/USDT");
  const [search, setSearch] = useState("");

  // Cross-exchange spread data (computed from real tickers)
  const [spreads, setSpreads] = useState<{ base: string; minEx: string; minPrice: number; maxEx: string; maxPrice: number; spreadPct: number; vol: number; feePct: number; netPct: number; profitable: boolean }[]>([]);

  const loadTickers = useCallback(async () => {
    try {
      // Single fast cached endpoint instead of 8 separate exchange calls
      const res = await fetchAllTickers(2000);
      const all = res.data || [];
      setTickers(all);
      setLastUpdate(new Date());

      // Compute cross-exchange spreads
      const byBase = new Map<string, { ex: string; price: number; vol: number }[]>();
      for (const t of all) {
        if (!t.price || t.price <= 0) continue;
        const key = t.base;
        if (!byBase.has(key)) byBase.set(key, []);
        byBase.get(key)!.push({ ex: t.exchange, price: t.price, vol: t.volume_24h || 0 });
      }
      const sp: typeof spreads = [];
      for (const [base, entries] of byBase) {
        if (entries.length < 2) continue;
        entries.sort((a, b) => a.price - b.price);
        const min = entries[0], max = entries[entries.length - 1];
        if (min.ex === max.ex) continue;
        const spreadPct = ((max.price - min.price) / min.price) * 100;
        if (spreadPct < 0.01 || spreadPct > 10) continue; // filter nonsense
        const vol = entries.reduce((s, e) => s + e.vol, 0);
        const buyFee = EX_FEES[min.ex]?.taker ?? 0.10;
        const sellFee = EX_FEES[max.ex]?.taker ?? 0.10;
        const feePct = buyFee + sellFee; // total round-trip fees %
        const netPct = spreadPct - feePct;
        sp.push({ base, minEx: min.ex, minPrice: min.price, maxEx: max.ex, maxPrice: max.price, spreadPct, vol, feePct, netPct, profitable: netPct > 0 });
      }
      sp.sort((a, b) => b.netPct - a.netPct);
      setSpreads(sp.slice(0, 10));
    } catch (err) { console.error("Spot loadTickers error:", err); }
    setLoading(false);
  }, []);

  const loadOrderFlow = useCallback(async (sym: string) => {
    try {
      const res = await fetchOrderFlow(sym, "binance");
      setOrderFlow(res.data);
      setOfSymbol(sym);
    } catch { setOrderFlow(null); }
  }, []);

  useEffect(() => { loadTickers(); }, [loadTickers]);
  useEffect(() => { loadOrderFlow("BTC/USDT"); }, [loadOrderFlow]);

  // Auto-refresh every 15s
  useEffect(() => {
    const iv = setInterval(loadTickers, 15000);
    return () => clearInterval(iv);
  }, [loadTickers]);

  // Deduplicate tickers by base — keep highest volume per base
  const deduped = (() => {
    const best = new Map<string, Ticker>();
    const filtered = exFilter === "all" ? tickers : tickers.filter(t => t.exchange === exFilter);
    for (const t of filtered) {
      const existing = best.get(t.base);
      if (!existing || t.volume_24h > existing.volume_24h) best.set(t.base, t);
    }
    return [...best.values()].sort((a, b) => b.volume_24h - a.volume_24h);
  })();

  const searchFiltered = search ? deduped.filter(t => t.base.toLowerCase().includes(search.toLowerCase()) || t.symbol.toLowerCase().includes(search.toLowerCase())) : deduped;

  // Volume by exchange
  const volByExchange = EXCHANGES.map(ex => ({
    name: ex.charAt(0).toUpperCase() + ex.slice(1),
    vol: tickers.filter(t => t.exchange === ex).reduce((s, t) => s + t.volume_24h, 0),
  })).sort((a, b) => b.vol - a.vol);
  const totalVol = volByExchange.reduce((s, e) => s + e.vol, 0);

  const tvSymbol = (t: Ticker) => `${t.exchange.toUpperCase()}:${t.base}USDT`;

  const topGainers = deduped.filter(t => (t.price_change_24h ?? 0) > 0).sort((a, b) => (b.price_change_24h ?? 0) - (a.price_change_24h ?? 0)).slice(0, 5);
  const topLosers = deduped.filter(t => (t.price_change_24h ?? 0) < 0).sort((a, b) => (a.price_change_24h ?? 0) - (b.price_change_24h ?? 0)).slice(0, 5);

  return (
    <AppShell header={<Header />}>
      <div className="space-y-3">
        {/* ── Stats Row ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {[
            { l: "Total Pairs", v: deduped.length.toString(), sub: `across ${EXCHANGES.length} exchanges`, icon: "currency_exchange", c: "text-neon-cyan", bg: "bg-neon-cyan/[0.04]", bc: "border-neon-cyan/10" },
            { l: "Total Volume", v: fU(totalVol), sub: "24h aggregate", icon: "bar_chart", c: "text-emerald-400", bg: "bg-emerald-400/[0.04]", bc: "border-emerald-400/10" },
            { l: "Exchanges", v: EXCHANGES.length.toString(), sub: "CEX connected", icon: "hub", c: "text-violet-400", bg: "bg-violet-400/[0.04]", bc: "border-violet-400/10" },
            { l: "Updated", v: lastUpdate ? lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—", sub: "auto-refresh 15s", icon: "schedule", c: "text-amber-400", bg: "bg-amber-400/[0.04]", bc: "border-amber-400/10" },
          ].map(s => (
            <div key={s.l} className={`rounded-xl px-3.5 py-3 border ${s.bc} ${s.bg} transition-all hover:-translate-y-0.5 duration-200`}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold">{s.l}</span>
                <span className={`material-symbols-outlined text-[14px] ${s.c} opacity-60`}>{s.icon}</span>
              </div>
              <div className={`font-mono text-lg font-bold ${s.c}`}>{s.v}</div>
              <div className="text-[11px] text-slate-600 mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>

        {/* ── Top Movers Row ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <div className="rounded-xl border border-emerald-500/10 bg-emerald-500/[0.03] p-3">
            <div className="flex items-center gap-1.5 mb-2">
              <span className="material-symbols-outlined text-emerald-400 text-[14px]">trending_up</span>
              <span className="text-[11px] text-emerald-400 uppercase tracking-wider font-bold">Top Gainers</span>
            </div>
            <div className="flex gap-2 overflow-x-auto">
              {topGainers.map(t => (
                <button key={`${t.exchange}-${t.base}`} onClick={() => setSelectedSymbol(tvSymbol(t))} className="shrink-0 rounded-lg bg-emerald-400/[0.06] border border-emerald-400/10 px-2.5 py-1.5 cursor-pointer hover:bg-emerald-400/10 transition-colors">
                  <div className="text-[11px] text-white font-bold">{t.base}</div>
                  <div className="text-[11px] text-emerald-400 font-mono font-bold">+{(t.price_change_24h ?? 0).toFixed(1)}%</div>
                </button>
              ))}
              {topGainers.length === 0 && <span className="text-[11px] text-slate-600">Loading...</span>}
            </div>
          </div>
          <div className="rounded-xl border border-rose-500/10 bg-rose-500/[0.03] p-3">
            <div className="flex items-center gap-1.5 mb-2">
              <span className="material-symbols-outlined text-rose-400 text-[14px]">trending_down</span>
              <span className="text-[11px] text-rose-400 uppercase tracking-wider font-bold">Top Losers</span>
            </div>
            <div className="flex gap-2 overflow-x-auto">
              {topLosers.map(t => (
                <button key={`${t.exchange}-${t.base}`} onClick={() => setSelectedSymbol(tvSymbol(t))} className="shrink-0 rounded-lg bg-rose-400/[0.06] border border-rose-400/10 px-2.5 py-1.5 cursor-pointer hover:bg-rose-400/10 transition-colors">
                  <div className="text-[11px] text-white font-bold">{t.base}</div>
                  <div className="text-[11px] text-rose-400 font-mono font-bold">{(t.price_change_24h ?? 0).toFixed(1)}%</div>
                </button>
              ))}
              {topLosers.length === 0 && <span className="text-[11px] text-slate-600">Loading...</span>}
            </div>
          </div>
        </div>

        {/* ── Cross-Exchange Spreads (left) + Market Breadth (right) ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
          <div className="rounded-xl border border-white/[0.06] overflow-hidden flex flex-col">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] flex items-center justify-between">
                <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-emerald-400 text-[16px]">swap_horiz</span>
                  Cross-Exchange Arbitrage
                </h3>
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-[11px] text-emerald-400 font-bold">LIVE</span>
                </span>
              </div>
              <div className="divide-y divide-white/[0.04] flex-1">
                {spreads.length === 0 && (
                  <div className="p-8 flex items-center justify-center">
                    <span className="text-[11px] text-slate-600">Calculating arbitrage spreads…</span>
                  </div>
                )}
                {spreads.map((s, idx) => (
                  <div key={s.base} className={`px-3 py-1.5 flex items-center gap-2.5 hover:bg-white/[0.02] transition-colors cursor-pointer ${idx % 2 === 0 ? "bg-white/[0.01]" : ""}`}>
                    <div className="w-16 shrink-0">
                      <div className="flex items-center gap-1">
                        <span className="text-white text-[11px] font-bold">{s.base}</span>
                        {s.profitable ? (
                          <span className="text-[10px] font-bold px-1 py-px rounded-full bg-emerald-400/15 text-emerald-400">NET+</span>
                        ) : (
                          <span className="text-[10px] font-bold px-1 py-px rounded-full bg-rose-400/10 text-rose-400/70">FEE</span>
                        )}
                      </div>
                      <span className="text-[11px] text-slate-600 font-mono">{fU(s.vol)}</span>
                    </div>
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <div className="rounded bg-emerald-400/[0.05] border border-emerald-400/10 px-2 py-1 text-center min-w-[70px]">
                        <div className="text-[10px] text-slate-500 uppercase leading-none">Buy</div>
                        <div className="text-[11px] text-emerald-400 font-bold capitalize leading-tight">{s.minEx}</div>
                        <div className="text-[11px] text-white font-mono leading-tight">{fU(s.minPrice)}</div>
                      </div>
                      <span className="material-symbols-outlined text-white/50 text-[12px] shrink-0">east</span>
                      <div className="rounded bg-violet-400/[0.05] border border-violet-400/10 px-2 py-1 text-center min-w-[70px]">
                        <div className="text-[10px] text-slate-500 uppercase leading-none">Sell</div>
                        <div className="text-[11px] text-violet-400 font-bold capitalize leading-tight">{s.maxEx}</div>
                        <div className="text-[11px] text-white font-mono leading-tight">{fU(s.maxPrice)}</div>
                      </div>
                    </div>
                    <div className="text-right shrink-0 min-w-[80px]">
                      <div className={`text-[12px] font-bold font-mono ${s.profitable ? "text-emerald-400" : "text-rose-400"}`}>
                        {s.netPct >= 0 ? "+" : ""}{s.netPct.toFixed(3)}%
                      </div>
                      <div className="text-[11px] text-slate-500 font-mono">
                        spd {s.spreadPct.toFixed(3)}% · fee {s.feePct.toFixed(2)}%
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="px-4 py-2 border-t border-white/[0.04] bg-white/[0.01] flex items-center gap-2 mt-auto">
                <span className="material-symbols-outlined text-[11px] text-amber-400/40">info</span>
                <span className="text-[11px] text-slate-600">{spreads.length > 0 ? "Taker fees shown · Excludes withdrawal fees · Spreads close fast" : "Waiting for spread data…"}</span>
              </div>
          </div>

          {/* Market Breadth — gainers vs losers + volume leaders */}
          <div className="rounded-xl border border-white/[0.06] overflow-hidden flex flex-col">
            <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] flex items-center justify-between">
              <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                <span className="material-symbols-outlined text-amber-400 text-[16px]">monitoring</span>
                Market Breadth
              </h3>
              <span className="text-[11px] text-slate-500 font-mono">{deduped.length} tokens</span>
            </div>
            <div className="p-4 flex-1 flex flex-col gap-3">
              {/* Gainers vs Losers bar */}
              {(() => {
                const gainers = deduped.filter(t => (t.price_change_24h ?? 0) > 0).length;
                const losers = deduped.filter(t => (t.price_change_24h ?? 0) < 0).length;
                const flat = deduped.length - gainers - losers;
                const gPct = deduped.length > 0 ? (gainers / deduped.length) * 100 : 50;
                return (
                  <div>
                    <div className="flex items-center justify-between text-[11px] font-bold mb-1.5">
                      <span className="text-emerald-400">Gainers {gainers}</span>
                      {flat > 0 && <span className="text-slate-500">Flat {flat}</span>}
                      <span className="text-rose-400">Losers {losers}</span>
                    </div>
                    <div className="h-3 rounded-full overflow-hidden flex bg-white/[0.03] border border-white/[0.04]">
                      <div className="h-full bg-gradient-to-r from-emerald-500/80 to-emerald-400/60 transition-all" style={{ width: `${gPct}%` }} />
                      <div className="h-full bg-gradient-to-r from-rose-400/60 to-rose-500/80 transition-all" style={{ width: `${100 - gPct}%` }} />
                    </div>
                  </div>
                );
              })()}

              {/* Volume leaders */}
              <div className="flex-1 space-y-2">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider font-bold">Volume Leaders (24h)</div>
                {deduped.slice(0, 8).map((t, i) => {
                  const pct = totalVol > 0 ? (t.volume_24h / totalVol) * 100 : 0;
                  const positive = (t.price_change_24h ?? 0) >= 0;
                  return (
                    <div key={`${t.exchange}-${t.base}`} className="flex items-center gap-2 cursor-pointer hover:bg-white/[0.02] rounded-lg px-1 -mx-1 transition-colors" onClick={() => setSelectedSymbol(tvSymbol(t))}>
                      <span className="text-[11px] text-white font-bold w-12 shrink-0">{t.base}</span>
                      <div className="flex-1 h-5 bg-white/[0.03] rounded-lg overflow-hidden relative border border-white/[0.04]">
                        <div className="h-full rounded-lg bg-gradient-to-r from-neon-cyan/40 to-neon-cyan/10 transition-all duration-500" style={{ width: `${Math.min(pct * 3, 100)}%` }} />
                        <span className="absolute inset-0 flex items-center px-2 text-[11px] text-white/60 font-mono font-bold">{fU(t.volume_24h)}</span>
                      </div>
                      <span className={`text-[11px] font-bold font-mono w-14 text-right shrink-0 ${positive ? "text-emerald-400" : "text-rose-400"}`}>
                        {fP(t.price_change_24h)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {/* ── TradingView Chart ── */}
        <div className="rounded-xl border border-white/[0.06] overflow-hidden">
          <div className="h-[420px] sm:h-[480px] w-full">
            <MemoizedWidget symbol={selectedSymbol} />
          </div>
        </div>

        <div className="grid grid-cols-12 gap-3 items-stretch">
          {/* ── Left: Volume + Order Flow ── */}
          <div className="col-span-12 lg:col-span-7 flex flex-col gap-3">
            {/* Volume Distribution */}
            <div className="rounded-xl border border-white/[0.06] overflow-hidden">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02]">
                <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-cyan text-[16px]">bar_chart</span>
                  Volume by Exchange
                </h3>
              </div>
              <div className="p-4 space-y-2.5">
                {volByExchange.map((ex) => {
                  const pct = totalVol > 0 ? (ex.vol / totalVol) * 100 : 0;
                  return (
                    <div key={ex.name} className="flex items-center gap-3">
                      <span className="text-[11px] text-white font-bold w-20 shrink-0 capitalize">{ex.name}</span>
                      <div className="flex-1 h-6 bg-white/[0.03] rounded-lg overflow-hidden relative border border-white/[0.04]">
                        <div className="h-full rounded-lg bg-gradient-to-r from-neon-cyan/40 to-neon-cyan/15 transition-all duration-500" style={{ width: `${Math.min(pct * 2, 100)}%` }} />
                        <span className="absolute inset-0 flex items-center px-2.5 text-[11px] text-white/70 font-mono font-bold">{pct.toFixed(1)}%</span>
                      </div>
                      <span className="text-[11px] text-white font-mono font-bold w-20 text-right shrink-0">{fU(ex.vol)}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Order Flow */}
            <div className="rounded-xl border border-white/[0.06] overflow-hidden">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] flex items-center justify-between">
                <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-violet-400 text-[16px]">layers</span>
                  Order Book Depth
                </h3>
                <div className="flex gap-0.5 bg-white/[0.03] rounded-lg p-0.5 border border-white/[0.06]">
                  {["BTC/USDT", "ETH/USDT", "SOL/USDT"].map(s => (
                    <button key={s} onClick={() => loadOrderFlow(s)} className={`px-2.5 py-1 text-[11px] rounded-md font-bold cursor-pointer transition-all ${ofSymbol === s ? "bg-violet-500/20 text-violet-300 shadow-sm" : "text-slate-500 hover:text-white"}`}>{s.split("/")[0]}</button>
                  ))}
                </div>
              </div>
              {orderFlow ? (
                <div className="p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-white text-sm font-bold">{orderFlow.symbol}</span>
                    <span className="font-mono text-[11px] text-slate-500 capitalize">{orderFlow.exchange}</span>
                    <span className="flex-1" />
                    <span className="font-mono text-[11px] text-slate-500">Spread {orderFlow.spread_pct.toFixed(4)}%</span>
                  </div>
                  <div>
                    <div className="flex items-center justify-between text-[11px] font-bold mb-1.5">
                      <span className="text-emerald-400">Bids {orderFlow.buy_pressure.toFixed(1)}%</span>
                      <span className="text-rose-400">Asks {(100 - orderFlow.buy_pressure).toFixed(1)}%</span>
                    </div>
                    <div className="h-3.5 rounded-full overflow-hidden flex bg-white/[0.03] border border-white/[0.04]">
                      <div className="h-full bg-gradient-to-r from-emerald-500/80 to-emerald-400/60 transition-all" style={{ width: `${orderFlow.buy_pressure}%` }} />
                      <div className="h-full bg-gradient-to-r from-rose-400/60 to-rose-500/80 transition-all" style={{ width: `${100 - orderFlow.buy_pressure}%` }} />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-[11px] text-emerald-400/70 uppercase font-bold mb-1.5 tracking-wider">Top Bids</div>
                      {orderFlow.top_bids?.slice(0, 5).map(([price, amount], i) => (
                        <div key={i} className="flex justify-between font-mono text-[11px] py-0.5 border-b border-white/[0.02] last:border-0">
                          <span className="text-emerald-400">{fU(price)}</span>
                          <span className="text-white/50">{amount.toFixed(4)}</span>
                        </div>
                      ))}
                    </div>
                    <div>
                      <div className="text-[11px] text-rose-400/70 uppercase font-bold mb-1.5 tracking-wider">Top Asks</div>
                      {orderFlow.top_asks?.slice(0, 5).map(([price, amount], i) => (
                        <div key={i} className="flex justify-between font-mono text-[11px] py-0.5 border-b border-white/[0.02] last:border-0">
                          <span className="text-rose-400">{fU(price)}</span>
                          <span className="text-white/50">{amount.toFixed(4)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="p-8 flex items-center justify-center gap-2">
                  <div className="w-4 h-4 rounded-full border-2 border-violet-500/20 border-t-violet-400 animate-spin" />
                  <span className="text-white/50 text-[11px]">Loading order book…</span>
                </div>
              )}
            </div>
          </div>

          {/* ── Right: Live Pair Table ── */}
          <div className="col-span-12 lg:col-span-5">
            <div className="rounded-xl border border-white/[0.06] overflow-hidden h-full flex flex-col">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] space-y-2 shrink-0">
                <div className="flex items-center justify-between">
                  <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                    <span className="material-symbols-outlined text-amber-400 text-[16px]">show_chart</span>
                    Top Pairs
                  </h3>
                  <span className="text-[11px] text-slate-500 font-mono">{searchFiltered.length} pairs</span>
                </div>
                <div className="flex gap-1.5">
                  <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search token..." className="flex-1 bg-white/[0.03] border border-white/[0.06] rounded-lg px-2.5 py-1.5 text-[11px] text-white font-mono placeholder:text-white/50 outline-none focus:border-violet-500/30 transition-colors" />
                  <div className="flex gap-0.5 bg-white/[0.03] rounded-lg p-0.5 border border-white/[0.06]">
                    {["all", ...EXCHANGES.slice(0, 4)].map(ex => (
                      <button key={ex} onClick={() => setExFilter(ex)} className={`px-2 py-1 text-[11px] rounded-md font-bold cursor-pointer transition-all capitalize ${exFilter === ex ? "bg-white/10 text-white shadow-sm" : "text-slate-600 hover:text-white"}`}>{ex === "all" ? "All" : ex.slice(0, 3)}</button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto max-h-[600px]">
                {loading ? (
                  <div className="p-8 flex flex-col items-center justify-center gap-2">
                    <div className="w-5 h-5 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" />
                    <span className="text-[11px] text-slate-600">Fetching from {EXCHANGES.length} exchanges...</span>
                  </div>
                ) : searchFiltered.slice(0, 50).map((t, idx) => {
                  const sym = tvSymbol(t);
                  const positive = (t.price_change_24h ?? 0) >= 0;
                  const isSelected = selectedSymbol === sym;
                  return (
                    <div
                      key={`${t.exchange}-${t.symbol}`}
                      onClick={() => setSelectedSymbol(sym)}
                      className={`px-4 py-2.5 flex items-center justify-between cursor-pointer transition-all border-b border-white/[0.03] last:border-0 ${isSelected ? "bg-neon-cyan/[0.06] border-l-2 border-l-neon-cyan" : "hover:bg-white/[0.02]"} ${idx % 2 === 0 && !isSelected ? "bg-white/[0.01]" : ""}`}
                    >
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-white text-[12px] font-bold">{t.base}<span className="text-slate-600 font-normal">/USDT</span></span>
                          <span className="text-[11px] text-slate-600 font-mono capitalize bg-white/[0.03] px-1 py-px rounded">{t.exchange}</span>
                        </div>
                        <span className="text-[11px] text-slate-600 font-mono">{fU(t.volume_24h)} vol</span>
                      </div>
                      <div className="text-right">
                        <div className="text-[12px] text-white font-mono font-bold">{fU(t.price)}</div>
                        <span className={`text-[11px] font-bold font-mono ${positive ? "text-emerald-400" : "text-rose-400"}`}>{fP(t.price_change_24h)}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-center gap-3 py-1.5">
          <div className="flex items-center gap-1.5 text-[11px] text-slate-600">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span>Live · auto-refresh 15s</span>
          </div>
          <span className="text-[11px] text-slate-700">·</span>
          <span className="text-[11px] text-slate-600">{EXCHANGES.join(" · ")}</span>
        </div>
      </div>
    </AppShell>
  );
}
