import { useState, useCallback, useRef, useEffect } from "react";
import {
  ComposedChart, AreaChart, BarChart, Area, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, ReferenceLine, Cell, CartesianGrid
} from "recharts";

// ─── Palette ──────────────────────────────────────────────────────────────────
const C = {
  bg: "#06090f",
  surface: "#0c1118",
  border: "rgba(255,255,255,0.07)",
  muted: "rgba(255,255,255,0.28)",
  dim: "rgba(255,255,255,0.12)",
  buy: "#00e5a0",
  sell: "#ff4d6d",
  accent: "#7c6aff",
  warn: "#f5a623",
  label: "#e2e8f0",
};

// ─── Mock Price Data ──────────────────────────────────────────────────────────
const buildCandles = () => {
  let p = 0.0842;
  const now = Date.now();
  return Array.from({ length: 121 }, (_, rev) => {
    const i = 120 - rev;
    const vol = Math.random() * 0.06 - 0.03;
    const spike =
      i === 72 ? 0.52 : i === 71 ? 0.31 : i === 70 ? -0.14 :
      i === 48 ? -0.28 : i === 47 ? -0.21 : 0;
    p = Math.max(0.008, p * (1 + vol + spike));
    const open = p, close = p * (1 + Math.random() * 0.03 - 0.015);
    return {
      idx: i,
      ts: now - i * 5 * 60 * 1000,
      time: new Date(now - i * 5 * 60 * 1000).toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit" }),
      open, close,
      high: Math.max(open, close) * (1 + Math.random() * 0.018),
      low: Math.min(open, close) * (1 - Math.random() * 0.018),
      volume: (200000 + Math.random() * 600000) * (1 + Math.abs(spike) * 9),
      bull: close >= open,
    };
  });
};
const CANDLES = buildCandles();

// ─── Mock Wallet Data ─────────────────────────────────────────────────────────
const PUMP_WALLETS = [
  {
    address: "0x7a4f…d91c", shortAddr: "7a4f…d91c",
    label: "Whale Alpha", tag: "whale",
    netUsd: +284000, buys: 3, sells: 0,
    supply: 4.2, historyEvents: ["pump", "pump"],
    clusterGroup: "A", onchainLabel: "Fresh wallet · 12d old",
    copySignal: true, alertRepeat: true,
    flow: [
      { t: "-5m", buy: 0, sell: 0 }, { t: "-4m", buy: 120000, sell: 0 },
      { t: "-3m", buy: 95000, sell: 0 }, { t: "-2m", buy: 69000, sell: 0 },
      { t: "-1m", buy: 0, sell: 0 }, { t: "0", buy: 0, sell: 0 },
      { t: "+1m", buy: 0, sell: 0 }, { t: "+2m", buy: 0, sell: 0 },
      { t: "+3m", buy: 0, sell: 0 }, { t: "+4m", buy: 0, sell: 0 },
    ],
    pnl: "+$284K",
  },
  {
    address: "0x3bc1…f02a", shortAddr: "3bc1…f02a",
    label: "Smart Money", tag: "smart",
    netUsd: +91000, buys: 7, sells: 1,
    supply: 1.8, historyEvents: ["pump"],
    clusterGroup: "A", onchainLabel: "Known MEV · 8 prev txns",
    copySignal: true, alertRepeat: false,
    flow: [
      { t: "-5m", buy: 0, sell: 0 }, { t: "-4m", buy: 18000, sell: 0 },
      { t: "-3m", buy: 33000, sell: 0 }, { t: "-2m", buy: 24000, sell: 0 },
      { t: "-1m", buy: 16000, sell: 0 }, { t: "0", buy: 0, sell: 0 },
      { t: "+1m", buy: 0, sell: 8000 }, { t: "+2m", buy: 0, sell: 0 },
      { t: "+3m", buy: 0, sell: 0 }, { t: "+4m", buy: 0, sell: 0 },
    ],
    pnl: "+$91K",
  },
  {
    address: "0x9f2c…bb34", shortAddr: "9f2c…bb34",
    label: "Sniper Bot", tag: "bot",
    netUsd: +33000, buys: 41, sells: 38,
    supply: 0.3, historyEvents: [],
    clusterGroup: "B", onchainLabel: "CEX deposit · Binance",
    copySignal: false, alertRepeat: false,
    flow: [
      { t: "-5m", buy: 4000, sell: 3000 }, { t: "-4m", buy: 9000, sell: 8000 },
      { t: "-3m", buy: 12000, sell: 10000 }, { t: "-2m", buy: 8000, sell: 7000 },
      { t: "-1m", buy: 0, sell: 0 }, { t: "0", buy: 0, sell: 0 },
      { t: "+1m", buy: 0, sell: 0 }, { t: "+2m", buy: 0, sell: 0 },
      { t: "+3m", buy: 0, sell: 0 }, { t: "+4m", buy: 0, sell: 0 },
    ],
    pnl: "+$33K",
  },
];

