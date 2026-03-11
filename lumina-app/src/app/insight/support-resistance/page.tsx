"use client";

import { useState } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";

const pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "SUI/USDT"];

const exchangeSources: Record<string, { name: string; type: "CEX" | "DEX"; vol: string }[]> = {
  "BTC/USDT": [
    { name: "Binance", type: "CEX", vol: "$2.4B" },
    { name: "Coinbase", type: "CEX", vol: "$820M" },
    { name: "OKX", type: "CEX", vol: "$680M" },
    { name: "Bybit", type: "CEX", vol: "$520M" },
    { name: "Uniswap", type: "DEX", vol: "$48M" },
    { name: "dYdX", type: "DEX", vol: "$32M" },
  ],
  "ETH/USDT": [
    { name: "Binance", type: "CEX", vol: "$1.1B" },
    { name: "Coinbase", type: "CEX", vol: "$420M" },
    { name: "OKX", type: "CEX", vol: "$340M" },
    { name: "Uniswap", type: "DEX", vol: "$280M" },
    { name: "Curve", type: "DEX", vol: "$62M" },
  ],
  "SOL/USDT": [
    { name: "Binance", type: "CEX", vol: "$820M" },
    { name: "Bybit", type: "CEX", vol: "$280M" },
    { name: "OKX", type: "CEX", vol: "$180M" },
    { name: "Jupiter", type: "DEX", vol: "$420M" },
    { name: "Raydium", type: "DEX", vol: "$140M" },
  ],
};

const supportLevels = [
  { price: "$67,200", strength: 92, type: "Major" as const, reason: "200 EMA + Whale buy wall $4.2M + Order book confluence", tested: 5 },
  { price: "$65,200", strength: 96, type: "Critical" as const, reason: "Weekly support + Fibonacci 0.618 + Whale wall $12M across 8 exchanges", tested: 7 },
  { price: "$61,500", strength: 88, type: "Major" as const, reason: "50 Weekly EMA + Strong bid liquidity on Binance/OKX/Kraken", tested: 4 },
];

const resistanceLevels = [
  { price: "$68,500", strength: 84, type: "Major" as const, reason: "Previous local high + Volume cluster + Ask wall $5.6M", tested: 4 },
  { price: "$69,800", strength: 94, type: "Critical" as const, reason: "ATH rejection zone + Sell wall $18M + Fibonacci 1.0 + Options cluster", tested: 3 },
  { price: "$73,800", strength: 90, type: "Major" as const, reason: "ATH + Fibonacci ext. 1.272 + Mass liquidation zone above", tested: 1 },
];

const technicalSignals = [
  { indicator: "RSI", value: "58.4", signal: "Neutral" as const },
  { indicator: "MACD", value: "Bullish Cross", signal: "Buy" as const },
  { indicator: "Volume", value: "+24%", signal: "Buy" as const },
  { indicator: "OBV", value: "Accum.", signal: "Buy" as const },
  { indicator: "Ichimoku", value: "Above", signal: "Buy" as const },
  { indicator: "VWAP", value: "$67,180", signal: "Buy" as const },
];

const volumeProfile = [
  { range: "$68.0K", pct: 45, type: "low" as const },
  { range: "$67.6K", pct: 88, type: "high" as const },
  { range: "$67.2K", pct: 95, type: "poc" as const },
  { range: "$66.8K", pct: 72, type: "high" as const },
  { range: "$66.4K", pct: 52, type: "low" as const },
  { range: "$66.0K", pct: 38, type: "low" as const },
  { range: "$65.6K", pct: 65, type: "high" as const },
  { range: "$65.2K", pct: 82, type: "high" as const },
];

