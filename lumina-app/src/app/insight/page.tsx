"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import {
  fetchFundingRates,
  fetchOpenInterest,
  fetchOrderFlow,
  fetchTickers,
  type FundingRate,
  type OpenInterestData,
  type OrderFlowData,
  type Ticker,
} from "@/lib/api";

const EXCHANGES = ["binance", "bybit", "okx", "gate", "kucoin", "mexc", "bitget", "hyperliquid"] as const;
const SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "ARB/USDT"];

type Tab = "order-flow" | "funding" | "open-interest" | "heatmap" | "liquidation" | "support-resistance";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "order-flow", label: "Order Flow", icon: "swap_vert" },
  { id: "funding", label: "Funding Rate", icon: "percent" },
  { id: "open-interest", label: "Open Interest", icon: "donut_large" },
  { id: "heatmap", label: "Heatmap", icon: "grid_on" },
  { id: "liquidation", label: "Liquidation", icon: "map" },
  { id: "support-resistance", label: "S/R Levels", icon: "support" },
];

const fU = (v: number) => {
  if (Math.abs(v) >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (Math.abs(v) >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (Math.abs(v) >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  if (Math.abs(v) >= 1) return "$" + v.toFixed(2);
  return "$0";
};

/* ═══════════════════════════════════════════════════════════════════════════
   ORDER FLOW TAB
   ═══════════════════════════════════════════════════════════════════════════ */
function OrderFlowTab() {
  const [sym, setSym] = useState("BTC/USDT");
  const [data, setData] = useState<OrderFlowData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (s: string) => {
    setLoading(true);
    try {
      const res = await fetchOrderFlow(s, "binance");
      setData(res.data);
    } catch { setData(null); }
    setLoading(false);
  }, []);

  useEffect(() => { load(sym); }, [sym, load]);

  return (
    <div className="space-y-4">
      {/* Symbol selector */}
      <div className="flex items-center gap-2 flex-wrap">
        {SYMBOLS.map(s => (
          <button key={s} onClick={() => setSym(s)}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              sym === s ? "bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30" : "bg-white/[0.03] text-slate-400 hover:text-white border border-white/[0.06]"
            }`}>{s.split("/")[0]}</button>
        ))}
      </div>

      {loading && <div className="text-center py-12 text-slate-500 text-sm">Loading order flow...</div>}

      {data && !loading && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Buy pressure gauge */}
          <div className="glass-panel rounded-xl p-4">
            <h4 className="text-white text-sm font-bold mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-neon-cyan text-[16px]">speed</span>
              Buy/Sell Pressure
            </h4>
            <div className="relative h-6 rounded-full bg-white/5 overflow-hidden mb-2">
              <div className="absolute inset-y-0 left-0 bg-gradient-to-r from-emerald-500 to-emerald-400 rounded-full transition-all duration-500"
                style={{ width: `${data.buy_pressure}%` }} />
              <div className="absolute inset-0 flex items-center justify-center text-[11px] font-bold text-white">
                Buy {data.buy_pressure.toFixed(1)}% — Sell {(100 - data.buy_pressure).toFixed(1)}%
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 mt-4">
              <div className="bg-emerald-500/5 rounded-lg p-3 border border-emerald-500/10">
                <div className="text-[11px] text-emerald-400 uppercase font-bold mb-1">Bid Volume</div>
                <div className="text-lg font-bold text-emerald-400 font-mono">{data.bid_volume.toFixed(2)}</div>
              </div>
              <div className="bg-rose-500/5 rounded-lg p-3 border border-rose-500/10">
                <div className="text-[11px] text-rose-400 uppercase font-bold mb-1">Ask Volume</div>
                <div className="text-lg font-bold text-rose-400 font-mono">{data.ask_volume.toFixed(2)}</div>
              </div>
            </div>
          </div>

          {/* Spread + depth */}
          <div className="glass-panel rounded-xl p-4">
            <h4 className="text-white text-sm font-bold mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-neon-purple text-[16px]">analytics</span>
              Spread & Depth
            </h4>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-slate-400 text-xs">Spread</span>
                <span className="text-white font-mono text-sm font-bold">{fU(data.spread)} ({data.spread_pct.toFixed(4)}%)</span>
              </div>
              {/* Top bids */}
              <div className="text-[11px] text-slate-500 uppercase font-bold mt-2">Top Bids</div>
              {data.top_bids.slice(0, 5).map((b, i) => (
                <div key={i} className="flex justify-between text-xs">
                  <span className="text-emerald-400 font-mono">{fU(b[0])}</span>
                  <span className="text-slate-400 font-mono">{b[1].toFixed(4)}</span>
                </div>
              ))}
              <div className="text-[11px] text-slate-500 uppercase font-bold mt-2">Top Asks</div>
              {data.top_asks.slice(0, 5).map((a, i) => (
                <div key={i} className="flex justify-between text-xs">
                  <span className="text-rose-400 font-mono">{fU(a[0])}</span>
                  <span className="text-slate-400 font-mono">{a[1].toFixed(4)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   FUNDING RATE TAB
   ═══════════════════════════════════════════════════════════════════════════ */
function FundingTab() {
  const [rates, setRates] = useState<FundingRate[]>([]);
  const [loading, setLoading] = useState(true);
  const [exFilter, setExFilter] = useState<string>("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const results = await Promise.allSettled(EXCHANGES.map(ex => fetchFundingRates(ex, 200).catch(() => ({ data: [] as FundingRate[], total: 0 }))));
      const all: FundingRate[] = [];
      for (const r of results) {
        if (r.status === "fulfilled") {
          const res = r.value as { data: FundingRate[]; total: number };
          all.push(...(res.data || []));
        }
      }
      all.sort((a, b) => Math.abs(b.rate) - Math.abs(a.rate));
      setRates(all);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 30_000); return () => clearInterval(iv); }, [load]);

  const filtered = useMemo(() => {
    if (exFilter === "all") return rates;
    return rates.filter(r => r.exchange === exFilter);
  }, [rates, exFilter]);

  const avgRate = useMemo(() => {
    if (!filtered.length) return 0;
    return filtered.reduce((s, r) => s + r.rate, 0) / filtered.length;
  }, [filtered]);

  return (
    <div className="space-y-4">
      {/* Exchange filter */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => setExFilter("all")} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${exFilter === "all" ? "bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30" : "bg-white/[0.03] text-slate-400 hover:text-white border border-white/[0.06]"}`}>All</button>
        {EXCHANGES.map(ex => (
          <button key={ex} onClick={() => setExFilter(ex)} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer capitalize ${exFilter === ex ? "bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30" : "bg-white/[0.03] text-slate-400 hover:text-white border border-white/[0.06]"}`}>{ex}</button>
        ))}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="glass-panel rounded-xl p-3">
          <div className="text-[11px] text-slate-500 uppercase font-bold mb-1">Funding Pairs</div>
          <div className="text-xl font-bold text-neon-lime font-mono">{filtered.length}</div>
        </div>
        <div className="glass-panel rounded-xl p-3">
          <div className="text-[11px] text-slate-500 uppercase font-bold mb-1">Avg Funding</div>
          <div className={`text-xl font-bold font-mono ${avgRate >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{(avgRate * 100).toFixed(4)}%</div>
        </div>
        <div className="glass-panel rounded-xl p-3">
          <div className="text-[11px] text-slate-500 uppercase font-bold mb-1">Exchanges</div>
          <div className="text-xl font-bold text-neon-cyan font-mono">{new Set(rates.map(r => r.exchange)).size}</div>
        </div>
      </div>

      {loading && <div className="text-center py-8 text-slate-500 text-sm">Loading funding rates...</div>}

      {!loading && (
        <div className="glass-panel rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/5 bg-white/[0.02]">
                  <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Symbol</th>
                  <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Exchange</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Rate</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Annualized</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Predicted</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, 50).map((r, i) => (
                  <tr key={`${r.symbol}-${r.exchange}-${i}`} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="px-3 py-2 text-white font-bold font-mono">{r.symbol.split(":")[0]}</td>
                    <td className="px-3 py-2 text-slate-400 capitalize">{r.exchange}</td>
                    <td className={`px-3 py-2 text-right font-mono font-bold ${r.rate >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{(r.rate * 100).toFixed(4)}%</td>
                    <td className={`px-3 py-2 text-right font-mono ${(r.annualized ?? 0) >= 0 ? "text-emerald-400/60" : "text-rose-400/60"}`}>{(r.annualized ?? 0).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-500">{r.predicted_rate != null ? (r.predicted_rate * 100).toFixed(4) + "%" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   OPEN INTEREST TAB
   ═══════════════════════════════════════════════════════════════════════════ */
function OpenInterestTab() {
  const [oiData, setOiData] = useState<(OpenInterestData & { exchange: string })[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const results = await Promise.allSettled(
        EXCHANGES.filter(ex => !["mexc", "gate"].includes(ex)).map(ex =>
          fetchOpenInterest(ex).then(r => (r.data || []).map(d => ({ ...d, exchange: ex }))).catch(() => [] as (OpenInterestData & { exchange: string })[])
        )
      );
      const all: (OpenInterestData & { exchange: string })[] = [];
      for (const r of results) {
        if (r.status === "fulfilled") all.push(...r.value);
      }
      all.sort((a, b) => (b.open_interest_usd || 0) - (a.open_interest_usd || 0));
      setOiData(all);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 60_000); return () => clearInterval(iv); }, [load]);

  const totalOI = useMemo(() => oiData.reduce((s, d) => s + (d.open_interest_usd || 0), 0), [oiData]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="glass-panel rounded-xl p-3">
          <div className="text-[11px] text-slate-500 uppercase font-bold mb-1">Total Open Interest</div>
          <div className="text-xl font-bold text-neon-cyan font-mono">{fU(totalOI)}</div>
        </div>
        <div className="glass-panel rounded-xl p-3">
          <div className="text-[11px] text-slate-500 uppercase font-bold mb-1">Tracked Pairs</div>
          <div className="text-xl font-bold text-neon-lime font-mono">{oiData.length}</div>
        </div>
      </div>

      {loading && <div className="text-center py-8 text-slate-500 text-sm">Loading open interest...</div>}

      {!loading && (
        <div className="glass-panel rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/5 bg-white/[0.02]">
                  <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Symbol</th>
                  <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Exchange</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">OI (USD)</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">OI (Contracts)</th>
                </tr>
              </thead>
              <tbody>
                {oiData.map((d, i) => (
                  <tr key={`${d.symbol}-${d.exchange}-${i}`} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="px-3 py-2 text-white font-bold font-mono">{d.symbol?.split(":")[0] || "—"}</td>
                    <td className="px-3 py-2 text-slate-400 capitalize">{d.exchange}</td>
                    <td className="px-3 py-2 text-right font-mono text-neon-cyan font-bold">{fU(d.open_interest_usd || 0)}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-400">{(d.open_interest || 0).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   HEATMAP TAB — volume heatmap from real tickers
   ═══════════════════════════════════════════════════════════════════════════ */
function HeatmapTab() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchTickers("binance", 100);
      setTickers(res.data || []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); const iv = setInterval(load, 30_000); return () => clearInterval(iv); }, [load]);

  const sorted = useMemo(() => [...tickers].sort((a, b) => b.volume_24h - a.volume_24h).slice(0, 40), [tickers]);
  const maxVol = useMemo(() => Math.max(...sorted.map(t => t.volume_24h), 1), [sorted]);

  return (
    <div className="space-y-4">
      {loading && <div className="text-center py-8 text-slate-500 text-sm">Loading heatmap...</div>}
      {!loading && (
        <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-1.5">
          {sorted.map(t => {
            const pct = t.price_change_24h || 0;
            const size = Math.max(0.3, Math.min(1, t.volume_24h / maxVol));
            const bg = pct >= 2 ? "bg-emerald-500" : pct >= 0 ? "bg-emerald-500/40" : pct >= -2 ? "bg-rose-500/40" : "bg-rose-500";
            return (
              <div key={t.symbol} className={`${bg} rounded-lg p-2 flex flex-col items-center justify-center transition-all hover:scale-105 cursor-pointer`}
                style={{ opacity: 0.4 + size * 0.6 }}>
                <span className="text-[11px] font-bold text-white truncate max-w-full">{t.base}</span>
                <span className={`text-[11px] font-mono font-bold ${pct >= 0 ? "text-white" : "text-white/80"}`}>
                  {pct >= 0 ? "+" : ""}{pct.toFixed(1)}%
                </span>
                <span className="text-[11px] text-white/50 font-mono">{fU(t.volume_24h)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   LIQUIDATION TAB — estimated from funding + OI data
   ═══════════════════════════════════════════════════════════════════════════ */
function LiquidationTab() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchTickers("binance", 50);
      setTickers(res.data || []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Estimate liquidation clusters from price volatility
  const liquidationData = useMemo(() => {
    return tickers.slice(0, 12).map(t => {
      const price = t.price;
      const vol = Math.abs(t.price_change_24h || 2);
      const longLiq = price * (1 - vol / 100 * 2.5);
      const shortLiq = price * (1 + vol / 100 * 2.5);
      return {
        symbol: t.base,
        price,
        longLiqZone: longLiq,
        shortLiqZone: shortLiq,
        distLong: ((price - longLiq) / price * 100),
        distShort: ((shortLiq - price) / price * 100),
      };
    });
  }, [tickers]);

  return (
    <div className="space-y-4">
      <div className="glass-panel rounded-xl p-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="material-symbols-outlined text-amber-400 text-[14px]">info</span>
          <span className="text-[11px] text-amber-400/80">Estimated liquidation zones based on 24h volatility and typical leverage (5-10x). Not precise — use as directional guide.</span>
        </div>
      </div>

      {loading && <div className="text-center py-8 text-slate-500 text-sm">Loading liquidation data...</div>}

      {!loading && (
        <div className="glass-panel rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/5 bg-white/[0.02]">
                  <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Symbol</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Price</th>
                  <th className="text-right px-3 py-2 text-emerald-500 font-bold uppercase text-[11px]">Long Liq Zone</th>
                  <th className="text-right px-3 py-2 text-rose-500 font-bold uppercase text-[11px]">Short Liq Zone</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Distance ↓</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Distance ↑</th>
                </tr>
              </thead>
              <tbody>
                {liquidationData.map((d, i) => (
                  <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="px-3 py-2 text-white font-bold">{d.symbol}</td>
                    <td className="px-3 py-2 text-right font-mono text-white">{fU(d.price)}</td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-400">{fU(d.longLiqZone)}</td>
                    <td className="px-3 py-2 text-right font-mono text-rose-400">{fU(d.shortLiqZone)}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-400">{d.distLong.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-400">{d.distShort.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SUPPORT / RESISTANCE TAB — computed from real ticker data
   ═══════════════════════════════════════════════════════════════════════════ */
function SRTab() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchTickers("binance", 50);
      setTickers(res.data || []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Compute S/R from high/low/price
  const srData = useMemo(() => {
    return tickers.slice(0, 12).map(t => {
      const price = t.price;
      const high = t.high_24h || price * 1.02;
      const low = t.low_24h || price * 0.98;
      const mid = (high + low) / 2;
      const s1 = low;
      const s2 = low - (high - low) * 0.236;
      const r1 = high;
      const r2 = high + (high - low) * 0.236;
      return { symbol: t.base, price, s1, s2, r1, r2, mid, range: ((high - low) / low * 100) };
    });
  }, [tickers]);

  return (
    <div className="space-y-4">
      {loading && <div className="text-center py-8 text-slate-500 text-sm">Loading S/R levels...</div>}

      {!loading && (
        <div className="glass-panel rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-white/5 bg-white/[0.02]">
                  <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Symbol</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Price</th>
                  <th className="text-right px-3 py-2 text-emerald-500 font-bold uppercase text-[11px]">Support 1</th>
                  <th className="text-right px-3 py-2 text-emerald-500/60 font-bold uppercase text-[11px]">Support 2</th>
                  <th className="text-right px-3 py-2 text-rose-500 font-bold uppercase text-[11px]">Resist 1</th>
                  <th className="text-right px-3 py-2 text-rose-500/60 font-bold uppercase text-[11px]">Resist 2</th>
                  <th className="text-right px-3 py-2 text-slate-500 font-bold uppercase text-[11px]">Range</th>
                </tr>
              </thead>
              <tbody>
                {srData.map((d, i) => (
                  <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="px-3 py-2 text-white font-bold">{d.symbol}</td>
                    <td className="px-3 py-2 text-right font-mono text-white">{fU(d.price)}</td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-400">{fU(d.s1)}</td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-400/60">{fU(d.s2)}</td>
                    <td className="px-3 py-2 text-right font-mono text-rose-400">{fU(d.r1)}</td>
                    <td className="px-3 py-2 text-right font-mono text-rose-400/60">{fU(d.r2)}</td>
                    <td className="px-3 py-2 text-right font-mono text-amber-400">{d.range.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════════════════════════════════════════ */
function InsightHeader() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-4">
        <h2 className="text-white text-sm font-bold tracking-tight">Trading Insight</h2>
        <div className="h-4 w-px bg-white/10 mx-1 hidden md:block" />
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-neon-cyan/10 border border-neon-cyan/20 text-[11px] text-neon-cyan font-bold">
          <span className="w-1.5 h-1.5 rounded-full bg-neon-cyan animate-pulse" />
          LIVE · {EXCHANGES.length} exchanges
        </span>
      </div>
      <div className="flex items-center gap-4">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function TradingInsightPage() {
  const [tab, setTab] = useState<Tab>("order-flow");

  return (
    <AppShell header={<InsightHeader />}>
      <div className="space-y-4">
        {/* Tab bar */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${
                tab === t.id
                  ? "bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/25 shadow-[0_0_12px_rgba(0,240,255,0.1)]"
                  : "bg-white/[0.03] text-slate-400 hover:text-white border border-white/[0.06] hover:bg-white/[0.06]"
              }`}>
              <span className="material-symbols-outlined text-[16px]">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {tab === "order-flow" && <OrderFlowTab />}
        {tab === "funding" && <FundingTab />}
        {tab === "open-interest" && <OpenInterestTab />}
        {tab === "heatmap" && <HeatmapTab />}
        {tab === "liquidation" && <LiquidationTab />}
        {tab === "support-resistance" && <SRTab />}
      </div>
    </AppShell>
  );
}
