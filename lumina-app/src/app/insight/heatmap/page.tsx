"use client";

import { useState } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";

/* ── Liquidation Heatmap data: price levels × liquidation density ── */
interface HeatCell {
  priceLabel: string;
  longVal: number;  // $ millions
  shortVal: number; // $ millions
}

interface AssetHeatmap {
  asset: string;
  price: string;
  priceNum: number;
  cells: HeatCell[];
  insight: string;
  insightType: "opportunity" | "danger" | "neutral";
  totalLong: string;
  totalShort: string;
}

const heatmaps: AssetHeatmap[] = [
  {
    asset: "BTC", price: "$67,420", priceNum: 67420,
    cells: [
      { priceLabel: "$72K", longVal: 42, shortVal: 0 },
      { priceLabel: "$71K", longVal: 68, shortVal: 0 },
      { priceLabel: "$70K", longVal: 180, shortVal: 0 },
      { priceLabel: "$69K", longVal: 120, shortVal: 0 },
      { priceLabel: "$68K", longVal: 85, shortVal: 12 },
      { priceLabel: "$67.5K", longVal: 42, shortVal: 38 },
      { priceLabel: "$67K", longVal: 15, shortVal: 55 },
      { priceLabel: "$66K", longVal: 0, shortVal: 95 },
      { priceLabel: "$65K", longVal: 0, shortVal: 145 },
      { priceLabel: "$64K", longVal: 0, shortVal: 210 },
      { priceLabel: "$63K", longVal: 0, shortVal: 85 },
      { priceLabel: "$62K", longVal: 0, shortVal: 42 },
    ],
    insight: "Massive $210M short wall at $64K creates strong bounce zone. If BTC drops there, forced buying could trigger a $2K bounce.",
    insightType: "opportunity",
    totalLong: "$552M", totalShort: "$682M",
  },
  {
    asset: "ETH", price: "$3,245", priceNum: 3245,
    cells: [
      { priceLabel: "$3.6K", longVal: 18, shortVal: 0 },
      { priceLabel: "$3.5K", longVal: 42, shortVal: 0 },
      { priceLabel: "$3.4K", longVal: 0, shortVal: 92 },
      { priceLabel: "$3.35K", longVal: 0, shortVal: 55 },
      { priceLabel: "$3.3K", longVal: 28, shortVal: 18 },
      { priceLabel: "$3.25K", longVal: 12, shortVal: 32 },
      { priceLabel: "$3.2K", longVal: 8, shortVal: 48 },
      { priceLabel: "$3.1K", longVal: 0, shortVal: 68 },
      { priceLabel: "$3.05K", longVal: 0, shortVal: 85 },
      { priceLabel: "$2.95K", longVal: 0, shortVal: 52 },
    ],
    insight: "$92M short squeeze at $3,400. If ETH breaks above, shorts get liquidated creating additional buying pressure to $3,500+.",
    insightType: "opportunity",
    totalLong: "$108M", totalShort: "$450M",
  },
  {
    asset: "SOL", price: "$148.20", priceNum: 148,
    cells: [
      { priceLabel: "$165", longVal: 8, shortVal: 0 },
      { priceLabel: "$160", longVal: 18, shortVal: 0 },
      { priceLabel: "$155", longVal: 42, shortVal: 0 },
      { priceLabel: "$152", longVal: 22, shortVal: 6 },
      { priceLabel: "$148", longVal: 8, shortVal: 14 },
      { priceLabel: "$145", longVal: 0, shortVal: 24 },
      { priceLabel: "$140", longVal: 0, shortVal: 28 },
      { priceLabel: "$138", longVal: 0, shortVal: 38 },
      { priceLabel: "$132", longVal: 0, shortVal: 18 },
    ],
    insight: "SOL longs dangerously stacked at $155. Elevated funding (+0.0065%) makes this a high-risk level. Rejection = cascade to $138.",
    insightType: "danger",
    totalLong: "$98M", totalShort: "$128M",
  },
  {
    asset: "DOGE", price: "$0.0842", priceNum: 0.084,
    cells: [
      { priceLabel: "$0.095", longVal: 4, shortVal: 0 },
      { priceLabel: "$0.092", longVal: 12, shortVal: 0 },
      { priceLabel: "$0.090", longVal: 24, shortVal: 0 },
      { priceLabel: "$0.088", longVal: 8, shortVal: 4 },
      { priceLabel: "$0.084", longVal: 2, shortVal: 8 },
      { priceLabel: "$0.080", longVal: 0, shortVal: 14 },
      { priceLabel: "$0.078", longVal: 0, shortVal: 18 },
      { priceLabel: "$0.075", longVal: 0, shortVal: 12 },
    ],
    insight: "DOGE funding overheated at +0.0082%. Overleveraged longs at $0.090 are prime squeeze targets. Short bias recommended.",
    insightType: "danger",
    totalLong: "$50M", totalShort: "$56M",
  },
];

