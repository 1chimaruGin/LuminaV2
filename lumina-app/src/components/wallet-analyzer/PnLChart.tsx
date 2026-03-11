"use client";

import { useState } from "react";

const periods = ["7D", "30D", "90D", "1Y", "ALL"];

export default function PnLChart() {
  const [period, setPeriod] = useState("30D");

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden h-full">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0">
        <h3 className="text-white text-sm font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-accent-success text-[18px]">show_chart</span>
          PnL Over Time
        </h3>
        <div className="flex gap-1">
          {periods.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer transition-colors ${
                period === p
                  ? "bg-accent-success/10 text-accent-success border border-accent-success/30"
                  : "text-slate-500 hover:text-white"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 p-4 relative min-h-[200px]">
        <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 400 150">
          <defs>
            <linearGradient id="pnlGradient" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#0bda5e" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#0bda5e" stopOpacity="0" />
            </linearGradient>
          </defs>
          {/* Grid */}
          {[30, 60, 90, 120].map((y) => (
            <line key={y} x1="0" x2="400" y1={y} y2={y} stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
          ))}
          {/* Zero line */}
          <line x1="0" x2="400" y1="90" y2="90" stroke="rgba(255,255,255,0.1)" strokeWidth="1" strokeDasharray="4 4" />
          {/* Area fill */}
          <path
            d="M0,110 L30,105 L60,95 L90,100 L120,85 L150,70 L180,75 L210,60 L240,55 L270,45 L300,50 L330,35 L360,30 L400,20 L400,150 L0,150 Z"
            fill="url(#pnlGradient)"
          />
          {/* Line */}
          <path
            d="M0,110 L30,105 L60,95 L90,100 L120,85 L150,70 L180,75 L210,60 L240,55 L270,45 L300,50 L330,35 L360,30 L400,20"
            fill="none"
            stroke="#0bda5e"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* Current dot */}
          <circle cx="400" cy="20" r="4" fill="#0bda5e" />
          <circle cx="400" cy="20" r="7" fill="#0bda5e" opacity="0.2">
            <animate attributeName="r" dur="2s" repeatCount="indefinite" values="7;12;7" />
            <animate attributeName="opacity" dur="2s" repeatCount="indefinite" values="0.2;0;0.2" />
          </circle>
        </svg>
        {/* Y-axis labels */}
        <div className="absolute left-5 top-4 bottom-4 flex flex-col justify-between text-[11px] text-slate-500 font-mono pointer-events-none">
          <span>+$40k</span>
          <span>+$20k</span>
          <span>$0</span>
          <span>-$10k</span>
        </div>
        {/* Current value indicator */}
        <div className="absolute top-4 right-4 text-right">
          <div className="text-accent-success text-lg font-bold">+$34,218</div>
          <div className="text-[11px] text-slate-400">Current PnL</div>
        </div>
      </div>
    </div>
  );
}
