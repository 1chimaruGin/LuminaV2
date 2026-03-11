"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchMarketPulse, type MarketPulseItem } from "@/lib/api";

const fU = (v: number) => {
  if (v >= 1000) return "$" + v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (v >= 1) return "$" + v.toFixed(2);
  if (v > 0) return "$" + v.toFixed(6);
  return "$0";
};

export default function MarketPulse() {
  const [markets, setMarkets] = useState<MarketPulseItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await fetchMarketPulse();
      if (res.data?.length) setMarkets(res.data);
    } catch { /* keep existing */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    return () => clearInterval(iv);
  }, [load]);

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0">
        <h3 className="text-white text-sm font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-neon-cyan text-[18px]">monitoring</span>
          AI Market Pulse
        </h3>
        <span className="text-[11px] text-slate-500">AI-scored · Live</span>
      </div>
      <div className="divide-y divide-white/5">
        {loading ? (
          <div className="p-6 flex items-center justify-center gap-2">
            <div className="w-4 h-4 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" />
            <span className="text-[11px] text-slate-600">Loading prices…</span>
          </div>
        ) : markets.map((m) => (
          <div key={m.symbol} className="flex items-center justify-between p-3 px-4 hover:bg-white/[0.03] transition-colors cursor-pointer group">
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center text-[11px] font-bold text-slate-300 group-hover:text-white transition-colors border border-white/5">
                {m.symbol.slice(0, 2)}
              </div>
              <div>
                <div className="text-white text-xs font-bold group-hover:text-neon-cyan transition-colors">{m.symbol}</div>
                <div className="text-[11px] text-slate-500">{m.name.split("/")[0]}</div>
              </div>
            </div>
            <div className="text-right flex items-center gap-4">
              <div>
                <div className="text-white text-xs font-mono">{fU(m.price)}</div>
                <div className={`text-[11px] ${m.changeColor}`}>{m.change >= 0 ? "+" : ""}{m.change.toFixed(1)}%</div>
              </div>
              <span className={`text-[11px] font-bold ${m.sentColor} hidden sm:block`}>{m.sentiment}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