function getHeatIntensity(val: number, max: number): number {
  return Math.min((val / max) * 100, 100);
}

function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Liquidation Heatmap</h2>
        <span className="text-slate-500 text-xs font-mono hidden sm:inline">Where forced buying & selling will happen</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function HeatmapPage() {
  const [activeAsset, setActiveAsset] = useState(0);
  const data = heatmaps[activeAsset];
  const maxVal = Math.max(...data.cells.map(c => Math.max(c.longVal, c.shortVal)));

  return (
    <AppShell header={<Header />}>
      <div className="space-y-6">
        {/* ── Insight Hero ── */}
        <div className="glass-panel glow-cyan rounded-xl p-5 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-accent-error/[0.03] via-transparent to-accent-warning/[0.03] pointer-events-none" />
          <div className="flex flex-col lg:flex-row items-start lg:items-center gap-4 relative z-10">
            <div className="flex items-center gap-3 flex-1">
              <div className="w-12 h-12 rounded-xl bg-accent-warning/10 border border-accent-warning/20 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-accent-warning text-[24px]">local_fire_department</span>
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">$1.4B in liquidations within ±10% of current prices</h3>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-accent-warning/15 text-accent-warning border border-accent-warning/20">HIGH LEVERAGE ENVIRONMENT</span>
                </div>
                <p className="text-xs text-slate-400 mt-1">
                  Shorts dominate below ($1.3B) vs longs above ($808M). Any sharp move will trigger cascading liquidations creating forced price action. Key levels: BTC $64K and $70K.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4 shrink-0">
              <div className="text-center px-3">
                <div className="text-[11px] text-slate-500">Longs at Risk</div>
                <div className="text-sm font-bold text-accent-success font-mono">$808M</div>
              </div>
              <div className="w-px h-8 bg-white/10" />
              <div className="text-center px-3">
                <div className="text-[11px] text-slate-500">Shorts at Risk</div>
                <div className="text-sm font-bold text-accent-error font-mono">$1.3B</div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Asset selector ── */}
        <div className="flex items-center justify-between">
          <div className="flex gap-1 bg-black/40 rounded-lg p-0.5 border border-white/5">
            {heatmaps.map((h, i) => (
              <button key={h.asset} onClick={() => setActiveAsset(i)} className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${activeAsset === i ? "bg-white/10 text-white" : "text-slate-500 hover:text-white"}`}>
                {h.asset} <span className="text-[11px] text-slate-500 ml-1">{h.price}</span>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-4 text-[11px] text-slate-400">
            <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-accent-success/50"></span> Long liq (forced buying)</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-accent-error/50"></span> Short liq (forced selling)</span>
          </div>
        </div>

        {/* ── Visual Liquidation Heatmap ── */}
        <div className="glass-panel glow-cyan rounded-xl overflow-hidden">
          <div className="p-4 border-b border-white/5 bg-white/[0.03] flex items-center justify-between">
            <h3 className="text-white text-sm font-bold flex items-center gap-2">
              <span className="material-symbols-outlined text-accent-warning text-[18px]">grid_on</span>
              {data.asset} Liquidation Density — Price Levels
            </h3>
            <div className="flex items-center gap-3 text-[11px] text-slate-500">
              <span>Long total: <span className="text-accent-success font-bold font-mono">{data.totalLong}</span></span>
              <span>Short total: <span className="text-accent-error font-bold font-mono">{data.totalShort}</span></span>
            </div>
          </div>
          <div className="p-4">
            {/* Heatmap rows */}
            <div className="space-y-1">
              {data.cells.map((cell) => {
                const longPct = getHeatIntensity(cell.longVal, maxVal);
                const shortPct = getHeatIntensity(cell.shortVal, maxVal);
                const isCurrentPrice = cell.priceLabel.includes(
                  data.asset === "BTC" ? "67.5K" : data.asset === "ETH" ? "3.25K" : data.asset === "SOL" ? "148" : "0.084"
                );

                return (
                  <div key={cell.priceLabel} className={`flex items-center gap-2 py-1.5 px-2 rounded-lg transition-colors group ${isCurrentPrice ? "bg-white/[0.06] border border-white/10" : "hover:bg-white/[0.02]"}`}>
                    <span className={`text-xs font-mono w-14 shrink-0 ${isCurrentPrice ? "text-neon-cyan font-bold" : "text-slate-400"}`}>
                      {cell.priceLabel}
                      {isCurrentPrice && <span className="text-[10px] text-neon-cyan ml-0.5">◄</span>}
                    </span>

                    {/* Long bar (left side) */}
                    <div className="flex-1 flex justify-end">
                      {cell.longVal > 0 && (
                        <div className="relative h-7 rounded-l-md overflow-hidden transition-all" style={{ width: `${Math.max(longPct, 8)}%` }}>
                          <div
                            className="absolute inset-0 rounded-l-md"
                            style={{
                              background: `linear-gradient(90deg, rgba(11,218,94,${0.1 + longPct * 0.005}), rgba(11,218,94,${0.2 + longPct * 0.006}))`,
                            }}
                          />
                          <span className="relative z-10 flex items-center justify-end h-full px-2 text-[11px] text-accent-success font-mono font-bold">
                            ${cell.longVal}M
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Center divider */}
                    <div className={`w-px h-7 shrink-0 ${isCurrentPrice ? "bg-neon-cyan/50" : "bg-white/10"}`} />

                    {/* Short bar (right side) */}
                    <div className="flex-1">
                      {cell.shortVal > 0 && (
                        <div className="relative h-7 rounded-r-md overflow-hidden transition-all" style={{ width: `${Math.max(shortPct, 8)}%` }}>
                          <div
                            className="absolute inset-0 rounded-r-md"
                            style={{
                              background: `linear-gradient(90deg, rgba(255,51,51,${0.2 + shortPct * 0.006}), rgba(255,51,51,${0.1 + shortPct * 0.005}))`,
                            }}
                          />
                          <span className="relative z-10 flex items-center h-full px-2 text-[11px] text-accent-error font-mono font-bold">
                            ${cell.shortVal}M
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-4 md:gap-6">
          {/* ── Actionable Insight ── */}
          <div className="col-span-12 lg:col-span-8">
            <div className={`glass-panel rounded-xl p-5 border ${
              data.insightType === "opportunity" ? "border-accent-success/20" : data.insightType === "danger" ? "border-accent-error/20" : "border-white/5"
            }`}>
              <div className="flex items-start gap-3">
                <span className={`material-symbols-outlined text-[20px] shrink-0 mt-0.5 ${
                  data.insightType === "opportunity" ? "text-accent-success" : data.insightType === "danger" ? "text-accent-error" : "text-slate-400"
                }`}>
                  {data.insightType === "opportunity" ? "lightbulb" : data.insightType === "danger" ? "shield" : "info"}
                </span>
                <div>
                  <h4 className={`text-sm font-bold mb-1 ${
                    data.insightType === "opportunity" ? "text-accent-success" : data.insightType === "danger" ? "text-accent-error" : "text-white"
                  }`}>
                    {data.insightType === "opportunity" ? "Opportunity Signal" : data.insightType === "danger" ? "Risk Warning" : "Market Note"}
                  </h4>
                  <p className="text-sm text-slate-300 leading-relaxed">{data.insight}</p>
                </div>
              </div>
            </div>
          </div>

          {/* ── Quick summary for all assets ── */}
          <div className="col-span-12 lg:col-span-4">
            <div className="glass-panel rounded-xl overflow-hidden h-full flex flex-col">
              <div className="p-4 border-b border-white/5 bg-white/[0.03] shrink-0">
                <h3 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-neon-cyan text-[18px]">analytics</span>
                  Cross-Asset Liq Summary
                </h3>
              </div>
              <div className="flex-1 divide-y divide-white/5">
                {heatmaps.map((h, i) => (
                  <div key={h.asset} onClick={() => setActiveAsset(i)} className={`px-4 py-3 hover:bg-white/[0.03] transition-colors cursor-pointer ${activeAsset === i ? "bg-neon-cyan/[0.04] border-l-2 border-l-neon-cyan" : ""}`}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="text-white text-xs font-bold">{h.asset}</span>
                        <span className="text-[11px] text-white font-mono">{h.price}</span>
                      </div>
                      <span className={`text-[11px] font-bold px-1 py-px rounded ${
                        h.insightType === "opportunity" ? "bg-accent-success/10 text-accent-success" : "bg-accent-error/10 text-accent-error"
                      }`}>
                        {h.insightType === "opportunity" ? "OPPORTUNITY" : "DANGER"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-[11px]">
                      <span className="text-accent-success">Long: {h.totalLong}</span>
                      <span className="text-accent-error">Short: {h.totalShort}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
