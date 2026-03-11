"use client";

import { useState } from "react";

const filters = ["All", "Trades", "Deposits", "Withdrawals"];

const activities = [
  {
    pair: "ETH/USDT",
    ticker: "ETH",
    tickerBg: "bg-indigo-900/30",
    tickerBorder: "border-indigo-500/30",
    source: "Bot Execution",
    sourceColor: "text-neon-cyan",
    side: "Buy",
    sideColor: "text-accent-success",
    sideBg: "bg-accent-success/10",
    sideBorder: "border-accent-success/20",
    size: "1.5 ETH",
    time: "2m ago",
  },
  {
    pair: "BTC/USDT",
    ticker: "BTC",
    tickerBg: "bg-orange-900/30",
    tickerBorder: "border-orange-500/30",
    source: "Manual Trade",
    sourceColor: "text-slate-400",
    side: "Sell",
    sideColor: "text-accent-error",
    sideBg: "bg-accent-error/10",
    sideBorder: "border-accent-error/20",
    size: "0.05 BTC",
    time: "15m ago",
  },
  {
    pair: "SOL/USDT",
    ticker: "SOL",
    tickerBg: "bg-purple-900/30",
    tickerBorder: "border-purple-500/30",
    source: "DCA Bot",
    sourceColor: "text-neon-cyan",
    side: "Buy",
    sideColor: "text-accent-success",
    sideBg: "bg-accent-success/10",
    sideBorder: "border-accent-success/20",
    size: "12.4 SOL",
    time: "1h ago",
  },
  {
    pair: "ARB/USDT",
    ticker: "ARB",
    tickerBg: "bg-blue-900/30",
    tickerBorder: "border-blue-500/30",
    source: "Grid Bot",
    sourceColor: "text-neon-lime",
    side: "Sell",
    sideColor: "text-accent-error",
    sideBg: "bg-accent-error/10",
    sideBorder: "border-accent-error/20",
    size: "850 ARB",
    time: "2h ago",
  },
];

export default function RecentActivity() {
  const [activeFilter, setActiveFilter] = useState("All");

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden h-[300px]">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0 backdrop-blur-sm">
        <h3 className="text-white text-lg font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-neon-purple text-[20px]">history</span>
          Recent Activity
        </h3>
        <div className="flex gap-1">
          {filters.slice(0, 2).map((f) => (
            <button
              key={f}
              onClick={() => setActiveFilter(f)}
              className={`px-2 py-1 text-xs rounded border transition-colors cursor-pointer ${
                activeFilter === f
                  ? "text-white bg-white/10 border-white/10"
                  : "text-slate-400 hover:text-white border-transparent"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-auto">
        <table className="w-full text-left border-collapse">
          <thead className="sticky top-0 bg-obsidian-light/95 backdrop-blur-sm z-10 shadow-lg">
            <tr className="text-slate-500 text-xs border-b border-white/5 uppercase tracking-wider font-semibold">
              <th className="px-3 md:px-4 py-3">Pair / Action</th>
              <th className="px-3 md:px-4 py-3">Side</th>
              <th className="px-3 md:px-4 py-3 hidden sm:table-cell">Size</th>
              <th className="px-3 md:px-4 py-3 text-right">Time</th>
            </tr>
          </thead>
          <tbody className="text-sm divide-y divide-white/5">
            {activities.map((a, i) => (
              <tr key={i} className="group hover:bg-white/5 cursor-pointer transition-colors">
                <td className="px-3 md:px-4 py-3">
                  <div className="flex items-center gap-2 md:gap-3">
                    <div className={`h-7 w-7 md:h-8 md:w-8 rounded-lg ${a.tickerBg} flex items-center justify-center text-[11px] font-bold text-white border ${a.tickerBorder}`}>
                      {a.ticker}
                    </div>
                    <div>
                      <span className="font-bold text-white block">{a.pair}</span>
                      <span className={`text-[11px] ${a.sourceColor}`}>{a.source}</span>
                    </div>
                  </div>
                </td>
                <td className="px-3 md:px-4 py-3">
                  <span className={`${a.sideColor} font-bold text-xs uppercase ${a.sideBg} px-2 py-0.5 rounded border ${a.sideBorder}`}>
                    {a.side}
                  </span>
                </td>
                <td className="px-3 md:px-4 py-3 text-white font-mono hidden sm:table-cell">{a.size}</td>
                <td className="px-3 md:px-4 py-3 text-right text-slate-400 text-xs font-mono">{a.time}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
