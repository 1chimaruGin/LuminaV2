"use client";

import { useMemo } from "react";
import type { MarketOverview, Ticker, FundingRate, WhaleTrade } from "@/lib/api";

const fU = (v: number) => { if (v >= 1e9) return "$" + (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(1) + "M"; if (v >= 1e3) return "$" + (v/1e3).toFixed(0) + "K"; return "$" + v.toFixed(0); };

interface Props { overview: MarketOverview | null; tickers: Ticker[]; fundingRates: FundingRate[]; whaleTrades: WhaleTrade[]; }

export default function MarketSentimentHero({ overview, tickers, fundingRates, whaleTrades }: Props) {
  const score = overview?.fear_greed_index || 0;
  const label = overview?.fear_greed_label || "—";
  const noData = !overview;

  const scoreColor = score >= 75 ? "text-emerald-400" : score >= 50 ? "text-lime-400" : score >= 25 ? "text-amber-400" : "text-rose-400";
  const scoreBg = score >= 75 ? "bg-emerald-400" : score >= 50 ? "bg-lime-400" : score >= 25 ? "bg-amber-400" : "bg-rose-400";
  const scoreGlow = score >= 75 ? "shadow-emerald-400/20" : score >= 50 ? "shadow-lime-400/20" : score >= 25 ? "shadow-amber-400/20" : "shadow-rose-400/20";

  const { whaleBuyPct, signals, opportunities, risks } = useMemo(() => {
    const buyVol = whaleTrades.filter(t => t.side === "buy").reduce((a, t) => a + t.usd_value, 0);
    const sellVol = whaleTrades.filter(t => t.side === "sell").reduce((a, t) => a + t.usd_value, 0);
    const total = buyVol + sellVol || 1;
    const buyPct = Math.round((buyVol / total) * 100);
    const bias = buyPct >= 60 ? "Accumulating" : buyPct <= 40 ? "Distributing" : "Neutral";

    const avgFunding = fundingRates.length > 0 ? fundingRates.reduce((a, f) => a + f.rate, 0) / fundingRates.length : 0;
    const fundingLabel = avgFunding > 0.0003 ? "Elevated" : avgFunding < -0.0003 ? "Shorts Paying" : "Normal";

    const gainers = [...tickers].filter(t => (t.price_change_24h ?? 0) > 5 && t.volume_24h > 100000).sort((a, b) => (b.price_change_24h ?? 0) - (a.price_change_24h ?? 0)).slice(0, 3);
    const losers = [...tickers].filter(t => (t.price_change_24h ?? 0) < -5 && t.volume_24h > 100000).sort((a, b) => (a.price_change_24h ?? 0) - (b.price_change_24h ?? 0)).slice(0, 3);

    const sigs = [
      { label: "Whale Bias", value: bias, icon: "water", color: buyPct >= 50 ? "text-neon-cyan" : "text-rose-400", bg: buyPct >= 50 ? "bg-neon-cyan/8" : "bg-rose-400/8" },
      { label: "Buy Pressure", value: `${buyPct}%`, icon: "compare_arrows", color: buyPct >= 50 ? "text-emerald-400" : "text-rose-400", bg: buyPct >= 50 ? "bg-emerald-400/8" : "bg-rose-400/8" },
      { label: "Funding", value: fundingLabel, icon: "percent", color: avgFunding > 0.0003 ? "text-amber-400" : "text-emerald-400", bg: avgFunding > 0.0003 ? "bg-amber-400/8" : "bg-emerald-400/8" },
      { label: "Volatility", value: tickers.length > 0 ? (tickers.filter(t => Math.abs(t.price_change_24h ?? 0) > 5).length > tickers.length * 0.3 ? "High" : "Normal") : "—", icon: "bolt", color: "text-violet-400", bg: "bg-violet-400/8" },
    ];

    const opps = gainers.map(t => `${t.base} +${t.price_change_24h?.toFixed(1)}%`);
    const rsk: string[] = [];
    if (avgFunding > 0.0005) rsk.push("High funding — squeeze risk");
    rsk.push(...losers.map(t => `${t.base} ${t.price_change_24h?.toFixed(1)}%`));
    if (whaleTrades.some(t => t.side === "sell" && t.usd_value >= 200000)) {
      const big = whaleTrades.filter(t => t.side === "sell" && t.usd_value >= 200000)[0];
      rsk.unshift(`${big.symbol.split("/")[0]} whale sell ${fU(big.usd_value)}`);
    }

    return { whaleBuyPct: buyPct, signals: sigs, opportunities: opps.slice(0, 3), risks: rsk.slice(0, 3) };
  }, [overview, tickers, fundingRates, whaleTrades]);

  const btc = tickers.find(t => t.base === "BTC" && t.quote === "USDT");
  const eth = tickers.find(t => t.base === "ETH" && t.quote === "USDT");

  return (
    <div className="glass-panel rounded-xl relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-r from-white/[0.01] via-transparent to-white/[0.01] pointer-events-none" />

      <div className="grid grid-cols-12 gap-0 relative z-10">
        {/* ── Left: Sentiment Score ── */}
        <div className="col-span-12 lg:col-span-3 p-4 flex flex-col justify-center border-b lg:border-b-0 lg:border-r border-white/[0.06]">
          {noData ? (
            <div className="flex flex-col items-center gap-2 py-4">
              <div className="w-16 h-16 rounded-2xl bg-white/[0.04] animate-pulse" />
              <div className="w-24 h-3 rounded bg-white/[0.04] animate-pulse" />
              <div className="w-32 h-2 rounded bg-white/[0.04] animate-pulse" />
            </div>
          ) : (
            <>
              <div className="flex items-center gap-1.5 mb-3">
                <span className="material-symbols-outlined text-slate-500 text-[14px]">sentiment_satisfied</span>
                <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">Market Sentiment</span>
              </div>
              <div className="flex items-end gap-3 mb-2">
                <span className={`text-4xl font-bold font-mono ${scoreColor} leading-none`}>{score}</span>
                <span className={`text-sm font-bold ${scoreColor} mb-0.5`}>{label}</span>
              </div>
              {/* Horizontal bar indicator */}
              <div className="w-full h-2 rounded-full bg-white/[0.04] overflow-hidden mb-2">
                <div className={`h-full rounded-full ${scoreBg} transition-all duration-700 shadow-lg ${scoreGlow}`} style={{ width: `${score}%` }} />
              </div>
              <div className="flex justify-between text-[11px] text-slate-600 font-mono">
                <span>FEAR</span>
                <span>NEUTRAL</span>
                <span>GREED</span>
              </div>
              {/* Quick prices */}
              <div className="mt-3 pt-3 border-t border-white/[0.04] flex flex-col gap-1.5">
                {btc && (
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-500 font-medium">BTC</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-white font-mono font-bold">${btc.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                      <span className={`text-[11px] font-bold font-mono ${(btc.price_change_24h ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{(btc.price_change_24h ?? 0) >= 0 ? "+" : ""}{(btc.price_change_24h ?? 0).toFixed(2)}%</span>
                    </div>
                  </div>
                )}
                {eth && (
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-500 font-medium">ETH</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-white font-mono font-bold">${eth.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                      <span className={`text-[11px] font-bold font-mono ${(eth.price_change_24h ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{(eth.price_change_24h ?? 0) >= 0 ? "+" : ""}{(eth.price_change_24h ?? 0).toFixed(2)}%</span>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* ── Center: Market Verdict + Signal Grid ── */}
        <div className="col-span-12 lg:col-span-5 p-4 border-b lg:border-b-0 lg:border-r border-white/[0.06]">
          <div className="flex items-center gap-1.5 mb-2.5">
            <span className="material-symbols-outlined text-neon-cyan text-[14px]">emergency</span>
            <h3 className="text-[11px] font-bold text-white uppercase tracking-widest">Market Verdict</h3>
          </div>
          {noData ? (
            <div className="space-y-2">
              <div className="w-full h-3 rounded bg-white/[0.04] animate-pulse" />
              <div className="w-3/4 h-3 rounded bg-white/[0.04] animate-pulse" />
              <div className="grid grid-cols-2 gap-1.5 mt-3">
                {[1,2,3,4].map(i => <div key={i} className="h-12 rounded-lg bg-white/[0.03] animate-pulse" />)}
              </div>
            </div>
          ) : (
            <>
              <p className="text-[11px] text-slate-400 leading-relaxed mb-3">
                {whaleBuyPct >= 60 ? (
                  <>Whales <span className="text-neon-cyan font-bold">accumulating</span> with {whaleBuyPct}% buy pressure. </>
                ) : whaleBuyPct <= 40 ? (
                  <>Whales <span className="text-rose-400 font-bold">distributing</span> with {100 - whaleBuyPct}% sell pressure. </>
                ) : (
                  <>Whale activity <span className="text-amber-400 font-bold">neutral</span> at {whaleBuyPct}% buy. </>
                )}
                {btc ? (
                  <>BTC trading at <span className="text-white font-semibold">${btc.price.toLocaleString()}</span>. </>
                ) : null}
                {fundingRates.length > 0 && fundingRates.some(f => Math.abs(f.rate) > 0.0005) ? (
                  <span className="text-amber-400">Elevated funding — watch for squeeze.</span>
                ) : (
                  <span className="text-slate-500">Funding rates within normal range.</span>
                )}
              </p>
              <div className="grid grid-cols-2 gap-1.5">
                {signals.map((s) => (
                  <div key={s.label} className={`${s.bg} rounded-lg px-2.5 py-2 border border-white/[0.04]`}>
                    <div className="flex items-center gap-1 mb-0.5">
                      <span className={`material-symbols-outlined text-[12px] ${s.color}`}>{s.icon}</span>
                      <span className="text-[11px] text-slate-500 uppercase tracking-wider font-medium">{s.label}</span>
                    </div>
                    <span className={`text-[12px] font-bold ${s.color}`}>{s.value}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* ── Right: Opportunities & Risks ── */}
        <div className="col-span-12 lg:col-span-4 p-4">
          <div className="flex items-center gap-1.5 mb-2.5">
            <span className="material-symbols-outlined text-violet-400 text-[14px]">radar</span>
            <h3 className="text-[11px] font-bold text-white uppercase tracking-widest">Radar</h3>
            <span className="ml-auto flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-[11px] text-emerald-400 font-bold">LIVE</span>
            </span>
          </div>
          {noData ? (
            <div className="space-y-2">
              {[1,2].map(i => <div key={i} className="h-20 rounded-lg bg-white/[0.03] animate-pulse" />)}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="rounded-lg bg-emerald-500/[0.04] border border-emerald-500/10 p-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[11px] font-bold text-emerald-400 uppercase tracking-wider">Opportunities</span>
                  <span className="text-[11px] font-bold text-emerald-400 font-mono bg-emerald-400/10 px-1.5 py-0.5 rounded">{opportunities.length}</span>
                </div>
                <div className="space-y-1">
                  {opportunities.length === 0 && <span className="text-[11px] text-slate-600">No standout movers</span>}
                  {opportunities.map((o, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      <span className="w-1 h-1 rounded-full bg-emerald-400 shrink-0" />
                      <span className="text-[11px] text-slate-300 font-medium">{o}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-lg bg-rose-500/[0.04] border border-rose-500/10 p-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[11px] font-bold text-rose-400 uppercase tracking-wider">Risk Alerts</span>
                  <span className="text-[11px] font-bold text-rose-400 font-mono bg-rose-400/10 px-1.5 py-0.5 rounded">{risks.length}</span>
                </div>
                <div className="space-y-1">
                  {risks.length === 0 && <span className="text-[11px] text-slate-600">No critical risks</span>}
                  {risks.map((r, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      <span className="w-1 h-1 rounded-full bg-rose-400 shrink-0" />
                      <span className="text-[11px] text-slate-300 font-medium">{r}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-lg bg-white/[0.02] border border-white/[0.04] px-2.5 py-1.5 flex items-center justify-between">
                <div className="text-[11px] text-slate-500">
                  <span className="text-neon-cyan font-bold font-mono">{overview?.exchanges_count || 0}</span> exchanges ·
                  <span className="text-white/70 font-bold font-mono ml-0.5">{(overview?.active_pairs || 0).toLocaleString()}</span> pairs
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
