"use client";

import type { MarketOverview } from "@/lib/api";

const fU = (v: number) => { if (v >= 1e12) return "$" + (v/1e12).toFixed(2) + "T"; if (v >= 1e9) return "$" + (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(1) + "M"; return "$" + v.toLocaleString(); };

function Shimmer({ w = "w-20", h = "h-5" }: { w?: string; h?: string }) {
  return <div className={`${w} ${h} rounded bg-white/[0.06] animate-pulse`} />;
}

interface Props { overview: MarketOverview | null; loading: boolean; }

export default function DashboardStatCards({ overview, loading }: Props) {
  const ov = overview;
  const noData = loading && !ov;
  const mcap = ov?.total_market_cap || 0;
  const vol = ov?.total_volume_24h || 0;
  const btcDom = ov?.btc_dominance || 0;
  const ethDom = ov?.eth_dominance || 0;
  const altDom = Math.max(0, 100 - btcDom - ethDom);
  const pairs = ov?.active_pairs || 0;
  const exchanges = ov?.exchanges_count || 0;

  return (
    <>
      <div className="col-span-12 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        {/* Global Market Cap */}
        <div className="glass-panel rounded-xl p-3.5 relative overflow-hidden group hover:border-neon-cyan/30 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex justify-between items-start mb-1 relative z-10">
            <div>
              <p className="text-slate-400 text-[11px] font-medium uppercase tracking-wide">Global Market Cap</p>
              {noData ? <Shimmer w="w-28" h="h-6" /> : <h3 className="text-lg font-bold text-white mt-0.5">{fU(mcap)}</h3>}
            </div>
            <span className="material-symbols-outlined text-neon-lime text-[16px]">monitoring</span>
          </div>
          {noData ? <Shimmer w="w-40" h="h-3" /> : (
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span>BTC approx: <span className="text-white font-mono">{fU(mcap * btcDom / 100)}</span></span>
              <span className="w-px h-3 bg-white/10"></span>
              <span>Pairs: <span className="text-neon-cyan font-mono">{pairs.toLocaleString()}</span></span>
            </div>
          )}
        </div>

        {/* 24h Global Volume */}
        <div className="glass-panel rounded-xl p-3.5 relative overflow-hidden group hover:border-accent-success/30 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex justify-between items-start mb-1 relative z-10">
            <div>
              <p className="text-slate-400 text-[11px] font-medium uppercase tracking-wide">24h Volume</p>
              {noData ? <Shimmer w="w-24" h="h-6" /> : <h3 className="text-lg font-bold text-white mt-0.5">{fU(vol)}</h3>}
            </div>
            <span className="material-symbols-outlined text-accent-success text-[16px]">bar_chart</span>
          </div>
          {noData ? <Shimmer w="w-32" h="h-3" /> : (
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span>Across <span className="text-white font-mono">{exchanges}</span> exchanges</span>
            </div>
          )}
        </div>

        {/* BTC Dominance */}
        <div className="glass-panel rounded-xl p-3.5 relative overflow-hidden group hover:border-neon-purple/30 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex justify-between items-start mb-1 relative z-10">
            <div>
              <p className="text-slate-400 text-[11px] font-medium uppercase tracking-wide">BTC Dominance</p>
              {noData ? <Shimmer w="w-16" h="h-6" /> : <h3 className="text-lg font-bold text-white mt-0.5">{btcDom.toFixed(1)}%</h3>}
            </div>
            <span className="material-symbols-outlined text-accent-warning text-[16px]">pie_chart</span>
          </div>
          {noData ? <Shimmer w="w-full" h="h-1.5" /> : (
            <>
              <div className="flex items-center gap-2 text-[11px] text-slate-500">
                <span>ETH: <span className="text-white font-mono">{ethDom.toFixed(1)}%</span></span>
                <span className="w-px h-3 bg-white/10"></span>
                <span>Alts: <span className="text-neon-purple font-mono">{altDom.toFixed(1)}%</span></span>
              </div>
              <div className="h-1.5 w-full bg-slate-800 rounded-full mt-2.5 overflow-hidden">
                <div className="h-full flex">
                  <div className="bg-accent-warning rounded-l-full" style={{ width: `${btcDom}%` }}></div>
                  <div className="bg-indigo-500" style={{ width: `${ethDom}%` }}></div>
                  <div className="bg-neon-purple rounded-r-full" style={{ width: `${altDom}%` }}></div>
                </div>
              </div>
              <div className="flex justify-between text-[11px] text-slate-500 mt-1">
                <span className="text-accent-warning">BTC</span>
                <span className="text-indigo-400">ETH</span>
                <span className="text-neon-purple">Alts</span>
              </div>
            </>
          )}
        </div>

        {/* Sentiment */}
        <div className="glass-panel rounded-xl p-3.5 relative overflow-hidden group hover:border-neon-lime/30 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex justify-between items-start mb-1 relative z-10">
            <div>
              <p className="text-slate-400 text-[11px] font-medium uppercase tracking-wide">Fear & Greed</p>
              {noData ? <Shimmer w="w-12" h="h-6" /> : <h3 className="text-lg font-bold text-white mt-0.5">{ov?.fear_greed_index || 0}</h3>}
            </div>
            {noData ? <Shimmer w="w-20" h="h-5" /> : (
              <span className={`text-xs font-bold px-2 py-0.5 rounded ${(ov?.fear_greed_index || 0) >= 60 ? "bg-accent-success/15 text-accent-success" : (ov?.fear_greed_index || 0) >= 40 ? "bg-accent-warning/15 text-accent-warning" : "bg-accent-error/15 text-accent-error"}`}>
                {ov?.fear_greed_label || "—"}
              </span>
            )}
          </div>
          {noData ? <Shimmer w="w-full" h="h-1.5" /> : (
            <>
              <div className="h-1.5 w-full bg-slate-800 rounded-full mt-2.5 overflow-hidden">
                <div className="h-full bg-gradient-to-r from-accent-error via-accent-warning to-accent-success rounded-full transition-all duration-700" style={{ width: `${ov?.fear_greed_index || 0}%` }}></div>
              </div>
              <div className="flex justify-between text-[11px] text-slate-500 mt-1">
                <span>Extreme Fear</span>
                <span>Neutral</span>
                <span>Extreme Greed</span>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
