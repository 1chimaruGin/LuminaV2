"use client";

import { useState, useCallback } from "react";

const tabs = ["Smart Money Bubble Map", "Whale Outflow"];
const timeframes = ["1H", "4H", "1D", "1W"];

const topTransactors = [
  { addr: "0x7a...4e2", amount: "$2.4M", color: "bg-neon-cyan", textColor: "text-neon-cyan" },
  { addr: "0x9b...1f0", amount: "$1.8M", color: "bg-accent-success", textColor: "text-accent-success" },
  { addr: "0x3c...8a9", amount: "$950k", color: "bg-neon-purple", textColor: "text-neon-purple" },
  { addr: "0x21...d44", amount: "$420k", color: "bg-accent-warning", textColor: "text-accent-warning" },
  { addr: "0xff...001", amount: "$380k", color: "bg-neon-magenta", textColor: "text-neon-magenta" },
];

interface Bubble {
  cx: number;
  cy: number;
  r: number;
  fill: string;
  opacity: number;
  label: string;
  wallet?: string;
  type: "inflow" | "outflow";
  animate?: boolean;
}

const inflowBubbles: Bubble[] = [
  { cx: 80,  cy: 310, r: 12, fill: "#0bda5e", opacity: 0.7, label: "+$82k",  wallet: "0x7a...4e2", type: "inflow" },
  { cx: 160, cy: 270, r: 16, fill: "#0bda5e", opacity: 0.6, label: "+$240k", wallet: "0x3c...8a9", type: "inflow" },
  { cx: 260, cy: 220, r: 22, fill: "#0bda5e", opacity: 0.85, label: "+$1.2M", wallet: "0x9b...1f0", type: "inflow" },
  { cx: 290, cy: 240, r: 8,  fill: "#00f0ff", opacity: 0.5, label: "+$45k",  wallet: "0xa1...b22", type: "inflow" },
  { cx: 340, cy: 190, r: 14, fill: "#0bda5e", opacity: 0.7, label: "+$380k", wallet: "0xff...001", type: "inflow" },
  { cx: 420, cy: 150, r: 30, fill: "#0bda5e", opacity: 0.8, label: "+$2.4M", wallet: "0x7a...4e2", type: "inflow", animate: true },
  { cx: 390, cy: 200, r: 10, fill: "#00f0ff", opacity: 0.6, label: "+$120k", wallet: "0x21...d44", type: "inflow" },
  { cx: 180, cy: 310, r: 6,  fill: "#0bda5e", opacity: 0.4, label: "",       wallet: "0xc0...fff", type: "inflow" },
  { cx: 310, cy: 270, r: 9,  fill: "#0bda5e", opacity: 0.55, label: "",      wallet: "0xd3...e11", type: "inflow" },
];

const outflowBubbles: Bubble[] = [
  { cx: 510, cy: 180, r: 12, fill: "#ff3333", opacity: 0.7, label: "-$340k", wallet: "0xb5...c99", type: "outflow" },
  { cx: 560, cy: 140, r: 8,  fill: "#ff3333", opacity: 0.5, label: "",       wallet: "0xe2...a01", type: "outflow" },
  { cx: 620, cy: 160, r: 20, fill: "#ff3333", opacity: 0.8, label: "-$890k", wallet: "0xf0...d88", type: "outflow" },
  { cx: 700, cy: 120, r: 26, fill: "#ff3333", opacity: 0.9, label: "-$1.8M", wallet: "0x44...a12", type: "outflow", animate: true },
  { cx: 660, cy: 200, r: 10, fill: "#bc13fe", opacity: 0.6, label: "-$150k", wallet: "0x88...c33", type: "outflow" },
  { cx: 590, cy: 220, r: 7,  fill: "#ff3333", opacity: 0.4, label: "",       wallet: "0x11...f44", type: "outflow" },
  { cx: 740, cy: 170, r: 14, fill: "#ff3333", opacity: 0.7, label: "-$520k", wallet: "0x99...b66", type: "outflow" },
];

const allBubbles = [...inflowBubbles, ...outflowBubbles];

const VB_W = 800;
const VB_H = 380;

