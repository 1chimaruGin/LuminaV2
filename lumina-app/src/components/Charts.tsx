import { useMemo } from "react";
import type { WhaleStats } from "@/app/whale-activity/page";

function fmtUsd(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function WhaleRetailVolChart({ stats }: { stats: WhaleStats }) {
  const bars = useMemo(() => {
    const entries = Object.entries(stats.bySymbol)
      .sort(([, a], [, b]) => (b.buy + b.sell) - (a.buy + a.sell))
      .slice(0, 7);
    return entries.map(([sym, data]) => ({
      label: sym,
      buy: data.buy,
      sell: data.sell,
      total: data.buy + data.sell,
    }));
  }, [stats.bySymbol]);

  const max = Math.max(...bars.map((b) => b.total), 1);

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden h-full">
      <div className="px-3.5 py-2.5 border-b border-white/5 bg-white/[0.03] flex items-center justify-between shrink-0">
        <h4 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-neon-cyan text-[14px]">bar_chart</span>
          Buy vs Sell by Token
        </h4>
        <div className="flex items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1 text-slate-400"><span className="w-2 h-2 rounded-sm bg-accent-success/80" />Buy</span>
          <span className="flex items-center gap-1 text-slate-400"><span className="w-2 h-2 rounded-sm bg-accent-error/60" />Sell</span>
        </div>
      </div>
      <div className="flex-1 p-3">
        {bars.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <p className="text-slate-600 text-xs">Waiting for trade data...</p>
          </div>
        ) : (
          <svg viewBox="0 0 280 140" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
            {[35, 70, 105].map((y) => (
              <line key={y} x1="0" x2="280" y1={y} y2={y} stroke="rgba(255,255,255,0.03)" />
            ))}
            {bars.map((bar, i) => {
              const x = i * 40 + 8;
              const buyH = (bar.buy / max) * 110;
              const sellH = (bar.sell / max) * 110;
              return (
                <g key={bar.label}>
                  <rect x={x} y={120 - buyH} width="14" height={Math.max(buyH, 2)} rx="2" fill="rgba(11,218,94,0.7)" />
                  <rect x={x + 16} y={120 - sellH} width="14" height={Math.max(sellH, 2)} rx="2" fill="rgba(255,68,68,0.5)" />
                  <text x={x + 15} y="135" textAnchor="middle" fill="#64748b" fontSize="8" fontFamily="monospace">{bar.label}</text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <div className="px-3.5 py-1.5 border-t border-white/5 flex items-center justify-between text-[11px] text-slate-500">
        <span>Buy dominance: <span className="text-accent-success font-bold font-mono">{stats.buyPct}%</span></span>
        <span>Total: <span className="text-white font-bold font-mono">{fmtUsd(stats.totalVolume)}</span></span>
      </div>
    </div>
  );
}

export function NetFlowChart({ stats }: { stats: WhaleStats }) {
  const flows = useMemo(() => {
    return Object.entries(stats.bySymbol)
      .map(([sym, data]) => ({
        name: sym,
        net: data.buy - data.sell,
      }))
      .sort((a, b) => b.net - a.net)
      .slice(0, 8);
  }, [stats.bySymbol]);

  const maxAbs = Math.max(...flows.map((f) => Math.abs(f.net)), 1);
  const totalNet = flows.reduce((sum, f) => sum + f.net, 0);
  const isNetBuy = totalNet >= 0;

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden h-full">
      <div className="px-3.5 py-2.5 border-b border-white/5 bg-white/[0.03] flex items-center justify-between shrink-0">
        <h4 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-slate-400 text-[14px]">compare_arrows</span>
          Net Buy/Sell by Token
        </h4>
        <span className="text-[11px] text-slate-500">Net: <span className={`font-bold ${isNetBuy ? "text-accent-success" : "text-accent-error"}`}>{isNetBuy ? "+" : ""}{fmtUsd(totalNet)}</span></span>
      </div>
      <div className="flex-1 p-3 flex flex-col justify-center gap-2">
        {flows.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <p className="text-slate-600 text-xs">Waiting for trade data...</p>
          </div>
        ) : flows.map((flow) => {
          const pct = (Math.abs(flow.net) / maxAbs) * 100;
          const isSell = flow.net < 0;
          return (
            <div key={flow.name} className="flex items-center gap-2 group">
              <span className="text-[11px] font-medium text-slate-400 w-12 text-right shrink-0 font-mono">{flow.name}</span>
              <div className="flex-1 flex items-center">
                <div className="w-1/2 flex justify-end">
                  {isSell && (
                    <div
                      className="h-3.5 bg-accent-error/50 group-hover:bg-accent-error/70 rounded-l-sm transition-colors"
                      style={{ width: `${pct}%` }}
                    />
                  )}
                </div>
                <div className="w-px h-5 bg-white/10 shrink-0" />
                <div className="w-1/2">
                  {!isSell && (
                    <div
                      className="h-3.5 bg-accent-success/50 group-hover:bg-accent-success/70 rounded-r-sm transition-colors"
                      style={{ width: `${pct}%` }}
                    />
                  )}
                </div>
              </div>
              <span className={`text-[11px] font-mono font-bold w-14 shrink-0 ${isSell ? "text-accent-error" : "text-accent-success"}`}>
                {isSell ? "-" : "+"}{fmtUsd(Math.abs(flow.net))}
              </span>
            </div>
          );
        })}
      </div>
      <div className="px-3.5 py-1.5 border-t border-white/5 flex items-center justify-between text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-accent-error/50" />Net sell</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-accent-success/50" />Net buy</span>
      </div>
    </div>
  );
}
