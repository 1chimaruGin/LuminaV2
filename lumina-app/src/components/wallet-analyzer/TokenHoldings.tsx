"use client";

import { useState } from "react";

const filters = ["All", "DeFi", "L1/L2", "Memes", "Stables"];

const holdings = [
  { token: "ETH", name: "Ethereum", chain: "ETH", source: "On-chain", sourceType: "On-chain" as const, amount: "42.5", value: "$137,946", pnl: "+$18,420", pnlPct: "+15.4%", pnlColor: "text-accent-success", allocation: 55.5 },
  { token: "SOL", name: "Solana", chain: "SOL", source: "On-chain", sourceType: "On-chain" as const, amount: "320", value: "$44,800", pnl: "+$12,160", pnlPct: "+37.2%", pnlColor: "text-accent-success", allocation: 18.0 },
  { token: "BTC", name: "Bitcoin", chain: "BTC", source: "Binance", sourceType: "CEX" as const, amount: "0.42", value: "$28,316", pnl: "+$4,820", pnlPct: "+20.5%", pnlColor: "text-accent-success", allocation: 11.4 },
  { token: "ARB", name: "Arbitrum", chain: "ARB", source: "On-chain", sourceType: "On-chain" as const, amount: "18,500", value: "$20,720", pnl: "-$2,405", pnlPct: "-10.4%", pnlColor: "text-accent-error", allocation: 8.3 },
  { token: "AAVE", name: "Aave", chain: "ETH", source: "Aave V3", sourceType: "DEX" as const, amount: "85", value: "$15,640", pnl: "+$3,842", pnlPct: "+32.5%", pnlColor: "text-accent-success", allocation: 6.3 },
  { token: "PEPE", name: "Pepe", chain: "ETH", source: "Uniswap", sourceType: "DEX" as const, amount: "2.4B", value: "$12,480", pnl: "+$8,220", pnlPct: "+192%", pnlColor: "text-neon-lime", allocation: 5.0 },
  { token: "USDC", name: "USD Coin", chain: "BASE", source: "Coinbase", sourceType: "CEX" as const, amount: "10,000", value: "$10,000", pnl: "$0", pnlPct: "0%", pnlColor: "text-slate-400", allocation: 4.0 },
  { token: "JUP", name: "Jupiter", chain: "SOL", source: "Jupiter", sourceType: "DEX" as const, amount: "4,200", value: "$5,208", pnl: "+$1,420", pnlPct: "+37.5%", pnlColor: "text-accent-success", allocation: 2.1 },
  { token: "OP", name: "Optimism", chain: "OP", source: "On-chain", sourceType: "On-chain" as const, amount: "3,200", value: "$5,920", pnl: "-$480", pnlPct: "-7.5%", pnlColor: "text-accent-error", allocation: 2.4 },
  { token: "CAKE", name: "PancakeSwap", chain: "BSC", source: "PancakeSwap", sourceType: "DEX" as const, amount: "1,800", value: "$4,320", pnl: "+$620", pnlPct: "+16.7%", pnlColor: "text-accent-success", allocation: 1.7 },
  { token: "AVAX", name: "Avalanche", chain: "AVAX", source: "OKX", sourceType: "CEX" as const, amount: "120", value: "$4,632", pnl: "+$840", pnlPct: "+22.1%", pnlColor: "text-accent-success", allocation: 1.9 },
  { token: "LDO", name: "Lido DAO", chain: "ETH", source: "On-chain", sourceType: "On-chain" as const, amount: "450", value: "$914", pnl: "+$145", pnlPct: "+18.8%", pnlColor: "text-accent-success", allocation: 0.4 },
];

export default function TokenHoldings() {
  const [filter, setFilter] = useState("All");

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden">
      <div className="p-4 border-b border-white/5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 bg-white/[0.03]">
        <h3 className="text-white text-lg font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-neon-cyan text-[20px]">account_balance</span>
          Token Holdings
        </h3>
        <div className="flex gap-1">
          {filters.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors cursor-pointer ${
                filter === f
                  ? "bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/30"
                  : "hover:bg-white/5 text-slate-400 hover:text-white border border-transparent"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="text-[11px] uppercase text-slate-500 border-b border-white/5">
              <th className="px-3 md:px-4 py-3 font-medium">Token</th>
              <th className="px-3 md:px-4 py-3 font-medium text-right hidden sm:table-cell">Amount</th>
              <th className="px-3 md:px-4 py-3 font-medium text-right">Value</th>
              <th className="px-3 md:px-4 py-3 font-medium text-right">PnL</th>
              <th className="px-3 md:px-4 py-3 font-medium text-right hidden md:table-cell">Allocation</th>
            </tr>
          </thead>
          <tbody className="text-xs divide-y divide-white/5">
            {holdings.map((h) => (
              <tr key={h.token} className="hover:bg-white/5 transition-colors group cursor-pointer">
                <td className="px-3 md:px-4 py-3">
                  <div className="flex items-center gap-2 md:gap-3">
                    <div className="w-7 h-7 md:w-8 md:h-8 rounded-full bg-slate-800 flex items-center justify-center text-[11px] font-bold text-slate-300 group-hover:text-white transition-colors border border-white/5">
                      {h.token.slice(0, 2)}
                    </div>
                    <div>
                      <div className="text-white font-bold group-hover:text-neon-cyan transition-colors">{h.token}</div>
                      <div className="flex items-center gap-1 mt-0.5">
                        <span className={`text-[10px] font-bold px-1 py-px rounded ${
                          h.sourceType === "CEX" ? "bg-neon-cyan/10 text-neon-cyan/70" : h.sourceType === "DEX" ? "bg-neon-purple/10 text-neon-purple/70" : "bg-white/5 text-slate-500"
                        }`}>{h.sourceType === "On-chain" ? h.chain : h.source}</span>
                        <span className="text-[11px] text-slate-600">{h.chain}</span>
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-3 md:px-4 py-3 text-right hidden sm:table-cell">
                  <div className="text-white font-mono">{h.amount}</div>
                  <div className="text-[11px] text-slate-500">{h.chain}</div>
                </td>
                <td className="px-3 md:px-4 py-3 text-right text-white font-mono">{h.value}</td>
                <td className="px-3 md:px-4 py-3 text-right">
                  <div className={`font-bold ${h.pnlColor}`}>{h.pnl}</div>
                  <div className={`text-[11px] ${h.pnlColor}`}>{h.pnlPct}</div>
                </td>
                <td className="px-3 md:px-4 py-3 text-right hidden md:table-cell">
                  <div className="flex items-center gap-2 justify-end">
                    <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div className="h-full bg-neon-cyan/60 rounded-full" style={{ width: `${h.allocation}%` }}></div>
                    </div>
                    <span className="text-slate-300 font-mono w-10 text-right">{h.allocation}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
