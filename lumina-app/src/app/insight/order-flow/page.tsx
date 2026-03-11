"use client";

import { useState } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";

const pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "SUI/USDT"];

const exchangeSources: Record<string, { name: string; type: "CEX" | "DEX"; depth: string }[]> = {
  "BTC/USDT": [
    { name: "Binance", type: "CEX", depth: "$42M" },
    { name: "Coinbase", type: "CEX", depth: "$28M" },
    { name: "OKX", type: "CEX", depth: "$18M" },
    { name: "Bybit", type: "CEX", depth: "$14M" },
    { name: "dYdX", type: "DEX", depth: "$6.2M" },
    { name: "Uniswap", type: "DEX", depth: "$4.8M" },
  ],
  "ETH/USDT": [
    { name: "Binance", type: "CEX", depth: "$22M" },
    { name: "Coinbase", type: "CEX", depth: "$15M" },
    { name: "OKX", type: "CEX", depth: "$9.4M" },
    { name: "Uniswap", type: "DEX", depth: "$8.2M" },
    { name: "dYdX", type: "DEX", depth: "$3.1M" },
  ],
  "SOL/USDT": [
    { name: "Binance", type: "CEX", depth: "$8.4M" },
    { name: "Bybit", type: "CEX", depth: "$5.2M" },
    { name: "OKX", type: "CEX", depth: "$3.8M" },
    { name: "Jupiter", type: "DEX", depth: "$6.4M" },
    { name: "Raydium", type: "DEX", depth: "$2.1M" },
  ],
};

const bids = [
  { price: "67,400", amount: "2.45", pct: 95, exchanges: ["Binance", "OKX"] },
  { price: "67,380", amount: "4.12", pct: 82, exchanges: ["Binance", "Coinbase"] },
  { price: "67,340", amount: "6.24", pct: 100, exchanges: ["Binance", "OKX", "Bybit"] },
  { price: "67,300", amount: "2.18", pct: 55, exchanges: ["Binance"] },
  { price: "67,280", amount: "5.42", pct: 88, exchanges: ["OKX", "Bybit"] },
];

const asks = [
  { price: "67,440", amount: "1.82", pct: 58, exchanges: ["Binance"] },
  { price: "67,460", amount: "3.64", pct: 78, exchanges: ["Coinbase", "OKX"] },
  { price: "67,500", amount: "8.42", pct: 100, exchanges: ["Binance", "OKX", "Coinbase"] },
  { price: "67,540", amount: "4.56", pct: 85, exchanges: ["Binance", "Kraken"] },
  { price: "67,600", amount: "6.84", pct: 95, exchanges: ["Binance", "OKX"] },
];

const whaleOrders = [
  { time: "14:23", side: "buy" as const, price: "$67,340", size: "$4.2M", exchange: "Binance", type: "Iceberg" },
  { time: "14:22", side: "sell" as const, price: "$67,500", size: "$2.8M", exchange: "OKX", type: "Limit" },
  { time: "14:19", side: "buy" as const, price: "$67,300", size: "$3.4M", exchange: "Bybit", type: "Market" },
  { time: "14:17", side: "buy" as const, price: "$67,220", size: "$5.8M", exchange: "dYdX", type: "Limit" },
  { time: "14:15", side: "sell" as const, price: "$67,480", size: "$1.4M", exchange: "Kraken", type: "Limit" },
];

const buyPressure = [
  { exchange: "Binance", buy: 62 },
  { exchange: "OKX", buy: 55 },
  { exchange: "Coinbase", buy: 68 },
  { exchange: "Bybit", buy: 58 },
  { exchange: "dYdX", buy: 72 },
  { exchange: "Uniswap", buy: 64 },
];

