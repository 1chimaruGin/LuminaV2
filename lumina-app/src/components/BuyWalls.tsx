"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
const SYMBOLS = ["BTC", "ETH", "SOL", "XRP"];

interface WallData {
  asset: string;
  bidPrice: number;
  bidVol: number;
  askPrice: number;
  askVol: number;
  buyPressure: number;
  spread: number;
}

function fmtPrice(n: number): string {
  if (n >= 10000) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (n >= 1) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  return `$${n.toFixed(4)}`;
}

function fmtVol(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return n.toFixed(1);
}

export default function BuyWalls() {
  const [walls, setWalls] = useState<WallData[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchWalls = useCallback(async () => {
    try {
      const results = await Promise.allSettled(
        SYMBOLS.map(async (sym) => {
          const res = await fetch(`${API_BASE}/market/order-flow/${sym}?exchange=binance`);
          if (!res.ok) return null;
          const { data } = await res.json();
          if (!data) return null;
          return {
            asset: sym,
            bidPrice: data.top_bids?.[0]?.[0] || 0,
            bidVol: data.bid_volume || 0,
            askPrice: data.top_asks?.[0]?.[0] || 0,
            askVol: data.ask_volume || 0,
            buyPressure: data.buy_pressure || 50,
            spread: data.spread_pct || 0,
          } as WallData;
        })
      );

      const valid: WallData[] = [];
      for (const r of results) {
        if (r.status === "fulfilled" && r.value) valid.push(r.value);
      }
      if (valid.length > 0) setWalls(valid);
    } catch {
      // keep existing
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWalls();
    const iv = setInterval(fetchWalls, 10_000);
    return () => clearInterval(iv);
  }, [fetchWalls]);

  const maxVol = Math.max(...walls.map((w) => Math.max(w.bidVol, w.askVol)), 1);

  return (
    <div className="glass-panel rounded-xl p-3.5 flex-1 flex flex-col min-h-[220px] relative overflow-hidden">
      <div className="absolute -right-10 -top-10 w-40 h-40 bg-neon-cyan/5 rounded-full blur-3xl pointer-events-none" />
      <div className="flex items-center justify-between mb-3 relative z-10">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-neon-cyan text-[15px]">layers</span>
          Order Book Depth
        </h3>
        <span className="text-xs text-slate-400">Top 50 levels · Live</span>
      </div>
      <div className="space-y-3 relative z-10 flex-1">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <span className="material-symbols-outlined text-neon-cyan text-[24px] animate-spin">progress_activity</span>
          </div>
        ) : walls.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-slate-600 text-xs">No order book data available</p>
          </div>
        ) : walls.map((wall) => {
          const bidPct = (wall.bidVol / maxVol) * 100;
          const askPct = (wall.askVol / maxVol) * 100;
          const isBuyDominant = wall.buyPressure >= 50;

          return (
            <div key={wall.asset}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-white font-bold">{wall.asset}</span>
                <div className="flex items-center gap-3">
                  <span className="text-accent-success text-[11px] font-mono">Bid {fmtVol(wall.bidVol)}</span>
                  <span className="text-accent-error text-[11px] font-mono">Ask {fmtVol(wall.askVol)}</span>
                </div>
              </div>
              <div className="flex gap-1 mb-1">
                <div className="flex-1">
                  <div className="w-full bg-slate-800/50 h-2 rounded-full overflow-hidden">
                    <div
                      className="bg-accent-success/60 h-full rounded-full transition-all duration-700"
                      style={{ width: `${bidPct}%`, boxShadow: bidPct > 80 ? "0 0 6px rgba(11,218,94,0.4)" : "none" }}
                    />
                  </div>
                </div>
                <div className="flex-1">
                  <div className="w-full bg-slate-800/50 h-2 rounded-full overflow-hidden flex justify-end">
                    <div
                      className="bg-accent-error/50 h-full rounded-full transition-all duration-700"
                      style={{ width: `${askPct}%` }}
                    />
                  </div>
                </div>
              </div>
              <div className="flex justify-between text-[11px] text-slate-500">
                <span>Best bid: <span className="text-white font-mono">{fmtPrice(wall.bidPrice)}</span></span>
                <span className={`font-bold ${isBuyDominant ? "text-accent-success" : "text-accent-error"}`}>
                  {wall.buyPressure.toFixed(0)}% buy pressure
                </span>
                <span>Spread: <span className="text-slate-300 font-mono">{wall.spread.toFixed(3)}%</span></span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
