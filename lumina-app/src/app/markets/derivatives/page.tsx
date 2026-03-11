"use client";

import { useState, useEffect, useRef, memo, useCallback } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import { fetchFundingRates, fetchOpenInterest, fetchOrderFlow, type FundingRate, type OpenInterestData, type OrderFlowData } from "@/lib/api";

const EXCHANGES = ["binance", "bybit", "okx", "gate", "kucoin", "mexc", "bitget", "hyperliquid"] as const;
const fU = (v: number) => {
  if (Math.abs(v) >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (Math.abs(v) >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (Math.abs(v) >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  if (Math.abs(v) >= 1) return "$" + v.toFixed(2);
  if (Math.abs(v) > 0) return "$" + v.toFixed(6);
  return "$0";
};

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
        <h2 className="text-white text-sm font-bold tracking-tight">Derivatives Intelligence</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">Live data · Binance · Bybit · OKX</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function DerivativesPage() {
  const [selectedSymbol, setSelectedSymbol] = useState("BINANCE:BTCUSDT.P");
  const [funding, setFunding] = useState<FundingRate[]>([]);
  const [oiData, setOiData] = useState<OpenInterestData[]>([]);
  const [orderFlow, setOrderFlow] = useState<OrderFlowData | null>(null);
  const [ofSymbol, setOfSymbol] = useState("BTC/USDT");
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // Funding arb: group by base symbol across exchanges, find biggest rate diff
  const fundingArbs = (() => {
    const byBase = new Map<string, FundingRate[]>();
    for (const f of funding) {
      const base = f.symbol.split("/")[0];
      if (!byBase.has(base)) byBase.set(base, []);
      byBase.get(base)!.push(f);
    }
    const arbs: { base: string; low: FundingRate; high: FundingRate; diff: number; annualized: number }[] = [];
    for (const [base, rates] of byBase) {
      if (rates.length < 2) continue;
      rates.sort((a, b) => a.rate - b.rate);
      const low = rates[0], high = rates[rates.length - 1];
      const diff = high.rate - low.rate;
      if (diff <= 0) continue;
      arbs.push({ base, low, high, diff, annualized: diff * 3 * 365 * 100 }); // 8h funding
    }
    arbs.sort((a, b) => b.diff - a.diff);
    return arbs.slice(0, 8);
  })();

  const totalOI = oiData.reduce((s, o) => s + (o.open_interest_usd || 0), 0);
  const avgFunding = funding.length > 0 ? funding.reduce((s, f) => s + f.rate, 0) / funding.length : 0;

  const loadData = useCallback(async () => {
    try {
      const [fundRes, oiRes] = await Promise.allSettled([
        fetchFundingRates(undefined, 200),
        fetchOpenInterest("binance"),
      ]);
      if (fundRes.status === "fulfilled") setFunding(fundRes.value.data || []);
      if (oiRes.status === "fulfilled") setOiData(oiRes.value.data || []);
      setLastUpdate(new Date());
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  const loadOF = useCallback(async (sym: string) => {
    try {
      const res = await fetchOrderFlow(sym, "binance");
      setOrderFlow(res.data);
      setOfSymbol(sym);
    } catch { setOrderFlow(null); }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => { loadOF("BTC/USDT"); }, [loadOF]);
  useEffect(() => {
    const iv = setInterval(loadData, 30000);
    return () => clearInterval(iv);
  }, [loadData]);

  // Top positive/negative funding for quick summary
  const topPosFunding = [...funding].filter(f => f.rate > 0).sort((a, b) => b.rate - a.rate).slice(0, 3);
  const topNegFunding = [...funding].filter(f => f.rate < 0).sort((a, b) => a.rate - b.rate).slice(0, 3);

  return (
    <AppShell header={<Header />}>
      <div className="space-y-3">
        {/* ── Stat cards ── */}
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-2">
          {[
            { label: "Total OI (Binance)", value: loading && !totalOI ? "—" : fU(totalOI), sub: `${oiData.length} instruments`, icon: "donut_large", c: "text-neon-cyan", bg: "bg-neon-cyan/[0.04]", bc: "border-neon-cyan/10" },
            { label: "Funding Pairs", value: loading && !funding.length ? "—" : funding.length.toString(), sub: `across ${EXCHANGES.length} exchanges`, icon: "bar_chart", c: "text-emerald-400", bg: "bg-emerald-400/[0.04]", bc: "border-emerald-400/10" },
            { label: "Avg Funding Rate", value: loading && !funding.length ? "—" : (avgFunding * 100).toFixed(4) + "%", sub: avgFunding >= 0 ? "longs pay shorts" : "shorts pay longs", icon: "percent", c: avgFunding >= 0 ? "text-emerald-400" : "text-rose-400", bg: avgFunding >= 0 ? "bg-emerald-400/[0.04]" : "bg-rose-400/[0.04]", bc: avgFunding >= 0 ? "border-emerald-400/10" : "border-rose-400/10" },
            { label: "Updated", value: lastUpdate ? lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—", sub: "auto-refresh 30s", icon: "schedule", c: "text-amber-400", bg: "bg-amber-400/[0.04]", bc: "border-amber-400/10" },
          ].map((s) => (
            <div key={s.label} className={`rounded-xl px-3.5 py-3 border ${s.bc} ${s.bg} transition-all hover:-translate-y-0.5 duration-200`}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold">{s.label}</span>
                <span className={`material-symbols-outlined text-[14px] ${s.c} opacity-60`}>{s.icon}</span>
              </div>
              <div className={`text-lg font-bold font-mono ${s.c}`}>{s.value}</div>
              <div className="text-[11px] text-slate-600 mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>

        {/* ── Funding Extremes Row ── */}
        {funding.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div className="rounded-xl border border-emerald-500/10 bg-emerald-500/[0.03] p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <span className="material-symbols-outlined text-emerald-400 text-[14px]">trending_up</span>
                <span className="text-[11px] text-emerald-400 uppercase tracking-wider font-bold">Highest Funding (Longs Pay)</span>
              </div>
              <div className="flex gap-2 overflow-x-auto">
                {topPosFunding.map(f => (
                  <button key={`${f.exchange}-${f.symbol}`} onClick={() => setSelectedSymbol(`${f.exchange.toUpperCase()}:${f.symbol.split("/")[0]}USDT.P`)} className="shrink-0 rounded-lg bg-emerald-400/[0.06] border border-emerald-400/10 px-2.5 py-1.5 cursor-pointer hover:bg-emerald-400/10 transition-colors">
                    <div className="text-[11px] text-white font-bold">{f.symbol.split("/")[0]}</div>
                    <div className="text-[11px] text-emerald-400 font-mono font-bold">+{(f.rate * 100).toFixed(4)}%</div>
                    <div className="text-[11px] text-slate-600 capitalize">{f.exchange}</div>
                  </button>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-rose-500/10 bg-rose-500/[0.03] p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <span className="material-symbols-outlined text-rose-400 text-[14px]">trending_down</span>
                <span className="text-[11px] text-rose-400 uppercase tracking-wider font-bold">Lowest Funding (Shorts Pay)</span>
              </div>
              <div className="flex gap-2 overflow-x-auto">
                {topNegFunding.map(f => (
                  <button key={`${f.exchange}-${f.symbol}`} onClick={() => setSelectedSymbol(`${f.exchange.toUpperCase()}:${f.symbol.split("/")[0]}USDT.P`)} className="shrink-0 rounded-lg bg-rose-400/[0.06] border border-rose-400/10 px-2.5 py-1.5 cursor-pointer hover:bg-rose-400/10 transition-colors">
                    <div className="text-[11px] text-white font-bold">{f.symbol.split("/")[0]}</div>
                    <div className="text-[11px] text-rose-400 font-mono font-bold">{(f.rate * 100).toFixed(4)}%</div>
                    <div className="text-[11px] text-slate-600 capitalize">{f.exchange}</div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Funding Rate Arbitrage (left) + Funding Snapshot (right) ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
          <div className="rounded-xl border border-white/[0.06] overflow-hidden flex flex-col">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] flex items-center justify-between">
                <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-violet-400 text-[16px]">swap_horiz</span>
                  Funding Rate Arbitrage
                </h3>
                <span className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-[11px] text-emerald-400 font-bold">LIVE</span>
                </span>
              </div>
              <div className="divide-y divide-white/[0.04]">
                {fundingArbs.map((a, idx) => (
                  <div key={a.base} className={`px-3 py-1.5 flex items-center gap-2.5 hover:bg-white/[0.02] transition-colors cursor-pointer ${idx % 2 === 0 ? "bg-white/[0.01]" : ""}`}>
                    <div className="w-14 shrink-0">
                      <div className="flex items-center gap-1">
                        <span className="text-white text-[11px] font-bold">{a.base}</span>
                        {a.annualized > 20 && <span className="text-[10px] font-bold px-1 py-px rounded-full bg-emerald-400/15 text-emerald-400">HOT</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <div className="rounded bg-emerald-400/[0.05] border border-emerald-400/10 px-2 py-1 text-center min-w-[70px]">
                        <div className="text-[10px] text-slate-500 uppercase leading-none">Short</div>
                        <div className="text-[11px] text-emerald-400 font-bold capitalize leading-tight">{a.high.exchange}</div>
                        <div className="text-[11px] text-emerald-400 font-mono leading-tight">{(a.high.rate * 100).toFixed(4)}%</div>
                      </div>
                      <span className="material-symbols-outlined text-white/50 text-[12px] shrink-0">east</span>
                      <div className="rounded bg-violet-400/[0.05] border border-violet-400/10 px-2 py-1 text-center min-w-[70px]">
                        <div className="text-[10px] text-slate-500 uppercase leading-none">Long</div>
                        <div className="text-[11px] text-violet-400 font-bold capitalize leading-tight">{a.low.exchange}</div>
                        <div className="text-[11px] text-violet-400 font-mono leading-tight">{(a.low.rate * 100).toFixed(4)}%</div>
                      </div>
                    </div>
                    <div className="text-right shrink-0 min-w-[80px]">
                      <div className="text-[12px] font-bold text-emerald-400 font-mono">~{a.annualized.toFixed(1)}%</div>
                      <div className="text-[11px] text-slate-500 font-mono">Δ {(a.diff * 100).toFixed(4)}%/8h</div>
                    </div>
                  </div>
                ))}
              </div>
              {fundingArbs.length === 0 && (
                <div className="p-8 flex items-center justify-center flex-1">
                  <span className="text-[11px] text-slate-600">Calculating funding arbitrage…</span>
                </div>
              )}
          </div>

          {/* Funding Snapshot — exchange avg rates + sentiment */}
          <div className="rounded-xl border border-white/[0.06] overflow-hidden flex flex-col">
            <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] flex items-center justify-between">
              <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                <span className="material-symbols-outlined text-amber-400 text-[16px]">monitoring</span>
                Funding Snapshot
              </h3>
              <span className="text-[11px] text-slate-500 font-mono">{funding.length} pairs</span>
            </div>
            <div className="p-4 flex-1 flex flex-col gap-3">
              {/* Long/Short pressure bar */}
              {(() => {
                const posCount = funding.filter(f => f.rate > 0).length;
                const negCount = funding.filter(f => f.rate < 0).length;
                const posPct = funding.length > 0 ? (posCount / funding.length) * 100 : 50;
                return (
                  <div>
                    <div className="flex items-center justify-between text-[11px] font-bold mb-1.5">
                      <span className="text-emerald-400">Longs Pay {posPct.toFixed(0)}% ({posCount})</span>
                      <span className="text-rose-400">Shorts Pay {(100 - posPct).toFixed(0)}% ({negCount})</span>
                    </div>
                    <div className="h-3 rounded-full overflow-hidden flex bg-white/[0.03] border border-white/[0.04]">
                      <div className="h-full bg-gradient-to-r from-emerald-500/80 to-emerald-400/60 transition-all" style={{ width: `${posPct}%` }} />
                      <div className="h-full bg-gradient-to-r from-rose-400/60 to-rose-500/80 transition-all" style={{ width: `${100 - posPct}%` }} />
                    </div>
                  </div>
                );
              })()}

              {/* Per-exchange average funding */}
              <div className="flex-1 space-y-2">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider font-bold">Avg Rate by Exchange</div>
                {(() => {
                  const byEx = new Map<string, { sum: number; count: number }>();
                  for (const f of funding) {
                    const cur = byEx.get(f.exchange) || { sum: 0, count: 0 };
                    cur.sum += f.rate;
                    cur.count++;
                    byEx.set(f.exchange, cur);
                  }
                  return [...byEx.entries()]
                    .map(([ex, { sum, count }]) => ({ ex, avg: sum / count, count }))
                    .sort((a, b) => b.avg - a.avg)
                    .map((e) => {
                      const positive = e.avg >= 0;
                      const barW = Math.min(Math.abs(e.avg) * 100 * 50, 100);
                      return (
                        <div key={e.ex} className="flex items-center gap-2">
                          <span className="text-[11px] text-white font-bold w-20 shrink-0 capitalize">{e.ex}</span>
                          <div className="flex-1 h-5 bg-white/[0.03] rounded-lg overflow-hidden relative border border-white/[0.04]">
                            <div
                              className={`h-full rounded-lg transition-all duration-500 ${positive ? "bg-gradient-to-r from-emerald-500/50 to-emerald-400/20" : "bg-gradient-to-r from-rose-500/50 to-rose-400/20"}`}
                              style={{ width: `${Math.max(barW, 4)}%` }}
                            />
                            <span className="absolute inset-0 flex items-center px-2 text-[11px] text-white/60 font-mono font-bold">
                              {positive ? "+" : ""}{(e.avg * 100).toFixed(4)}%
                            </span>
                          </div>
                          <span className="text-[11px] text-slate-600 font-mono w-8 text-right shrink-0">{e.count}</span>
                        </div>
                      );
                    });
                })()}
              </div>
            </div>
          </div>
        </div>

        {/* ── TradingView Chart ── */}
        <div className="rounded-xl border border-white/[0.06] overflow-hidden">
          <div className="h-[380px] sm:h-[440px] w-full">
            <MemoizedWidget symbol={selectedSymbol} />
          </div>
        </div>

        <div className="grid grid-cols-12 gap-3 items-stretch">
          {/* ── Left: OI + Order Flow ── */}
          <div className="col-span-12 lg:col-span-7 flex flex-col gap-3">
            {/* Open Interest */}
            <div className="rounded-xl border border-white/[0.06] overflow-hidden">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02]">
                <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-cyan text-[16px]">donut_large</span>
                  Open Interest — Binance Perps
                </h3>
              </div>
              {oiData.length > 0 ? (
                <div>
                  {oiData.map((o, idx) => {
                    const base = o.symbol.split("/")[0];
                    const oiPct = totalOI > 0 ? (o.open_interest_usd / totalOI) * 100 : 0;
                    return (
                      <div key={o.symbol} className={`px-4 py-2.5 flex items-center gap-3 hover:bg-white/[0.02] transition-colors cursor-pointer border-b border-white/[0.03] last:border-0 ${idx % 2 === 0 ? "bg-white/[0.01]" : ""}`} onClick={() => setSelectedSymbol(`BINANCE:${base}USDT.P`)}>
                        <div className="w-20 shrink-0">
                          <span className="text-white text-[12px] font-bold">{base}<span className="text-slate-600 font-normal">-PERP</span></span>
                        </div>
                        <div className="flex-1 h-5 bg-white/[0.03] rounded-lg overflow-hidden relative border border-white/[0.04]">
                          <div className="h-full rounded-lg bg-gradient-to-r from-neon-cyan/40 to-neon-cyan/10 transition-all duration-500" style={{ width: `${Math.min(oiPct * 2.5, 100)}%` }} />
                          <span className="absolute inset-0 flex items-center px-2 text-[11px] text-white/60 font-mono font-bold">{oiPct.toFixed(1)}%</span>
                        </div>
                        <div className="text-right shrink-0 w-24">
                          <div className="text-[12px] font-bold text-neon-cyan font-mono">{fU(o.open_interest_usd)}</div>
                          <div className="text-[11px] text-slate-600 font-mono">{o.open_interest.toFixed(2)} ctrs</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="p-8 flex items-center justify-center gap-2">
                  {loading ? (
                    <>
                      <div className="w-4 h-4 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" />
                      <span className="text-[11px] text-slate-600">Loading OI data…</span>
                    </>
                  ) : (
                    <span className="text-[11px] text-slate-600">No OI data available</span>
                  )}
                </div>
              )}
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
                    <button key={s} onClick={() => loadOF(s)} className={`px-2.5 py-1 text-[11px] rounded-md font-bold cursor-pointer transition-all ${ofSymbol === s ? "bg-violet-500/20 text-violet-300 shadow-sm" : "text-slate-500 hover:text-white"}`}>{s.split("/")[0]}</button>
                  ))}
                </div>
              </div>
              {orderFlow ? (
                <div className="p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-white text-sm font-bold">{orderFlow.symbol}</span>
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

          {/* ── Right: Funding Rates Table ── */}
          <div className="col-span-12 lg:col-span-5">
            <div className="rounded-xl border border-white/[0.06] overflow-hidden h-full flex flex-col">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] shrink-0">
                <h3 className="text-white text-[13px] font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-violet-400 text-[16px]">percent</span>
                  All Funding Rates
                </h3>
                <span className="text-[11px] text-slate-600 mt-0.5">{funding.length} pairs across {EXCHANGES.length} exchanges</span>
              </div>
              <div className="flex-1 overflow-y-auto max-h-[600px]">
                {loading ? (
                  <div className="p-8 flex flex-col items-center justify-center gap-2">
                    <div className="w-5 h-5 rounded-full border-2 border-violet-500/20 border-t-violet-400 animate-spin" />
                    <span className="text-[11px] text-slate-600">Fetching funding rates...</span>
                  </div>
                ) : funding.slice(0, 50).map((f, i) => {
                  const base = f.symbol.split("/")[0];
                  const positive = f.rate >= 0;
                  return (
                    <div key={`${f.exchange}-${f.symbol}-${i}`} className={`px-4 py-2.5 flex items-center justify-between cursor-pointer transition-all border-b border-white/[0.03] last:border-0 hover:bg-white/[0.02] ${i % 2 === 0 ? "bg-white/[0.01]" : ""}`} onClick={() => setSelectedSymbol(`${f.exchange.toUpperCase()}:${base}USDT.P`)}>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-white text-[12px] font-bold">{base}</span>
                          <span className="text-[11px] text-slate-600 font-mono capitalize bg-white/[0.03] px-1 py-px rounded">{f.exchange}</span>
                        </div>
                        {f.annualized != null && (
                          <span className={`text-[11px] font-mono ${f.annualized >= 0 ? "text-emerald-400/50" : "text-rose-400/50"}`}>
                            {f.annualized >= 0 ? "+" : ""}{f.annualized.toFixed(1)}% APR
                          </span>
                        )}
                      </div>
                      <div className="text-right">
                        <div className={`text-[13px] font-mono font-bold ${positive ? "text-emerald-400" : "text-rose-400"}`}>
                          {positive ? "+" : ""}{(f.rate * 100).toFixed(4)}%
                        </div>
                        <span className="text-[11px] text-slate-600">per 8h</span>
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
            <span>Live · auto-refresh 30s</span>
          </div>
          <span className="text-[11px] text-slate-700">·</span>
          <span className="text-[11px] text-slate-600">{EXCHANGES.join(" · ")}</span>
        </div>
      </div>
    </AppShell>
  );
}
