"use client";

import { useState } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";

/* ── Per-pair funding data ── */
interface ExSource { name: string; type: "CEX" | "DEX"; rate: string }
interface PairFunding {
  symbol: string; label: string; price: string;
  exchanges: ExSource[];
  hero: { title: string; badge: string; badgeColor: string; desc: string; avgRate: string; nextReset: string };
  stats: { label: string; value: string; change: string; icon: string; color: string }[];
  table: { symbol: string; rate: string; annualized: string; predicted: string; oi: string; sentiment: string }[];
}

const pairMap: Record<string, PairFunding> = {
  "BTC-PERP": {
    symbol: "BTC-PERP", label: "Bitcoin", price: "$67,420",
    exchanges: [
      { name: "Binance", type: "CEX", rate: "+0.0042%" },
      { name: "Bybit", type: "CEX", rate: "+0.0038%" },
      { name: "OKX", type: "CEX", rate: "+0.0045%" },
      { name: "dYdX", type: "DEX", rate: "+0.0032%" },
      { name: "Hyperliquid", type: "DEX", rate: "+0.0028%" },
    ],
    hero: { title: "DOGE funding overheated — squeeze risk", badge: "OVERCROWDED LONGS", badgeColor: "accent-warning", desc: "DOGE +0.008% funding = 30% annualized. Longs paying heavy premiums. SOL and ARB also elevated. BNB and OP are negative — shorts paying.", avgRate: "+0.0034%", nextReset: "2h 14m" },
    stats: [
      { label: "Avg Funding Rate", value: "+0.0034%", change: "Longs paying shorts", icon: "percent", color: "text-neon-cyan" },
      { label: "Annualized Avg", value: "+12.4%", change: "Carry trade viable", icon: "trending_up", color: "text-accent-success" },
      { label: "Highest Funding", value: "DOGE +0.008%", change: "Overcrowded long", icon: "local_fire_department", color: "text-accent-warning" },
      { label: "Next Reset", value: "2h 14m", change: "Every 8 hours", icon: "schedule", color: "text-neon-purple" },
    ],
    table: [
      { symbol: "BTC-PERP", rate: "+0.0042%", annualized: "+15.3%", predicted: "+0.0038%", oi: "$4.2B", sentiment: "Bullish" },
      { symbol: "ETH-PERP", rate: "+0.0038%", annualized: "+13.9%", predicted: "+0.0035%", oi: "$2.1B", sentiment: "Bullish" },
      { symbol: "SOL-PERP", rate: "+0.0065%", annualized: "+23.7%", predicted: "+0.0058%", oi: "$680M", sentiment: "Very Bullish" },
      { symbol: "DOGE-PERP", rate: "+0.0082%", annualized: "+29.9%", predicted: "+0.0074%", oi: "$240M", sentiment: "Extremely Bullish" },
      { symbol: "BNB-PERP", rate: "-0.0012%", annualized: "-4.4%", predicted: "-0.0008%", oi: "$420M", sentiment: "Neutral" },
      { symbol: "XRP-PERP", rate: "+0.0018%", annualized: "+6.6%", predicted: "+0.0015%", oi: "$310M", sentiment: "Mildly Bullish" },
      { symbol: "AVAX-PERP", rate: "+0.0045%", annualized: "+16.4%", predicted: "+0.0040%", oi: "$180M", sentiment: "Bullish" },
      { symbol: "LINK-PERP", rate: "+0.0028%", annualized: "+10.2%", predicted: "+0.0025%", oi: "$120M", sentiment: "Bullish" },
      { symbol: "ARB-PERP", rate: "+0.0055%", annualized: "+20.1%", predicted: "+0.0048%", oi: "$95M", sentiment: "Bullish" },
      { symbol: "OP-PERP", rate: "-0.0022%", annualized: "-8.0%", predicted: "-0.0018%", oi: "$68M", sentiment: "Bearish" },
    ],
  },
  "ETH-PERP": {
    symbol: "ETH-PERP", label: "Ethereum", price: "$3,245",
    exchanges: [
      { name: "Binance", type: "CEX", rate: "+0.0038%" },
      { name: "Bybit", type: "CEX", rate: "+0.0035%" },
      { name: "OKX", type: "CEX", rate: "+0.0040%" },
      { name: "dYdX", type: "DEX", rate: "+0.0025%" },
      { name: "Uniswap", type: "DEX", rate: "+0.0018%" },
    ],
    hero: { title: "ETH funding mild — room to run", badge: "NEUTRAL-BULLISH", badgeColor: "accent-success", desc: "ETH funding at +0.0038% is sustainable. No overcrowding detected. Delta between CEX (+0.0038%) and DEX (+0.0022%) suggests CEX longs slightly heavier.", avgRate: "+0.0031%", nextReset: "2h 14m" },
    stats: [
      { label: "Avg Funding Rate", value: "+0.0031%", change: "Mild long bias", icon: "percent", color: "text-neon-cyan" },
      { label: "Annualized Avg", value: "+11.3%", change: "Sustainable level", icon: "trending_up", color: "text-accent-success" },
      { label: "CEX vs DEX Delta", value: "0.0016%", change: "CEX heavier", icon: "compare_arrows", color: "text-accent-warning" },
      { label: "Next Reset", value: "2h 14m", change: "Every 8 hours", icon: "schedule", color: "text-neon-purple" },
    ],
    table: [
      { symbol: "Binance", rate: "+0.0038%", annualized: "+13.9%", predicted: "+0.0035%", oi: "$820M", sentiment: "Bullish" },
      { symbol: "Bybit", rate: "+0.0035%", annualized: "+12.8%", predicted: "+0.0032%", oi: "$420M", sentiment: "Bullish" },
      { symbol: "OKX", rate: "+0.0040%", annualized: "+14.6%", predicted: "+0.0036%", oi: "$380M", sentiment: "Bullish" },
      { symbol: "dYdX", rate: "+0.0025%", annualized: "+9.1%", predicted: "+0.0022%", oi: "$95M", sentiment: "Mildly Bullish" },
      { symbol: "Uniswap", rate: "+0.0018%", annualized: "+6.6%", predicted: "+0.0015%", oi: "$42M", sentiment: "Neutral" },
    ],
  },
  "SOL-PERP": {
    symbol: "SOL-PERP", label: "Solana", price: "$148.20",
    exchanges: [
      { name: "Binance", type: "CEX", rate: "+0.0065%" },
      { name: "Bybit", type: "CEX", rate: "+0.0058%" },
      { name: "OKX", type: "CEX", rate: "+0.0072%" },
      { name: "dYdX", type: "DEX", rate: "+0.0048%" },
      { name: "Drift", type: "DEX", rate: "+0.0055%" },
    ],
    hero: { title: "SOL funding elevated — longs paying heavy", badge: "OVERCROWDED LONG", badgeColor: "accent-warning", desc: "SOL +0.0065% funding = 23.7% annualized. OKX at +0.0072% is highest. Drift DEX at +0.0055% also elevated. Squeeze risk if price stalls at $155 resistance.", avgRate: "+0.0060%", nextReset: "2h 14m" },
    stats: [
      { label: "Avg Funding Rate", value: "+0.0060%", change: "Longs paying heavy", icon: "percent", color: "text-neon-cyan" },
      { label: "Annualized Avg", value: "+21.9%", change: "Overheated", icon: "trending_up", color: "text-accent-warning" },
      { label: "Highest Exchange", value: "OKX +0.0072%", change: "26.3% annualized", icon: "local_fire_department", color: "text-accent-error" },
      { label: "Next Reset", value: "2h 14m", change: "Every 8 hours", icon: "schedule", color: "text-neon-purple" },
    ],
    table: [
      { symbol: "Binance", rate: "+0.0065%", annualized: "+23.7%", predicted: "+0.0058%", oi: "$280M", sentiment: "Very Bullish" },
      { symbol: "Bybit", rate: "+0.0058%", annualized: "+21.2%", predicted: "+0.0052%", oi: "$180M", sentiment: "Bullish" },
      { symbol: "OKX", rate: "+0.0072%", annualized: "+26.3%", predicted: "+0.0065%", oi: "$120M", sentiment: "Extremely Bullish" },
      { symbol: "dYdX", rate: "+0.0048%", annualized: "+17.5%", predicted: "+0.0042%", oi: "$48M", sentiment: "Bullish" },
      { symbol: "Drift", rate: "+0.0055%", annualized: "+20.1%", predicted: "+0.0048%", oi: "$32M", sentiment: "Very Bullish" },
    ],
  },
};