function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Support & Resistance</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">Multi-source confluence</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function SupportResistancePage() {
  const [selectedPair, setSelectedPair] = useState("BTC/USDT");

  return (
    <AppShell header={<Header />}>
      <div className="space-y-6">
        {/* ── Pair + Exchange Selector ── */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold shrink-0">Pair</span>
            <div className="flex gap-1 bg-black/40 rounded-lg p-0.5 border border-white/5">
              {pairs.map((pair) => (
                <button key={pair} onClick={() => setSelectedPair(pair)} className={`px-2.5 py-1.5 text-[11px] rounded font-bold transition-colors cursor-pointer ${selectedPair === pair ? "bg-white/10 text-white" : "text-slate-500 hover:text-white"}`}>
                  {pair.split("/")[0]}
                </button>
              ))}
            </div>
          </div>
          <div className="w-px h-5 bg-white/10 hidden sm:block" />
          <div className="flex items-center gap-2 overflow-x-auto">
            <span className="text-[11px] text-slate-500 uppercase tracking-wider font-bold shrink-0">Sources</span>
            {(exchangeSources[selectedPair] || []).map((ex) => (
              <span key={ex.name} className={`text-[11px] font-medium px-1.5 py-0.5 rounded-md border shrink-0 ${
                ex.type === "CEX" ? "bg-neon-cyan/5 text-neon-cyan/70 border-neon-cyan/10" : "bg-neon-purple/5 text-neon-purple/70 border-neon-purple/10"
              }`}>
                {ex.name} <span className="font-mono">{ex.vol}</span>
              </span>
            ))}
          </div>
        </div>

        {/* Insight Hero */}
        <div className="glass-panel glow-cyan rounded-xl p-5 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-accent-success/[0.03] via-transparent to-neon-purple/[0.03] pointer-events-none" />
          <div className="flex flex-col lg:flex-row items-start lg:items-center gap-4 relative z-10">
            <div className="flex items-center gap-3 flex-1">
              <div className="w-12 h-12 rounded-xl bg-neon-cyan/10 border border-neon-cyan/20 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-neon-cyan text-[24px]">trending_up</span>
              </div>
              <div>
                <div className="flex items-center gap-2 mb-0.5">
                  <h3 className="text-lg font-bold text-white">68% chance of upside breakout</h3>
                  <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-accent-success/15 text-accent-success">BULLISH BIAS</span>
                </div>
                <p className="text-xs text-slate-400">Trading in $65,200–$69,800 range for 14 days. Volume profile, OI, and 5/6 technical indicators favor upside. Key level to watch: $69,800.</p>
              </div>
            </div>
            <div className="flex items-center gap-5 shrink-0">
              <div className="text-center">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider">Support</div>
                <div className="text-lg font-bold text-accent-success">$65,200</div>
              </div>
              <div className="w-px h-8 bg-white/10"></div>
              <div className="text-center">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider">Current</div>
                <div className="text-lg font-bold text-white">$67,420</div>
              </div>
              <div className="w-px h-8 bg-white/10"></div>
              <div className="text-center">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider">Resistance</div>
                <div className="text-lg font-bold text-accent-error">$69,800</div>
              </div>
            </div>
          </div>
        </div>

        {/* Visual S/R Price Map */}
        <div className="glass-panel rounded-xl overflow-hidden">
          <div className="p-4 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
            <h3 className="text-white text-sm font-bold flex items-center gap-2">
              <span className="material-symbols-outlined text-neon-cyan text-[18px]">straighten</span>
              Price Level Map
            </h3>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-accent-success/60"></span>Support</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-accent-error/60"></span>Resistance</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-neon-cyan"></span>Current</span>
            </div>
          </div>
          <div className="p-6">
            <svg viewBox="0 0 800 200" className="w-full h-[200px]" preserveAspectRatio="xMidYMid meet">
              {/* Price axis line */}
              <line x1="40" x2="760" y1="100" y2="100" stroke="rgba(255,255,255,0.08)" strokeWidth="1" />

              {/* Support zones */}
              <rect x="100" y="85" width="30" height="30" rx="4" fill="rgba(11,218,94,0.15)" stroke="#0bda5e" strokeWidth="1" strokeOpacity="0.4" />
              <text x="115" y="80" textAnchor="middle" fill="#0bda5e" fontSize="9" fontFamily="monospace" fontWeight="bold">$61.5K</text>
              <text x="115" y="130" textAnchor="middle" fill="#64748b" fontSize="7" fontFamily="monospace">Major</text>
              <rect x="80" y="78" width="70" height="44" rx="6" fill="none" stroke="#0bda5e" strokeWidth="0.5" strokeDasharray="3 3" strokeOpacity="0.3" />

              <rect x="260" y="82" width="40" height="36" rx="4" fill="rgba(11,218,94,0.2)" stroke="#0bda5e" strokeWidth="1.5" strokeOpacity="0.6" />
              <text x="280" y="76" textAnchor="middle" fill="#0bda5e" fontSize="10" fontFamily="monospace" fontWeight="bold">$65.2K</text>
              <text x="280" y="132" textAnchor="middle" fill="#0bda5e" fontSize="8" fontFamily="monospace" fontWeight="bold">CRITICAL</text>

              <rect x="380" y="87" width="25" height="26" rx="4" fill="rgba(11,218,94,0.12)" stroke="#0bda5e" strokeWidth="1" strokeOpacity="0.3" />
              <text x="392" y="80" textAnchor="middle" fill="#0bda5e" fontSize="9" fontFamily="monospace">$67.2K</text>

              {/* Current price */}
              <line x1="440" x2="440" y1="55" y2="145" stroke="#00f0ff" strokeWidth="2" strokeOpacity="0.8" />
              <circle cx="440" cy="100" r="6" fill="#00f0ff">
                <animate attributeName="r" dur="2s" repeatCount="indefinite" values="5;7;5" />
              </circle>
              <rect x="415" y="40" width="50" height="16" rx="4" fill="#00f0ff" fillOpacity="0.15" />
              <text x="440" y="51" textAnchor="middle" fill="#00f0ff" fontSize="9" fontFamily="monospace" fontWeight="bold">$67.4K</text>

              {/* Resistance zones */}
              <rect x="520" y="85" width="30" height="30" rx="4" fill="rgba(255,51,51,0.15)" stroke="#ff3333" strokeWidth="1" strokeOpacity="0.4" />
              <text x="535" y="80" textAnchor="middle" fill="#ff3333" fontSize="9" fontFamily="monospace">$68.5K</text>
              <text x="535" y="130" textAnchor="middle" fill="#64748b" fontSize="7" fontFamily="monospace">Major</text>

              <rect x="600" y="80" width="45" height="40" rx="4" fill="rgba(255,51,51,0.2)" stroke="#ff3333" strokeWidth="1.5" strokeOpacity="0.6" />
              <text x="622" y="74" textAnchor="middle" fill="#ff3333" fontSize="10" fontFamily="monospace" fontWeight="bold">$69.8K</text>
              <text x="622" y="134" textAnchor="middle" fill="#ff3333" fontSize="8" fontFamily="monospace" fontWeight="bold">CRITICAL</text>

              <rect x="710" y="85" width="30" height="30" rx="4" fill="rgba(255,51,51,0.12)" stroke="#ff3333" strokeWidth="1" strokeOpacity="0.3" />
              <text x="725" y="80" textAnchor="middle" fill="#ff3333" fontSize="9" fontFamily="monospace">$73.8K</text>
              <text x="725" y="130" textAnchor="middle" fill="#64748b" fontSize="7" fontFamily="monospace">Major</text>

              {/* Range highlight */}
              <rect x="260" y="95" width="362" height="10" rx="2" fill="rgba(0,240,255,0.04)" />
              <text x="441" y="170" textAnchor="middle" fill="#64748b" fontSize="8" fontFamily="monospace">14-day consolidation range</text>
            </svg>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-4 md:gap-6">
          {/* Support Levels */}
          <div className="col-span-12 lg:col-span-6">
            <div className="glass-panel glow-cyan rounded-xl overflow-hidden h-full">
              <div className="p-4 border-b border-white/5 bg-white/[0.03]">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-accent-success text-[18px]">shield</span>
                  Support Levels
                </h3>
              </div>
              <div className="divide-y divide-white/5">
                {supportLevels.map((s) => (
                  <div key={s.price} className="p-4 hover:bg-white/[0.02] transition-colors cursor-pointer">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-accent-success font-mono font-bold text-base">{s.price}</span>
                        <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                          s.type === "Critical" ? "bg-accent-error/10 text-accent-error" : "bg-neon-cyan/10 text-neon-cyan"
                        }`}>{s.type}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-20 bg-slate-800 rounded-full overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-accent-success to-neon-lime" style={{ width: `${s.strength}%` }}></div>
                        </div>
                        <span className="text-[11px] text-slate-400 font-mono">{s.strength}%</span>
                      </div>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">{s.reason}</p>
                    <span className="text-[11px] text-slate-600 mt-1 block">Tested {s.tested}x</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Resistance Levels */}
          <div className="col-span-12 lg:col-span-6">
            <div className="glass-panel glow-purple rounded-xl overflow-hidden h-full">
              <div className="p-4 border-b border-white/5 bg-white/[0.03]">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-accent-error text-[18px]">block</span>
                  Resistance Levels
                </h3>
              </div>
              <div className="divide-y divide-white/5">
                {resistanceLevels.map((r) => (
                  <div key={r.price} className="p-4 hover:bg-white/[0.02] transition-colors cursor-pointer">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-accent-error font-mono font-bold text-base">{r.price}</span>
                        <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                          r.type === "Critical" ? "bg-accent-error/10 text-accent-error" : "bg-neon-purple/10 text-neon-purple"
                        }`}>{r.type}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-20 bg-slate-800 rounded-full overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-accent-error to-accent-warning" style={{ width: `${r.strength}%` }}></div>
                        </div>
                        <span className="text-[11px] text-slate-400 font-mono">{r.strength}%</span>
                      </div>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">{r.reason}</p>
                    <span className="text-[11px] text-slate-600 mt-1 block">Tested {r.tested}x</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-4 md:gap-6">
          {/* Volume Profile */}
          <div className="col-span-12 lg:col-span-5">
            <div className="glass-panel rounded-xl overflow-hidden h-full">
              <div className="p-4 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-lime text-[18px]">bar_chart</span>
                  Volume Profile
                </h3>
                <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-neon-lime/10 text-neon-lime">30D</span>
              </div>
              <div className="p-3 space-y-1">
                {volumeProfile.map((v) => (
                  <div key={v.range} className="flex items-center gap-2 py-0.5 group hover:bg-white/[0.02] rounded px-2 cursor-pointer">
                    <span className="text-[11px] text-slate-400 font-mono w-14 shrink-0">{v.range}</span>
                    <div className="flex-1 h-4 bg-slate-800/50 rounded-sm overflow-hidden relative">
                      <div
                        className={`h-full rounded-sm ${
                          v.type === "poc" ? "bg-neon-cyan/60" : v.type === "high" ? "bg-neon-lime/40" : "bg-slate-600/30"
                        }`}
                        style={{ width: `${v.pct}%` }}
                      />
                      {v.type === "poc" && <span className="absolute right-1 top-1/2 -translate-y-1/2 text-[10px] font-bold text-neon-cyan">POC</span>}
                    </div>
                  </div>
                ))}
              </div>
              <div className="px-4 py-2 border-t border-white/5 flex items-center gap-3 text-[11px] text-slate-500">
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-neon-cyan/60"></span>POC</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-neon-lime/40"></span>High Vol</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-slate-600/30"></span>Low Vol</span>
              </div>
            </div>
          </div>

          {/* Technical Signals — compact */}
          <div className="col-span-12 lg:col-span-7">
            <div className="glass-panel rounded-xl overflow-hidden h-full">
              <div className="p-4 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-cyan text-[18px]">analytics</span>
                  Technical Signals
                </h3>
                <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-accent-success/10 text-accent-success border border-accent-success/20">BULLISH — 5/6 Buy</span>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {technicalSignals.map((t) => (
                    <div key={t.indicator} className="glass-panel rounded-lg p-3 hover:-translate-y-0.5 transition-all cursor-pointer">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[11px] text-slate-400 font-medium">{t.indicator}</span>
                        <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                          t.signal === "Buy" ? "bg-accent-success/10 text-accent-success" : "bg-white/5 text-slate-400"
                        }`}>{t.signal}</span>
                      </div>
                      <span className="text-sm font-bold text-white font-mono">{t.value}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="px-4 py-3 border-t border-white/5 bg-white/[0.02]">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[11px] text-slate-500">Overall Signal Strength</span>
                  <span className="text-[11px] text-accent-success font-bold">83%</span>
                </div>
                <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-neon-cyan to-accent-success rounded-full" style={{ width: "83%" }}></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
