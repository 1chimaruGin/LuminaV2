import type { WhaleTrade } from "@/lib/api";

const fU = (v: number) => { if (v >= 1e9) return "$" + (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(1) + "M"; if (v >= 1e3) return "$" + (v/1e3).toFixed(0) + "K"; return "$" + v.toFixed(0); };

function timeAgo(ts: string) {
  const d = Date.now() - new Date(ts).getTime();
  if (d < 60000) return "Just now";
  if (d < 3600000) return Math.floor(d / 60000) + "m ago";
  if (d < 86400000) return Math.floor(d / 3600000) + "h ago";
  return Math.floor(d / 86400000) + "d ago";
}

function signal(side: string | undefined, usd: number) {
  if (side === "buy" && usd >= 500000) return { label: "Whale Buy", color: "text-accent-success", bg: "bg-accent-success/10", icon: "trending_up", iconColor: "text-accent-success" };
  if (side === "sell" && usd >= 500000) return { label: "Whale Sell", color: "text-accent-error", bg: "bg-accent-error/10", icon: "trending_down", iconColor: "text-accent-error" };
  if (side === "buy") return { label: "Buy", color: "text-neon-cyan", bg: "bg-neon-cyan/10", icon: "arrow_upward", iconColor: "text-neon-cyan" };
  return { label: "Sell", color: "text-accent-warning", bg: "bg-accent-warning/10", icon: "arrow_downward", iconColor: "text-accent-warning" };
}

interface Props { trades: WhaleTrade[]; loading: boolean; }

export default function WhaleMovementTracker({ trades, loading }: Props) {
  const top = trades.slice(0, 8);

  return (
    <div className="glass-panel rounded-xl overflow-hidden">
      <div className="px-3.5 py-2.5 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-neon-cyan text-[15px]">water</span>
          Recent Whale Trades
        </h3>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-cyan opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-neon-cyan"></span>
            </span>
            <span className="text-[11px] text-neon-cyan font-bold">LIVE</span>
          </div>
          <a href="/whale-activity" className="text-[11px] text-neon-cyan hover:underline font-bold flex items-center gap-0.5">
            View All <span className="material-symbols-outlined text-[11px]">arrow_forward</span>
          </a>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 text-[11px] uppercase tracking-wider border-b border-white/5">
              <th className="text-left px-3 py-1.5 font-medium">Asset</th>
              <th className="text-left px-3 py-1.5 font-medium hidden sm:table-cell">Side</th>
              <th className="text-right px-3 py-1.5 font-medium">Value</th>
              <th className="text-left px-3 py-1.5 font-medium hidden md:table-cell">Exchange</th>
              <th className="text-center px-3 py-1.5 font-medium">Signal</th>
              <th className="text-right px-3 py-1.5 font-medium">Time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading && top.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-slate-500 text-xs">Loading whale trades...</td></tr>
            )}
            {top.map((t, i) => {
              const base = t.symbol.split("/")[0];
              const s = signal(t.side, t.usd_value);
              return (
                <tr key={i} className="hover:bg-white/[0.03] transition-colors cursor-pointer">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className={`material-symbols-outlined text-[13px] ${s.iconColor}`}>{s.icon}</span>
                      <span className="text-white font-bold">{base}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 hidden sm:table-cell">
                    <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${t.side === "buy" ? "bg-accent-success/10 text-accent-success" : "bg-accent-error/10 text-accent-error"}`}>{t.side?.toUpperCase() || "—"}</span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <span className="text-white font-bold font-mono">{fU(t.usd_value)}</span>
                    <span className="text-slate-500 text-[11px] block">{t.amount.toFixed(4)} {base}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-300 hidden md:table-cell">{t.exchange || "—"}</td>
                  <td className="px-3 py-2 text-center">
                    <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${s.bg} ${s.color}`}>{s.label}</span>
                  </td>
                  <td className="px-3 py-2 text-right text-slate-500 font-mono">{t.timestamp ? timeAgo(t.timestamp) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