const DIP_WALLETS = [
  {
    address: "0x5e3f…220d", shortAddr: "5e3f…220d",
    label: "Dumper", tag: "sell",
    netUsd: -124000, buys: 0, sells: 5,
    supply: 3.1, historyEvents: ["pump", "dip"],
    clusterGroup: "C", onchainLabel: "Bridge · Arbitrum→ETH",
    copySignal: false, alertRepeat: true,
    flow: [
      { t: "-5m", buy: 0, sell: 0 }, { t: "-4m", buy: 0, sell: 38000 },
      { t: "-3m", buy: 0, sell: 44000 }, { t: "-2m", buy: 0, sell: 28000 },
      { t: "-1m", buy: 0, sell: 14000 }, { t: "0", buy: 0, sell: 0 },
      { t: "+1m", buy: 0, sell: 0 }, { t: "+2m", buy: 0, sell: 0 },
      { t: "+3m", buy: 0, sell: 0 }, { t: "+4m", buy: 0, sell: 0 },
    ],
    pnl: "-$124K",
  },
  {
    address: "0xd44e…9a1b", shortAddr: "d44e…9a1b",
    label: "Deployer", tag: "deployer",
    netUsd: -47000, buys: 1, sells: 2,
    supply: 8.7, historyEvents: ["pump", "dip"],
    clusterGroup: "C", onchainLabel: "Contract deployer",
    copySignal: false, alertRepeat: true,
    flow: [
      { t: "-5m", buy: 0, sell: 12000 }, { t: "-4m", buy: 0, sell: 22000 },
      { t: "-3m", buy: 0, sell: 13000 }, { t: "-2m", buy: 0, sell: 0 },
      { t: "-1m", buy: 8000, sell: 0 }, { t: "0", buy: 0, sell: 0 },
      { t: "+1m", buy: 0, sell: 0 }, { t: "+2m", buy: 0, sell: 0 },
      { t: "+3m", buy: 0, sell: 0 }, { t: "+4m", buy: 0, sell: 0 },
    ],
    pnl: "-$47K",
  },
  {
    address: "0x3bc1…f02a", shortAddr: "3bc1…f02a",
    label: "Smart Money", tag: "smart",
    netUsd: +14000, buys: 4, sells: 0,
    supply: 1.8, historyEvents: ["pump"],
    clusterGroup: "D", onchainLabel: "Known MEV · 8 prev txns",
    copySignal: true, alertRepeat: false,
    flow: [
      { t: "-5m", buy: 0, sell: 0 }, { t: "-4m", buy: 0, sell: 0 },
      { t: "-3m", buy: 4000, sell: 0 }, { t: "-2m", buy: 6000, sell: 0 },
      { t: "-1m", buy: 4000, sell: 0 }, { t: "0", buy: 0, sell: 0 },
      { t: "+1m", buy: 0, sell: 0 }, { t: "+2m", buy: 0, sell: 0 },
      { t: "+3m", buy: 0, sell: 0 }, { t: "+4m", buy: 0, sell: 0 },
    ],
    pnl: "+$14K",
  },
];

