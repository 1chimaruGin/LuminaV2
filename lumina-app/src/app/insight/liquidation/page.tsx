"use client";

import { useState } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";

/* ── Pair definitions with per-pair data ── */
interface PairData {
  symbol: string;
  label: string;
  price: string;
  exchanges: { name: string; type: "CEX" | "DEX"; oi: string }[];
  hero: { title: string; badge: string; badgeColor: string; desc: string; nearLong: string; nearShort: string };
  stats: { label: string; value: string; change: string; icon: string; color: string }[];
  levels: { price: string; longLiq: string; shortLiq: string; cluster: string; intensity: number }[];
}

const pairMap: Record<string, PairData> = {
  "BTC-PERP": {
    symbol: "BTC-PERP", label: "Bitcoin", price: "$67,420",
    exchanges: [
      { name: "Binance", type: "CEX", oi: "$1.8B" },
      { name: "Bybit", type: "CEX", oi: "$920M" },
      { name: "OKX", type: "CEX", oi: "$780M" },
      { name: "dYdX", type: "DEX", oi: "$180M" },
      { name: "Hyperliquid", type: "DEX", oi: "$120M" },
    ],
    hero: { title: "Long liquidation cluster at $70K", badge: "CAUTION — LONG HEAVY", badgeColor: "accent-warning", desc: "$180M in longs stacked at $70K. Short squeeze risk below $65K with $210M shorts. Current bias: longs 59% of liquidations.", nearLong: "$70,000", nearShort: "$64,000" },
    stats: [
      { label: "24h Liquidations", value: "$142M", change: "-12% vs avg", icon: "warning", color: "text-accent-error" },
      { label: "Long Liquidations", value: "$84M", change: "59% of total", icon: "arrow_upward", color: "text-accent-success" },
      { label: "Short Liquidations", value: "$58M", change: "41% of total", icon: "arrow_downward", color: "text-accent-error" },
      { label: "Largest Single", value: "$4.2M", change: "Long @ $66,800", icon: "local_fire_department", color: "text-accent-warning" },
    ],
    levels: [
      { price: "$70,000", longLiq: "$180M", shortLiq: "$0", cluster: "Major long cluster", intensity: 95 },
      { price: "$69,000", longLiq: "$120M", shortLiq: "$0", cluster: "Long cluster", intensity: 72 },
      { price: "$68,000", longLiq: "$85M", shortLiq: "$0", cluster: "Moderate", intensity: 55 },
      { price: "$67,500", longLiq: "$42M", shortLiq: "$8M", cluster: "Near price", intensity: 30 },
      { price: "$67,000", longLiq: "$0", shortLiq: "$38M", cluster: "Near price", intensity: 28 },
      { price: "$66,000", longLiq: "$0", shortLiq: "$95M", cluster: "Short cluster", intensity: 62 },
      { price: "$65,000", longLiq: "$0", shortLiq: "$145M", cluster: "Major short cluster", intensity: 88 },
      { price: "$64,000", longLiq: "$0", shortLiq: "$210M", cluster: "Massive short wall", intensity: 100 },
    ],
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
    hero: { title: "Shorts stacked at $3,400 — squeeze zone", badge: "SHORT HEAVY ABOVE", badgeColor: "accent-error", desc: "$92M in shorts clustered at $3,400. If BTC breaks $68K, ETH could squeeze to $3,500. Longs vulnerable below $3,050.", nearLong: "$3,050", nearShort: "$3,400" },
    stats: [
      { label: "24h Liquidations", value: "$38M", change: "+8% vs avg", icon: "warning", color: "text-accent-error" },
      { label: "Long Liquidations", value: "$18M", change: "47% of total", icon: "arrow_upward", color: "text-accent-success" },
      { label: "Short Liquidations", value: "$20M", change: "53% of total", icon: "arrow_downward", color: "text-accent-error" },
      { label: "Largest Single", value: "$1.8M", change: "Short @ $3,280", icon: "local_fire_department", color: "text-accent-warning" },
    ],
    levels: [
      { price: "$3,500", longLiq: "$42M", shortLiq: "$0", cluster: "Long cluster", intensity: 48 },
      { price: "$3,400", longLiq: "$0", shortLiq: "$92M", cluster: "Major short wall", intensity: 90 },
      { price: "$3,350", longLiq: "$0", shortLiq: "$55M", cluster: "Short cluster", intensity: 58 },
      { price: "$3,250", longLiq: "$28M", shortLiq: "$18M", cluster: "Current price", intensity: 25 },
      { price: "$3,150", longLiq: "$0", shortLiq: "$32M", cluster: "Below price", intensity: 35 },
      { price: "$3,050", longLiq: "$0", shortLiq: "$68M", cluster: "Major long liq zone", intensity: 72 },
      { price: "$2,950", longLiq: "$0", shortLiq: "$85M", cluster: "Deep long liq", intensity: 82 },
    ],
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
    hero: { title: "SOL longs overextended — $155 resistance", badge: "OVERLEVERAGED LONG", badgeColor: "accent-warning", desc: "$42M in longs stacked at $155. If rejected, cascade liquidation down to $138 ($28M). Funding extremely elevated at +0.0065%.", nearLong: "$138.00", nearShort: "$155.00" },
    stats: [
      { label: "24h Liquidations", value: "$18M", change: "+22% vs avg", icon: "warning", color: "text-accent-error" },
      { label: "Long Liquidations", value: "$12M", change: "67% of total", icon: "arrow_upward", color: "text-accent-success" },
      { label: "Short Liquidations", value: "$6M", change: "33% of total", icon: "arrow_downward", color: "text-accent-error" },
      { label: "Largest Single", value: "$620K", change: "Long @ $142.50", icon: "local_fire_department", color: "text-accent-warning" },
    ],
    levels: [
      { price: "$160.00", longLiq: "$18M", shortLiq: "$0", cluster: "Long cluster", intensity: 42 },
      { price: "$155.00", longLiq: "$42M", shortLiq: "$0", cluster: "Major long wall", intensity: 88 },
      { price: "$150.00", longLiq: "$22M", shortLiq: "$6M", cluster: "Near price", intensity: 32 },
      { price: "$145.00", longLiq: "$8M", shortLiq: "$14M", cluster: "Near price", intensity: 22 },
      { price: "$140.00", longLiq: "$0", shortLiq: "$24M", cluster: "Short cluster", intensity: 52 },
      { price: "$138.00", longLiq: "$0", shortLiq: "$28M", cluster: "Major short zone", intensity: 62 },
      { price: "$132.00", longLiq: "$0", shortLiq: "$38M", cluster: "Deep short zone", intensity: 78 },
    ],
  },
};