export default function BubbleMap() {
  const [activeTab, setActiveTab] = useState(0);
  const [activeTf, setActiveTf] = useState("4H");
  const [hoveredBubble, setHoveredBubble] = useState<number | null>(null);
  const [selectedBubble, setSelectedBubble] = useState<number | null>(null);

  const handleClick = useCallback((i: number) => {
    setSelectedBubble((prev) => (prev === i ? null : i));
  }, []);

  const activeBubble = selectedBubble ?? hoveredBubble;

  return (
    <div className="glass-panel glow-purple rounded-xl flex flex-col overflow-hidden relative" style={{ minHeight: 480 }}>
      {/* Header bar */}
      <div className="p-3 sm:p-4 border-b border-white/5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 bg-white/[0.03] shrink-0 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2 flex-wrap">
          {tabs.map((tab, i) => (
            <button
              key={tab}
              onClick={() => setActiveTab(i)}
              className={`text-xs font-bold px-3 py-1.5 rounded-lg border flex items-center gap-1.5 cursor-pointer transition-all ${
                activeTab === i
                  ? "bg-neon-cyan/10 text-white border-neon-cyan/40 shadow-[0_0_8px_rgba(0,240,255,0.1)]"
                  : "bg-black/30 hover:bg-black/50 text-slate-400 border-white/10"
              }`}
            >
              {activeTab === i && <span className="w-2 h-2 rounded-full bg-neon-cyan animate-pulse"></span>}
              {tab}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {timeframes.map((tf) => (
            <button
              key={tf}
              onClick={() => setActiveTf(tf)}
              className={`px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer transition-colors ${
                activeTf === tf ? "bg-white/10 text-white" : "text-slate-500 hover:text-white"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Main chart area */}
      <div className="flex-1 relative" style={{ minHeight: 360 }}>
        {/* Grid background */}
        <div
          className="absolute inset-0"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        {/* SVG chart */}
        <svg
          className="absolute inset-0 w-full h-full"
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          preserveAspectRatio="xMidYMid slice"
        >
          <defs>
            <linearGradient id="momentumGrad" x1="0%" x2="100%">
              <stop offset="0%" stopColor="#0bda5e" />
              <stop offset="45%" stopColor="#0bda5e" />
              <stop offset="55%" stopColor="#ff3333" />
              <stop offset="100%" stopColor="#ff3333" />
            </linearGradient>
            <filter id="glow">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <radialGradient id="inflowGlow">
              <stop offset="0%" stopColor="#0bda5e" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#0bda5e" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="outflowGlow">
              <stop offset="0%" stopColor="#ff3333" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#ff3333" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* Horizontal grid lines */}
          {[80, 160, 240, 320].map((y) => (
            <line key={y} x1="0" x2={VB_W} y1={y} y2={y} stroke="rgba(255,255,255,0.03)" strokeWidth="1" />
          ))}

          {/* Momentum curve */}
          <path
            d="M30,330 C80,320 130,340 180,290 S260,230 320,200 S400,170 440,140 S540,130 600,110 S680,90 760,70"
            fill="none"
            stroke="url(#momentumGrad)"
            strokeWidth="2.5"
            strokeLinecap="round"
            filter="url(#glow)"
            opacity="0.7"
          />

          {/* Divider zone */}
          <line x1={VB_W / 2} x2={VB_W / 2} y1="20" y2={VB_H - 20} stroke="rgba(255,255,255,0.05)" strokeWidth="1" strokeDasharray="4 6" />
          <text x={180} y={VB_H - 10} textAnchor="middle" fill="rgba(0,240,255,0.2)" fontSize="10" fontFamily="Space Grotesk, monospace" fontWeight="bold">
            ACCUMULATION ZONE
          </text>
          <text x={620} y={VB_H - 10} textAnchor="middle" fill="rgba(255,51,51,0.2)" fontSize="10" fontFamily="Space Grotesk, monospace" fontWeight="bold">
            DISTRIBUTION ZONE
          </text>

          {/* Bubbles */}
          {allBubbles.map((b, i) => {
            const isHovered = hoveredBubble === i;
            const isSelected = selectedBubble === i;
            const isActive = isHovered || isSelected;
            const r = isActive ? b.r * 1.3 : b.r;

            return (
              <g key={i} className="cursor-pointer">
                {/* Ambient glow */}
                <circle
                  cx={b.cx} cy={b.cy} r={b.r * 2.5}
                  fill={b.type === "inflow" ? "url(#inflowGlow)" : "url(#outflowGlow)"}
                  opacity={isActive ? 0.5 : 0.15}
                />

                {/* Selection ring */}
                {isActive && (
                  <circle cx={b.cx} cy={b.cy} r={r + 5} fill="none" stroke={b.fill} strokeWidth="1.5" opacity="0.4" strokeDasharray="3 3">
                    <animateTransform attributeName="transform" type="rotate" from={`0 ${b.cx} ${b.cy}`} to={`360 ${b.cx} ${b.cy}`} dur="8s" repeatCount="indefinite" />
                  </circle>
                )}

                {/* Main bubble */}
                <circle
                  cx={b.cx} cy={b.cy} r={r}
                  fill={b.fill}
                  opacity={isActive ? 1 : b.opacity}
                  style={{ filter: isActive ? `drop-shadow(0 0 12px ${b.fill})` : undefined, transition: "all 0.2s ease" }}
                  onMouseEnter={() => setHoveredBubble(i)}
                  onMouseLeave={() => setHoveredBubble(null)}
                  onClick={() => handleClick(i)}
                >
                  {b.animate && (
                    <animate attributeName="r" dur="3s" repeatCount="indefinite" values={`${b.r};${b.r + 3};${b.r}`} />
                  )}
                </circle>

                {/* Label */}
                {b.label && (
                  <text
                    x={b.cx} y={b.cy - r - 6}
                    fill="white"
                    fontFamily="Space Grotesk, monospace"
                    fontSize={isActive ? "12" : "10"}
                    textAnchor="middle"
                    opacity={isActive ? 1 : 0.7}
                    fontWeight={isActive ? "bold" : "normal"}
                    style={{ transition: "all 0.2s ease", pointerEvents: "none" }}
                  >
                    {b.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {/* Top transactors overlay */}
        <div className="absolute top-3 left-3 z-10 w-44 hidden sm:block">
          <div className="bg-obsidian/85 backdrop-blur-md border border-white/10 rounded-lg p-3 shadow-xl">
            <h4 className="text-[11px] uppercase font-bold text-slate-400 mb-2 tracking-wider">Top Smart Transactors</h4>
            <div className="space-y-1.5">
              {topTransactors.map((t, i) => (
                <div key={t.addr} className="flex items-center justify-between text-xs group cursor-pointer hover:bg-white/5 rounded px-1 py-0.5 -mx-1 transition-colors">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-slate-600 w-3">{i + 1}</span>
                    <div className={`w-1.5 h-1.5 rounded-full ${t.color}`}></div>
                    <span className="font-mono text-white text-[11px] group-hover:text-neon-cyan transition-colors">{t.addr}</span>
                  </div>
                  <span className={`${t.textColor} font-bold text-[11px]`}>{t.amount}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Selected bubble detail panel */}
        {activeBubble !== null && (
          <div
            className="absolute z-20 bg-obsidian/95 backdrop-blur-md border rounded-lg px-3 py-2.5 shadow-2xl pointer-events-none animate-fade-in-down"
            style={{
              left: `clamp(10px, ${(allBubbles[activeBubble].cx / VB_W) * 100}%, calc(100% - 170px))`,
              top: `clamp(10px, ${(allBubbles[activeBubble].cy / VB_H) * 100 - 18}%, calc(100% - 80px))`,
              transform: "translate(-50%, -100%)",
              borderColor: allBubbles[activeBubble].type === "inflow" ? "rgba(11,218,94,0.3)" : "rgba(255,51,51,0.3)",
            }}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className={`w-2 h-2 rounded-full ${allBubbles[activeBubble].type === "inflow" ? "bg-accent-success" : "bg-accent-error"}`}></span>
              <span className="text-[11px] text-slate-400 font-mono">
                {allBubbles[activeBubble].type === "inflow" ? "Smart Inflow" : "Smart Outflow"}
              </span>
            </div>
            <div className="text-sm font-bold text-white">
              {allBubbles[activeBubble].label || `$${(allBubbles[activeBubble].r * 38).toFixed(0)}k`}
            </div>
            {allBubbles[activeBubble].wallet && (
              <div className="text-[11px] text-slate-500 font-mono mt-0.5">{allBubbles[activeBubble].wallet}</div>
            )}
          </div>
        )}
      </div>

      {/* Bottom legend bar */}
      <div className="border-t border-white/5 bg-black/30 flex items-center px-4 py-2 justify-between text-xs text-slate-400 backdrop-blur-sm shrink-0">
        <div className="flex gap-4 items-center">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-accent-success"></span>
            <span>Inflow</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-accent-error"></span>
            <span>Outflow</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-4 h-0.5 bg-gradient-to-r from-accent-success to-accent-error rounded"></span>
            <span>Momentum</span>
          </div>
        </div>
        <div className="text-[11px] text-slate-500">
          {allBubbles.length} active flows · Click to inspect
        </div>
      </div>
    </div>
  );
}
