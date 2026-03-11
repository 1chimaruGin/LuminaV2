"use client";

import { useState, useMemo } from "react";
import type { RawWhaleTrade } from "@/app/whale-activity/page";

const filters = ["All", "Buys", "Sells"];

const TICKER_STYLES: Record<string, { bg: string; border: string; category: string }> = {
  BTC: { bg: "bg-amber-900/30", border: "border-amber-500/30", category: "Layer 1" },
  ETH: { bg: "bg-indigo-900/30", border: "border-indigo-500/30", category: "Layer 1" },
  SOL: { bg: "bg-pink-900/30", border: "border-pink-500/30", category: "Layer 1" },
  DOGE: { bg: "bg-amber-900/30", border: "border-amber-400/30", category: "Meme" },
  XRP: { bg: "bg-blue-900/30", border: "border-blue-500/30", category: "Layer 1" },
  ARB: { bg: "bg-sky-900/30", border: "border-sky-500/30", category: "Layer 2" },
  LINK: { bg: "bg-blue-900/30", border: "border-blue-500/30", category: "Oracle" },
  AVAX: { bg: "bg-red-900/30", border: "border-red-500/30", category: "Layer 1" },
  OP: { bg: "bg-red-900/30", border: "border-red-400/30", category: "Layer 2" },
  PEPE: { bg: "bg-orange-900/30", border: "border-orange-500/30", category: "Meme" },
};
const DEFAULT_STYLE = { bg: "bg-slate-800/50", border: "border-slate-600/30", category: "Token" };