const pairKeys = Object.keys(pairMap);

const recentLiqs = [
  { time: "14:22", pair: "BTC-PERP", side: "Long", size: "$842K", price: "$67,180", exchange: "Binance" },
  { time: "14:20", pair: "ETH-PERP", side: "Short", size: "$420K", price: "$3,262", exchange: "Bybit" },
  { time: "14:18", pair: "SOL-PERP", side: "Long", size: "$180K", price: "$146.80", exchange: "OKX" },
  { time: "14:15", pair: "BTC-PERP", side: "Long", size: "$1.2M", price: "$67,050", exchange: "Binance" },
  { time: "14:12", pair: "ETH-PERP", side: "Long", size: "$340K", price: "$3,228", exchange: "Bybit" },
  { time: "14:08", pair: "DOGE-PERP", side: "Short", size: "$92K", price: "$0.0856", exchange: "Binance" },
  { time: "14:05", pair: "BTC-PERP", side: "Short", size: "$2.4M", price: "$67,520", exchange: "OKX" },
  { time: "14:02", pair: "SOL-PERP", side: "Long", size: "$560K", price: "$145.20", exchange: "Binance" },
];

function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Liquidation Map</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">Cross-exchange liquidation clusters</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function LiquidationMapPage() {
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
          <div className="absolute inset-0 bg-gradient-to-r from-accent-error/[0.03] via-transparent to-accent-warning/[0.03] pointer-events-none" />
          <div className="flex flex-col lg:flex-row items-start lg:items-center gap-4 relative z-10">
            <div className="flex items-center gap-3 flex-1">
              <div className={`w-12 h-12 rounded-xl bg-${data.hero.badgeColor}/10 border border-${data.hero.badgeColor}/20 flex items-center justify-center shrink-0`}>
                <span className={`material-symbols-outlined text-${data.hero.badgeColor} text-[24px]`}>warning</span>
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
                <div className="text-[11px] text-slate-500">Nearest Long Liq</div>
                <div className="text-sm font-bold text-accent-success font-mono">{data.hero.nearLong}</div>
              </div>
              <div className="w-px h-8 bg-white/10" />
              <div className="text-center px-3">
                <div className="text-[11px] text-slate-500">Nearest Short Liq</div>
                <div className="text-sm font-bold text-accent-error font-mono">{data.hero.nearShort}</div>
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

        <div className="grid grid-cols-12 gap-4 md:gap-6">
          {/* Liquidation cluster viz (dynamic) */}
          <div className="col-span-12 lg:col-span-8">
            <div className="glass-panel glow-cyan rounded-xl overflow-hidden">
              <div className="p-4 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-accent-warning text-[18px]">map</span>
                  Liquidation Clusters — {activePair.replace("-PERP", "")}
                </h3>
                <span className="text-[11px] text-slate-500 font-mono">Cumulative leverage · {data.exchanges.length} exchanges</span>
              </div>
              <div className="p-4 space-y-1">
                {data.levels.map((l) => (
                  <div key={l.price} className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-white/[0.03] transition-colors group">
                    <span className="text-xs text-white font-mono w-20 shrink-0">{l.price}</span>
                    <div className="flex-1 flex items-center gap-1">
                      <div className="flex-1 flex justify-end">
                        {l.longLiq !== "$0" && (
                          <div className="h-6 rounded-l-md bg-gradient-to-r from-accent-success/20 to-accent-success/40 flex items-center justify-end px-2 transition-all group-hover:from-accent-success/30 group-hover:to-accent-success/50" style={{ width: `${l.intensity}%` }}>
                            <span className="text-[11px] text-accent-success font-mono font-bold">{l.longLiq}</span>
                          </div>
                        )}
                      </div>
                      <div className="w-px h-6 bg-white/10 shrink-0" />
                      <div className="flex-1">
                        {l.shortLiq !== "$0" && (
                          <div className="h-6 rounded-r-md bg-gradient-to-r from-accent-error/40 to-accent-error/20 flex items-center px-2 transition-all group-hover:from-accent-error/50 group-hover:to-accent-error/30" style={{ width: `${l.intensity}%` }}>
                            <span className="text-[11px] text-accent-error font-mono font-bold">{l.shortLiq}</span>
                          </div>
                        )}
                      </div>
                    </div>
                    <span className="text-[11px] text-slate-500 w-32 text-right shrink-0 hidden md:block">{l.cluster}</span>
                  </div>
                ))}
              </div>
              <div className="px-4 pb-3 flex items-center justify-center gap-8 text-[11px] text-slate-500">
                <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-accent-success/40"></span> Long Liquidations</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-accent-error/40"></span> Short Liquidations</span>
              </div>
            </div>
          </div>

          {/* Recent liquidations feed */}
          <div className="col-span-12 lg:col-span-4">
            <div className="glass-panel rounded-xl overflow-hidden h-full flex flex-col">
              <div className="p-4 border-b border-white/5 bg-white/[0.03] shrink-0">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-accent-error text-[18px]">local_fire_department</span>
                  Live Liquidations
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-error animate-pulse ml-1"></span>
                </h3>
              </div>
              <div className="flex-1 divide-y divide-white/5 overflow-y-auto">
                {recentLiqs.map((l, i) => (
                  <div key={i} className="px-4 py-2.5 hover:bg-white/[0.03] transition-colors">
                    <div className="flex items-center justify-between mb-0.5">
                      <div className="flex items-center gap-2">
                        <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                          l.side === "Long" ? "bg-accent-success/10 text-accent-success" : "bg-accent-error/10 text-accent-error"
                        }`}>{l.side}</span>
                        <span className="text-white text-xs font-bold">{l.pair}</span>
                      </div>
                      <span className="text-white text-xs font-bold font-mono">{l.size}</span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-slate-500">
                      <span className="font-mono">@ {l.price}</span>
                      <span>{l.exchange} · {l.time}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
