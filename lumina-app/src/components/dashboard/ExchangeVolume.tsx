"use client";

import { useMemo } from "react";
import type { Ticker } from "@/lib/api";

const fV = (v: number) => { if (v >= 1e9) return "$" + (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(0) + "M"; if (v >= 1e3) return "$" + (v/1e3).toFixed(0) + "K"; return "$" + v.toFixed(0); };
const COLORS = ["bg-accent-warning", "bg-indigo-500", "bg-neon-cyan", "bg-blue-400", "bg-pink-500", "bg-neon-purple", "bg-neon-lime", "bg-violet-500"];

interface Props { tickers: Ticker[]; loading: boolean; }

export default function ExchangeVolume({ tickers, loading }: Props) {
  const exchangeData = useMemo(() => {
    const byExchange: Record<string, number> = {};
    for (const t of tickers) {
      const ex = t.exchange || "unknown";
      byExchange[ex] = (byExchange[ex] || 0) + (t.volume_24h || 0);
    }
    const totalVol = Object.values(byExchange).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(byExchange)
      .map(([name, vol]) => ({ name, vol, pct: (vol / totalVol) * 100 }))
      .sort((a, b) => b.vol - a.vol)
      .slice(0, 8);
  }, [tickers]);

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden h-full">
      <div className="px-3.5 py-2.5 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-neon-cyan text-[15px]">bar_chart</span>
          Exchange Volume (24h)
        </h3>
        <span className="text-[11px] text-slate-500 font-bold">LIVE</span>
      </div>
      <div className="flex-1 overflow-y-auto p-2.5 space-y-1">
        {loading && exchangeData.length === 0 && (
          <div className="py-6 text-center text-slate-500 text-xs">Loading...</div>
        )}
        {exchangeData.map((ex, i) => (
          <div key={ex.name} className="flex items-center gap-2.5 group hover:bg-white/[0.03] rounded-md px-2 py-1 transition-colors cursor-pointer">
            <span className="text-slate-600 text-[11px] font-mono w-4">{i + 1}</span>
            <div className={`w-2 h-2 rounded-full ${COLORS[i] || "bg-slate-500"} shrink-0`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-white text-xs font-bold capitalize">{ex.name}</span>
                <span className="text-[11px] font-bold px-1 py-px rounded bg-neon-cyan/10 text-neon-cyan/70">CEX</span>
              </div>
              <div className="h-1 bg-white/[0.04] rounded-full mt-1 overflow-hidden">
                <div className={`h-full ${COLORS[i] || "bg-slate-500"} rounded-full transition-all duration-500`} style={{ width: `${Math.min(ex.pct * 2, 100)}%` }} />
              </div>
            </div>
            <div className="text-right shrink-0">
              <span className="text-white text-xs font-mono font-bold block">{fV(ex.vol)}</span>
              <span className="text-[11px] text-slate-500">{ex.pct.toFixed(1)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