const EX_COLORS: Record<string, { text: string; bg: string; border: string }> = {
  binance: { text: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/20" },
  bybit: { text: "text-orange-400", bg: "bg-orange-500/10", border: "border-orange-500/20" },
  okx: { text: "text-sky-400", bg: "bg-sky-500/10", border: "border-sky-500/20" },
  gate: { text: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/20" },
};
const DEFAULT_EX = { text: "text-slate-400", bg: "bg-slate-500/10", border: "border-slate-500/20" };

function getSignal(side: string, usdValue: number) {
  if (side === "buy" && usdValue > 200_000) return { label: "Whale Accumulation", icon: "psychology", color: "text-neon-lime", bg: "bg-neon-lime/10", border: "border-neon-lime/20" };
  if (side === "buy" && usdValue > 100_000) return { label: "Large Buy", icon: "trending_up", color: "text-accent-success", bg: "bg-accent-success/10", border: "border-accent-success/20" };
  if (side === "sell" && usdValue > 200_000) return { label: "Whale Dump", icon: "warning", color: "text-accent-error", bg: "bg-accent-error/10", border: "border-accent-error/20" };
  if (side === "sell" && usdValue > 100_000) return { label: "Dumping", icon: "trending_down", color: "text-accent-error", bg: "bg-accent-error/10", border: "border-accent-error/20" };
  if (side === "buy" && usdValue > 40_000) return { label: "Smart Buy", icon: "bolt", color: "text-neon-cyan", bg: "bg-neon-cyan/10", border: "border-neon-cyan/20" };
  if (side === "sell" && usdValue > 40_000) return { label: "Distribution", icon: "swap_horiz", color: "text-amber-300", bg: "bg-amber-500/10", border: "border-amber-500/20" };
  if (side === "buy") return { label: "Buy Flow", icon: "bolt", color: "text-neon-cyan", bg: "bg-neon-cyan/10", border: "border-neon-cyan/20" };
  return { label: "Sell Flow", icon: "swap_horiz", color: "text-slate-300", bg: "bg-slate-700", border: "border-slate-600" };
}

function fmtUsd(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60_000) return "Just now";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}h ago`;
  return `${Math.floor(diff / 86400_000)}d ago`;
}

interface Props {
  trades: RawWhaleTrade[];
  loading: boolean;
}

export default function WhaleFeed({ trades, loading }: Props) {
  const [activeFilter, setActiveFilter] = useState("All");

  const filtered = useMemo(() => {
    let list = trades;
    if (activeFilter === "Buys") list = trades.filter((t) => t.side === "buy");
    if (activeFilter === "Sells") list = trades.filter((t) => t.side === "sell");
    return list.slice(0, 50);
  }, [trades, activeFilter]);

  return (
    <div className="glass-panel glow-cyan rounded-xl flex flex-col h-[480px] overflow-hidden">
      <div className="px-3 py-2.5 border-b border-white/5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 bg-white/[0.03] shrink-0 backdrop-blur-sm">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-neon-cyan text-[16px] animate-pulse-glow">
            network_intelligence
          </span>
          Live Whale Feed
          {!loading && trades.length > 0 && (
            <span className="text-[11px] font-mono text-slate-500 font-normal ml-1">{trades.length} trades</span>
          )}
        </h3>
        <div className="flex items-center gap-2 sm:gap-3 text-xs">
          <div className="flex items-center gap-1 bg-black/40 rounded-lg p-1 border border-white/5 overflow-x-auto">
            {filters.map((f) => (
              <button
                key={f}
                onClick={() => setActiveFilter(f)}
                className={`px-2 sm:px-3 py-1 rounded font-medium transition-colors cursor-pointer whitespace-nowrap ${
                  activeFilter === f
                    ? "bg-white/10 text-white shadow-sm"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-auto">
        <table className="w-full text-left border-collapse">
          <thead className="sticky top-0 bg-obsidian-light/95 backdrop-blur-sm z-10 shadow-lg">
            <tr className="text-slate-500 text-[11px] border-b border-white/5 uppercase tracking-wider font-semibold">
              <th className="px-3 py-2">Asset</th>
              <th className="px-3 py-2 hidden md:table-cell">Flow Path</th>
              <th className="px-3 py-2">Value</th>
              <th className="px-3 py-2 hidden sm:table-cell">Signal</th>
              <th className="px-3 py-2 text-right">Time</th>
            </tr>
          </thead>
          <tbody className="text-sm divide-y divide-white/5">
            {loading ? (
              <tr><td colSpan={5} className="px-4 py-16 text-center">
                <span className="material-symbols-outlined text-neon-cyan text-[32px] animate-spin">progress_activity</span>
                <p className="text-slate-400 text-sm mt-3">Scanning whale trades across 5 tokens...</p>
                <p className="text-[11px] text-slate-500 mt-1">Aggregating from Binance · Bybit · OKX</p>
              </td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-16 text-center">
                <span className="material-symbols-outlined text-slate-600 text-[32px]">search_off</span>
                <p className="text-slate-400 text-sm mt-3">No whale trades match this filter</p>
                <p className="text-[11px] text-slate-500 mt-1">Auto-refreshing every 15 seconds</p>
              </td></tr>
            ) : null}
            {filtered.map((t, i) => {
              const base = t.symbol.split("/")[0];
              const style = TICKER_STYLES[base] || DEFAULT_STYLE;
              const signal = getSignal(t.side, t.usd_value);
              const isBuy = t.side === "buy";

              return (
                <tr
                  key={`${t.symbol}-${t.usd_value}-${t.timestamp}-${i}`}
                  className={`group hover:bg-white/5 cursor-pointer transition-all duration-300 ${
                    i === 0 ? "bg-neon-cyan/[0.03]" : ""
                  }`}
                >
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className="relative">
                        <div className={`h-7 w-7 rounded-md ${style.bg} flex items-center justify-center text-[11px] font-bold text-white border ${style.border}`}>
                          {base}
                        </div>
                        {i === 0 && (
                          <div className="absolute -bottom-1 -right-1 bg-obsidian border border-white/10 rounded-full p-0.5">
                            <span className="block w-2 h-2 bg-neon-lime rounded-full" style={{ boxShadow: "0 0 5px #ccff00" }} />
                          </div>
                        )}
                      </div>
                      <div>
                        <span className="font-bold text-white block">{base}</span>
                        <div className="flex items-center gap-1 mt-0.5">
                          {(() => { const ec = EX_COLORS[t.exchange] || DEFAULT_EX; return <span className={`text-[11px] font-bold px-1 py-px rounded ${ec.bg} ${ec.text} border ${ec.border}`}>{t.exchange}</span>; })()}
                          <span className="text-[11px] text-slate-600">CEX</span>
                          <span className="text-[11px] text-slate-600">·</span>
                          <span className="text-[11px] text-slate-600">{style.category}</span>
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2 hidden md:table-cell">
                    <div className="flex items-center gap-2 text-xs">
                      <div className={`flex items-center gap-1 ${isBuy ? "text-slate-400" : "text-neon-cyan"}`}>
                        <span className="material-symbols-outlined text-[14px]">{isBuy ? "account_balance" : "account_balance_wallet"}</span>
                        <span>{isBuy ? t.exchange : "Whale"}</span>
                      </div>
                      <span className="material-symbols-outlined text-slate-600 text-[12px]">arrow_right_alt</span>
                      <div className={`flex items-center gap-1 ${isBuy ? "text-neon-cyan" : "text-slate-400"} font-medium`}>
                        <span className="material-symbols-outlined text-[14px]">{isBuy ? "account_balance_wallet" : "account_balance"}</span>
                        <span>{isBuy ? "Buyer" : t.exchange}</span>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className={`font-bold text-xs ${isBuy ? "text-accent-success" : "text-accent-error"}`}>{fmtUsd(t.usd_value)}</div>
                    <div className="text-[11px] text-slate-400 font-mono">{t.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} {base}</div>
                  </td>
                  <td className="px-3 py-2 hidden sm:table-cell">
                    <span className={`inline-flex items-center gap-1.5 ${signal.bg} ${signal.color} px-2 py-0.5 rounded text-[11px] font-bold border ${signal.border}`}>
                      <span className="material-symbols-outlined text-[12px]">{signal.icon}</span>
                      {signal.label}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right text-slate-400 text-[11px] font-mono">{timeAgo(t.timestamp)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