function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Order Flow Analysis</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">49 exchanges · Live</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function OrderFlowPage() {
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
                {ex.name} <span className="font-mono">{ex.depth}</span>
              </span>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-1.5 shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-accent-success animate-pulse"></span>
            <span className="text-[11px] text-accent-success font-bold">LIVE</span>
          </div>
        </div>

        {/* Insight Hero */}
        <div className="glass-panel glow-cyan rounded-xl p-5 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-accent-success/[0.03] via-transparent to-neon-cyan/[0.03] pointer-events-none" />
          <div className="flex flex-col lg:flex-row items-start lg:items-center gap-4 relative z-10">
            <div className="flex items-center gap-3 flex-1">
              <div className="w-12 h-12 rounded-xl bg-accent-success/10 border border-accent-success/20 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-accent-success text-[24px]">trending_up</span>
              </div>
              <div>
                <div className="flex items-center gap-2 mb-0.5">
                  <h3 className="text-lg font-bold text-white">Buy pressure dominating</h3>
                  <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-accent-success/15 text-accent-success">BULLISH FLOW</span>
                </div>
                <p className="text-xs text-slate-400">Bids outweigh asks by 18.4%. Whale orders 3.2:1 buy/sell ratio. Iceberg detection on bid side at $67,340.</p>
              </div>
            </div>
            <div className="flex items-center gap-5 shrink-0">
              <div className="text-center">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider">Net Pressure</div>
                <div className="text-lg font-bold text-accent-success">+$24.8M</div>
              </div>
              <div className="w-px h-8 bg-white/10"></div>
              <div className="text-center">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider">Spread</div>
                <div className="text-lg font-bold text-white">0.018%</div>
              </div>
              <div className="w-px h-8 bg-white/10"></div>
              <div className="text-center">
                <div className="text-[11px] text-slate-500 uppercase tracking-wider">Imbalance</div>
                <div className="text-lg font-bold text-neon-cyan">+18.4%</div>
              </div>
            </div>
          </div>
        </div>

        {/* Depth Chart Visualization */}
        <div className="glass-panel rounded-xl overflow-hidden">
          <div className="p-4 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
            <h3 className="text-white text-sm font-bold flex items-center gap-2">
              <span className="material-symbols-outlined text-neon-cyan text-[18px]">stacked_line_chart</span>
              Aggregated Depth Chart
            </h3>
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span className="px-1.5 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan/70 font-bold">5 CEX</span>
              <span className="px-1.5 py-0.5 rounded bg-neon-purple/10 text-neon-purple/70 font-bold">2 DEX</span>
              <span>aggregated</span>
            </div>
          </div>
          <div className="p-6">
            <svg viewBox="0 0 800 250" className="w-full h-[250px]" preserveAspectRatio="xMidYMid meet">
              <defs>
                <linearGradient id="bidFill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#0bda5e" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="#0bda5e" stopOpacity="0.02" />
                </linearGradient>
                <linearGradient id="askFill" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#ff3333" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="#ff3333" stopOpacity="0.02" />
                </linearGradient>
              </defs>

              {/* Grid */}
              {[50, 100, 150, 200].map((y) => (
                <line key={y} x1="0" x2="800" y1={y} y2={y} stroke="rgba(255,255,255,0.03)" />
              ))}
              <line x1="400" x2="400" y1="0" y2="230" stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />

              {/* Bid curve */}
              <path d="M400,50 L380,55 L340,70 L300,90 L240,115 L180,135 L120,160 L60,185 L0,210 L0,230 L400,230 Z" fill="url(#bidFill)" />
              <path d="M400,50 L380,55 L340,70 L300,90 L240,115 L180,135 L120,160 L60,185 L0,210" fill="none" stroke="#0bda5e" strokeWidth="2" strokeLinecap="round" />

              {/* Ask curve */}
              <path d="M400,50 L420,58 L460,75 L500,100 L560,130 L620,155 L680,175 L740,195 L800,215 L800,230 L400,230 Z" fill="url(#askFill)" />
              <path d="M400,50 L420,58 L460,75 L500,100 L560,130 L620,155 L680,175 L740,195 L800,215" fill="none" stroke="#ff3333" strokeWidth="2" strokeLinecap="round" />

              {/* Whale buy wall annotation */}
              <rect x="105" y="155" width="30" height="75" fill="rgba(11,218,94,0.12)" rx="3" />
              <text x="120" y="148" textAnchor="middle" fill="#0bda5e" fontSize="9" fontFamily="monospace" fontWeight="bold">$4.2M Wall</text>

              {/* Whale sell wall annotation */}
              <rect x="485" y="92" width="30" height="138" fill="rgba(255,51,51,0.12)" rx="3" />
              <text x="500" y="85" textAnchor="middle" fill="#ff3333" fontSize="9" fontFamily="monospace" fontWeight="bold">$8.4M Wall</text>

              {/* Current price */}
              <circle cx="400" cy="50" r="5" fill="#00f0ff">
                <animate attributeName="r" dur="2s" repeatCount="indefinite" values="4;6;4" />
              </circle>
              <text x="400" y="240" textAnchor="middle" fill="#00f0ff" fontSize="10" fontFamily="monospace" fontWeight="bold">$67,420</text>

              {/* Labels */}
              <text x="10" y="18" fill="#0bda5e" fontSize="9" fontFamily="monospace" opacity="0.6">BIDS</text>
              <text x="760" y="18" fill="#ff3333" fontSize="9" fontFamily="monospace" opacity="0.6">ASKS</text>
            </svg>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-4 md:gap-6">
          {/* Order Book — compact */}
          <div className="col-span-12 lg:col-span-5">
            <div className="glass-panel rounded-xl overflow-hidden h-full">
              <div className="p-3 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
                <h3 className="text-white text-xs font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-cyan text-[16px]">swap_vert</span>
                  Order Book
                </h3>
                <span className="text-[11px] text-slate-500">Mid: <span className="text-white font-mono font-bold">$67,420</span></span>
              </div>
              <div className="grid grid-cols-2">
                <div className="border-r border-white/5">
                  <div className="px-3 py-1.5 border-b border-white/5 text-[11px] uppercase text-slate-600 tracking-wider flex">
                    <span className="flex-1">Bid</span><span className="flex-1 text-right">Size</span>
                  </div>
                  {bids.map((b, i) => (
                    <div key={i} className="relative flex items-center px-3 py-1 text-[11px] hover:bg-white/[0.03] cursor-pointer">
                      <div className="absolute left-0 top-0 bottom-0 bg-accent-success/[0.06]" style={{ width: `${b.pct}%` }} />
                      <span className="flex-1 text-accent-success font-mono relative z-10">${b.price}</span>
                      <span className="flex-1 text-right text-slate-300 font-mono relative z-10">{b.amount}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <div className="px-3 py-1.5 border-b border-white/5 text-[11px] uppercase text-slate-600 tracking-wider flex">
                    <span className="flex-1">Ask</span><span className="flex-1 text-right">Size</span>
                  </div>
                  {asks.map((a, i) => (
                    <div key={i} className="relative flex items-center px-3 py-1 text-[11px] hover:bg-white/[0.03] cursor-pointer">
                      <div className="absolute right-0 top-0 bottom-0 bg-accent-error/[0.06]" style={{ width: `${a.pct}%` }} />
                      <span className="flex-1 text-accent-error font-mono relative z-10">${a.price}</span>
                      <span className="flex-1 text-right text-slate-300 font-mono relative z-10">{a.amount}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Buy/Sell Pressure */}
          <div className="col-span-12 lg:col-span-3">
            <div className="glass-panel rounded-xl overflow-hidden h-full">
              <div className="p-3 border-b border-white/5 bg-white/[0.03]">
                <h3 className="text-white text-xs font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-purple text-[16px]">balance</span>
                  Pressure by Exchange
                </h3>
              </div>
              <div className="p-3 space-y-3">
                {buyPressure.map((ex) => (
                  <div key={ex.exchange}>
                    <div className="flex items-center justify-between text-[11px] mb-1">
                      <span className="text-slate-400">{ex.exchange}</span>
                      <span className={`font-bold font-mono ${ex.buy >= 60 ? "text-accent-success" : ex.buy <= 45 ? "text-accent-error" : "text-slate-300"}`}>{ex.buy}% buy</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-slate-800 flex overflow-hidden">
                      <div className="h-full bg-accent-success/60 rounded-l-full" style={{ width: `${ex.buy}%` }}></div>
                      <div className="h-full bg-accent-error/60 rounded-r-full" style={{ width: `${100 - ex.buy}%` }}></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Whale Orders */}
          <div className="col-span-12 lg:col-span-4">
            <div className="glass-panel glow-purple rounded-xl overflow-hidden h-full">
              <div className="p-3 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
                <h3 className="text-white text-xs font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-purple text-[16px]">water</span>
                  Whale Orders (&gt;$1M)
                  <span className="text-[10px] font-bold px-1 py-0.5 rounded bg-accent-error/15 text-accent-error animate-pulse">LIVE</span>
                </h3>
                <span className="text-[11px] text-slate-500"><span className="text-accent-success font-mono">32</span> buy / <span className="text-accent-error font-mono">10</span> sell</span>
              </div>
              <div className="divide-y divide-white/5">
                {whaleOrders.map((w, i) => (
                  <div key={i} className="px-3 py-2 hover:bg-white/[0.02] cursor-pointer flex items-center gap-2">
                    <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                      w.side === "buy" ? "bg-accent-success/10 text-accent-success" : "bg-accent-error/10 text-accent-error"
                    }`}>{w.side.toUpperCase()}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-white font-mono text-xs">{w.price}</span>
                        <span className="text-neon-cyan font-mono text-xs font-bold">{w.size}</span>
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                        <span>{w.exchange}</span>
                        <span className={`font-bold ${w.type === "Iceberg" ? "text-neon-purple" : w.type === "Market" ? "text-accent-warning" : "text-slate-400"}`}>{w.type}</span>
                      </div>
                    </div>
                    <span className="text-[11px] text-slate-600 font-mono shrink-0">{w.time}</span>
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
