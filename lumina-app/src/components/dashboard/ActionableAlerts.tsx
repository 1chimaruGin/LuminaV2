"use client";

import { useMemo } from "react";
import type { Ticker, FundingRate, WhaleTrade } from "@/lib/api";

const fU = (v: number) => { if (v >= 1e9) return "$" + (v/1e9).toFixed(1) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(1) + "M"; if (v >= 1e3) return "$" + (v/1e3).toFixed(0) + "K"; return "$" + v.toFixed(0); };

type Severity = "critical" | "warning" | "opportunity" | "info";
interface Alert { severity: Severity; title: string; description: string; action: string; href: string; }

const severityStyles: Record<Severity, { bg: string; dot: string; glow: string; badge: string; badgeLabel: string }> = {
  critical: { bg: "bg-accent-error/5", dot: "bg-accent-error", glow: "shadow-[0_0_8px_rgba(255,51,51,0.3)]", badge: "bg-accent-error/15 text-accent-error", badgeLabel: "CRITICAL" },
  warning: { bg: "bg-accent-warning/5", dot: "bg-accent-warning", glow: "", badge: "bg-accent-warning/15 text-accent-warning", badgeLabel: "WARNING" },
  opportunity: { bg: "bg-neon-lime/5", dot: "bg-neon-lime", glow: "", badge: "bg-neon-lime/15 text-neon-lime", badgeLabel: "OPPORTUNITY" },
  info: { bg: "bg-transparent", dot: "bg-neon-cyan", glow: "", badge: "bg-neon-cyan/10 text-neon-cyan", badgeLabel: "INTEL" },
};

interface Props { tickers: Ticker[]; whaleTrades: WhaleTrade[]; fundingRates: FundingRate[]; }

export default function ActionableAlerts({ tickers, whaleTrades, fundingRates }: Props) {
  const alerts = useMemo(() => {
    const items: Alert[] = [];

    // Whale alert — biggest trade
    if (whaleTrades.length > 0) {
      const biggest = whaleTrades.reduce((a, b) => b.usd_value > a.usd_value ? b : a, whaleTrades[0]);
      const base = biggest.symbol.split("/")[0];
      const severity: Severity = biggest.usd_value >= 500000 ? "critical" : "warning";
      items.push({ severity, title: `${base} Whale ${biggest.side === "buy" ? "Buy" : "Sell"}: ${fU(biggest.usd_value)}`, description: `${biggest.amount.toFixed(4)} ${base} traded on ${biggest.exchange || "exchange"}. ${biggest.side === "sell" ? "Potential sell pressure." : "Accumulation signal."}`, action: "View Whale Activity", href: "/whale-activity" });
    }

    // Whale buy/sell imbalance
    if (whaleTrades.length >= 3) {
      const buyVol = whaleTrades.filter(t => t.side === "buy").reduce((a, t) => a + t.usd_value, 0);
      const sellVol = whaleTrades.filter(t => t.side === "sell").reduce((a, t) => a + t.usd_value, 0);
      const total = buyVol + sellVol || 1;
      const buyPct = Math.round((buyVol / total) * 100);
      if (buyPct >= 65) items.push({ severity: "opportunity", title: `Whale Accumulation: ${buyPct}% Buy`, description: `${fU(buyVol)} buy vs ${fU(sellVol)} sell across ${whaleTrades.length} whale trades. Strong buy pressure.`, action: "View Whale Activity", href: "/whale-activity" });
      else if (buyPct <= 35) items.push({ severity: "warning", title: `Whale Distribution: ${100 - buyPct}% Sell`, description: `${fU(sellVol)} sell vs ${fU(buyVol)} buy. Whales are offloading.`, action: "View Whale Activity", href: "/whale-activity" });
    }

    // Funding rate extremes
    if (fundingRates.length > 0) {
      const extreme = fundingRates.filter(f => Math.abs(f.rate) > 0.0005);
      if (extreme.length > 0) {
        const top = extreme.sort((a, b) => Math.abs(b.rate) - Math.abs(a.rate))[0];
        const base = top.symbol.split("/")[0];
        items.push({ severity: top.rate > 0 ? "warning" : "opportunity", title: `${base} Funding ${top.rate > 0 ? "+" : ""}${(top.rate * 100).toFixed(3)}%`, description: `${top.rate > 0 ? "Longs paying shorts — potential long squeeze risk." : "Shorts paying longs — potential short squeeze opportunity."}`, action: "Funding Rates", href: "/insight/funding" });
      }
    }

    // Top gainer alert
    const validTickers = tickers.filter(t => t.price_change_24h != null && t.volume_24h > 100000);
    if (validTickers.length > 0) {
      const topGainer = validTickers.sort((a, b) => (b.price_change_24h ?? 0) - (a.price_change_24h ?? 0))[0];
      if ((topGainer.price_change_24h ?? 0) > 10) {
        items.push({ severity: "info", title: `${topGainer.base} surging +${topGainer.price_change_24h?.toFixed(1)}%`, description: `Price: $${topGainer.price.toLocaleString()} with ${fU(topGainer.volume_24h)} volume. Major move detected.`, action: "Token Analyzer", href: "/token-analyzer" });
      }
    }

    // Top loser alert
    if (validTickers.length > 0) {
      const topLoser = validTickers.sort((a, b) => (a.price_change_24h ?? 0) - (b.price_change_24h ?? 0))[0];
      if ((topLoser.price_change_24h ?? 0) < -10) {
        items.push({ severity: "warning", title: `${topLoser.base} dumping ${topLoser.price_change_24h?.toFixed(1)}%`, description: `Price: $${topLoser.price.toLocaleString()} with ${fU(topLoser.volume_24h)} volume. Avoid catching falling knives.`, action: "Token Analyzer", href: "/token-analyzer" });
      }
    }

    return items.slice(0, 6);
  }, [tickers, whaleTrades, fundingRates]);

  return (
    <div className="glass-panel rounded-xl overflow-hidden flex flex-col">
      <div className="px-3.5 py-2.5 border-b border-white/5 bg-white/[0.03] flex items-center justify-between shrink-0">
        <h3 className="text-white text-xs font-bold flex items-center gap-1.5">
          <span className="material-symbols-outlined text-accent-warning text-[15px]">notifications_active</span>
          Actionable Alerts
        </h3>
        <span className="text-[11px] text-slate-500">{alerts.length} active</span>
      </div>
      <div className="divide-y divide-white/5">
        {alerts.length === 0 && (
          <div className="px-3.5 py-4 text-center text-slate-500 text-xs">Loading alerts from live market data...</div>
        )}
        {alerts.map((alert, i) => {
          const style = severityStyles[alert.severity];
          return (
            <a key={i} href={alert.href} className={`block px-3.5 py-2 hover:bg-white/[0.02] transition-all cursor-pointer ${style.bg}`}>
              <div className="flex items-start gap-3">
                <div className={`w-1 self-stretch rounded-full ${style.dot} shrink-0 mt-0.5 ${style.glow}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                    <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${style.badge}`}>{style.badgeLabel}</span>
                    <span className="text-xs font-bold text-white">{alert.title}</span>
                  </div>
                  <p className="text-[11px] text-slate-400 mb-1.5 leading-relaxed">{alert.description}</p>
                  <span className="text-[11px] font-bold text-neon-cyan hover:underline inline-flex items-center gap-0.5">
                    {alert.action}
                    <span className="material-symbols-outlined text-[11px]">arrow_forward</span>
                  </span>
                </div>
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}
