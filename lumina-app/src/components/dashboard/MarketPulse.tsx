"use client";

import { useMemo } from "react";
import type { Ticker, FundingRate, WhaleTrade } from "@/lib/api";

const fU = (v: number) => { if (v >= 1e9) return "$" + (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(1) + "M"; if (v >= 1e3) return "$" + (v/1e3).toFixed(0) + "K"; return "$" + v.toFixed(0); };

interface Props { tickers: Ticker[]; fundingRates: FundingRate[]; whaleTrades: WhaleTrade[]; }

export default function MarketPulse({ tickers, fundingRates, whaleTrades }: Props) {
  const pulseItems = useMemo(() => {
    const items: { label: string; value: string; status: string; statusColor: string; icon: string; detail: string }[] = [];

    // Funding rates
    if (fundingRates.length > 0) {
      const avgRate = fundingRates.reduce((a, f) => a + f.rate, 0) / fundingRates.length;
      const positive = fundingRates.filter(f => f.rate > 0).length;
      const isBull = avgRate > 0;
      items.push({ label: "Avg Funding Rate", value: `${avgRate >= 0 ? "+" : ""}${(avgRate * 100).toFixed(4)}%`, status: isBull ? "Bullish Bias" : "Bearish Bias", statusColor: isBull ? "text-accent-success" : "text-accent-error", icon: "percent", detail: `${positive}/${fundingRates.length} positive` });
    }

    // Total volume from tickers
    if (tickers.length > 0) {
      const totalVol = tickers.reduce((a, t) => a + (t.volume_24h || 0), 0);
      items.push({ label: "Total 24h Volume", value: fU(totalVol), status: "Aggregated", statusColor: "text-neon-cyan", icon: "bar_chart", detail: `Across ${tickers.length} pairs` });
    }

    // Whale pressure
    if (whaleTrades.length > 0) {
      const buyVol = whaleTrades.filter(t => t.side === "buy").reduce((a, t) => a + t.usd_value, 0);
      const sellVol = whaleTrades.filter(t => t.side === "sell").reduce((a, t) => a + t.usd_value, 0);
      const total = buyVol + sellVol || 1;
      const buyPct = Math.round((buyVol / total) * 100);
      const isBull = buyPct >= 50;
      items.push({ label: "Whale Pressure", value: `${buyPct}% Buy`, status: isBull ? "Accumulating" : "Distributing", statusColor: isBull ? "text-accent-success" : "text-accent-error", icon: "water", detail: `${whaleTrades.length} trades tracked` });
      items.push({ label: "Whale Buy Vol", value: fU(buyVol), status: "vs " + fU(sellVol) + " sell", statusColor: "text-neon-lime", icon: "trending_up", detail: "Aggregated whale trades" });
    }

    // Top BTC ticker
    const btc = tickers.find(t => t.base === "BTC" && t.quote === "USDT");
    if (btc) {
      const chg = btc.price_change_24h ?? 0;
      items.push({ label: "BTC Price", value: "$" + btc.price.toLocaleString(), status: `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}% 24h`, statusColor: chg >= 0 ? "text-accent-success" : "text-accent-error", icon: "currency_bitcoin", detail: "Vol: " + fU(btc.volume_24h) });
    }
    const eth = tickers.find(t => t.base === "ETH" && t.quote === "USDT");
    if (eth) {
      const chg = eth.price_change_24h ?? 0;
      items.push({ label: "ETH Price", value: "$" + eth.price.toLocaleString(), status: `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}% 24h`, statusColor: chg >= 0 ? "text-accent-success" : "text-accent-error", icon: "diamond", detail: "Vol: " + fU(eth.volume_24h) });
    }

    return items;
  }, [tickers, fundingRates, whaleTrades]);

  return (
    <div className="glass-panel rounded-xl overflow-hidden h-full flex flex-col">
      <div className="px-3.5 py-2.5 border-b border-white/5 bg-white/[0.03] flex items-center justify-between shrink-0">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-neon-cyan text-[15px]">monitor_heart</span>
          Market Pulse
        </h3>
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-accent-success animate-pulse"></span>
          <span className="text-[11px] text-accent-success font-bold">LIVE</span>
        </div>
      </div>
      <div className="flex-1 divide-y divide-white/5 overflow-y-auto">
        {pulseItems.length === 0 && (
          <div className="px-3.5 py-4 text-center text-slate-500 text-xs">Loading market data...</div>
        )}
        {pulseItems.map((item) => (
          <div key={item.label} className="px-3.5 py-2 hover:bg-white/[0.02] transition-colors cursor-pointer group">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[14px] text-slate-500 group-hover:text-white transition-colors">{item.icon}</span>
                <span className="text-xs font-medium text-white">{item.label}</span>
              </div>
              <span className="text-xs font-bold font-mono text-white">{item.value}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className={`text-[11px] font-bold ${item.statusColor}`}>{item.status}</span>
              <span className="text-[11px] text-slate-500 hidden sm:block">{item.detail}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