const pairKeys = Object.keys(pairMap);

function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Funding Rate</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">Perpetual funding analysis</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function FundingRatePage() {
  const [activePair, setActivePair] = useState("BTC-PERP");
  const data = pairMap[activePair];

  return (
    <AppShell header={<Header />}>
      <div className="space-y-6">
        {/* ── Pair + Exchange Selector ── */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold shrink-0">Pair</span>
            <div className="flex gap-1 bg-black/40 rounded-lg p-0.5 border border-white/5">
              {pairKeys.map((k) => (
                <button key={k} onClick={() => setActivePair(k)} className={`px-2.5 py-1.5 text-[11px] rounded font-bold transition-colors cursor-pointer ${activePair === k ? "bg-white/10 text-white" : "text-slate-500 hover:text-white"}`}>
                  {k.replace("-PERP", "")}
                </button>
              ))}
            </div>
          </div>
          <div className="w-px h-5 bg-white/10 hidden sm:block" />
          <div className="flex items-center gap-2 overflow-x-auto">
            <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold shrink-0">Sources</span>
            {data.exchanges.map((ex) => (
              <span key={ex.name} className={`text-[11px] font-medium px-1.5 py-0.5 rounded-md border shrink-0 ${
                ex.type === "CEX" ? "bg-neon-cyan/5 text-neon-cyan/70 border-neon-cyan/10" : "bg-neon-purple/5 text-neon-purple/70 border-neon-purple/10"
              }`}>
                {ex.name} <span className="font-mono">{ex.rate}</span>
              </span>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2 shrink-0">
            <span className="text-xs text-white font-mono font-bold">{data.price}</span>
            <span className="text-[11px] text-slate-500">{data.label}</span>
          </div>
        </div>

        {/* ── Insight Hero (dynamic) ── */}
        <div className="glass-panel glow-cyan rounded-xl p-5 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-accent-success/[0.03] via-transparent to-accent-warning/[0.03] pointer-events-none" />
          <div className="flex flex-col lg:flex-row items-start lg:items-center gap-4 relative z-10">
            <div className="flex items-center gap-3 flex-1">
              <div className="w-12 h-12 rounded-xl bg-accent-warning/10 border border-accent-warning/20 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-accent-warning text-[24px]">local_fire_department</span>
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">{data.hero.title}</h3>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded bg-${data.hero.badgeColor}/15 text-${data.hero.badgeColor} border border-${data.hero.badgeColor}/20`}>{data.hero.badge}</span>
                </div>
                <p className="text-xs text-slate-400 mt-1">{data.hero.desc}</p>
              </div>
            </div>
            <div className="flex items-center gap-4 shrink-0">
              <div className="text-center px-3">
                <div className="text-[11px] text-slate-500">Avg Funding</div>
                <div className="text-sm font-bold text-accent-success font-mono">{data.hero.avgRate}</div>
              </div>
              <div className="w-px h-8 bg-white/10" />
              <div className="text-center px-3">
                <div className="text-[11px] text-slate-500">Next Reset</div>
                <div className="text-sm font-bold text-white font-mono">{data.hero.nextReset}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Stats (dynamic) */}
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          {data.stats.map((s) => (
            <div key={s.label} className="glass-panel rounded-xl p-4 hover:-translate-y-0.5 transition-all duration-300">
              <div className="flex items-center justify-between mb-1">
                <span className="text-slate-400 text-[11px] font-medium uppercase tracking-wider">{s.label}</span>
                <span className={`material-symbols-outlined text-[16px] ${s.color}`}>{s.icon}</span>
              </div>
              <h3 className="text-xl font-bold text-white">{s.value}</h3>
              <span className="text-[11px] text-slate-400">{s.change}</span>
            </div>
          ))}
        </div>

        {/* Funding rate chart (dynamic label) */}
        <div className="glass-panel glow-cyan rounded-xl overflow-hidden">
          <div className="p-4 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
            <h3 className="text-white text-sm font-bold flex items-center gap-2">
              <span className="material-symbols-outlined text-neon-cyan text-[18px]">show_chart</span>
              {activePair.replace("-PERP", "")} Funding Rate History (30d)
            </h3>
            <span className="text-[11px] text-slate-500 font-mono">8h intervals · {data.exchanges.length} exchanges</span>
          </div>
          <div className="p-6 min-h-[240px]">
            <svg className="w-full h-[200px]" viewBox="0 0 800 180" preserveAspectRatio="none">
              <line x1="0" x2="800" y1="90" y2="90" stroke="rgba(255,255,255,0.1)" strokeWidth="1" strokeDasharray="4 4" />
              <text x="5" y="87" fill="#64748b" fontSize="9" fontFamily="monospace">0%</text>
              {Array.from({ length: 90 }, (_, i) => {
                const seed = activePair === "SOL-PERP" ? 25 : activePair === "ETH-PERP" ? 10 : 15;
                const val = Math.sin(i * 0.15) * 30 + Math.sin(i * 0.3 + 1) * 10 - 5 + seed;
                const h = Math.abs(val);
                const y = val >= 0 ? 90 - h : 90;
                const color = val >= 0 ? "#0bda5e" : "#ff3333";
                return <rect key={i} x={i * 8.8 + 2} y={y} width="7" height={h} fill={color} opacity="0.5" rx="1" />;
              })}
            </svg>
          </div>
        </div>

        {/* Funding table (dynamic) */}
        <div className="glass-panel rounded-xl overflow-hidden">
          <div className="p-4 border-b border-white/5 bg-white/[0.03]">
            <h3 className="text-white text-sm font-bold flex items-center gap-2">
              <span className="material-symbols-outlined text-neon-lime text-[18px]">table_chart</span>
              {activePair === "BTC-PERP" ? "All Funding Rates" : `${activePair.replace("-PERP", "")} Funding by Exchange`}
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-[11px] uppercase tracking-wider border-b border-white/5">
                  <th className="text-left px-4 py-3 font-medium">{activePair === "BTC-PERP" ? "Contract" : "Exchange"}</th>
                  <th className="text-right px-4 py-3 font-medium">Current Rate</th>
                  <th className="text-right px-4 py-3 font-medium hidden sm:table-cell">Annualized</th>
                  <th className="text-right px-4 py-3 font-medium hidden md:table-cell">Predicted</th>
                  <th className="text-right px-4 py-3 font-medium hidden lg:table-cell">Open Interest</th>
                  <th className="text-right px-4 py-3 font-medium">Sentiment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {data.table.map((f) => (
                  <tr key={f.symbol} className="hover:bg-white/[0.03] transition-colors cursor-pointer">
                    <td className="px-4 py-3">
                      <span className="text-white font-bold text-xs">{f.symbol}</span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={`text-xs font-bold font-mono ${f.rate.startsWith("+") ? "text-accent-success" : "text-accent-error"}`}>{f.rate}</span>
                    </td>
                    <td className="px-4 py-3 text-right hidden sm:table-cell">
                      <span className={`text-xs font-mono ${f.annualized.startsWith("+") ? "text-accent-success" : "text-accent-error"}`}>{f.annualized}</span>
                    </td>
                    <td className="px-4 py-3 text-right text-slate-400 font-mono text-xs hidden md:table-cell">{f.predicted}</td>
                    <td className="px-4 py-3 text-right text-slate-300 font-mono text-xs hidden lg:table-cell">{f.oi}</td>
                    <td className="px-4 py-3 text-right">
                      <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full border ${
                        f.sentiment.includes("Bullish")
                          ? "text-accent-success bg-accent-success/10 border-accent-success/20"
                          : f.sentiment.includes("Bearish")
                          ? "text-accent-error bg-accent-error/10 border-accent-error/20"
                          : "text-slate-400 bg-white/5 border-white/10"
                      }`}>
                        {f.sentiment}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
