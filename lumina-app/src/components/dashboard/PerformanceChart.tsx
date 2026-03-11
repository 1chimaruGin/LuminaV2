"use client";

import { useState } from "react";

const periods = ["1D", "1W", "1M", "3M", "1Y"];

export default function PerformanceChart() {
  const [activePeriod, setActivePeriod] = useState("1M");

  return (
    <div className="glass-panel glow-cyan rounded-xl flex flex-col overflow-hidden relative h-full">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0 backdrop-blur-sm">
        <h3 className="text-white text-lg font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-neon-cyan text-[20px]">ssid_chart</span>
          Performance
        </h3>
        <div className="flex bg-black/40 rounded-lg p-1 border border-white/5">
          {periods.map((p) => (
            <button
              key={p}
              onClick={() => setActivePeriod(p)}
              className={`px-2.5 py-0.5 text-[11px] rounded font-medium transition-colors cursor-pointer ${
                activePeriod === p
                  ? "bg-white/10 text-white shadow-sm"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 w-full h-full relative p-4">
        <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 800 300">
          <defs>
            <linearGradient id="perfGradient" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="rgba(0, 240, 255, 0.2)" />
              <stop offset="100%" stopColor="rgba(0, 240, 255, 0)" />
            </linearGradient>
          </defs>
          <line stroke="rgba(255,255,255,0.05)" strokeWidth="1" x1="0" x2="800" y1="75" y2="75" />
          <line stroke="rgba(255,255,255,0.05)" strokeWidth="1" x1="0" x2="800" y1="150" y2="150" />
          <line stroke="rgba(255,255,255,0.05)" strokeWidth="1" x1="0" x2="800" y1="225" y2="225" />
          <path
            d="M0,250 C50,240 100,200 150,210 C200,220 250,180 300,150 C350,120 400,160 450,140 C500,120 550,80 600,90 C650,100 700,50 750,40 L800,20 L800,300 L0,300 Z"
            fill="url(#perfGradient)"
          />
          <path
            d="M0,250 C50,240 100,200 150,210 C200,220 250,180 300,150 C350,120 400,160 450,140 C500,120 550,80 600,90 C650,100 700,50 750,40 L800,20"
            fill="none"
            stroke="#00f0ff"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
          <circle cx="600" cy="90" fill="#00f0ff" r="4" stroke="white" strokeWidth="2">
            <animate attributeName="r" dur="2s" repeatCount="indefinite" values="4;6;4" />
          </circle>
        </svg>
        <div className="absolute top-[25%] left-[55%] bg-[rgba(20,20,25,0.8)] border border-white/10 p-2.5 rounded-lg backdrop-blur-md shadow-xl pointer-events-none">
          <p className="text-[11px] text-slate-400 mb-0.5">Oct 24</p>
          <p className="text-sm font-bold text-white">$235,120</p>
          <p className="text-[11px] text-accent-success">+$12,400</p>
        </div>
      </div>
    </div>
  );
}
