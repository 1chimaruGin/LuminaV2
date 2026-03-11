"use client";

import { useMemo } from "react";
import type { RawWhaleTrade } from "@/app/whale-activity/page";

function fmtUsd(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

const RANK_STYLES = [
  { rankColor: "bg-accent-warning", rankTextColor: "text-black", barColor: "bg-accent-warning", accentColor: "border-accent-warning/20 hover:border-accent-warning/50" },
  { rankColor: "bg-slate-500", rankTextColor: "text-black", barColor: "bg-slate-600", accentColor: "border-white/5 hover:border-white/20" },
  { rankColor: "bg-orange-700", rankTextColor: "text-white", barColor: "bg-orange-700", accentColor: "border-white/5 hover:border-white/20" },
  { rankColor: "bg-slate-600", rankTextColor: "text-white", barColor: "bg-slate-700", accentColor: "border-white/5 hover:border-white/20" },
];

interface Props {
  trades: RawWhaleTrade[];
}

export default function SmartMoney({ trades }: Props) {
  const topTokens = useMemo(() => {
    const map: Record<string, { buy: number; sell: number; count: number; biggest: number }> = {};
    for (const t of trades) {
      const base = t.symbol.split("/")[0];
      if (!map[base]) map[base] = { buy: 0, sell: 0, count: 0, biggest: 0 };
      map[base].count++;
      if (t.side === "buy") map[base].buy += t.usd_value;
      else map[base].sell += t.usd_value;
      if (t.usd_value > map[base].biggest) map[base].biggest = t.usd_value;
    }
    return Object.entries(map)
      .map(([sym, data]) => ({ sym, total: data.buy + data.sell, ...data }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 4);
  }, [trades]);

  return (
    <div className="glass-panel rounded-xl p-3.5 flex-1 flex flex-col min-h-[320px]">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-accent-warning text-[15px]">emoji_events</span>
          Top Whale Tokens
        </h3>
        <span className="text-[11px] text-slate-500">By whale trade volume</span>
      </div>
      <div className="flex-1 flex flex-col gap-2.5 overflow-y-auto pr-1">
        {topTokens.length === 0 ? (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-slate-600 text-xs">Waiting for whale data...</p>
          </div>
        ) : topTokens.map((entry, idx) => {
          const style = RANK_STYLES[idx] || RANK_STYLES[3];
          const netBuy = entry.buy - entry.sell;
          const isBullish = netBuy >= 0;
          const buyPct = Math.round((entry.buy / (entry.total || 1)) * 100);

          return (
            <div
              key={entry.sym}
              className={`relative p-3 rounded-lg bg-gradient-to-r from-slate-800/40 to-slate-900/40 border ${style.accentColor} transition-all group cursor-pointer`}
            >
              <div
                className={`absolute -left-px top-4 bottom-4 w-1 ${style.barColor} rounded-r-full`}
                style={idx === 0 ? { boxShadow: "0 0 10px rgba(255,176,32,0.5)" } : {}}
              />
              <div className="flex justify-between items-start mb-1.5">
                <div className="flex items-center gap-2.5">
                  <div className="h-8 w-8 rounded-full bg-slate-800 flex items-center justify-center text-xs border border-white/10 relative overflow-hidden">
                    <div className="w-full h-full bg-gradient-to-br from-slate-700 to-slate-800 flex items-center justify-center">
                      <span className="text-white font-bold text-[11px]">{entry.sym}</span>
                    </div>
                    <div className={`absolute -top-1 -right-1 ${style.rankColor} ${style.rankTextColor} text-[11px] font-bold px-1 rounded-sm`}>
                      #{idx + 1}
                    </div>
                  </div>
                  <div>
                    <div className="text-white text-sm font-bold">{entry.sym}/USDT</div>
                    <div className="flex gap-1 mt-0.5">
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20">
                        {entry.count} trades
                      </span>
                      <span className={`text-[11px] px-1.5 py-0.5 rounded ${isBullish ? "bg-accent-success/10 text-accent-success border border-accent-success/20" : "bg-accent-error/10 text-accent-error border border-accent-error/20"}`}>
                        {isBullish ? "Net Buy" : "Net Sell"}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-white font-bold text-sm font-mono">{fmtUsd(entry.total)}</div>
                  <div className="text-[11px] text-slate-400">Total Vol</div>
                </div>
              </div>
              <div className="mt-2">
                <div className="flex items-center justify-between text-[11px] mb-1">
                  <span className="text-accent-success font-bold">Buy {buyPct}%</span>
                  <span className="text-slate-500">Largest: {fmtUsd(entry.biggest)}</span>
                  <span className="text-accent-error font-bold">Sell {100 - buyPct}%</span>
                </div>
                <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden flex">
                  <div className="h-full bg-accent-success/70 rounded-l-full transition-all duration-700" style={{ width: `${buyPct}%` }} />
                  <div className="h-full bg-accent-error/50 rounded-r-full transition-all duration-700" style={{ width: `${100 - buyPct}%` }} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
