"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { fetchMarketOverview, fetchTickers, fetchFundingRates, type Ticker, type FundingRate } from "@/lib/api";

interface Notification {
  id: number;
  icon: string;
  iconColor: string;
  title: string;
  desc: string;
  time: string;
  unread: boolean;
}

const fU = (v: number) => {
  if (Math.abs(v) >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (Math.abs(v) >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (Math.abs(v) >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  if (Math.abs(v) >= 1) return "$" + v.toFixed(2);
  return "$0";
};

function buildNotifications(tickers: Ticker[], funding: FundingRate[], overview: Record<string, unknown> | null): Notification[] {
  const notifs: Notification[] = [];
  let id = 1;
  const now = new Date();
  const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  // Fear & Greed
  if (overview) {
    const fgi = overview.fear_greed_index as number;
    const fgl = overview.fear_greed_label as string;
    if (fgi != null) {
      notifs.push({
        id: id++, icon: fgi <= 30 ? "warning" : fgi >= 70 ? "trending_up" : "monitoring",
        iconColor: fgi <= 30 ? "text-accent-error" : fgi >= 70 ? "text-accent-success" : "text-neon-cyan",
        title: `Fear & Greed: ${fgi} (${fgl})`,
        desc: fgi <= 30 ? "Market fear is elevated — potential contrarian buy zone." : fgi >= 70 ? "Market greed is high — consider taking profits." : "Market sentiment is neutral.",
        time: timeStr, unread: true,
      });
    }
  }

  // Top gainers
  const sorted = [...tickers].filter(t => t.price_change_24h != null).sort((a, b) => (b.price_change_24h ?? 0) - (a.price_change_24h ?? 0));
  const topGainer = sorted[0];
  if (topGainer && (topGainer.price_change_24h ?? 0) > 5) {
    notifs.push({
      id: id++, icon: "trending_up", iconColor: "text-accent-success",
      title: `${topGainer.base} Surging +${(topGainer.price_change_24h ?? 0).toFixed(1)}%`,
      desc: `${topGainer.base}/USDT at ${fU(topGainer.price)} with ${fU(topGainer.volume_24h)} 24h volume.`,
      time: timeStr, unread: true,
    });
  }

  // Top loser
  const topLoser = sorted[sorted.length - 1];
  if (topLoser && (topLoser.price_change_24h ?? 0) < -5) {
    notifs.push({
      id: id++, icon: "trending_down", iconColor: "text-accent-error",
      title: `${topLoser.base} Dropping ${(topLoser.price_change_24h ?? 0).toFixed(1)}%`,
      desc: `${topLoser.base}/USDT at ${fU(topLoser.price)}. Watch for support levels.`,
      time: timeStr, unread: true,
    });
  }

  // High volume alert
  const highVol = tickers.filter(t => t.volume_24h > 1e9).slice(0, 1);
  for (const t of highVol) {
    notifs.push({
      id: id++, icon: "bar_chart", iconColor: "text-neon-lime",
      title: `High Volume: ${t.base}`,
      desc: `${fU(t.volume_24h)} in 24h trading volume on ${t.exchange}.`,
      time: timeStr, unread: false,
    });
  }

  // Extreme funding rates
  const extremeFunding = funding.filter(f => Math.abs(f.rate) > 0.0005).slice(0, 2);
  for (const f of extremeFunding) {
    const base = f.symbol.split("/")[0];
    notifs.push({
      id: id++, icon: "percent", iconColor: f.rate > 0 ? "text-neon-purple" : "text-neon-cyan",
      title: `${base} Funding ${(f.rate * 100).toFixed(4)}%`,
      desc: f.rate > 0 ? `Longs paying shorts on ${f.exchange}. Potential long squeeze risk.` : `Shorts paying longs on ${f.exchange}. Short squeeze setup possible.`,
      time: timeStr, unread: false,
    });
  }

  // BTC dominance
  if (overview) {
    const btcDom = overview.btc_dominance as number;
    if (btcDom) {
      notifs.push({
        id: id++, icon: "donut_large", iconColor: "text-amber-400",
        title: `BTC Dominance: ${btcDom}%`,
        desc: btcDom > 55 ? "Bitcoin dominance rising — altcoins may underperform." : "Bitcoin dominance moderate — altcoin rotation possible.",
        time: timeStr, unread: false,
      });
    }
  }

  return notifs.slice(0, 8);
}

export default function NotificationPanel() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  const [loaded, setLoaded] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const loadNotifications = useCallback(async () => {
    try {
      const [ovRes, tickRes, frRes] = await Promise.allSettled([
        fetchMarketOverview(),
        fetchTickers(undefined, 100),
        fetchFundingRates("binance", 50),
      ]);
      const ov = ovRes.status === "fulfilled" ? ovRes.value : null;
      const tickers = tickRes.status === "fulfilled" ? (tickRes.value.data || []) : [];
      const funding = frRes.status === "fulfilled" ? (frRes.value.data || []) : [];
      const notifs = buildNotifications(tickers, funding, ov as Record<string, unknown> | null);
      setItems(notifs);
    } catch { /* silent */ }
    setLoaded(true);
  }, []);

  // Load when panel opens for the first time
  useEffect(() => {
    if (open && !loaded) loadNotifications();
  }, [open, loaded, loadNotifications]);

  const unreadCount = items.filter((n) => n.unread).length;

  const markAllRead = () => {
    setItems((prev) => prev.map((n) => ({ ...n, unread: false })));
  };

  const markRead = (id: number) => {
    setItems((prev) => prev.map((n) => n.id === id ? { ...n, unread: false } : n));
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="h-9 w-9 rounded-lg hover:bg-white/5 flex items-center justify-center text-slate-400 hover:text-white transition-colors relative cursor-pointer"
      >
        <span className="material-symbols-outlined text-[20px]">notifications</span>
        {unreadCount > 0 && (
          <span className="absolute top-1.5 right-1.5 h-2.5 w-2.5 bg-neon-cyan rounded-full animate-pulse flex items-center justify-center">
            <span className="text-[10px] font-bold text-black">{unreadCount}</span>
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-12 w-80 sm:w-96 glass-panel rounded-xl shadow-2xl z-50 border border-white/10 overflow-hidden animate-fade-in-up">
          <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03]">
            <h3 className="text-white text-sm font-bold flex items-center gap-2">
              <span className="material-symbols-outlined text-neon-cyan text-[16px]">notifications</span>
              Notifications
              {unreadCount > 0 && (
                <span className="px-1.5 py-0.5 rounded-full bg-neon-cyan/10 text-neon-cyan text-[11px] font-bold border border-neon-cyan/30">
                  {unreadCount}
                </span>
              )}
            </h3>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="text-[11px] text-slate-400 hover:text-neon-cyan transition-colors cursor-pointer"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-[400px] overflow-y-auto divide-y divide-white/5">
            {items.map((n) => (
              <div
                key={n.id}
                onClick={() => markRead(n.id)}
                className={`p-3 px-4 flex gap-3 hover:bg-white/[0.03] transition-colors cursor-pointer ${n.unread ? "bg-neon-cyan/[0.02]" : ""}`}
              >
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${n.unread ? "bg-white/10" : "bg-white/5"}`}>
                  <span className={`material-symbols-outlined text-[16px] ${n.iconColor}`}>{n.icon}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-white text-xs font-bold truncate">{n.title}</span>
                    {n.unread && <span className="w-1.5 h-1.5 rounded-full bg-neon-cyan shrink-0"></span>}
                  </div>
                  <p className="text-slate-400 text-[11px] leading-relaxed line-clamp-2">{n.desc}</p>
                  <span className="text-[11px] text-slate-600 mt-1 block">{n.time}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="p-3 border-t border-white/5 text-center bg-white/[0.02]">
            <button onClick={() => setOpen(false)} className="text-xs text-neon-cyan hover:text-cyan-300 transition-colors cursor-pointer font-medium">
              View All Notifications
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
