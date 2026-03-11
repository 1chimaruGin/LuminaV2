"use client";

import { useState, useMemo } from "react";
import type { Ticker } from "@/lib/api";

const fP = (v: number) => `$${v < 0.001 ? v.toExponential(2) : v >= 10000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v >= 1 ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v.toFixed(4)}`;
const fV = (v: number) => { if (v >= 1e9) return "$" + (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(0) + "M"; if (v >= 1e3) return "$" + (v/1e3).toFixed(0) + "K"; return "$" + v.toFixed(0); };

interface Props { tickers: Ticker[]; loading: boolean; }

export default function TopMovers({ tickers, loading }: Props) {
  const [view, setView] = useState<"gainers" | "losers">("gainers");

  const { gainers, losers } = useMemo(() => {
    const valid = tickers.filter(t => t.price_change_24h != null && t.volume_24h > 10000);
    const sorted = [...valid].sort((a, b) => (b.price_change_24h ?? 0) - (a.price_change_24h ?? 0));
    return { gainers: sorted.slice(0, 8), losers: sorted.slice(-8).reverse() };
  }, [tickers]);

  const data = view === "gainers" ? gainers : losers;

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden">
      <div className="px-3.5 py-2.5 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-neon-lime text-[15px]">trending_up</span>
          Top Movers
        </h3>
        <div className="flex gap-0.5 bg-black/40 rounded-lg p-0.5 border border-white/5">
          <button
            onClick={() => setView("gainers")}
            className={`px-2.5 py-1 text-[11px] rounded font-bold transition-colors cursor-pointer ${
              view === "gainers" ? "bg-accent-success/15 text-accent-success" : "text-slate-500 hover:text-white"
            }`}
          >
            Gainers
          </button>
          <button
            onClick={() => setView("losers")}
            className={`px-2.5 py-1 text-[11px] rounded font-bold transition-colors cursor-pointer ${
              view === "losers" ? "bg-accent-error/15 text-accent-error" : "text-slate-500 hover:text-white"
            }`}
          >
            Losers
          </button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 text-[11px] uppercase tracking-wider border-b border-white/5">
              <th className="text-left px-3 py-1.5 font-medium">Token</th>
              <th className="text-right px-3 py-1.5 font-medium">Price</th>
              <th className="text-right px-3 py-1.5 font-medium">24h</th>
              <th className="text-right px-3 py-1.5 font-medium hidden sm:table-cell">Volume</th>
              <th className="text-right px-3 py-1.5 font-medium hidden md:table-cell">Source</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 text-center text-slate-500 text-xs">{loading ? "Loading..." : "No data"}</td></tr>
            )}
            {data.map((m) => {
              const chg = m.price_change_24h ?? 0;
              return (
              <tr key={`${m.exchange}-${m.symbol}`} className="hover:bg-white/[0.03] transition-colors cursor-pointer">
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-5 w-5 rounded-full bg-white/5 flex items-center justify-center text-[10px] font-bold text-white border border-white/10">
                      {m.base.slice(0, 2)}
                    </div>
                    <div>
                      <span className="text-white font-bold">{m.base}</span>
                      <span className="text-slate-500 text-[11px] block">/{m.quote}</span>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2 text-right text-white font-mono">{fP(m.price)}</td>
                <td className="px-3 py-2 text-right">
                  <span className={`font-bold ${chg >= 0 ? "text-accent-success" : "text-accent-error"}`}>{chg >= 0 ? "+" : ""}{chg.toFixed(2)}%</span>
                </td>
                <td className="px-3 py-2 text-right text-slate-400 font-mono hidden sm:table-cell">{fV(m.volume_24h)}</td>
                <td className="px-3 py-2 text-right hidden md:table-cell">
                  <span className="text-[11px] font-bold px-1 py-px rounded bg-neon-cyan/10 text-neon-cyan/70">CEX</span>
                  <span className="text-slate-400 text-[11px] ml-1">{m.exchange}</span>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