const TAG_STYLE = {
  whale:    { bg: "rgba(0,229,160,0.10)",  border: "#00e5a0", text: "#00e5a0" },
  smart:    { bg: "rgba(124,106,255,0.12)", border: "#7c6aff", text: "#a89fff" },
  deployer: { bg: "rgba(245,166,35,0.12)", border: "#f5a623", text: "#f5c96a" },
  bot:      { bg: "rgba(56,189,248,0.10)", border: "#38bdf8", text: "#7dd3fc" },
  sell:     { bg: "rgba(255,77,109,0.12)", border: "#ff4d6d", text: "#ff8fa3" },
  degen:    { bg: "rgba(251,146,60,0.10)", border: "#fb923c", text: "#fdba74" },
};

// ─── Cluster Graph (SVG) ──────────────────────────────────────────────────────
const ClusterGraph = ({ wallets }) => {
  const groups = {};
  wallets.forEach(w => {
    if (!groups[w.clusterGroup]) groups[w.clusterGroup] = [];
    groups[w.clusterGroup].push(w);
  });
  const groupKeys = Object.keys(groups);
  const centerX = 130, centerY = 70;
  const nodes = [];
  const edges = [];

  groupKeys.forEach((g, gi) => {
    const gx = 40 + gi * 90;
    const gy = centerY;
    const members = groups[g];
    members.forEach((w, wi) => {
      const nx = gx + (wi - (members.length - 1) / 2) * 38;
      const ny = gy + (members.length > 1 ? (wi % 2 === 0 ? -18 : 18) : 0);
      nodes.push({ ...w, nx, ny, g });
      if (members.length > 1 && wi > 0) {
        edges.push({ x1: nodes[nodes.length - 2].nx, y1: nodes[nodes.length - 2].ny, x2: nx, y2: ny, g });
      }
    });
  });

  return (
    <svg width="100%" viewBox="0 0 260 140" style={{ overflow: "visible" }}>
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="2.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {edges.map((e, i) => (
        <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
          stroke={C.accent} strokeWidth="1.5" strokeDasharray="4 3" opacity="0.5" />
      ))}
      {nodes.map((n, i) => {
        const ts = TAG_STYLE[n.tag] || TAG_STYLE.degen;
        const isBuy = n.netUsd >= 0;
        return (
          <g key={i} filter="url(#glow)">
            <circle cx={n.nx} cy={n.ny} r="14"
              fill={ts.bg} stroke={ts.border} strokeWidth="1.5" />
            <circle cx={n.nx} cy={n.ny} r={5 + Math.min(8, Math.abs(n.netUsd) / 30000)}
              fill={isBuy ? C.buy : C.sell} opacity="0.7" />
            <text x={n.nx} y={n.ny + 26} textAnchor="middle"
              fontSize="8" fill={C.muted} fontFamily="monospace">{n.shortAddr}</text>
            {n.clusterGroup && (
              <text x={n.nx} y={n.ny - 20} textAnchor="middle"
                fontSize="7" fill={C.accent} fontFamily="monospace" opacity="0.7">GRP {n.clusterGroup}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
};

// ─── Mini Flow Chart ──────────────────────────────────────────────────────────
const FlowChart = ({ flow }) => (
  <ResponsiveContainer width="100%" height={52}>
    <BarChart data={flow} barGap={1} barCategoryGap="15%">
      <XAxis dataKey="t" tick={{ fontSize: 8, fill: C.muted }} tickLine={false} axisLine={false} />
      <Bar dataKey="buy" stackId="a" fill={C.buy} radius={[2, 2, 0, 0]} />
      <Bar dataKey="sell" stackId="b" fill={C.sell} radius={[2, 2, 0, 0]} />
    </BarChart>
  </ResponsiveContainer>
);

// ─── History Badge ────────────────────────────────────────────────────────────
const HistoryBadge = ({ events }) => {
  if (!events?.length) return <span style={{ fontSize: 10, color: C.muted }}>No prior moves</span>;
  return (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
      {events.map((e, i) => (
        <span key={i} style={{
          fontSize: 9, padding: "2px 6px", borderRadius: 20, fontFamily: "monospace",
          background: e === "pump" ? "rgba(0,229,160,0.12)" : "rgba(255,77,109,0.12)",
          border: `1px solid ${e === "pump" ? C.buy : C.sell}`,
          color: e === "pump" ? C.buy : C.sell,
        }}>
          {e === "pump" ? "▲ caused pump" : "▼ caused dip"}
        </span>
      ))}
    </div>
  );
};

// ─── Wallet Card ──────────────────────────────────────────────────────────────
const WalletCard = ({ w, rank, expanded, onToggle, delay }) => {
  const ts = TAG_STYLE[w.tag] || TAG_STYLE.degen;
  const isBuy = w.netUsd >= 0;

  return (
    <div style={{
      borderRadius: 10,
      background: expanded ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.02)",
      border: `1px solid ${expanded ? C.accent + "55" : C.border}`,
      overflow: "hidden",
      animation: `fadeUp 0.3s ease ${delay}ms both`,
      transition: "border-color 0.2s",
    }}>
      {/* Header row */}
      <div onClick={onToggle} style={{
        padding: "10px 12px", cursor: "pointer",
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <span style={{ fontSize: 10, color: C.dim, fontFamily: "monospace", width: 14, textAlign: "center" }}>{rank}</span>

        {/* Tag */}
        <span style={{
          fontSize: 9, padding: "2px 7px", borderRadius: 20, whiteSpace: "nowrap",
          background: ts.bg, border: `1px solid ${ts.border}`, color: ts.text,
          fontFamily: "monospace", fontWeight: 600,
        }}>{w.label}</span>

        <span style={{ fontSize: 10, color: C.muted, fontFamily: "monospace", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {w.address}
        </span>

        {/* Alerts */}
        <div style={{ display: "flex", gap: 4 }}>
          {w.alertRepeat && (
            <span title="Caused previous moves" style={{
              fontSize: 9, padding: "1px 5px", borderRadius: 20,
              background: "rgba(245,166,35,0.15)", border: "1px solid #f5a623", color: "#f5a623"
            }}>⚠ repeat</span>
          )}
          {w.copySignal && (
            <span title="Copy-trade signal" style={{
              fontSize: 9, padding: "1px 5px", borderRadius: 20,
              background: "rgba(0,229,160,0.12)", border: "1px solid #00e5a0", color: "#00e5a0"
            }}>⚡ copy</span>
          )}
        </div>

        <span style={{ color: isBuy ? C.buy : C.sell, fontSize: 12, fontWeight: 700, fontFamily: "monospace", whiteSpace: "nowrap" }}>
          {isBuy ? "+" : ""}{w.netUsd >= 0 ? "+" : ""}${Math.abs(w.netUsd / 1000).toFixed(0)}K
        </span>

        <span style={{ color: C.dim, fontSize: 10, marginLeft: 2 }}>{expanded ? "▲" : "▼"}</span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{ padding: "0 12px 12px", display: "flex", flexDirection: "column", gap: 10, borderTop: `1px solid ${C.border}`, paddingTop: 10 }}>

          {/* Row: supply + onchain label */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 9, color: C.muted, marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.08em" }}>Supply Held</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: C.label, fontFamily: "monospace" }}>{w.supply}%</div>
              <div style={{ height: 3, background: C.border, borderRadius: 2, marginTop: 4 }}>
                <div style={{ height: "100%", width: `${Math.min(100, w.supply * 5)}%`, background: ts.border, borderRadius: 2 }} />
              </div>
            </div>
            <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 9, color: C.muted, marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.08em" }}>On-chain Label</div>
              <div style={{ fontSize: 10, color: C.warn, fontFamily: "monospace", lineHeight: 1.5 }}>{w.onchainLabel}</div>
            </div>
          </div>

          {/* Flow timeline */}
          <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ fontSize: 9, color: C.muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Buy / Sell Flow · ±5min window
            </div>
            <FlowChart flow={w.flow} />
          </div>

          {/* History */}
          <div style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ fontSize: 9, color: C.muted, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Prior Move History
            </div>
            <HistoryBadge events={w.historyEvents} />
          </div>

          {/* Txn count */}
          <div style={{ display: "flex", gap: 6, fontSize: 10, fontFamily: "monospace" }}>
            <span style={{ color: C.buy }}>▲ {w.buys} buys</span>
            <span style={{ color: C.dim }}>·</span>
            <span style={{ color: C.sell }}>▼ {w.sells} sells</span>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Custom Chart Tooltip ─────────────────────────────────────────────────────
const ChartTip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const chg = ((d.close - d.open) / d.open * 100).toFixed(2);
  return (
    <div style={{
      background: "rgba(6,9,15,0.96)", border: `1px solid ${C.border}`,
      borderRadius: 8, padding: "8px 12px", fontSize: 11, fontFamily: "monospace", lineHeight: 1.8,
    }}>
      <div style={{ color: C.muted }}>{d.time}</div>
      <div style={{ color: parseFloat(chg) >= 0 ? C.buy : C.sell }}>
        {chg > 0 ? "+" : ""}{chg}% · ${d.close?.toFixed(5)}
      </div>
      <div style={{ color: C.dim }}>Vol {(d.volume / 1000).toFixed(0)}K</div>
    </div>
  );
};

// ─── Main ─────────────────────────────────────────────────────────────────────
export default function LuminaInvestigate() {
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [selectedCandle, setSelectedCandle] = useState(null);
  const [wallets, setWallets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expandedWallet, setExpandedWallet] = useState(null);
  const [activeTab, setActiveTab] = useState("wallets"); // wallets | cluster

  const handleClick = useCallback((data) => {
    if (!data?.activePayload?.[0]) return;
    const c = data.activePayload[0].payload;
    setSelectedCandle(c);
    setSelectedIdx(c.idx);
    setLoading(true);
    setWallets([]);
    setExpandedWallet(null);
    setActiveTab("wallets");

    setTimeout(() => {
      const isDip = c.idx >= 46 && c.idx <= 52;
      setWallets(isDip ? DIP_WALLETS : PUMP_WALLETS);
      setLoading(false);
    }, 750);
  }, []);

  const priceChg = selectedCandle
    ? ((selectedCandle.close - selectedCandle.open) / selectedCandle.open * 100).toFixed(2)
    : null;

  const isOpen = selectedIdx !== null;

  // group cluster summary
  const clusterGroups = {};
  wallets.forEach(w => {
    if (!clusterGroups[w.clusterGroup]) clusterGroups[w.clusterGroup] = 0;
    clusterGroups[w.clusterGroup]++;
  });

  return (
    <div style={{
      minHeight: "100vh", background: C.bg, color: C.label,
      fontFamily: "'Syne Mono', 'IBM Plex Mono', monospace",
      display: "flex", flexDirection: "column",
      position: "relative", overflow: "hidden",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne+Mono&family=Syne:wght@500;600;700;800&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes fadeUp { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.35} }
        @keyframes spin { to { transform: rotate(360deg); } }
        ::-webkit-scrollbar { width: 3px; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }
        .recharts-cartesian-grid-horizontal line,
        .recharts-cartesian-grid-vertical line { stroke: rgba(255,255,255,0.04) !important; }
      `}</style>

      {/* Grain overlay */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
        backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E\")",
        backgroundRepeat: "repeat", backgroundSize: "120px",
      }} />

      {/* Header */}
      <header style={{
        position: "relative", zIndex: 10,
        padding: "12px 20px", borderBottom: `1px solid ${C.border}`,
        display: "flex", alignItems: "center", gap: 16,
        background: "rgba(6,9,15,0.9)", backdropFilter: "blur(12px)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 28, height: 28, borderRadius: "50%",
            background: "linear-gradient(135deg, #7c6aff 0%, #00e5a0 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 12, fontWeight: 800, color: "#06090f", fontFamily: "'Syne', sans-serif",
          }}>L</div>
          <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 13, letterSpacing: "0.15em" }}>LUMINA</span>
        </div>

        <div style={{ width: 1, height: 24, background: C.border }} />

        <div>
          <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 600, fontSize: 14 }}>
            PEPE / USDT <span style={{ color: C.buy, fontSize: 11 }}>+12.4%</span>
          </div>
          <div style={{ fontSize: 9, color: C.muted, letterSpacing: "0.06em" }}>5M · BSC · 121 candles</div>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: C.buy, animation: "blink 2s infinite" }} />
          <span style={{ fontSize: 10, color: C.muted }}>LIVE</span>
        </div>
      </header>

      {/* Tip bar */}
      <div style={{
        position: "relative", zIndex: 10, fontSize: 10, color: "rgba(124,106,255,0.7)",
        padding: "6px 20px", borderBottom: `1px solid rgba(124,106,255,0.12)`,
        background: "rgba(124,106,255,0.05)",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <span>⬡</span>
        <span>Click any candle · surface top wallets · flow timeline · cluster coordination · history patterns</span>
        {selectedCandle && (
          <span style={{ marginLeft: "auto", color: "rgba(124,106,255,0.45)" }}>
            {selectedCandle.time} selected · {parseFloat(priceChg) >= 0 ? "▲" : "▼"} {priceChg}%
          </span>
        )}
      </div>

      {/* Body */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", position: "relative", zIndex: 5 }}>

        {/* ── Charts ── */}
        <div style={{
          flex: 1, display: "flex", flexDirection: "column", padding: "16px 20px", gap: 10,
          transition: "flex 0.35s cubic-bezier(0.4,0,0.2,1)",
        }}>

          {/* Price */}
          <div style={{
            flex: 3, background: C.surface, border: `1px solid ${C.border}`,
            borderRadius: 12, padding: "14px 16px",
          }}>
            <div style={{ fontSize: 9, color: C.muted, letterSpacing: "0.1em", marginBottom: 10 }}>PRICE · USD</div>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={CANDLES} onClick={handleClick} style={{ cursor: "crosshair" }}>
                <defs>
                  <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={C.accent} stopOpacity={0.18} />
                    <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="selGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={C.accent} stopOpacity={0.6} />
                    <stop offset="100%" stopColor={C.accent} stopOpacity={0.1} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="time" tick={{ fontSize: 8, fill: C.muted }} tickLine={false} axisLine={false} interval={19} />
                <YAxis tick={{ fontSize: 8, fill: C.muted }} tickLine={false} axisLine={false} width={52}
                  tickFormatter={v => `$${v.toFixed(3)}`} domain={["auto", "auto"]} />
                <Tooltip content={<ChartTip />} />
                {selectedIdx !== null && (
                  <ReferenceLine x={CANDLES[selectedIdx]?.time}
                    stroke={C.accent} strokeWidth={1} strokeDasharray="3 3" />
                )}
                <Area type="monotone" dataKey="close" stroke={C.accent} strokeWidth={1.5}
                  fill="url(#areaGrad)" dot={false} activeDot={{ r: 3, fill: C.accent }} />
                {selectedIdx !== null && (
                  <Bar dataKey="close" barSize={5}>
                    {CANDLES.map((_, i) => (
                      <Cell key={i} fill={i === selectedIdx ? "url(#selGrad)" : "transparent"} />
                    ))}
                  </Bar>
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* Volume */}
          <div style={{
            flex: 1, background: C.surface, border: `1px solid ${C.border}`,
            borderRadius: 12, padding: "10px 16px",
          }}>
            <div style={{ fontSize: 9, color: C.muted, letterSpacing: "0.1em", marginBottom: 6 }}>VOLUME</div>
            <ResponsiveContainer width="100%" height={60}>
              <BarChart data={CANDLES} onClick={handleClick} style={{ cursor: "crosshair" }} barGap={1} barCategoryGap="10%">
                <XAxis dataKey="time" hide />
                <YAxis hide />
                {selectedIdx !== null && (
                  <ReferenceLine x={CANDLES[selectedIdx]?.time} stroke={C.accent} strokeDasharray="3 3" strokeWidth={1} />
                )}
                <Bar dataKey="volume" radius={[2, 2, 0, 0]}>
                  {CANDLES.map((c, i) => (
                    <Cell key={i}
                      fill={i === selectedIdx ? C.accent
                        : c.bull ? "rgba(0,229,160,0.35)" : "rgba(255,77,109,0.35)"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* ── Side Panel ── */}
        <div style={{
          width: isOpen ? 360 : 0,
          overflow: "hidden",
          transition: "width 0.38s cubic-bezier(0.4,0,0.2,1)",
          borderLeft: isOpen ? `1px solid ${C.border}` : "none",
          background: C.surface,
          display: "flex", flexDirection: "column",
        }}>
          <div style={{ width: 360, height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>

            {/* Panel header */}
            <div style={{ padding: "14px 16px", borderBottom: `1px solid ${C.border}` }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 700, fontSize: 12, letterSpacing: "0.1em" }}>
                  WALLET INVESTIGATION
                </span>
                <button onClick={() => { setSelectedIdx(null); setSelectedCandle(null); setWallets([]); }}
                  style={{ background: "none", border: "none", color: C.muted, cursor: "pointer", fontSize: 16 }}>✕</button>
              </div>

              {selectedCandle && (
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  {[
                    ["Time", selectedCandle.time],
                    ["Δ", `${parseFloat(priceChg) >= 0 ? "+" : ""}${priceChg}%`, parseFloat(priceChg) >= 0 ? C.buy : C.sell],
                    ["Vol", `${(selectedCandle.volume / 1000).toFixed(0)}K`],
                    ["Close", `$${selectedCandle.close?.toFixed(5)}`],
                  ].map(([k, v, col]) => (
                    <div key={k} style={{ fontSize: 10, fontFamily: "monospace" }}>
                      <span style={{ color: C.muted }}>{k} </span>
                      <span style={{ color: col || C.label }}>{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Tabs */}
            <div style={{ display: "flex", borderBottom: `1px solid ${C.border}` }}>
              {["wallets", "cluster"].map(tab => (
                <button key={tab} onClick={() => setActiveTab(tab)} style={{
                  flex: 1, padding: "8px", background: "none", border: "none",
                  cursor: "pointer", fontSize: 10, letterSpacing: "0.08em",
                  fontFamily: "monospace",
                  color: activeTab === tab ? C.accent : C.muted,
                  borderBottom: `2px solid ${activeTab === tab ? C.accent : "transparent"}`,
                  transition: "color 0.15s, border-color 0.15s",
                }}>
                  {tab.toUpperCase()}
                  {tab === "cluster" && wallets.length > 0 && (
                    <span style={{ marginLeft: 4, color: C.warn }}>
                      {Object.keys(clusterGroups).length} GRP
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Content */}
            <div style={{ flex: 1, overflowY: "auto", padding: "14px 14px" }}>

              {loading && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingTop: 4 }}>
                  {[0, 1, 2].map(i => (
                    <div key={i} style={{
                      height: 52, borderRadius: 10,
                      background: `rgba(255,255,255,0.02)`,
                      border: `1px solid ${C.border}`,
                      animation: `blink 1.3s ease ${i * 180}ms infinite`,
                    }} />
                  ))}
                  <div style={{ textAlign: "center", fontSize: 10, color: C.dim, marginTop: 8 }}>
                    querying on-chain · assembling wallet graph…
                  </div>
                </div>
              )}

              {!loading && wallets.length > 0 && activeTab === "wallets" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {/* Coordination alert */}
                  {Object.values(clusterGroups).some(v => v > 1) && (
                    <div style={{
                      padding: "8px 12px", borderRadius: 8, marginBottom: 4,
                      background: "rgba(245,166,35,0.08)", border: `1px solid rgba(245,166,35,0.3)`,
                      fontSize: 10, color: C.warn, display: "flex", alignItems: "center", gap: 6
                    }}>
                      <span>⚠</span>
                      <span>Multiple wallets in same cluster — possible coordinated move</span>
                    </div>
                  )}
                  {wallets.map((w, i) => (
                    <WalletCard key={w.address} w={w} rank={i + 1} delay={i * 55}
                      expanded={expandedWallet === w.address}
                      onToggle={() => setExpandedWallet(expandedWallet === w.address ? null : w.address)}
                    />
                  ))}
                </div>
              )}

              {!loading && wallets.length > 0 && activeTab === "cluster" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{
                    background: "rgba(255,255,255,0.02)", border: `1px solid ${C.border}`,
                    borderRadius: 10, padding: "14px 10px",
                  }}>
                    <div style={{ fontSize: 9, color: C.muted, marginBottom: 10, letterSpacing: "0.08em" }}>WALLET COORDINATION GRAPH</div>
                    <ClusterGraph wallets={wallets} />
                  </div>

                  {Object.entries(clusterGroups).map(([g, count]) => (
                    <div key={g} style={{
                      background: "rgba(255,255,255,0.02)", border: `1px solid ${C.border}`,
                      borderRadius: 8, padding: "10px 12px",
                    }}>
                      <div style={{ fontSize: 10, color: C.accent, fontFamily: "monospace", marginBottom: 6 }}>
                        Group {g} · {count} wallet{count > 1 ? "s" : ""}
                        {count > 1 && <span style={{ color: C.warn, marginLeft: 8 }}>⚠ coordinating</span>}
                      </div>
                      {wallets.filter(w => w.clusterGroup === g).map(w => (
                        <div key={w.address} style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "monospace", marginBottom: 2 }}>
                          <span style={{ color: C.muted }}>{w.address}</span>
                          <span style={{ color: w.netUsd >= 0 ? C.buy : C.sell }}>
                            {w.netUsd >= 0 ? "+" : ""}${(w.netUsd / 1000).toFixed(0)}K
                          </span>
                        </div>
                      ))}
                    </div>
                  ))}

                  <div style={{
                    fontSize: 10, color: C.dim, fontFamily: "monospace", lineHeight: 1.6,
                    padding: "8px 10px", borderRadius: 8, background: "rgba(255,255,255,0.02)",
                    border: `1px solid ${C.border}`,
                  }}>
                    Wallets in the same group share: overlapping entry timing · common token source · similar wallet age
                  </div>
                </div>
              )}

              {!loading && wallets.length === 0 && !selectedCandle && (
                <div style={{ textAlign: "center", paddingTop: 40, fontSize: 11, color: C.dim, lineHeight: 2 }}>
                  Click a candle<br />to begin investigation
                </div>
              )}
            </div>

            {/* Footer */}
            {!loading && wallets.length > 0 && (
              <div style={{
                padding: "8px 14px", borderTop: `1px solid ${C.border}`,
                fontSize: 9, color: C.dim, fontFamily: "monospace",
              }}>
                Moralis · The Graph · Internal wallet DB · ±5 min window
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
