"use client";

import { useState } from "react";

const viewOptions = ["By Category", "By Token", "By Chain"];

const datasets: Record<string, { label: string; pct: number; value: string; color: string; dasharray: string; offset: string }[]> = {
  "By Category": [
    { label: "L1", pct: 50, value: "$124,210", color: "#3b82f6", dasharray: "125 251", offset: "0" },
    { label: "DeFi", pct: 30, value: "$74,526", color: "#ccff00", dasharray: "75 251", offset: "-125" },
    { label: "Memes", pct: 20, value: "$49,684", color: "#bc13fe", dasharray: "51 251", offset: "-200" },
  ],
  "By Token": [
    { label: "ETH", pct: 40, value: "$99,368", color: "#6366f1", dasharray: "100 251", offset: "0" },
    { label: "SOL", pct: 25, value: "$62,105", color: "#a855f7", dasharray: "63 251", offset: "-100" },
    { label: "BTC", pct: 20, value: "$49,684", color: "#f59e0b", dasharray: "50 251", offset: "-163" },
    { label: "Other", pct: 15, value: "$37,263", color: "#64748b", dasharray: "38 251", offset: "-213" },
  ],
  "By Chain": [
    { label: "Ethereum", pct: 65, value: "$161,473", color: "#6366f1", dasharray: "163 251", offset: "0" },
    { label: "Solana", pct: 25, value: "$62,105", color: "#a855f7", dasharray: "63 251", offset: "-163" },
    { label: "Arbitrum", pct: 10, value: "$24,842", color: "#38bdf8", dasharray: "25 251", offset: "-226" },
  ],
};

export default function AllocationChart() {
  const [view, setView] = useState("By Category");
  const [hovered, setHovered] = useState<number | null>(null);

  const allocations = datasets[view] || datasets["By Category"];
  const center = hovered !== null ? allocations[hovered] : allocations[0];

  return (
    <div className="glass-panel glow-purple rounded-xl flex flex-col overflow-hidden h-full">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0 backdrop-blur-sm">
        <h3 className="text-white text-lg font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-neon-lime text-[20px]">pie_chart</span>
          Allocation
        </h3>
        <select
          value={view}
          onChange={(e) => setView(e.target.value)}
          className="bg-black/40 border border-white/10 text-[11px] text-slate-300 rounded px-2 py-1 outline-none focus:border-neon-lime cursor-pointer"
        >
          {viewOptions.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </div>
      <div className="flex-1 w-full h-full relative p-4 flex items-center justify-center">
        <div className="relative w-48 h-48">
          <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
            {allocations.map((a, i) => (
              <circle
                key={a.label}
                cx="50"
                cy="50"
                r="40"
                fill="transparent"
                stroke={a.color}
                strokeWidth={hovered === i ? 16 : 12}
                strokeDasharray={a.dasharray}
                strokeDashoffset={a.offset}
                className="transition-all duration-300 cursor-pointer"
                opacity={hovered !== null && hovered !== i ? 0.4 : 1}
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
              />
            ))}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none transition-all duration-200">
            <span className="text-[11px] text-slate-400 uppercase tracking-wide">
              {hovered !== null ? center.label : "Largest"}
            </span>
            <span className="text-xl font-bold text-white">
              {center.label} ({center.pct}%)
            </span>
            <span className="text-xs font-mono mt-0.5" style={{ color: center.color }}>
              {center.value}
            </span>
          </div>
        </div>
        <div className="absolute bottom-4 left-4 right-4 flex justify-center gap-4 flex-wrap text-[11px]">
          {allocations.map((a, i) => (
            <div
              key={a.label}
              className="flex items-center gap-1.5 cursor-pointer transition-opacity duration-200"
              style={{ opacity: hovered !== null && hovered !== i ? 0.4 : 1 }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
            >
              <span className="w-2 h-2 rounded-full" style={{ background: a.color }}></span>
              <span className="text-slate-300">{a.label}</span>
              <span className="text-white font-bold">{a.pct}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
