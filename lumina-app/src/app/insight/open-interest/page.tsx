"use client";

import { useState } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";

/* ── Per-pair OI data ── */
interface ExOI { name: string; type: "CEX" | "DEX"; oi: string }
interface PairOI {
  symbol: string; label: string; price: string;
  exchanges: ExOI[];
  hero: { title: string; badge: string; badgeColor: string; desc: string; totalOI: string; lsRatio: string };
  stats: { label: string; value: string; change: string; icon: string; color: string }[];
  byExchange: { exchange: string; oi: string; change: string; lsRatio: string; pctTotal: number; color: string }[];
  longPct: number; longVal: string; shortVal: string;
}

const pairMap: Record<string, PairOI> = {
  "BTC-PERP": {
    symbol: "BTC-PERP", label: "Bitcoin", price: "$67,420",
    exchanges: [
      { name: "Binance", type: "CEX", oi: "$1.8B" },
      { name: "Bybit", type: "CEX", oi: "$920M" },
      { name: "OKX", type: "CEX", oi: "$780M" },
      { name: "dYdX", type: "DEX", oi: "$180M" },
      { name: "Hyperliquid", type: "DEX", oi: "$120M" },
    ],
    hero: { title: "OI rising with price — conviction rally", badge: "BULLISH POSITIONING", badgeColor: "accent-success", desc: "$1.14B net inflow in 24h across all pairs. BTC OI +3.8% with strong momentum. Longs dominate at 56.1%. Binance holds 47% of BTC OI.", totalOI: "$3.80B", lsRatio: "1.28" },
    stats: [
      { label: "Total OI", value: "$3.80B", change: "+3.8% 24h", icon: "donut_large", color: "text-neon-cyan" },
      { label: "24h OI Change", value: "+$139M", change: "Net inflow", icon: "trending_up", color: "text-accent-success" },
      { label: "Long/Short Ratio", value: "1.28", change: "Longs dominant", icon: "balance", color: "text-neon-purple" },
      { label: "Largest Exchange", value: "Binance 47%", change: "$1.8B", icon: "pie_chart", color: "text-accent-warning" },
    ],
    byExchange: [
      { exchange: "Binance", oi: "$1.8B", change: "+4.2%", lsRatio: "1.32", pctTotal: 47.4, color: "from-accent-warning/40 to-accent-warning/10" },
      { exchange: "Bybit", oi: "$920M", change: "+3.1%", lsRatio: "1.24", pctTotal: 24.2, color: "from-neon-cyan/40 to-neon-cyan/10" },
      { exchange: "OKX", oi: "$780M", change: "+2.8%", lsRatio: "1.18", pctTotal: 20.5, color: "from-neon-purple/40 to-neon-purple/10" },
      { exchange: "dYdX", oi: "$180M", change: "+8.4%", lsRatio: "1.45", pctTotal: 4.7, color: "from-neon-lime/40 to-neon-lime/10" },
      { exchange: "Hyperliquid", oi: "$120M", change: "+12.2%", lsRatio: "1.52", pctTotal: 3.2, color: "from-accent-success/40 to-accent-success/10" },
    ],
    longPct: 56.1, longVal: "$2.13B", shortVal: "$1.67B",
  },
  "ETH-PERP": {
    symbol: "ETH-PERP", label: "Ethereum", price: "$3,245",
    exchanges: [
      { name: "Binance", type: "CEX", oi: "$820M" },
      { name: "Bybit", type: "CEX", oi: "$420M" },
      { name: "OKX", type: "CEX", oi: "$380M" },
      { name: "dYdX", type: "DEX", oi: "$95M" },
      { name: "Uniswap", type: "DEX", oi: "$42M" },
    ],
    hero: { title: "ETH OI surging +5.1% — new money entering", badge: "INFLOW DETECTED", badgeColor: "accent-success", desc: "ETH OI up $88M in 24h. dYdX OI +11.2% — DEX derivatives growing fast. Bybit L/S ratio at 1.38 suggests concentrated long bias. Watch for overcrowding.", totalOI: "$1.76B", lsRatio: "1.22" },
    stats: [
      { label: "Total OI", value: "$1.76B", change: "+5.1% 24h", icon: "donut_large", color: "text-neon-cyan" },
      { label: "24h OI Change", value: "+$88M", change: "Net inflow", icon: "trending_up", color: "text-accent-success" },
      { label: "Long/Short Ratio", value: "1.22", change: "Longs leading", icon: "balance", color: "text-neon-purple" },
      { label: "DEX OI Growth", value: "+11.2%", change: "dYdX leading", icon: "rocket_launch", color: "text-accent-warning" },
    ],
    byExchange: [
      { exchange: "Binance", oi: "$820M", change: "+4.8%", lsRatio: "1.18", pctTotal: 46.6, color: "from-accent-warning/40 to-accent-warning/10" },
      { exchange: "Bybit", oi: "$420M", change: "+5.2%", lsRatio: "1.38", pctTotal: 23.9, color: "from-neon-cyan/40 to-neon-cyan/10" },
      { exchange: "OKX", oi: "$380M", change: "+3.4%", lsRatio: "1.15", pctTotal: 21.6, color: "from-neon-purple/40 to-neon-purple/10" },
      { exchange: "dYdX", oi: "$95M", change: "+11.2%", lsRatio: "1.28", pctTotal: 5.4, color: "from-neon-lime/40 to-neon-lime/10" },
      { exchange: "Uniswap", oi: "$42M", change: "+6.8%", lsRatio: "1.08", pctTotal: 2.4, color: "from-accent-success/40 to-accent-success/10" },
    ],
    longPct: 55.0, longVal: "$968M", shortVal: "$792M",
  },
  "SOL-PERP": {
    symbol: "SOL-PERP", label: "Solana", price: "$148.20",
    exchanges: [
      { name: "Binance", type: "CEX", oi: "$280M" },
      { name: "Bybit", type: "CEX", oi: "$180M" },
      { name: "OKX", type: "CEX", oi: "$120M" },
      { name: "dYdX", type: "DEX", oi: "$48M" },
      { name: "Drift", type: "DEX", oi: "$32M" },
    ],
    hero: { title: "SOL OI +8.4% — speculative heat building", badge: "OVERCROWDED", badgeColor: "accent-warning", desc: "SOL OI surging as price approaches $155 resistance. L/S ratio at 1.42 — heavily long-biased. Drift DEX OI up +18.5%. If $155 rejected, long liquidation cascade risk is elevated.", totalOI: "$660M", lsRatio: "1.42" },
    stats: [
      { label: "Total OI", value: "$660M", change: "+8.4% 24h", icon: "donut_large", color: "text-neon-cyan" },
      { label: "24h OI Change", value: "+$51M", change: "Aggressive inflow", icon: "trending_up", color: "text-accent-warning" },
      { label: "Long/Short Ratio", value: "1.42", change: "Long crowded", icon: "balance", color: "text-accent-error" },
      { label: "DEX OI Growth", value: "+18.5%", change: "Drift leading", icon: "rocket_launch", color: "text-accent-warning" },
    ],
    byExchange: [
      { exchange: "Binance", oi: "$280M", change: "+7.2%", lsRatio: "1.38", pctTotal: 42.4, color: "from-accent-warning/40 to-accent-warning/10" },
      { exchange: "Bybit", oi: "$180M", change: "+8.8%", lsRatio: "1.45", pctTotal: 27.3, color: "from-neon-cyan/40 to-neon-cyan/10" },
      { exchange: "OKX", oi: "$120M", change: "+6.4%", lsRatio: "1.32", pctTotal: 18.2, color: "from-neon-purple/40 to-neon-purple/10" },
      { exchange: "dYdX", oi: "$48M", change: "+14.2%", lsRatio: "1.55", pctTotal: 7.3, color: "from-neon-lime/40 to-neon-lime/10" },
      { exchange: "Drift", oi: "$32M", change: "+18.5%", lsRatio: "1.62", pctTotal: 4.8, color: "from-accent-error/40 to-accent-error/10" },
    ],
    longPct: 58.7, longVal: "$387M", shortVal: "$273M",
  },
};

