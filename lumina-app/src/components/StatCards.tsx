import type { WhaleStats } from "@/app/whale-activity/page";

function fmtUsd(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return `${Math.floor(diff / 3600_000)}h ago`;
}

export default function StatCards({ stats, loading }: { stats: WhaleStats; loading: boolean }) {
  const isBullish = stats.buyPct >= 50;
  const sentiment = isBullish ? "Accumulating" : "Distributing";
  const sentimentTag = isBullish ? "BULLISH" : "BEARISH";
  const sentimentTagColor = isBullish
    ? "bg-accent-success/15 text-accent-success border-accent-success/20"
    : "bg-accent-error/15 text-accent-error border-accent-error/20";

  const impactScore = Math.min(10, Math.max(1, (stats.totalVolume / 500_000) * 2 + stats.tradeCount * 0.3)).toFixed(1);

  const largest = stats.largestTrade;
  const largestBase = largest ? largest.symbol.split("/")[0] : "—";
  const largestSideLabel = largest?.side === "buy" ? "Buy" : "Sell";
  const largestSideColor = largest?.side === "buy" ? "text-accent-success" : "text-accent-error";

  const topSymbols = Object.entries(stats.bySymbol)
    .sort(([, a], [, b]) => (b.buy + b.sell) - (a.buy + a.sell))
    .slice(0, 3)
    .map(([sym]) => sym);

  const skeleton = "animate-pulse bg-white/5 rounded h-5 w-20";

  return (
    <>
      {/* Whale Impact Summary — hero banner */}
      <div className="col-span-12 glass-panel glow-cyan rounded-xl p-3.5 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-neon-cyan/[0.03] via-transparent to-neon-lime/[0.03] pointer-events-none" />
        <div className="flex flex-col lg:flex-row items-start lg:items-center gap-3 relative z-10">
          <div className="flex items-center gap-2.5">
            <div className={`w-10 h-10 rounded-lg ${isBullish ? "bg-neon-cyan/10 border-neon-cyan/20" : "bg-accent-error/10 border-accent-error/20"} border flex items-center justify-center shrink-0`}>
              <span className={`material-symbols-outlined ${isBullish ? "text-neon-cyan" : "text-accent-error"} text-[20px]`}>
                {isBullish ? "trending_up" : "trending_down"}
              </span>
            </div>
            <div>
              <div className="flex items-center gap-2 mb-0.5">
                <h3 className="text-sm font-bold text-white">
                  {loading ? <span className={skeleton} /> : `Whales are ${sentiment.toLowerCase()}`}
                </h3>
                {!loading && (
                  <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded border ${sentimentTagColor}`}>{sentimentTag}</span>
                )}
              </div>
              <p className="text-xs text-slate-400">
                {loading
                  ? "Scanning whale trades across exchanges..."
                  : `${stats.tradeCount} whale trades detected. Buy side at ${stats.buyPct}%. ${topSymbols.length > 0 ? `Most active: ${topSymbols.join(", ")}.` : ""}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-6 lg:ml-auto shrink-0">
            <div className="text-center">
              <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-0.5">Buy / Sell</div>
              <div className="flex items-center gap-1">
                <span className="text-sm font-bold text-accent-success">{loading ? "—" : `${stats.buyPct}%`}</span>
                <span className="text-slate-600">/</span>
                <span className="text-sm font-bold text-accent-error">{loading ? "—" : `${stats.sellPct}%`}</span>
              </div>
            </div>
            <div className="w-px h-8 bg-white/10 hidden sm:block" />
            <div className="text-center">
              <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-0.5">Impact Score</div>
              <div className="text-sm font-bold text-neon-lime" style={{ textShadow: "0 0 8px rgba(204,255,0,0.3)" }}>
                {loading ? "—" : `${impactScore} / 10`}
              </div>
            </div>
            <div className="w-px h-8 bg-white/10 hidden sm:block" />
            <div className="text-center">
              <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-0.5">Whale Trades</div>
              <div className="text-sm font-bold text-white">{loading ? "—" : stats.tradeCount.toLocaleString()}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Stat cards */}
      <div className="col-span-12 grid grid-cols-2 lg:grid-cols-4 gap-2">
        <div className="glass-panel rounded-xl p-3 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-slate-400 text-[11px] font-medium uppercase tracking-wider">Total Volume</span>
            <span className="material-symbols-outlined text-neon-cyan text-[14px]">monitoring</span>
          </div>
          <h3 className="text-base font-bold text-white font-mono">{loading ? "—" : fmtUsd(stats.totalVolume)}</h3>
          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500">
            <span>Buy <span className="text-accent-success font-mono font-bold">{fmtUsd(stats.buyVolume)}</span></span>
            <span className="w-px h-2.5 bg-white/10" />
            <span>Sell <span className="text-accent-error font-mono font-bold">{fmtUsd(stats.sellVolume)}</span></span>
          </div>
        </div>

        <div className="glass-panel rounded-xl p-3 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-slate-400 text-[11px] font-medium uppercase tracking-wider">Buy Pressure</span>
            <span className={`text-[11px] font-bold ${isBullish ? "text-accent-success" : "text-accent-error"}`}>{isBullish ? "Bullish" : "Bearish"}</span>
          </div>
          <h3 className="text-base font-bold text-white">{loading ? "—" : `${stats.buyPct}%`}</h3>
          <div className="mt-1.5">
            <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden flex">
              <div className="h-full bg-accent-success rounded-l-full transition-all duration-700" style={{ width: `${stats.buyPct}%` }} />
              <div className="h-full bg-accent-error rounded-r-full transition-all duration-700" style={{ width: `${stats.sellPct}%` }} />
            </div>
          </div>
        </div>

        <div className="glass-panel rounded-xl p-3 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-slate-400 text-[11px] font-medium uppercase tracking-wider">Largest Move</span>
            {largest && <span className={`text-[11px] font-bold ${largestSideColor}`}>{largestSideLabel}</span>}
          </div>
          <h3 className="text-base font-bold text-white font-mono">{loading || !largest ? "—" : fmtUsd(largest.usd_value)}</h3>
          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500">
            {largest ? (
              <>
                <span>{largestBase} on <span className="text-white font-mono">{largest.exchange}</span></span>
                <span className="w-px h-2.5 bg-white/10" />
                <span>{timeAgo(largest.timestamp)}</span>
              </>
            ) : <span>No trades yet</span>}
          </div>
        </div>

        <div className="glass-panel rounded-xl p-3 hover:-translate-y-0.5 transition-all duration-300">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-slate-400 text-[11px] font-medium uppercase tracking-wider">Active Tokens</span>
            <span className="material-symbols-outlined text-accent-warning text-[14px]">token</span>
          </div>
          <h3 className="text-base font-bold text-white">{loading ? "—" : Object.keys(stats.bySymbol).length}</h3>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            {topSymbols.map((sym) => (
              <span key={sym} className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/15">{sym}</span>
            ))}
            {!loading && Object.keys(stats.bySymbol).length === 0 && <span className="text-[11px] text-slate-500">Scanning...</span>}
          </div>
        </div>
      </div>
    </>
  );
}