const pairKeys = Object.keys(pairMap);

function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Open Interest</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">Derivatives positioning</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function OpenInterestPage() {
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
                {ex.name} <span className="font-mono">{ex.oi}</span>
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
          <div className="absolute inset-0 bg-gradient-to-r from-accent-success/[0.03] via-transparent to-neon-purple/[0.03] pointer-events-none" />
          <div className="flex flex-col lg:flex-row items-start lg:items-center gap-4 relative z-10">
            <div className="flex items-center gap-3 flex-1">
              <div className="w-12 h-12 rounded-xl bg-accent-success/10 border border-accent-success/20 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-accent-success text-[24px]">trending_up</span>
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
                <div className="text-[11px] text-slate-500">Total OI</div>
                <div className="text-sm font-bold text-white font-mono">{data.hero.totalOI}</div>
              </div>
              <div className="w-px h-8 bg-white/10" />
              <div className="text-center px-3">
                <div className="text-[11px] text-slate-500">Long/Short</div>
                <div className="text-sm font-bold text-accent-success font-mono">{data.hero.lsRatio}</div>
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
              <span className="text-[11px] text-accent-success">{s.change}</span>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-12 gap-4 md:gap-6">
          {/* OI by exchange (dynamic) */}
          <div className="col-span-12 lg:col-span-7">
            <div className="glass-panel glow-purple rounded-xl overflow-hidden">
              <div className="p-4 border-b border-white/5 bg-white/[0.03]">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-purple text-[18px]">donut_large</span>
                  {activePair.replace("-PERP", "")} OI by Exchange
                </h3>
              </div>
              <div className="p-4 space-y-3">
                {data.byExchange.map((a) => (
                  <div key={a.exchange} className="group">
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-3">
                        <span className="text-white text-xs font-bold w-24">{a.exchange}</span>
                        <span className="text-white text-xs font-mono">{a.oi}</span>
                        <span className={`text-[11px] font-bold ${a.change.startsWith("+") ? "text-accent-success" : "text-accent-error"}`}>{a.change}</span>
                      </div>
                      <div className="flex items-center gap-3 text-[11px]">
                        <span className="text-slate-500">L/S: <span className={`font-mono font-bold ${parseFloat(a.lsRatio) >= 1 ? "text-accent-success" : "text-accent-error"}`}>{a.lsRatio}</span></span>
                        <span className="text-slate-500">{a.pctTotal}%</span>
                      </div>
                    </div>
                    <div className="h-3 bg-white/[0.03] rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full bg-gradient-to-r ${a.color} transition-all duration-500 group-hover:opacity-90`}
                        style={{ width: `${Math.min(a.pctTotal * 2.0, 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* L/S Ratio (dynamic) */}
          <div className="col-span-12 lg:col-span-5">
            <div className="glass-panel rounded-xl overflow-hidden h-full flex flex-col">
              <div className="p-4 border-b border-white/5 bg-white/[0.03]">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-accent-success text-[18px]">balance</span>
                  {activePair.replace("-PERP", "")} Long/Short
                </h3>
              </div>
              <div className="p-4 flex-1 flex flex-col justify-center">
                <div className="flex items-center justify-between mb-3 text-xs">
                  <span className="text-accent-success font-bold">Longs {data.longPct}%</span>
                  <span className="text-accent-error font-bold">Shorts {(100 - data.longPct).toFixed(1)}%</span>
                </div>
                <div className="h-4 rounded-full overflow-hidden flex">
                  <div className="h-full bg-gradient-to-r from-accent-success/60 to-accent-success/40" style={{ width: `${data.longPct}%` }} />
                  <div className="h-full bg-gradient-to-r from-accent-error/40 to-accent-error/60" style={{ width: `${100 - data.longPct}%` }} />
                </div>
                <div className="flex items-center justify-between mt-3 text-[11px] text-slate-500">
                  <span>{data.longVal} in longs</span>
                  <span>Ratio: <span className="text-white font-bold">{data.hero.lsRatio}</span></span>
                  <span>{data.shortVal} in shorts</span>
                </div>

                {/* Per-exchange L/S mini bars */}
                <div className="mt-5 space-y-2">
                  <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold">By Exchange</span>
                  {data.byExchange.map((ex) => {
                    const lp = (parseFloat(ex.lsRatio) / (1 + parseFloat(ex.lsRatio))) * 100;
                    return (
                      <div key={ex.exchange}>
                        <div className="flex items-center justify-between text-[11px] mb-0.5">
                          <span className="text-slate-400">{ex.exchange}</span>
                          <span className="text-slate-400 font-mono">{ex.lsRatio}</span>
                        </div>
                        <div className="h-1.5 rounded-full overflow-hidden flex">
                          <div className="h-full bg-accent-success/50 rounded-l-full" style={{ width: `${lp}%` }} />
                          <div className="h-full bg-accent-error/50 rounded-r-full" style={{ width: `${100 - lp}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
