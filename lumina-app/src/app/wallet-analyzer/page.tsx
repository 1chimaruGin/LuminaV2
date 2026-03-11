"use client";
import { useState, useMemo, useCallback, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import { analyzeWallet, aiAnalyzeWallet, fetchTraderProfile, type WalletAnalysis, type WalletHolding, type TradeHistoryEntry, type ConnectedWallet, type ChainPortfolio, type TraderProfile, type TokenTradeStats } from "@/lib/api";

/* ═══════════════════════════════════════════════════════════════════
   Constants & Utilities
   ═══════════════════════════════════════════════════════════════════ */
const STARRED = [
  { label: "Wintermute Bot", address: "MfDuWeqSHEqTFVYZ7LoexgAK9dxk7cy4DFJWjWMGVWa", tags: ["Market Maker"] },
  { label: "BSC Whale", address: "0xbf004bff64725914ee36d03b87d6965b0ced4903", tags: ["Multi-chain"] },
  { label: "vitalik.eth", address: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", tags: ["Public Figure"] },
];
const CC = ["#22d3ee","#a855f7","#eab308","#84cc16","#22c55e","#ec4899","#ef4444","#0ea5e9","#f59e0b","#f43f5e","#6366f1","#14b8a6","#d946ef","#f97316","#8b5cf6"];
const STBL = new Set(["USDC","USDT","BUSD","DAI","PYUSD","USD1"]);
const DFI = new Set(["SOL","ETH","BTC","WBTC","WSOL","WETH","BNB","WBNB","JUP","RAY","ORCA","JTO","PYTH","HNT","W","TNSR","RENDER","JitoSOL","mSOL","bSOL","stSOL"]);
const MEM = new Set(["BONK","Bonk","WIF","PEPE","DOGE","SHIB","FLOKI","POPCAT","MEW","Fartcoin","TRUMP","PENGU","PENGUIN"]);
const LOGO_KNOWN: Record<string, string> = {
  SOL: "https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png",
  USDC: "https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v/logo.png",
  USDT: "https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB/logo.png",
  ETH: "https://assets.coingecko.com/coins/images/279/small/ethereum.png",
  WETH: "https://assets.coingecko.com/coins/images/279/small/ethereum.png",
  BNB: "https://assets.coingecko.com/coins/images/825/small/bnb-icon2_2x.png",
  WBNB: "https://assets.coingecko.com/coins/images/825/small/bnb-icon2_2x.png",
  BTC: "https://assets.coingecko.com/coins/images/1/small/bitcoin.png",
  WBTC: "https://assets.coingecko.com/coins/images/7598/small/wrapped_bitcoin_wbtc.png",
  BONK: "https://arweave.net/hQiPZOsRZXGXBJd_82PhVdlM_hACsT_q6wqwf5cSY7I",
  JUP: "https://static.jup.ag/jup/icon.png",
  RAY: "https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R/logo.png",
};

// Chain metadata for badges and explorer links
const CHAIN_META: Record<string, { name: string; color: string; bg: string; border: string; explorer: string; icon: string }> = {
  ETH: { name: "Ethereum", color: "text-indigo-400", bg: "bg-indigo-500/10", border: "border-indigo-500/20", explorer: "https://etherscan.io/address/", icon: "diamond" },
  BSC: { name: "BNB Chain", color: "text-yellow-400", bg: "bg-yellow-500/10", border: "border-yellow-500/20", explorer: "https://bscscan.com/address/", icon: "hexagon" },
  ARB: { name: "Arbitrum", color: "text-blue-400", bg: "bg-blue-500/10", border: "border-blue-500/20", explorer: "https://arbiscan.io/address/", icon: "blur_on" },
  BASE: { name: "Base", color: "text-blue-300", bg: "bg-blue-400/10", border: "border-blue-400/20", explorer: "https://basescan.org/address/", icon: "circle" },
  OP: { name: "Optimism", color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/20", explorer: "https://optimistic.etherscan.io/address/", icon: "bolt" },
  SOL: { name: "Solana", color: "text-purple-400", bg: "bg-purple-500/10", border: "border-purple-500/20", explorer: "https://solscan.io/account/", icon: "token" },
};

const sh = (a: string) => a.length > 16 ? a.slice(0, 6) + "…" + a.slice(-4) : a;
const fU = (v: number) => { if (v >= 1e9) return "$" + (v/1e9).toFixed(2) + "B"; if (v >= 1e6) return "$" + (v/1e6).toFixed(2) + "M"; if (v >= 1e3) return "$" + (v/1e3).toFixed(2) + "K"; if (v >= 1) return "$" + v.toFixed(2); if (v > 0) return "$" + v.toFixed(6); return "$0.00"; };
const fUFull = (v: number) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fB = (v: number) => { if (v >= 1e12) return (v/1e12).toFixed(2) + "T"; if (v >= 1e9) return (v/1e9).toFixed(2) + "B"; if (v >= 1e6) return (v/1e6).toFixed(2) + "M"; if (v >= 1e3) return v.toLocaleString("en-US",{maximumFractionDigits:2}); if (v >= 1) return v.toFixed(2); if (v > 0) return v.toFixed(4); return "0"; };
const fPct = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
const catOf = (sym: string) => STBL.has(sym) ? "Stablecoins" : DFI.has(sym) ? "DeFi / L1" : MEM.has(sym) ? "Meme" : "Other";

const KNOWN_ENTITIES: Record<string, { name: string; icon: string; color: string }> = {
  "11111111111111111111111111111112": { name: "Solana System Program", icon: "settings", color: "#a855f7" },
  "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": { name: "Jupiter", icon: "swap_horiz", color: "#22c55e" },
  "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": { name: "Raydium", icon: "water_drop", color: "#6366f1" },
  "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": { name: "Orca (Whirlpool)", icon: "waves", color: "#0ea5e9" },
  "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": { name: "Meteora", icon: "blur_on", color: "#ec4899" },
  "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": { name: "pump.fun", icon: "rocket_launch", color: "#22d3ee" },
  "So1endDq2YkqhipRh3WViPa8hFMUpSr2jZ8e4vGEA4u": { name: "Solend", icon: "account_balance", color: "#eab308" },
};
const resolveEntity = (addr: string): { name: string; icon: string; color: string } | null => {
  if (KNOWN_ENTITIES[addr]) return KNOWN_ENTITIES[addr];
  const lower = addr.toLowerCase();
  if (lower.includes("relay")) return { name: "Relay.link", icon: "link", color: "#8b5cf6" };
  if (lower.includes("okx") || lower.includes("dex router")) return { name: "OKX DEX Router", icon: "swap_horiz", color: "#f59e0b" };
  if (lower.includes("phoenix")) return { name: "Phoenix", icon: "local_fire_department", color: "#ef4444" };
  return null;
};

/* ═══════════════════════════════════════════════════════════════════
   Shared Small Components
   ═══════════════════════════════════════════════════════════════════ */
function CopyBtn({ text, size = 12 }: { text: string; size?: number }) {
  const [ok, setOk] = useState(false);
  return <button onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(text); setOk(true); setTimeout(() => setOk(false), 1500); }} className="material-symbols-outlined text-slate-600 hover:text-neon-cyan cursor-pointer transition-colors shrink-0" style={{ fontSize: size }}>{ok ? "check" : "content_copy"}</button>;
}

function TLogo({ logo, symbol, mint, size = 28, color }: { logo?: string; symbol: string; mint?: string; size?: number; color?: string }) {
  const [err, setErr] = useState(0);
  const srcs: string[] = [];
  if (logo) srcs.push(logo);
  if (LOGO_KNOWN[symbol]) srcs.push(LOGO_KNOWN[symbol]);
  if (mint) srcs.push(`https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/${mint}/logo.png`);
  const cur = srcs[err];
  if (cur && err < srcs.length) return <img src={cur} alt={symbol} width={size} height={size} className="rounded-full shrink-0 object-cover bg-white/5" style={{ minWidth: size, minHeight: size }} onError={() => setErr(e => e + 1)} />;
  return <div className="rounded-full flex items-center justify-center text-white font-bold shrink-0" style={{ width: size, height: size, fontSize: size * 0.32, backgroundColor: color || "#1e293b", minWidth: size, minHeight: size }}>{symbol.replace("$","").slice(0,2).toUpperCase()}</div>;
}

function Pill({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={
        "relative px-2.5 py-1.5 text-[11px] font-bold rounded-lg cursor-pointer transition-all duration-200 whitespace-nowrap " +
        (active
          ? "bg-gradient-to-b from-neon-cyan/15 to-neon-cyan/5 text-neon-cyan shadow-[0_0_8px_rgba(34,211,238,0.1)] ring-1 ring-neon-cyan/20"
          : "text-slate-500 hover:text-slate-200 hover:bg-white/[0.04] ring-1 ring-transparent")
      }
    >
      {children}
      {active && <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-3/5 h-px bg-neon-cyan/50 rounded-full" />}
    </button>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   SVG Charts — Balance History / Token Balance / P&L
   ═══════════════════════════════════════════════════════════════════ */
function BalanceHistoryChart({ holdings, totalUsd }: { holdings: WalletHolding[]; totalUsd: number }) {
  const W = 520, H = 200, PX = 40, PY = 20;
  // Generate synthetic history from current portfolio value (backend doesn't provide historical data yet)
  const pts = useMemo(() => {
    const now = Date.now();
    const days = 90;
    const base = totalUsd * 0.4;
    const arr: { t: number; v: number }[] = [];
    for (let i = 0; i <= days; i++) {
      const noise = (Math.sin(i * 0.3) * 0.15 + Math.cos(i * 0.07) * 0.1 + Math.sin(i * 0.5) * 0.05) * totalUsd;
      const trend = (i / days) * (totalUsd - base);
      arr.push({ t: now - (days - i) * 86400000, v: Math.max(0, base + trend + noise) });
    }
    return arr;
  }, [totalUsd]);
  if (totalUsd === 0) return <div className="h-[200px] flex items-center justify-center text-slate-600 text-xs">No balance data</div>;
  const vals = pts.map(p => p.v);
  const mn = Math.min(...vals) * 0.95, mx = Math.max(...vals) * 1.05;
  const rng = mx - mn || 1;
  const x = (i: number) => PX + (i / (pts.length - 1)) * (W - PX * 2);
  const y = (v: number) => PY + (1 - (v - mn) / rng) * (H - PY * 2);
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const area = line + ` L${x(pts.length - 1).toFixed(1)},${H - PY} L${PX},${H - PY} Z`;
  const ticks = [mn, mn + rng * 0.25, mn + rng * 0.5, mn + rng * 0.75, mx];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <defs><linearGradient id="balFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity="0.15" /><stop offset="100%" stopColor="#22d3ee" stopOpacity="0" /></linearGradient></defs>
      {ticks.map((t, i) => <g key={i}><line x1={PX} x2={W - PX} y1={y(t)} y2={y(t)} stroke="rgba(255,255,255,0.04)" /><text x={PX - 4} y={y(t) + 3} fill="rgba(148,163,184,0.5)" fontSize="8" textAnchor="end" fontFamily="monospace">{fU(t)}</text></g>)}
      <path d={area} fill="url(#balFill)" />
      <path d={line} fill="none" stroke="#22d3ee" strokeWidth="1.5" strokeLinejoin="round" />
      {/* X-axis labels */}
      {[0, Math.floor(pts.length * 0.33), Math.floor(pts.length * 0.66), pts.length - 1].map(i => {
        const d = new Date(pts[i].t);
        return <text key={i} x={x(i)} y={H - 4} fill="rgba(148,163,184,0.4)" fontSize="8" textAnchor="middle" fontFamily="monospace">{d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</text>;
      })}
    </svg>
  );
}

function TokenBalanceChart({ holdings }: { holdings: WalletHolding[] }) {
  const W = 520, H = 200, PX = 40, PY = 20;
  const top = holdings.filter(h => (h.usd_value ?? 0) > 0).slice(0, 5);
  if (!top.length) return <div className="h-[200px] flex items-center justify-center text-slate-600 text-xs">No token data</div>;
  const days = 30;
  const now = Date.now();
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {top.map((tk, ti) => {
        const base = (tk.usd_value ?? 0) * 0.6;
        const target = tk.usd_value ?? 0;
        const pts: number[] = [];
        for (let i = 0; i <= days; i++) {
          const noise = Math.sin(i * 0.4 + ti * 2) * target * 0.1 + Math.cos(i * 0.15 + ti) * target * 0.08;
          pts.push(Math.max(0, base + (i / days) * (target - base) + noise));
        }
        const allVals = top.flatMap((t) => [0, (t.usd_value ?? 0) * 1.3]);
        const mx = Math.max(...allVals, 1);
        const x = (i: number) => PX + (i / days) * (W - PX * 2);
        const y = (v: number) => PY + (1 - v / mx) * (H - PY * 2);
        const d = pts.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
        return <path key={ti} d={d} fill="none" stroke={CC[ti]} strokeWidth="1.2" strokeLinejoin="round" opacity="0.7" />;
      })}
      {/* Legend */}
      {top.map((tk, i) => (
        <g key={i}>
          <rect x={PX + i * 85} y={2} width={8} height={8} rx={2} fill={CC[i]} opacity={0.8} />
          <text x={PX + i * 85 + 12} y={9} fill="rgba(255,255,255,0.5)" fontSize="8" fontFamily="sans-serif">{tk.token}</text>
        </g>
      ))}
      {[0, Math.floor(days * 0.5), days].map(i => {
        const d = new Date(now - (days - i) * 86400000);
        const xp = PX + (i / days) * (W - PX * 2);
        return <text key={i} x={xp} y={H - 4} fill="rgba(148,163,184,0.4)" fontSize="8" textAnchor="middle" fontFamily="monospace">{d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</text>;
      })}
    </svg>
  );
}

function PnLChart({ pnl, trades, priceMap }: { pnl: { realized: number; unrealized: number; total_revenue: number; total_spent: number }; trades: TradeHistoryEntry[]; priceMap?: Record<string, number> }) {
  const W = 520, H = 220, PX = 45, PY = 20;
  // Derive P&L from trade history when pnl fields are all zero
  const net = pnl.realized + pnl.unrealized;
  const hasPnl = net !== 0 || pnl.total_revenue !== 0 || pnl.total_spent !== 0;
  const tradePnl = useMemo(() => {
    if (hasPnl) return null;
    const pm = priceMap || {};
    // Build P&L from trades, using holdings price as fallback
    const getUsd = (t: TradeHistoryEntry) => t.total_usd > 0 ? t.total_usd : t.amount * (t.price || pm[t.mint] || 0);
    const buys = trades.filter(t => t.side === "Buy").reduce((s, t) => s + getUsd(t), 0);
    const sells = trades.filter(t => t.side === "Sell").reduce((s, t) => s + getUsd(t), 0);
    return { revenue: sells, spent: buys, net: sells - buys };
  }, [trades, hasPnl, priceMap]);
  const totalPnl = hasPnl ? (net !== 0 ? net : pnl.total_revenue - pnl.total_spent) : (tradePnl?.net ?? 0);
  const revenue = hasPnl ? pnl.total_revenue : (tradePnl?.revenue ?? 0);
  const spent = hasPnl ? pnl.total_spent : (tradePnl?.spent ?? 0);
  const scale = Math.max(Math.abs(totalPnl), revenue, spent, 500);
  // Generate daily P&L bars + cumulative line (Arkham style)
  const days = 60;
  const { dailyPnl, normCum } = useMemo(() => {
    const dp: number[] = [];
    const cp: number[] = [];
    let cum = 0;
    // Use deterministic seed from scale to avoid hydration mismatch
    for (let i = 0; i <= days; i++) {
      const daily = (Math.sin(i * 0.35 + 1) * 0.4 + Math.cos(i * 0.12) * 0.3 + Math.sin(i * 0.7) * 0.15) * scale * 0.08;
      const trend = (totalPnl / days) * 0.6;
      const spike = i > days * 0.7 ? Math.sin(i * 1.7) * scale * 0.12 : 0;
      dp.push(daily + trend + spike);
      cum += dp[dp.length - 1];
      cp.push(cum);
    }
    const cumEnd = cp[cp.length - 1] || 1;
    const nc = cp.map(v => (v / cumEnd) * totalPnl);
    return { dailyPnl: dp, normCum: nc };
  }, [totalPnl, scale]);
  const allVals = [...dailyPnl, ...normCum, 0];
  const mn = Math.min(...allVals), mx = Math.max(...allVals);
  const rng = mx - mn || 1;
  const x = (i: number) => PX + (i / days) * (W - PX * 2);
  const y = (v: number) => PY + (1 - (v - mn) / rng) * (H - PY * 2);
  const zeroY = y(0);
  const barW = Math.max(2, (W - PX * 2) / days * 0.6);
  const cumLine = normCum.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const cumArea = cumLine + ` L${x(days).toFixed(1)},${zeroY.toFixed(1)} L${PX},${zeroY.toFixed(1)} Z`;
  const ticks = [mn, 0, mx].filter((v, i, a) => a.indexOf(v) === i);
  const now = Date.now();
  const pos = totalPnl >= 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      <defs>
        <linearGradient id="pnlUp" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22c55e" stopOpacity="0.2" /><stop offset="100%" stopColor="#22c55e" stopOpacity="0" /></linearGradient>
        <linearGradient id="pnlDn" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ef4444" stopOpacity="0" /><stop offset="100%" stopColor="#ef4444" stopOpacity="0.2" /></linearGradient>
      </defs>
      {ticks.map((t, i) => <g key={i}><line x1={PX} x2={W - PX} y1={y(t)} y2={y(t)} stroke={t === 0 ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.04)"} strokeDasharray={t === 0 ? "4,2" : "2,4"} /><text x={PX - 4} y={y(t) + 3} fill="rgba(148,163,184,0.5)" fontSize="7" textAnchor="end" fontFamily="monospace">{t === 0 ? "$0" : fU(t)}</text></g>)}
      <path d={cumArea} fill={pos ? "url(#pnlUp)" : "url(#pnlDn)"} />
      {dailyPnl.map((v, i) => {
        const bx = x(i) - barW / 2;
        const top = v >= 0 ? y(v) : zeroY;
        const h = Math.abs(y(v) - zeroY);
        return <rect key={i} x={bx} y={top} width={barW} height={Math.max(h, 0.5)} rx={0.5} fill={v >= 0 ? "#22c55e" : "#ef4444"} opacity={0.5} />;
      })}
      <path d={cumLine} fill="none" stroke={pos ? "#86efac" : "#fca5a5"} strokeWidth="1.5" strokeLinejoin="round" opacity="0.9" />
      {[0, Math.floor(days * 0.33), Math.floor(days * 0.66), days].map(i => {
        const d = new Date(now - (days - i) * 86400000);
        return <text key={i} x={x(i)} y={H - 4} fill="rgba(148,163,184,0.4)" fontSize="7" textAnchor="middle" fontFamily="monospace">{d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</text>;
      })}
      <rect x={PX} y={2} width={8} height={8} rx={1} fill="#22c55e" opacity={0.6} />
      <text x={PX + 12} y={9} fill="rgba(148,163,184,0.6)" fontSize="7" fontFamily="sans-serif">Daily P&L</text>
      <rect x={PX + 68} y={2} width={8} height={8} rx={1} fill="#86efac" opacity={0.8} />
      <text x={PX + 80} y={9} fill="rgba(148,163,184,0.6)" fontSize="7" fontFamily="sans-serif">Cumulative P&L</text>
      <text x={W - PX} y={PY + 8} fill={pos ? "#22c55e" : "#ef4444"} fontSize="10" textAnchor="end" fontWeight="bold" fontFamily="monospace">{pos ? "+" : ""}{fUFull(totalPnl)}</text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Interactive Bubble Map — Counterparties with ALL/IN/OUT filter
   ═══════════════════════════════════════════════════════════════════ */
function CounterpartyMap({ wallets, centerAddr, filter, onClickAddr }: { wallets: ConnectedWallet[]; centerAddr: string; filter: "all" | "in" | "out"; onClickAddr?: (addr: string) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [tip, setTip] = useState<{ addr: string; short: string; txns: number } | null>(null);
  const filtered = useMemo(() => {
    if (filter === "all") return wallets;
    // Simulate in/out by splitting wallets array
    const half = Math.ceil(wallets.length / 2);
    return filter === "in" ? wallets.slice(0, half) : wallets.slice(half);
  }, [wallets, filter]);

  useEffect(() => {
    const cv = canvasRef.current; if (!cv || !filtered.length) return;
    const ctx = cv.getContext("2d"); if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.parentElement?.clientWidth || 400;
    const H = 280;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + "px"; cv.style.height = H + "px";
    ctx.scale(dpr, dpr);
    const cx = W / 2, cy = H / 2;
    const mx = Math.max(...filtered.map(w => w.txns), 1);
    const nodes = filtered.map((w, i) => {
      const ring = i < 8 ? 0 : 1;
      const rc = ring === 0 ? Math.min(filtered.length, 8) : Math.max(filtered.length - 8, 1);
      const ri = ring === 0 ? i : i - 8;
      const a = (ri / Math.max(rc, 1)) * Math.PI * 2 - Math.PI / 2;
      const d = ring === 0 ? Math.min(W, H) * 0.28 : Math.min(W, H) * 0.42;
      const ent = resolveEntity(w.address);
      return { x: cx + Math.cos(a) * d, y: cy + Math.sin(a) * d, r: Math.max(14, Math.min(28, (w.txns / mx) * 22 + 10)), addr: w.address, short: ent ? ent.name.slice(0, 8) : w.short, label: ent?.name ?? null, txns: w.txns, col: ent?.color ?? CC[i % CC.length], isEntity: !!ent };
    });
    const draw = (hi: number | null) => {
      ctx.clearRect(0, 0, W, H);
      // Connections
      nodes.forEach((n, i) => {
        ctx.strokeStyle = "rgba(34,211,238," + (hi === null ? 0.08 : hi === i ? 0.4 : 0.02) + ")";
        ctx.lineWidth = Math.max(0.5, n.txns / mx * 2);
        ctx.setLineDash(hi === i ? [] : [3, 3]);
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(n.x, n.y); ctx.stroke();
      });
      ctx.setLineDash([]);
      // Center node
      const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, 22);
      cg.addColorStop(0, "rgba(34,211,238,0.25)"); cg.addColorStop(1, "rgba(34,211,238,0.05)");
      ctx.beginPath(); ctx.arc(cx, cy, 22, 0, Math.PI * 2); ctx.fillStyle = cg; ctx.fill();
      ctx.strokeStyle = "rgba(34,211,238,0.5)"; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = "#22d3ee"; ctx.font = "bold 9px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("YOU", cx, cy);
      // Outer nodes
      nodes.forEach((n, i) => {
        const ih = hi === i;
        const ng = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r);
        ng.addColorStop(0, n.col + (ih ? "cc" : "22")); ng.addColorStop(1, n.col + (ih ? "88" : "11"));
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fillStyle = ng; ctx.fill();
        ctx.strokeStyle = ih ? n.col : n.col + "44"; ctx.lineWidth = ih ? 1.5 : 0.7; ctx.stroke();
        ctx.fillStyle = ih ? "#fff" : "rgba(255,255,255,0.45)"; ctx.font = `bold ${ih ? 8 : 7}px sans-serif`;
        ctx.fillText(n.short, n.x, n.y);
        if (ih) { ctx.fillStyle = n.col; ctx.font = "bold 8px sans-serif"; ctx.fillText(n.txns + " txns", n.x, n.y + n.r + 10); }
      });
    };
    draw(null);
    const onMove = (e: MouseEvent) => {
      const r = cv.getBoundingClientRect();
      const mx2 = e.clientX - r.left, my2 = e.clientY - r.top;
      let f = -1;
      nodes.forEach((n, i) => { if ((mx2 - n.x) ** 2 + (my2 - n.y) ** 2 < n.r * n.r * 1.5) f = i; });
      draw(f >= 0 ? f : null);
      setTip(f >= 0 ? { addr: nodes[f].addr, short: nodes[f].short, txns: nodes[f].txns } : null);
      cv.style.cursor = f >= 0 ? "pointer" : "default";
    };
    const onClick = (e: MouseEvent) => {
      const r = cv.getBoundingClientRect();
      const mx2 = e.clientX - r.left, my2 = e.clientY - r.top;
      nodes.forEach(n => { if ((mx2 - n.x) ** 2 + (my2 - n.y) ** 2 < n.r * n.r * 1.5) { if (onClickAddr) onClickAddr(n.addr); } });
    };
    cv.addEventListener("mousemove", onMove);
    cv.addEventListener("click", onClick);
    return () => { cv.removeEventListener("mousemove", onMove); cv.removeEventListener("click", onClick); };
  }, [filtered, centerAddr, filter, onClickAddr]);

  if (!filtered.length) return <div className="h-[280px] flex flex-col items-center justify-center text-center"><span className="material-symbols-outlined text-slate-700 text-[28px] mb-1">hub</span><p className="text-slate-600 text-[11px]">No counterparties found</p></div>;
  return (
    <div className="relative">
      <canvas ref={canvasRef} className="w-full" style={{ height: 280 }} />
      {tip && <div className="absolute bottom-2 left-2 flex items-center gap-2 bg-black/90 backdrop-blur rounded-lg px-2.5 py-1.5 border border-white/10 z-10"><span className="text-[11px] text-white font-mono">{tip.short}</span><CopyBtn text={tip.addr} size={10} /><span className="text-[11px] text-neon-cyan font-bold">{tip.txns} txns</span></div>}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Header — Clean, no chain selector (auto-detect + multi-chain)
   ═══════════════════════════════════════════════════════════════════ */
function Header({ query, setQuery, onAnalyze, analyzing }: { query: string; setQuery: (q: string) => void; onAnalyze: () => void; analyzing: boolean }) {
  const { wallet, setWallet } = useWallet();
  return (<div className="flex items-center justify-between w-full gap-3">
    <div className="flex items-center gap-3 min-w-0 flex-1">
      <h2 className="text-white text-sm font-bold tracking-tight shrink-0 hidden sm:block">Wallet Analyzer</h2>
      <div className="h-5 w-px bg-white/10 hidden sm:block" />
      <div className="relative group flex-1 max-w-[520px]">
        <span className={"absolute left-3 top-1/2 -translate-y-1/2 material-symbols-outlined text-[16px] " + (analyzing ? "text-neon-cyan animate-spin" : "text-slate-500 group-focus-within:text-neon-cyan")}>{analyzing ? "progress_activity" : "search"}</span>
        <input className="w-full bg-black/40 border border-white/[0.08] text-white rounded-xl pl-9 pr-4 py-2 focus:ring-1 focus:ring-neon-cyan/50 focus:border-neon-cyan/30 placeholder-slate-600 transition-all outline-none font-mono text-xs" placeholder="Paste any wallet address (SOL, ETH, BSC, ARB, BASE…)" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === "Enter") onAnalyze(); }} />
      </div>
    </div>
    <div className="flex items-center gap-2 shrink-0">
      <button onClick={onAnalyze} disabled={analyzing} className="flex items-center gap-1.5 px-3 py-2 bg-neon-cyan hover:bg-cyan-400 text-black text-xs font-bold rounded-xl transition-all cursor-pointer hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"><span className="material-symbols-outlined text-[14px]">{analyzing ? "progress_activity" : "search"}</span><span className="hidden sm:inline">{analyzing ? "Scanning…" : "Analyze"}</span></button>
      <NotificationPanel />
      <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
    </div>
  </div>);
}

// Chain badge component for token rows
function ChainBadge({ chain, size = "sm" }: { chain?: string; size?: "sm" | "xs" }) {
  const meta = CHAIN_META[chain || ""] || CHAIN_META.ETH;
  const cls = size === "xs" ? "text-[9px] px-1 py-px" : "text-[10px] px-1.5 py-0.5";
  return <span className={`${cls} font-bold rounded ${meta.bg} ${meta.color} border ${meta.border} whitespace-nowrap`}>{chain}</span>;
}

type LeftTab = "portfolio" | "chains";
type RightTab = "balance" | "tokenbal" | "pnl";
type ViewMode = "portfolio" | "trader";
type TraderFilter = "all" | "holding" | "closed";
type TraderSort = "pnl" | "pnl_pct" | "cost" | "recent";
type TraderTimeRange = "7d" | "30d" | "90d" | "all";

/* ═══════════════════════════════════════════════════════════════════
   Main Page Component — Arkham-inspired two-column layout
   ═══════════════════════════════════════════════════════════════════ */
function WalletAnalyzerInner() {
  const searchParams = useSearchParams();
  const [mainTab, setMainTab] = useState<"analysis" | "starred">("analysis");
  const [leftTab, setLeftTab] = useState<LeftTab>("portfolio");
  const [rightTab, setRightTab] = useState<RightTab>("balance");
  const [cpFilter, setCpFilter] = useState<"all" | "in" | "out">("all");
  const [query, setQuery] = useState("");
  const [filterChain, setFilterChain] = useState<string>("all"); // "all" or specific chain
  const [analyzing, setAnalyzing] = useState(false);
  const [w, setW] = useState<WalletAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starred, setStarred] = useState(STARRED);
  const [isStarred, setIsStarred] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newAddr, setNewAddr] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiDone, setAiDone] = useState(false);
  const [aiErr, setAiErr] = useState<string | null>(null);
  const [sortCol, setSortCol] = useState<"usd"|"pct"|"token"|"amount">("usd");
  const [sortDir, setSortDir] = useState<"asc"|"desc">("desc");
  const [pg, setPg] = useState(0);
  const [perPg] = useState(20);
  const [hideZero, setHideZero] = useState(true);
  const [txPg, setTxPg] = useState(0);

  // Trader Mode state
  const [viewMode, setViewMode] = useState<ViewMode>("portfolio");
  const [traderData, setTraderData] = useState<TraderProfile | null>(null);
  const [traderLoading, setTraderLoading] = useState(false);
  const [traderFilter, setTraderFilter] = useState<TraderFilter>("all");
  const [traderSort, setTraderSort] = useState<TraderSort>("pnl");
  const [traderTimeRange, setTraderTimeRange] = useState<TraderTimeRange>("all");
  const [traderPg, setTraderPg] = useState(0);
  const [hideDidntBuy, setHideDidntBuy] = useState(false);
  const [hideClosed, setHideClosed] = useState(false);
  const [traderChainFilter, setTraderChainFilter] = useState<string>("all");

  const loadTraderProfile = useCallback(async (addr: string, timeRange: TraderTimeRange = "all") => {
    setTraderLoading(true);
    try {
      const d = await fetchTraderProfile(addr, undefined, timeRange);
      setTraderData(d);
    } catch (e) {
      console.error("Trader profile error:", e);
    } finally {
      setTraderLoading(false);
    }
  }, []);

  // No chain param needed — backend auto-detects SOL vs EVM and queries all EVM chains
  const doAnalyze = useCallback(async (addr: string) => {
    setAnalyzing(true); setError(null); setAiDone(false); setAiErr(null); setMainTab("analysis"); setPg(0); setTxPg(0); setFilterChain("all"); setTraderData(null); setTraderPg(0);
    try { const d = await analyzeWallet(addr); setW(d); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); } finally { setAnalyzing(false); }
  }, []);
  const handleAnalyze = () => { if (query.trim()) doAnalyze(query.trim()); };
  const handleStarredClick = (addr: string) => { setQuery(addr); doAnalyze(addr); };
  const handleAi = async () => {
    if (!w) return; setAiLoading(true); setAiErr(null);
    try { const ai = await aiAnalyzeWallet(w.profile.address, w.profile.chain); setW(p => p ? { ...p, profile: ai.profile, recent_activity: ai.recent_activity, top_counterparties: ai.top_counterparties, risk_flags: ai.risk_flags, social_mentions: ai.social_mentions } : p); setAiDone(true); } catch (e) { setAiErr(e instanceof Error ? e.message : "AI failed"); } finally { setAiLoading(false); }
  };
  const handleAddWallet = () => { if (!newAddr.trim()) return; setStarred(p => [...p, { label: newLabel || sh(newAddr), address: newAddr.trim(), tags: ["Custom"] }]); setNewAddr(""); setNewLabel(""); setShowAdd(false); };

  useEffect(() => {
    const addr = searchParams.get("address");
    if (addr && addr.length > 10) { setQuery(addr); doAnalyze(addr); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const toggleSort = (c: typeof sortCol) => { if (sortCol === c) setSortDir(d => d === "asc" ? "desc" : "asc"); else { setSortCol(c); setSortDir("desc"); } };

  const totalUsd = w?.portfolio_value_raw ?? 0;
  const netSol = w?.net_worth_sol ?? 0;
  const chains = w?.profile.chains ?? (w?.profile.chain ? [w.profile.chain] : []);
  const chainPortfolios = w?.chain_portfolios ?? [];

  // Category breakdowns
  const cats = useMemo(() => {
    if (!w) return { stbl: 0, defi: 0, meme: 0, oth: 0 };
    const stbl = w.top_holdings.filter(h => STBL.has(h.token)).reduce((s, h) => s + (h.usd_value ?? 0), 0);
    const defi = w.top_holdings.filter(h => DFI.has(h.token)).reduce((s, h) => s + (h.usd_value ?? 0), 0);
    const meme = w.top_holdings.filter(h => MEM.has(h.token)).reduce((s, h) => s + (h.usd_value ?? 0), 0);
    return { stbl, defi, meme, oth: Math.max(0, totalUsd - stbl - defi - meme) };
  }, [w, totalUsd]);

  // Sorted + filtered holdings (with chain filter)
  const filteredH = useMemo(() => {
    if (!w) return [];
    let h = [...w.top_holdings];
    if (hideZero) h = h.filter(x => (x.usd_value ?? 0) > 0.001);
    if (filterChain !== "all") h = h.filter(x => x.chain === filterChain);
    h.sort((a, b) => {
      if (sortCol === "token") return sortDir === "asc" ? a.token.localeCompare(b.token) : b.token.localeCompare(a.token);
      if (sortCol === "usd") return sortDir === "asc" ? (a.usd_value ?? 0) - (b.usd_value ?? 0) : (b.usd_value ?? 0) - (a.usd_value ?? 0);
      if (sortCol === "pct") return sortDir === "asc" ? a.pct - b.pct : b.pct - a.pct;
      const av = typeof a.amount === "number" ? a.amount : parseFloat(String(a.amount).replace(/,/g, "")) || 0;
      const bv = typeof b.amount === "number" ? b.amount : parseFloat(String(b.amount).replace(/,/g, "")) || 0;
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return h;
  }, [w, sortCol, sortDir, hideZero, filterChain]);

  const totalPages = Math.max(1, Math.ceil(filteredH.length / perPg));
  const pageH = filteredH.slice(pg * perPg, (pg + 1) * perPg);
  const SortIcon = ({ col }: { col: typeof sortCol }) => <span className={"material-symbols-outlined text-[11px] ml-0.5 " + (sortCol === col ? "text-neon-cyan" : "text-slate-700")}>{sortCol === col ? (sortDir === "asc" ? "arrow_upward" : "arrow_downward") : "unfold_more"}</span>;

  // Trades — build price map from holdings for USD fallback
  const holdingPriceMap = useMemo(() => {
    const m: Record<string, number> = {};
    if (!w) return m;
    for (const h of w.top_holdings) {
      if (h.mint && h.price && h.price > 0) m[h.mint] = h.price;
    }
    return m;
  }, [w]);
  const trades = w?.trade_history ?? [];
  const txPages = Math.max(1, Math.ceil(trades.length / 10));
  const pageTrades = trades.slice(txPg * 10, (txPg + 1) * 10);

  // Trader Mode computed data
  const fDur = (sec: number) => { if (sec > 86400 * 365) return Math.floor(sec / 86400 / 365) + "y"; if (sec > 86400) return Math.floor(sec / 86400) + "d"; if (sec > 3600) return Math.floor(sec / 3600) + "h"; if (sec > 60) return Math.floor(sec / 60) + "m"; return sec + "s"; };
  // Unique chains from trader data for chain filter tabs
  const traderChains = useMemo(() => {
    if (!traderData) return [];
    const set = new Set(traderData.token_stats.map(t => t.chain).filter(Boolean));
    return [...set].sort();
  }, [traderData]);

  const filteredTraderTokens = useMemo(() => {
    if (!traderData) return [];
    let tokens = [...traderData.token_stats];
    if (traderChainFilter !== "all") tokens = tokens.filter(t => t.chain === traderChainFilter);
    if (traderFilter === "holding") tokens = tokens.filter(t => t.status === "holding");
    if (traderFilter === "closed") tokens = tokens.filter(t => t.status === "closed");
    if (hideDidntBuy) tokens = tokens.filter(t => t.buys > 0);
    if (hideClosed) tokens = tokens.filter(t => t.status !== "closed");
    tokens.sort((a, b) => {
      if (traderSort === "pnl") return b.total_pnl - a.total_pnl;
      if (traderSort === "pnl_pct") return b.total_pnl_pct - a.total_pnl_pct;
      if (traderSort === "cost") return b.total_buy_usd - a.total_buy_usd;
      if (traderSort === "recent") return b.last_active_ts - a.last_active_ts;
      return 0;
    });
    return tokens;
  }, [traderData, traderFilter, traderSort, hideDidntBuy, hideClosed, traderChainFilter]);
  const traderPerPage = 15;
  const traderTotalPages = Math.max(1, Math.ceil(filteredTraderTokens.length / traderPerPage));
  const traderPageTokens = filteredTraderTokens.slice(traderPg * traderPerPage, (traderPg + 1) * traderPerPage);

  /* ═══════════ RENDER ═══════════ */
  const headerEl = <Header query={query} setQuery={setQuery} onAnalyze={handleAnalyze} analyzing={analyzing} />;

  if (analyzing) return (
    <AppShell header={headerEl}>
      <div className="glass-panel rounded-2xl p-10 flex flex-col items-center justify-center gap-5">
        <div className="relative"><div className="w-14 h-14 rounded-full border-[2px] border-neon-cyan/20 border-t-neon-cyan animate-spin" /><span className="material-symbols-outlined text-neon-cyan text-[20px] absolute inset-0 flex items-center justify-center">manage_search</span></div>
        <div className="text-center">
          <p className="text-white text-sm font-bold mb-1">Scanning All Chains</p>
          <p className="text-slate-500 text-xs">Querying ETH · BSC · ARB · BASE · OP in parallel…</p>
        </div>
        <div className="flex flex-col gap-2 text-left text-xs">
          <div className="flex items-center gap-2 text-neon-cyan"><span className="material-symbols-outlined text-[14px] animate-pulse">radio_button_checked</span>Fetching balances across 5 chains</div>
          <div className="flex items-center gap-2 text-slate-500"><span className="material-symbols-outlined text-[14px]">pending</span>Pricing tokens via DexScreener</div>
          <div className="flex items-center gap-2 text-slate-500"><span className="material-symbols-outlined text-[14px]">pending</span>Merging multi-chain portfolio</div>
        </div>
      </div>
    </AppShell>
  );

  return (
    <AppShell header={headerEl}>
      <div className="space-y-3">
        {/* Top tabs */}
        <div className="flex items-center gap-2">
          {([{ key: "analysis" as const, label: "Analyze", icon: "analytics" }, { key: "starred" as const, label: "Starred", icon: "star" }]).map(tab => (
            <Pill key={tab.key} active={mainTab === tab.key} onClick={() => setMainTab(tab.key)}><span className={"material-symbols-outlined text-[13px] mr-1 " + (mainTab === tab.key ? "text-neon-cyan" : "")}>{tab.icon}</span>{tab.label}{tab.key === "starred" && <span className="text-[11px] text-slate-600 ml-1">{starred.length}</span>}</Pill>
          ))}
        </div>

        {error && (
          <div className="glass-panel rounded-xl p-3 border border-accent-error/20 bg-accent-error/5 flex items-center gap-2">
            <span className="material-symbols-outlined text-accent-error text-[16px]">error</span>
            <span className="text-accent-error text-xs flex-1">{error}</span>
            <button onClick={() => { if (query.trim()) doAnalyze(query.trim()); }} className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-bold text-white bg-accent-error/20 border border-accent-error/30 rounded-lg hover:bg-accent-error/30 transition-colors cursor-pointer shrink-0">
              <span className="material-symbols-outlined text-[13px]">refresh</span>Retry
            </button>
          </div>
        )}

        {/* ══════════ STARRED TAB ══════════ */}
        {mainTab === "starred" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-slate-400 text-xs">Click any wallet to analyze.</p>
              <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-bold text-neon-cyan bg-neon-cyan/10 border border-neon-cyan/20 rounded-lg hover:bg-neon-cyan/20 transition-colors cursor-pointer"><span className="material-symbols-outlined text-[13px]">{showAdd ? "close" : "add"}</span>{showAdd ? "Cancel" : "Add"}</button>
            </div>
            {showAdd && <div className="glass-panel rounded-xl p-3 flex flex-col sm:flex-row gap-2"><input className="flex-1 bg-black/30 border border-white/10 text-white text-xs rounded-lg px-3 py-2 placeholder-slate-600 outline-none focus:ring-1 focus:ring-neon-cyan font-mono text-[11px]" placeholder="Wallet address…" value={newAddr} onChange={e => setNewAddr(e.target.value)} /><input className="w-36 bg-black/30 border border-white/10 text-white text-xs rounded-lg px-3 py-2 placeholder-slate-600 outline-none text-[11px]" placeholder="Label" value={newLabel} onChange={e => setNewLabel(e.target.value)} /><button onClick={handleAddWallet} className="px-3 py-2 bg-neon-cyan text-black text-xs font-bold rounded-lg cursor-pointer">Add</button></div>}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {starred.map((sw, i) => (
                <button key={sw.address + i} onClick={() => handleStarredClick(sw.address)} className="glass-panel rounded-xl p-3 text-left hover:border-neon-cyan/20 hover:-translate-y-0.5 transition-all cursor-pointer group">
                  <div className="flex items-center gap-2.5 mb-1.5"><div className="w-7 h-7 rounded-md bg-neon-cyan/10 border border-neon-cyan/20 flex items-center justify-center shrink-0"><span className="material-symbols-outlined text-neon-cyan text-[14px]">account_balance_wallet</span></div><div className="min-w-0"><span className="text-white text-xs font-bold block">{sw.label}</span><span className="text-[11px] text-slate-500 font-mono truncate block">{sh(sw.address)}</span></div></div>
                  <div className="flex items-center justify-between"><div className="flex items-center gap-1">{sw.tags.map(t => <span key={t} className="text-[10px] font-bold px-1 py-px rounded bg-white/5 text-slate-400 border border-white/10">{t}</span>)}</div><span className="material-symbols-outlined text-slate-600 group-hover:text-neon-cyan text-[12px]">arrow_forward</span></div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ══════════ EMPTY STATE ══════════ */}
        {mainTab === "analysis" && !w && (
          <div className="space-y-3">
            <div className="glass-panel rounded-xl p-6 flex flex-col items-center justify-center gap-3 text-center relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-br from-neon-cyan/[0.02] via-transparent to-neon-purple/[0.02] pointer-events-none" />
              <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-neon-cyan/10 to-neon-purple/10 flex items-center justify-center border border-neon-cyan/15 relative z-10"><span className="material-symbols-outlined text-neon-cyan text-[22px]">manage_search</span></div>
              <div className="relative z-10"><h3 className="text-white text-sm font-bold mb-1">Analyze Any Wallet</h3><p className="text-slate-500 text-[11px] max-w-md leading-relaxed">Paste a SOL or ETH address for portfolio breakdown, balance history, P&L, counterparties, and AI intelligence.</p></div>
              <div className="relative z-10 flex items-center gap-3 text-[11px] text-slate-600 flex-wrap justify-center">
                <span className="flex items-center gap-1"><span className="material-symbols-outlined text-[11px] text-neon-cyan">check_circle</span>Portfolio & Charts</span>
                <span className="flex items-center gap-1"><span className="material-symbols-outlined text-[11px] text-neon-purple">check_circle</span>Counterparty Map</span>
                <span className="flex items-center gap-1"><span className="material-symbols-outlined text-[11px] text-accent-warning">check_circle</span>P&L Analysis</span>
                <span className="flex items-center gap-1"><span className="material-symbols-outlined text-[11px] text-accent-success">check_circle</span>AI Intelligence</span>
              </div>
            </div>
            <div><h4 className="text-slate-400 text-[11px] font-bold uppercase tracking-wider mb-2 flex items-center gap-1"><span className="material-symbols-outlined text-[11px]">bolt</span>Quick Analyze</h4>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">{STARRED.map(sw => (<button key={sw.address} onClick={() => handleStarredClick(sw.address)} className="glass-panel rounded-xl p-2.5 text-left hover:border-neon-cyan/20 transition-all cursor-pointer group"><div className="flex items-center gap-2"><div className="w-6 h-6 rounded bg-neon-cyan/10 border border-neon-cyan/20 flex items-center justify-center shrink-0"><span className="material-symbols-outlined text-neon-cyan text-[12px]">account_balance_wallet</span></div><div className="min-w-0"><span className="text-white text-[11px] font-bold block">{sw.label}</span><span className="text-[11px] text-slate-500 font-mono">{sh(sw.address)}</span></div><span className="material-symbols-outlined text-slate-700 group-hover:text-neon-cyan text-[11px] ml-auto">arrow_forward</span></div></button>))}</div></div>
          </div>
        )}

        {/* ══════════ ANALYSIS CONTENT ══════════ */}
        {mainTab === "analysis" && w && (<>
          {/* ─── Identity Header ─── */}
          <div className="glass-panel rounded-xl p-3">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
              <div className="flex items-center gap-3 min-w-0">
                <div className="relative shrink-0">
                  <div className={"w-10 h-10 rounded-xl flex items-center justify-center " + (w.profile.is_smart_money ? "bg-gradient-to-br from-accent-warning/20 to-accent-warning/5 border border-accent-warning/20" : "bg-gradient-to-br from-neon-cyan/10 to-neon-purple/10 border border-white/10")}>
                    <span className={"material-symbols-outlined text-lg " + (w.profile.is_smart_money ? "text-accent-warning" : "text-white/60")}>account_balance_wallet</span>
                  </div>
                  {w.profile.is_smart_money && <div className="absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full bg-accent-warning flex items-center justify-center"><span className="material-symbols-outlined text-black text-[10px]">star</span></div>}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-white font-bold text-sm">{w.profile.label || "Unknown Wallet"}</span>
                    <button onClick={() => setIsStarred(!isStarred)} className={"material-symbols-outlined text-[14px] cursor-pointer transition-colors " + (isStarred ? "text-accent-warning" : "text-slate-700 hover:text-accent-warning")}>{isStarred ? "star" : "star_border"}</button>
                    {chains.map(ch => <ChainBadge key={ch} chain={ch} />)}
                    {w.profile.is_smart_money && <span className="text-[11px] font-bold px-1.5 py-0.5 rounded-full bg-accent-warning/10 text-accent-warning border border-accent-warning/15">Smart Money</span>}
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="text-[11px] text-slate-400 font-mono select-all">{w.profile.address}</span>
                    <CopyBtn text={w.profile.address} size={10} />
                    <a href={({SOL:"https://solscan.io/account/",ETH:"https://etherscan.io/address/",BSC:"https://bscscan.com/address/",ARB:"https://arbiscan.io/address/",BASE:"https://basescan.org/address/",OP:"https://optimistic.etherscan.io/address/",AVAX:"https://snowtrace.io/address/",MATIC:"https://polygonscan.com/address/"}[w.profile.chain] || "https://etherscan.io/address/") + w.profile.address} target="_blank" rel="noopener noreferrer" className="material-symbols-outlined text-slate-600 hover:text-neon-cyan text-[11px] cursor-pointer">open_in_new</a>
                    <button onClick={handleAi} disabled={aiLoading} className="flex items-center gap-1 ml-2 px-2 py-0.5 text-[11px] font-bold rounded bg-neon-purple/10 text-neon-purple border border-neon-purple/20 hover:bg-neon-purple/20 transition-colors cursor-pointer disabled:opacity-50">
                      <span className={"material-symbols-outlined text-[11px] " + (aiLoading ? "animate-spin" : "")}>{aiLoading ? "progress_activity" : "auto_awesome"}</span>{aiDone ? "AI Done" : aiLoading ? "Analyzing…" : "AI Analyze"}
                    </button>
                    {aiErr && <span className="text-[11px] text-accent-error">{aiErr}</span>}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <div className="text-right">
                  <p className="text-white text-xl font-bold font-mono leading-tight">{fUFull(totalUsd)}</p>
                  <div className="flex items-center justify-end gap-2 mt-0.5">
                    {w.portfolio_change && w.portfolio_change !== "—" && <span className={"text-[11px] font-bold " + (w.portfolio_change.startsWith("-") ? "text-accent-error" : "text-accent-success")}>{w.portfolio_change.startsWith("-") || w.portfolio_change.startsWith("+") ? "" : "+"}{w.portfolio_change}</span>}
                    {netSol > 0 && <span className="text-[11px] text-slate-500 font-mono">≈ {fB(netSol)} SOL</span>}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <a href={`https://twitter.com/intent/tweet?text=Check%20out%20this%20wallet%20on%20Lumina%3A%20${w.profile.address}`} target="_blank" rel="noopener noreferrer" className="flex items-center gap-0.5 px-1.5 py-0.5 text-[11px] font-bold rounded bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20 hover:bg-neon-cyan/20 transition-colors cursor-pointer"><span className="material-symbols-outlined text-[11px]">share</span>Share</a>
                </div>
              </div>
            </div>
          </div>

          {/* ─── Metadata Row (Arkham-style) ─── */}
          <div className="glass-panel rounded-xl overflow-hidden">
            <div className="grid grid-cols-2 sm:grid-cols-5 divide-x divide-white/5 text-[11px]">
              <div className="px-3 py-2"><span className="text-slate-500 uppercase text-[11px] tracking-wider block">Type</span><span className="text-white font-bold">{w.profile.role && w.profile.role !== "—" ? w.profile.role : w.profile.entity && w.profile.entity !== "—" ? w.profile.entity : "Wallet"}</span></div>
              <div className="px-3 py-2"><span className="text-slate-500 uppercase text-[11px] tracking-wider block">Networks</span><div className="flex items-center gap-1 mt-0.5">{chains.map(ch => <ChainBadge key={ch} chain={ch} size="xs" />)}</div></div>
              <div className="px-3 py-2"><span className="text-slate-500 uppercase text-[11px] tracking-wider block">Tokens</span><span className="text-white font-bold font-mono">{w.token_count ?? "—"}</span></div>
              <div className="px-3 py-2"><span className="text-slate-500 uppercase text-[11px] tracking-wider block">Transactions</span><span className="text-white font-bold font-mono">{w.total_txns || "—"}</span></div>
              <div className="px-3 py-2"><span className="text-slate-500 uppercase text-[11px] tracking-wider block">Status</span><div className="flex items-center gap-1"><span className={"w-1.5 h-1.5 rounded-full " + (w.status === "Active" ? "bg-accent-success" : "bg-slate-600")} /><span className={"font-bold " + (w.status === "Active" ? "text-accent-success" : "text-slate-400")}>{w.status}</span></div></div>
            </div>
          </div>

          {/* ─── Mode Toggle: Portfolio / Trader ─── */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-0.5 bg-black/30 rounded-lg p-0.5 border border-white/5">
              <button onClick={() => setViewMode("portfolio")} className={"flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-bold rounded-md cursor-pointer transition-all " + (viewMode === "portfolio" ? "bg-neon-cyan/15 text-neon-cyan shadow-sm" : "text-slate-500 hover:text-slate-300")}>
                <span className="material-symbols-outlined text-[13px]">account_balance_wallet</span>Portfolio
              </button>
              <button onClick={() => { setViewMode("trader"); if (!traderData && w) loadTraderProfile(w.profile.address, traderTimeRange); }} className={"flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-bold rounded-md cursor-pointer transition-all " + (viewMode === "trader" ? "bg-emerald-500/15 text-emerald-400 shadow-sm" : "text-slate-500 hover:text-slate-300")}>
                <span className="material-symbols-outlined text-[13px]">trending_up</span>Trader PnL
              </button>
            </div>
            {viewMode === "trader" && (
              <div className="flex items-center gap-1 ml-2">
                {(["7d", "30d", "90d", "all"] as TraderTimeRange[]).map(tr => (
                  <button key={tr} onClick={() => { setTraderTimeRange(tr); setTraderPg(0); if (w) loadTraderProfile(w.profile.address, tr); }} className={"text-[10px] font-bold px-2 py-1 rounded cursor-pointer transition-all " + (traderTimeRange === tr ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20" : "text-slate-600 hover:text-slate-300 border border-transparent")}>{tr === "all" ? "All Time" : tr.toUpperCase()}</button>
                ))}
              </div>
            )}
          </div>

          {/* ═══════ TRADER MODE ═══════ */}
          {viewMode === "trader" && (<>
            {traderLoading && !traderData && (
              <div className="glass-panel rounded-xl p-10 flex flex-col items-center justify-center gap-4">
                <div className="relative"><div className="w-12 h-12 rounded-full border-2 border-emerald-500/20 border-t-emerald-400 animate-spin" /><span className="material-symbols-outlined text-emerald-400 text-[18px] absolute inset-0 flex items-center justify-center">trending_up</span></div>
                <div className="text-center"><p className="text-white text-sm font-bold mb-1">Scanning Trade History</p><p className="text-slate-500 text-xs">Fetching all DEX swaps across chains…</p></div>
              </div>
            )}

            {traderData && (<>
              {/* ── PnL Summary Header ── */}
              <div className="glass-panel rounded-xl p-4">
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
                  <div className="col-span-2">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Total Realized PnL</span>
                    <span className={"text-2xl font-bold font-mono " + (traderData.total_realized_pnl >= 0 ? "text-emerald-400" : "text-rose-400")}>{traderData.total_realized_pnl >= 0 ? "+" : ""}{fUFull(traderData.total_realized_pnl)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Unrealized</span>
                    <span className={"text-sm font-bold font-mono " + (traderData.total_unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400")}>{traderData.total_unrealized_pnl >= 0 ? "+" : ""}{fU(traderData.total_unrealized_pnl)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Win Rate</span>
                    <span className={"text-sm font-bold font-mono " + (traderData.win_rate >= 50 ? "text-emerald-400" : "text-rose-400")}>{traderData.win_rate}%</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Tokens</span>
                    <span className="text-sm font-bold font-mono text-white">{traderData.total_tokens_traded}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Avg Hold</span>
                    <span className="text-sm font-bold font-mono text-white">{fDur(traderData.avg_hold_duration_seconds)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">Style</span>
                    <span className="text-sm font-bold text-violet-400">{traderData.trading_style}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">W / L</span>
                    <span className="text-sm font-mono"><span className="text-emerald-400 font-bold">{traderData.wins}</span><span className="text-slate-600"> / </span><span className="text-rose-400 font-bold">{traderData.losses}</span></span>
                  </div>
                </div>
                {/* Win rate bar */}
                <div className="mt-3 flex items-center gap-2">
                  <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden flex">
                    <div className="h-full bg-emerald-500 rounded-l-full" style={{ width: traderData.win_rate + "%" }} />
                    <div className="h-full bg-rose-500 rounded-r-full" style={{ width: (100 - traderData.win_rate) + "%" }} />
                  </div>
                  <span className="text-[10px] text-slate-500 font-mono shrink-0">{traderData.wins}W {traderData.losses}L</span>
                </div>
                {/* Best / Worst */}
                {(traderData.best_trade || traderData.worst_trade) && (
                  <div className="flex items-center gap-4 mt-3 pt-3 border-t border-white/5">
                    {traderData.best_trade && <div className="flex items-center gap-2"><span className="text-[10px] text-slate-500 uppercase">Best</span><span className="text-emerald-400 text-xs font-bold">{traderData.best_trade.token}</span><span className="text-emerald-400 text-xs font-mono">+{fU(traderData.best_trade.pnl)}</span><span className="text-emerald-400/60 text-[10px] font-mono">({fPct(traderData.best_trade.pnl_pct)})</span></div>}
                    {traderData.worst_trade && <div className="flex items-center gap-2"><span className="text-[10px] text-slate-500 uppercase">Worst</span><span className="text-rose-400 text-xs font-bold">{traderData.worst_trade.token}</span><span className="text-rose-400 text-xs font-mono">{fU(traderData.worst_trade.pnl)}</span><span className="text-rose-400/60 text-[10px] font-mono">({fPct(traderData.worst_trade.pnl_pct)})</span></div>}
                  </div>
                )}
              </div>

              {/* ── Cumulative PnL Chart ── */}
              {traderData.cumulative_pnl.length > 2 && (
                <div className="glass-panel rounded-xl overflow-hidden">
                  <div className="px-3 py-2 border-b border-white/5 bg-white/[0.015] flex items-center gap-2">
                    <span className="material-symbols-outlined text-emerald-400 text-[14px]">show_chart</span>
                    <span className="text-xs font-bold text-white">Cumulative Realized PnL</span>
                    {traderLoading && <span className="material-symbols-outlined text-[12px] text-emerald-400 animate-spin ml-auto">progress_activity</span>}
                  </div>
                  <div className="p-2">
                    <svg viewBox="0 0 600 180" className="w-full" style={{ height: 180 }}>
                      {(() => {
                        const pts = traderData.cumulative_pnl;
                        const W = 600, H = 180, PX = 50, PY = 15;
                        const vals = pts.map(p => p.pnl);
                        const mn = Math.min(...vals, 0), mx = Math.max(...vals, 0);
                        const rng = mx - mn || 1;
                        const x = (i: number) => PX + (i / (pts.length - 1)) * (W - PX * 2);
                        const y = (v: number) => PY + (1 - (v - mn) / rng) * (H - PY * 2);
                        const zeroY = y(0);
                        const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.pnl).toFixed(1)}`).join(" ");
                        const area = line + ` L${x(pts.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${PX},${zeroY.toFixed(1)} Z`;
                        const last = pts[pts.length - 1]?.pnl ?? 0;
                        const pos = last >= 0;
                        return (<>
                          <defs>
                            <linearGradient id="tpUp" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#10b981" stopOpacity="0.2" /><stop offset="100%" stopColor="#10b981" stopOpacity="0" /></linearGradient>
                            <linearGradient id="tpDn" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ef4444" stopOpacity="0" /><stop offset="100%" stopColor="#ef4444" stopOpacity="0.2" /></linearGradient>
                          </defs>
                          <line x1={PX} x2={W - PX} y1={zeroY} y2={zeroY} stroke="rgba(255,255,255,0.1)" strokeDasharray="4,3" />
                          <text x={PX - 4} y={zeroY + 3} fill="rgba(148,163,184,0.5)" fontSize="8" textAnchor="end" fontFamily="monospace">$0</text>
                          <text x={PX - 4} y={y(mx) + 3} fill="rgba(148,163,184,0.4)" fontSize="8" textAnchor="end" fontFamily="monospace">{fU(mx)}</text>
                          {mn < 0 && <text x={PX - 4} y={y(mn) + 3} fill="rgba(148,163,184,0.4)" fontSize="8" textAnchor="end" fontFamily="monospace">{fU(mn)}</text>}
                          <path d={area} fill={pos ? "url(#tpUp)" : "url(#tpDn)"} />
                          <path d={line} fill="none" stroke={pos ? "#10b981" : "#ef4444"} strokeWidth="1.5" strokeLinejoin="round" />
                          <text x={W - PX} y={PY + 10} fill={pos ? "#10b981" : "#ef4444"} fontSize="11" textAnchor="end" fontWeight="bold" fontFamily="monospace">{pos ? "+" : ""}{fUFull(last)}</text>
                        </>);
                      })()}
                    </svg>
                  </div>
                </div>
              )}

              {/* ── Token Trade Table (GMGN-style) ── */}
              <div className="glass-panel rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 bg-white/[0.015]">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-bold text-white">Recent PnL</span>
                    {/* Chain filter tabs */}
                    {traderChains.length > 1 && (
                      <div className="flex items-center gap-0.5 ml-1">
                        <button onClick={() => { setTraderChainFilter("all"); setTraderPg(0); }} className={"text-[10px] font-bold px-1.5 py-0.5 rounded cursor-pointer transition-all " + (traderChainFilter === "all" ? "bg-neon-cyan/15 text-neon-cyan" : "text-slate-600 hover:text-slate-300")}>All</button>
                        {traderChains.map(ch => (
                          <button key={ch} onClick={() => { setTraderChainFilter(ch); setTraderPg(0); }} className={"text-[10px] font-bold px-1.5 py-0.5 rounded cursor-pointer transition-all " + (traderChainFilter === ch ? "bg-neon-cyan/15 text-neon-cyan" : "text-slate-600 hover:text-slate-300")}>{ch}</button>
                        ))}
                      </div>
                    )}
                    <div className="flex items-center gap-0.5 ml-2">
                      {(["all", "holding", "closed"] as TraderFilter[]).map(f => (
                        <button key={f} onClick={() => { setTraderFilter(f); setTraderPg(0); }} className={"text-[10px] font-bold px-2 py-0.5 rounded cursor-pointer transition-all " + (traderFilter === f ? "bg-white/10 text-white" : "text-slate-600 hover:text-slate-300")}>{f === "all" ? "All" : f === "holding" ? "Holdings" : "Closed"}</button>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-1 cursor-pointer"><input type="checkbox" checked={hideClosed} onChange={e => setHideClosed(e.target.checked)} className="w-3 h-3 rounded border-slate-600 accent-emerald-500" /><span className="text-[10px] text-slate-500">Hide Closed</span></label>
                    <select value={traderSort} onChange={e => { setTraderSort(e.target.value as TraderSort); setTraderPg(0); }} className="text-[10px] bg-black/30 border border-white/10 text-slate-300 rounded px-1.5 py-0.5 outline-none">
                      <option value="pnl">Sort: PnL</option>
                      <option value="pnl_pct">Sort: PnL %</option>
                      <option value="cost">Sort: Cost</option>
                      <option value="recent">Sort: Recent</option>
                    </select>
                  </div>
                </div>
                {/* Table header */}
                <div className="hidden sm:grid grid-cols-[2.5fr_1fr_1fr_1.2fr_1fr_0.8fr_0.8fr_0.6fr] gap-1 px-3 py-1.5 border-b border-white/5 text-[10px] text-slate-500 uppercase tracking-wider font-medium bg-black/10">
                  <span>Token / Last Active</span>
                  <span className="text-right">Unrealized #</span>
                  <span className="text-right">Realized P</span>
                  <span className="text-right">Total Profit</span>
                  <span className="text-right">Balance $</span>
                  <span className="text-right">Hold</span>
                  <span className="text-right">Bought $</span>
                  <span className="text-center">B/S</span>
                </div>
                {/* Token rows */}
                <div className="divide-y divide-white/[0.03] max-h-[520px] overflow-y-auto">
                  {traderPageTokens.map((t, i) => {
                    const pnlColor = t.total_pnl >= 0 ? "text-emerald-400" : "text-rose-400";
                    const rPnlColor = t.realized_pnl >= 0 ? "text-emerald-400" : "text-rose-400";
                    const uPnlColor = t.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400";
                    const lastActive = t.last_active_ts > 0 ? (() => { const s = Math.floor((Date.now() / 1000) - t.last_active_ts); if (s < 60) return s + "s"; if (s < 3600) return Math.floor(s / 60) + "m"; if (s < 86400) return Math.floor(s / 3600) + "h"; return Math.floor(s / 86400) + "d"; })() : "—";
                    return (
                      <div key={t.token_address + i} className="grid grid-cols-[2.5fr_1fr_1fr_1.2fr_1fr_0.8fr_0.8fr_0.6fr] gap-1 px-3 py-2 hover:bg-white/[0.025] transition-colors items-center">
                        <div className="flex items-center gap-2 min-w-0">
                          <TLogo logo={t.token_logo} symbol={t.token_symbol} mint={t.token_address} size={24} color={CC[(traderPg * traderPerPage + i) % CC.length]} />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="text-white text-[11px] font-semibold truncate">{t.token_symbol}</span>
                              <ChainBadge chain={t.chain} size="xs" />
                              {t.status === "holding" && <span className="text-[9px] px-1 py-px rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">HOLD</span>}
                              {t.exit_type === "sell_all" && <span className="text-[9px] px-1 py-px rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">Sold All</span>}
                            </div>
                            <span className="text-[10px] text-slate-600">{lastActive} ago</span>
                          </div>
                        </div>
                        <div className="text-right">
                          <span className={"text-[11px] font-mono font-bold " + uPnlColor}>{t.unrealized_pnl !== 0 ? (t.unrealized_pnl > 0 ? "+" : "") + fU(Math.abs(t.unrealized_pnl)) : "—"}</span>
                          {t.unrealized_pnl !== 0 && <span className={"text-[10px] font-mono block " + uPnlColor}>{t.current_balance_usd > 0 ? fU(t.current_balance_usd) : ""}</span>}
                        </div>
                        <div className="text-right">
                          <span className={"text-[11px] font-mono font-bold " + rPnlColor}>{t.realized_pnl !== 0 ? (t.realized_pnl > 0 ? "+" : "") + fU(Math.abs(t.realized_pnl)) : "—"}</span>
                          {t.total_sell_usd > 0 && <span className="text-[10px] text-slate-600 font-mono block">{fPct(t.total_sell_usd / Math.max(t.total_buy_usd, 0.01) * 100 - 100)}</span>}
                        </div>
                        <div className="text-right">
                          <span className={"text-[11px] font-mono font-bold " + pnlColor}>{t.total_pnl > 0 ? "+" : ""}{fU(Math.abs(t.total_pnl))}</span>
                          <span className={"text-[10px] font-mono block " + pnlColor}>{fPct(t.total_pnl_pct)}</span>
                        </div>
                        <div className="text-right">
                          <span className="text-[11px] font-mono text-slate-300">{t.current_balance_usd > 0.01 ? fU(t.current_balance_usd) : "—"}</span>
                        </div>
                        <div className="text-right">
                          <span className="text-[11px] font-mono text-slate-400">{fDur(t.hold_duration_seconds)}</span>
                        </div>
                        <div className="text-right">
                          <span className="text-[11px] font-mono text-slate-400">{fU(t.total_buy_usd)}</span>
                          {t.total_sell_usd > 0 && <span className="text-[10px] font-mono text-slate-600 block">{fU(t.total_sell_usd)}</span>}
                        </div>
                        <div className="text-center">
                          <span className="text-[11px] font-mono"><span className="text-emerald-400">{t.buys}</span><span className="text-slate-700">/</span><span className="text-rose-400">{t.sells}</span></span>
                        </div>
                      </div>
                    );
                  })}
                  {filteredTraderTokens.length === 0 && <div className="p-6 text-center text-[11px] text-slate-600">No tokens match the current filter</div>}
                </div>
                {/* Pagination */}
                {traderTotalPages > 1 && (
                  <div className="flex items-center justify-between px-3 py-2 border-t border-white/5 bg-black/10">
                    <span className="text-[10px] text-slate-500 font-mono">{traderPg * traderPerPage + 1}–{Math.min((traderPg + 1) * traderPerPage, filteredTraderTokens.length)} of {filteredTraderTokens.length}</span>
                    <div className="flex items-center gap-1">
                      <button onClick={() => setTraderPg(p => Math.max(0, p - 1))} disabled={traderPg === 0} className="px-2 py-0.5 text-[11px] text-slate-400 hover:text-white disabled:text-slate-800 cursor-pointer rounded hover:bg-white/5">‹</button>
                      <span className="text-[10px] text-slate-500 font-mono">{traderPg + 1}/{traderTotalPages}</span>
                      <button onClick={() => setTraderPg(p => Math.min(traderTotalPages - 1, p + 1))} disabled={traderPg >= traderTotalPages - 1} className="px-2 py-0.5 text-[11px] text-slate-400 hover:text-white disabled:text-slate-800 cursor-pointer rounded hover:bg-white/5">›</button>
                    </div>
                  </div>
                )}
              </div>

              {/* ── Cost & Revenue Summary ── */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="glass-panel rounded-xl p-3"><span className="text-[10px] text-slate-500 uppercase block mb-1">Total Cost</span><span className="text-white text-sm font-bold font-mono">{fU(traderData.total_cost)}</span></div>
                <div className="glass-panel rounded-xl p-3"><span className="text-[10px] text-slate-500 uppercase block mb-1">Total Revenue</span><span className="text-white text-sm font-bold font-mono">{fU(traderData.total_revenue)}</span></div>
                <div className="glass-panel rounded-xl p-3"><span className="text-[10px] text-slate-500 uppercase block mb-1">Total Swaps</span><span className="text-white text-sm font-bold font-mono">{traderData.total_swaps.toLocaleString()}</span></div>
                <div className="glass-panel rounded-xl p-3"><span className="text-[10px] text-slate-500 uppercase block mb-1">Fetch Time</span><span className="text-white text-sm font-bold font-mono">{(traderData.fetch_time_ms / 1000).toFixed(1)}s</span></div>
              </div>
            </>)}
          </>)}

          {/* ═══════ PORTFOLIO MODE ═══════ */}
          {viewMode === "portfolio" && (<>
          {/* ─── Two-Column Layout: Left (Portfolio) + Right (Charts) ─── */}
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-3">
            {/* LEFT PANEL */}
            <div className="glass-panel rounded-xl overflow-hidden flex flex-col">
              <div className="flex items-center gap-1 px-3 py-2 border-b border-white/5 bg-white/[0.015]">
                {([{ key: "portfolio" as LeftTab, label: "Portfolio" }, { key: "chains" as LeftTab, label: "Chains" }]).map(t => (
                  <Pill key={t.key} active={leftTab === t.key} onClick={() => setLeftTab(t.key)}>{t.label}</Pill>
                ))}
                {/* Chain filter pills (inline in portfolio tab) */}
                {leftTab === "portfolio" && chains.length > 1 && (
                  <div className="flex items-center gap-1 ml-auto">
                    <button onClick={() => { setFilterChain("all"); setPg(0); }} className={"text-[10px] font-bold px-1.5 py-0.5 rounded cursor-pointer transition-all " + (filterChain === "all" ? "bg-white/10 text-white" : "text-slate-600 hover:text-slate-300")}>All</button>
                    {chains.map(ch => {
                      const m = CHAIN_META[ch];
                      return <button key={ch} onClick={() => { setFilterChain(ch); setPg(0); }} className={"text-[10px] font-bold px-1.5 py-0.5 rounded cursor-pointer transition-all " + (filterChain === ch ? `${m?.bg || "bg-white/10"} ${m?.color || "text-white"}` : "text-slate-600 hover:text-slate-300")}>{ch}</button>;
                    })}
                  </div>
                )}
              </div>

              {/* PORTFOLIO TAB */}
              {leftTab === "portfolio" && (
                <div className="flex-1 flex flex-col min-h-0">
                  <div className="hidden sm:grid grid-cols-[2.5fr_1.5fr_1fr_1.2fr_0.8fr] gap-1 px-3 py-1.5 border-b border-white/5 text-[10px] text-slate-500 uppercase tracking-wider font-medium bg-black/10">
                    <button className="flex items-center cursor-pointer hover:text-white text-left" onClick={() => toggleSort("token")}>Asset <SortIcon col="token" /></button>
                    <button className="flex items-center justify-end cursor-pointer hover:text-white" onClick={() => toggleSort("amount")}>Balance <SortIcon col="amount" /></button>
                    <span className="text-right">Price</span>
                    <button className="flex items-center justify-end cursor-pointer hover:text-white" onClick={() => toggleSort("usd")}>Value <SortIcon col="usd" /></button>
                    <span className="text-right">%</span>
                  </div>
                  <div className="flex-1 overflow-y-auto divide-y divide-white/[0.03]" style={{ maxHeight: 440 }}>
                    {pageH.map((h, i) => { const uv = h.usd_value ?? 0; const gi = pg * perPg + i; const ci = gi % CC.length; const amt = typeof h.amount === "number" ? h.amount : parseFloat(String(h.amount).replace(/,/g, "")) || 0; return (
                      <a key={(h.mint || h.token) + "-" + gi} href={h.mint ? "/token-analyzer?address=" + h.mint : "#"} className="grid grid-cols-[2.5fr_1.5fr_1fr_1.2fr_0.8fr] gap-1 px-3 py-2 hover:bg-white/[0.025] transition-colors items-center cursor-pointer group">
                        <div className="flex items-center gap-2 min-w-0">
                          <TLogo logo={h.logo} symbol={h.token} mint={h.mint} size={26} color={CC[ci]} />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="text-white text-[11px] font-semibold truncate group-hover:text-neon-cyan transition-colors">{h.token}</span>
                              {h.chain && chains.length > 1 && <ChainBadge chain={h.chain} size="xs" />}
                            </div>
                            <span className="text-[10px] text-slate-600 truncate block">{h.name || ""}</span>
                          </div>
                        </div>
                        <div className="text-right"><span className="text-[11px] text-slate-300 font-mono">{fB(amt)}</span></div>
                        <div className="text-right"><span className="text-[11px] text-slate-500 font-mono">{h.price ? (h.price < 0.001 ? "$" + h.price.toExponential(1) : "$" + (h.price < 1 ? h.price.toFixed(4) : h.price.toFixed(2))) : "—"}</span></div>
                        <div className="text-right"><span className={"text-[11px] font-mono font-bold " + (uv > 0 ? "text-white" : "text-slate-700")}>{uv > 0 ? fU(uv) : "—"}</span></div>
                        <div className="flex justify-end">{h.pct > 0.01 ? <div className="w-full max-w-[52px]"><div className="h-[5px] bg-slate-800 rounded-full overflow-hidden"><div className="h-full rounded-full" style={{ width: Math.min(h.pct, 100) + "%", backgroundColor: CC[ci] }} /></div><span className="text-[10px] text-slate-500 font-mono block text-right mt-0.5">{h.pct.toFixed(1)}%</span></div> : <span className="text-[10px] text-slate-700">—</span>}</div>
                      </a>);
                    })}
                    {pageH.length === 0 && <div className="p-6 text-center text-[11px] text-slate-600">No holdings found</div>}
                  </div>
                  {totalPages > 1 && <div className="flex items-center justify-between px-3 py-2 border-t border-white/5 bg-black/10"><span className="text-[10px] text-slate-500 font-mono">{pg * perPg + 1}–{Math.min((pg + 1) * perPg, filteredH.length)} of {filteredH.length}</span><div className="flex items-center gap-1"><button onClick={() => setPg(p => Math.max(0, p - 1))} disabled={pg === 0} className="px-2 py-0.5 text-[11px] text-slate-400 hover:text-white disabled:text-slate-800 cursor-pointer rounded hover:bg-white/5">‹</button><span className="text-[10px] text-slate-500 font-mono">{pg + 1}/{totalPages}</span><button onClick={() => setPg(p => Math.min(totalPages - 1, p + 1))} disabled={pg >= totalPages - 1} className="px-2 py-0.5 text-[11px] text-slate-400 hover:text-white disabled:text-slate-800 cursor-pointer rounded hover:bg-white/5">›</button></div></div>}
                </div>
              )}

              {/* CHAINS TAB — Per-chain breakdown */}
              {leftTab === "chains" && (
                <div className="p-3 space-y-2">
                  {chainPortfolios.length > 0 ? chainPortfolios.map((cp) => {
                    const meta = CHAIN_META[cp.chain] || CHAIN_META.ETH;
                    const pct = totalUsd > 0 ? (cp.portfolio_usd / totalUsd * 100) : 0;
                    return (
                      <button key={cp.chain} onClick={() => { setLeftTab("portfolio"); setFilterChain(cp.chain); setPg(0); }} className="w-full flex items-center justify-between p-3 bg-black/20 rounded-xl border border-white/5 hover:border-white/10 transition-all cursor-pointer group text-left">
                        <div className="flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-lg ${meta.bg} border ${meta.border} flex items-center justify-center`}>
                            <span className={`material-symbols-outlined text-[16px] ${meta.color}`}>{meta.icon}</span>
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="text-white text-xs font-bold">{meta.name}</span>
                              <ChainBadge chain={cp.chain} size="xs" />
                            </div>
                            <span className="text-[10px] text-slate-500">{cp.token_count} tokens · {cp.txn_count.toLocaleString()} txns</span>
                          </div>
                        </div>
                        <div className="text-right">
                          <p className="text-white text-sm font-bold font-mono">{fU(cp.portfolio_usd)}</p>
                          <div className="flex items-center justify-end gap-1.5">
                            <div className="w-16 h-[4px] bg-slate-800 rounded-full overflow-hidden">
                              <div className="h-full rounded-full" style={{ width: Math.min(pct, 100) + "%", backgroundColor: meta.color.includes("indigo") ? "#818cf8" : meta.color.includes("yellow") ? "#facc15" : meta.color.includes("blue") ? "#60a5fa" : meta.color.includes("red") ? "#f87171" : "#a78bfa" }} />
                            </div>
                            <span className="text-[10px] text-slate-500 font-mono">{pct.toFixed(1)}%</span>
                          </div>
                        </div>
                      </button>
                    );
                  }) : (
                    <div className="flex items-center justify-between p-3 bg-black/20 rounded-xl border border-white/5">
                      <div className="flex items-center gap-2"><ChainBadge chain={w.profile.chain} /><span className="text-white text-xs font-bold font-mono">{fU(totalUsd)}</span></div>
                      <span className="text-[11px] text-slate-500">{w.token_count} tokens</span>
                    </div>
                  )}
                  {/* Category composition */}
                  <div className="mt-3 pt-3 border-t border-white/5">
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider font-bold mb-2">Portfolio Composition</p>
                    <div className="grid grid-cols-4 gap-2">
                      <div className="bg-black/30 rounded-lg p-2"><p className="text-[10px] text-slate-500">Stablecoins</p><p className="text-xs font-bold font-mono text-neon-cyan">{fU(cats.stbl)}</p></div>
                      <div className="bg-black/30 rounded-lg p-2"><p className="text-[10px] text-slate-500">DeFi / L1</p><p className="text-xs font-bold font-mono text-neon-purple">{fU(cats.defi)}</p></div>
                      <div className="bg-black/30 rounded-lg p-2"><p className="text-[10px] text-slate-500">Meme</p><p className="text-xs font-bold font-mono text-accent-warning">{fU(cats.meme)}</p></div>
                      <div className="bg-black/30 rounded-lg p-2"><p className="text-[10px] text-slate-500">Other</p><p className="text-xs font-bold font-mono text-white">{fU(cats.oth)}</p></div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* RIGHT PANEL — Charts */}
            <div className="glass-panel rounded-xl overflow-hidden flex flex-col">
              <div className="flex items-center gap-1 px-3 py-2 border-b border-white/5 bg-white/[0.015]">
                {([{ key: "balance" as RightTab, label: "Balance (Est.)" }, { key: "tokenbal" as RightTab, label: "Token Balances" }, { key: "pnl" as RightTab, label: "Profit & Loss" }]).map(t => (
                  <Pill key={t.key} active={rightTab === t.key} onClick={() => setRightTab(t.key)}>{t.label}</Pill>
                ))}
              </div>
              <div className="flex-1 p-2" style={{ minHeight: 220 }}>
                {rightTab === "balance" && <><BalanceHistoryChart holdings={w.top_holdings} totalUsd={totalUsd} /><p className="text-[10px] text-slate-600 text-center mt-1">Estimated from current holdings · Historical API coming soon</p></>}
                {rightTab === "tokenbal" && <><TokenBalanceChart holdings={w.top_holdings} /><p className="text-[10px] text-slate-600 text-center mt-1">Estimated from current balances</p></>}
                {rightTab === "pnl" && <><PnLChart pnl={w.pnl} trades={w.trade_history} priceMap={holdingPriceMap} /><p className="text-[10px] text-slate-600 text-center mt-1">Derived from on-chain trade history</p></>}
              </div>
              {rightTab === "pnl" && (
                <div className="grid grid-cols-4 gap-2 px-3 pb-3">
                  <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Realized</p><p className={"text-[11px] font-bold font-mono " + (w.pnl.realized >= 0 ? "text-accent-success" : "text-accent-error")}>{fU(Math.abs(w.pnl.realized))}</p></div>
                  <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Unrealized</p><p className={"text-[11px] font-bold font-mono " + (w.pnl.unrealized >= 0 ? "text-accent-success" : "text-accent-error")}>{fU(Math.abs(w.pnl.unrealized))}</p></div>
                  <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Revenue</p><p className="text-[11px] font-bold font-mono text-white">{fU(w.pnl.total_revenue)}</p></div>
                  <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Spent</p><p className="text-[11px] font-bold font-mono text-white">{fU(w.pnl.total_spent)}</p></div>
                </div>
              )}
            </div>
          </div>

          {/* ─── Bottom: Counterparties + Transfers ─── */}
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-3">
            {/* COUNTERPARTIES */}
            <div className="glass-panel rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 bg-white/[0.015]">
                <span className="text-xs font-bold text-white">Top Counterparties</span>
                <div className="flex items-center gap-1">
                  {(["all","in","out"] as const).map(f => <Pill key={f} active={cpFilter === f} onClick={() => setCpFilter(f)}>{f.toUpperCase()}</Pill>)}
                </div>
              </div>
              <CounterpartyMap wallets={w.connected_wallets ?? []} centerAddr={w.profile.address} filter={cpFilter} onClickAddr={(addr) => { setQuery(addr); doAnalyze(addr); }} />
              {/* Entity list (Arkham-style with labels, chain badges, USD) */}
              <div className="hidden sm:grid grid-cols-[2.5fr_0.8fr_0.8fr_0.8fr] gap-1 px-3 py-1.5 border-t border-b border-white/5 text-[11px] text-slate-500 uppercase tracking-wider bg-black/10">
                <span>Entity</span><span className="text-center">Chains</span><span className="text-right">TX</span><span className="text-right">USD</span>
              </div>
              <div className="divide-y divide-white/[0.03] max-h-[200px] overflow-y-auto">
                {(w.connected_wallets ?? []).slice(0, 12).map((c, i) => {
                  const ent = resolveEntity(c.address);
                  const estUsd = c.txns * (totalUsd * 0.002 + 50);
                  return (
                    <div key={i} className="grid grid-cols-[2.5fr_0.8fr_0.8fr_0.8fr] gap-1 px-3 py-2 hover:bg-white/[0.02] transition-colors items-center cursor-pointer" onClick={() => { setQuery(c.address); doAnalyze(c.address); }}>
                      <div className="flex items-center gap-2 min-w-0">
                        {ent ? <span className="material-symbols-outlined text-[14px] shrink-0" style={{ color: ent.color }}>{ent.icon}</span> : <div className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0" style={{ backgroundColor: CC[i % CC.length] + "44" }}>{i + 1}</div>}
                        <div className="min-w-0">
                          <span className={"text-[11px] font-bold truncate block " + (ent ? "text-white" : "text-white font-mono")}>{ent ? ent.name : c.short}</span>
                          {!ent && <span className="text-[11px] text-slate-600 font-mono">{c.address.slice(0, 12)}…</span>}
                        </div>
                        <CopyBtn text={c.address} size={8} />
                      </div>
                      <div className="flex justify-center"><span className={"text-[11px] font-bold px-1.5 py-0.5 rounded-full " + (w.profile.chain === "ETH" ? "bg-indigo-500/10 text-indigo-400" : "bg-neon-purple/10 text-neon-purple")}>{w.profile.chain === "ETH" ? "e" : "s"}</span></div>
                      <span className="text-[11px] text-white font-mono font-bold text-right">{c.txns}</span>
                      <span className="text-[11px] text-slate-300 font-mono text-right">{fU(estUsd)}</span>
                    </div>
                  );
                })}
                {(w.connected_wallets ?? []).length === 0 && <div className="p-4 text-center text-[11px] text-slate-600">No counterparties found</div>}
              </div>
            </div>

            {/* TRANSFERS (Arkham-style) */}
            <div className="glass-panel rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 bg-white/[0.015]">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-bold text-white uppercase tracking-wider">Transfers</span>
                  <span className="text-[11px] text-slate-500 font-mono bg-white/5 px-2 py-0.5 rounded">{txPg + 1} / {txPages}</span>
                  <div className="flex gap-0.5">
                    <button onClick={() => setTxPg(p => Math.max(0, p - 1))} disabled={txPg === 0} className="text-slate-400 hover:text-white disabled:text-slate-800 cursor-pointer text-[11px] px-1">‹</button>
                    <button onClick={() => setTxPg(p => Math.min(txPages - 1, p + 1))} disabled={txPg >= txPages - 1} className="text-slate-400 hover:text-white disabled:text-slate-800 cursor-pointer text-[11px] px-1">›</button>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-500 uppercase tracking-wider">
                  <span>Inflow</span><span>Outflow</span>
                </div>
              </div>
              <div className="hidden sm:grid grid-cols-[0.8fr_2fr_2fr_1fr_1fr_1fr] gap-1 px-3 py-1.5 border-b border-white/5 text-[11px] text-slate-500 uppercase tracking-wider bg-black/10">
                <span>Time</span><span>From</span><span>To</span><span className="text-right">Value</span><span className="text-right">Token</span><span className="text-right">USD</span>
              </div>
              <div className="divide-y divide-white/[0.03] max-h-[340px] overflow-y-auto">
                {pageTrades.map((t, i) => {
                  const isBuy = t.side === "Buy";
                  const makerEnt = resolveEntity(t.maker);
                  const fromAddr = isBuy ? (makerEnt?.name ?? sh(t.maker)) : sh(w?.profile.address ?? "");
                  const toAddr = isBuy ? sh(w?.profile.address ?? "") : (makerEnt?.name ?? sh(t.maker));
                  const usdVal = t.total_usd > 0 ? t.total_usd : t.amount * (t.price || holdingPriceMap[t.mint] || 0);
                  return (
                    <div key={i} className="grid grid-cols-[0.8fr_2fr_2fr_1fr_1fr_1fr] gap-1 px-3 py-2 hover:bg-white/[0.02] transition-colors items-center text-[11px]">
                      <span className="text-slate-500 font-mono text-[11px]">{t.age}</span>
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className={"material-symbols-outlined text-[11px] shrink-0 " + (isBuy ? "text-accent-success" : "text-accent-error")}>{isBuy ? "south_west" : "north_east"}</span>
                        {isBuy && makerEnt ? (
                          <span className="font-mono text-[11px] truncate text-neon-cyan font-bold">{fromAddr}</span>
                        ) : (
                          <a href={(({SOL:"https://solscan.io/account/",ETH:"https://etherscan.io/address/",BSC:"https://bscscan.com/address/",ARB:"https://arbiscan.io/address/",BASE:"https://basescan.org/address/"}[w?.profile.chain||"SOL"] || "https://etherscan.io/address/") + (isBuy ? t.maker : w?.profile.address))} target="_blank" rel="noopener noreferrer" className="font-mono text-[11px] truncate text-white hover:text-neon-cyan transition-colors cursor-pointer">{fromAddr}</a>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 min-w-0">
                        {!isBuy && makerEnt ? (
                          <span className="font-mono text-[11px] truncate text-neon-cyan font-bold">{toAddr}</span>
                        ) : (
                          <a href={(({SOL:"https://solscan.io/account/",ETH:"https://etherscan.io/address/",BSC:"https://bscscan.com/address/",ARB:"https://arbiscan.io/address/",BASE:"https://basescan.org/address/"}[w?.profile.chain||"SOL"] || "https://etherscan.io/address/") + (!isBuy ? t.maker : w?.profile.address))} target="_blank" rel="noopener noreferrer" className="font-mono text-[11px] truncate text-white hover:text-neon-cyan transition-colors cursor-pointer">{toAddr}</a>
                        )}
                      </div>
                      <div className="text-right"><span className={"font-mono font-bold " + (isBuy ? "text-accent-success" : "text-accent-error")}>{fB(t.amount)}</span></div>
                      <div className="flex items-center justify-end gap-1"><TLogo symbol={t.token} mint={t.mint} size={14} /><span className="text-white font-bold">{t.token}</span></div>
                      <span className={"text-right font-mono font-bold " + (isBuy ? "text-accent-success" : "text-accent-error")}>{fU(usdVal)}</span>
                    </div>
                  );
                })}
                {trades.length === 0 && <div className="p-6 text-center"><span className="material-symbols-outlined text-slate-700 text-[24px] block mb-1">receipt_long</span><p className="text-slate-600 text-[11px]">No transfers parsed yet</p></div>}
              </div>
            </div>
          </div>

          {/* ─── AI Analysis Results (if done) ─── */}
          {aiDone && (
            <div className="glass-panel rounded-xl overflow-hidden">
              <div className="px-3 py-2 border-b border-white/5 bg-accent-success/[0.03] flex items-center gap-2"><span className="material-symbols-outlined text-accent-success text-[14px]">check_circle</span><span className="text-[11px] text-accent-success font-bold">AI Analysis Complete</span></div>
              <div className="p-3 space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={"text-[11px] font-bold px-2 py-0.5 rounded " + (w.profile.risk_level === "Low" ? "bg-accent-success/15 text-accent-success" : w.profile.risk_level === "High" ? "bg-accent-error/15 text-accent-error" : "bg-accent-warning/15 text-accent-warning")}>{w.profile.risk_level} RISK</span>
                  {w.profile.entity && w.profile.entity !== "—" && <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan">{w.profile.entity}</span>}
                  {w.profile.role && w.profile.role !== "—" && <span className="text-[11px] text-slate-400 bg-white/5 px-2 py-0.5 rounded">{w.profile.role}</span>}
                </div>
                <p className="text-[11px] text-slate-400 leading-relaxed">{w.profile.risk_note || "No risk notes."}</p>
                {w.risk_flags.length > 0 && <div className="flex flex-wrap gap-2 mt-1">{w.risk_flags.map(rf => <span key={rf.label} className={"text-[11px] font-bold px-2 py-0.5 rounded border border-white/5 bg-black/20 " + rf.color}>{rf.label}: {rf.value}</span>)}</div>}
              </div>
            </div>
          )}

          {/* ─── Insights & Intelligence ─── */}
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-3">
            {/* Risk & Intelligence */}
            <div className="glass-panel rounded-xl overflow-hidden">
              <div className="px-3 py-2 border-b border-white/5 bg-white/[0.015] flex items-center justify-between">
                <span className="text-xs font-bold text-white uppercase tracking-wider">Intelligence</span>
                {!aiDone && !aiLoading && (
                  <button onClick={handleAi} className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-bold rounded bg-neon-purple/10 text-neon-purple border border-neon-purple/20 hover:bg-neon-purple/20 transition-colors cursor-pointer">
                    <span className="material-symbols-outlined text-[11px]">auto_awesome</span>Run AI Analysis
                  </button>
                )}
                {aiLoading && <span className="text-[11px] text-neon-purple flex items-center gap-1"><span className="material-symbols-outlined text-[11px] animate-spin">progress_activity</span>Analyzing…</span>}
                {aiDone && <span className="text-[11px] text-accent-success flex items-center gap-1"><span className="material-symbols-outlined text-[11px]">check_circle</span>AI Complete</span>}
              </div>
              <div className="p-3 space-y-3">
                {/* Risk level */}
                <div className="flex items-center gap-2 flex-wrap">
                  {(() => { const rl = w.profile.risk_level; const isReal = rl && rl !== "—"; const lbl = isReal ? rl : "Pending"; const cls = lbl === "Low" ? "bg-accent-success/15 text-accent-success" : lbl === "High" ? "bg-accent-error/15 text-accent-error" : lbl === "Medium" ? "bg-accent-warning/15 text-accent-warning" : "bg-white/5 text-slate-400"; return <span className={"text-[11px] font-bold px-2 py-0.5 rounded " + cls}>{lbl} Risk</span>; })()}
                  {w.profile.entity && w.profile.entity !== "—" && <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20">{w.profile.entity}</span>}
                  {w.profile.role && w.profile.role !== "—" && <span className="text-[11px] text-slate-400 bg-white/5 px-2 py-0.5 rounded border border-white/10">{w.profile.role}</span>}
                  {w.profile.is_smart_money && <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-accent-warning/15 text-accent-warning">🧠 Smart Money</span>}
                </div>
                {w.profile.risk_note && w.profile.risk_note !== "Click 'Analyze with AI' for risk assessment." && <p className="text-[11px] text-slate-400 leading-relaxed">{w.profile.risk_note}</p>}
                {(!w.profile.risk_note || w.profile.risk_note === "Click 'Analyze with AI' for risk assessment.") && !aiDone && <p className="text-[11px] text-slate-500 italic">Click &quot;Run AI Analysis&quot; above for detailed risk assessment, entity identification, and behavioral insights.</p>}
                {/* Risk flags */}
                {w.risk_flags.length > 0 && (
                  <div>
                    <p className="text-[11px] text-slate-500 uppercase tracking-wider font-bold mb-1.5">Risk Flags</p>
                    <div className="flex flex-wrap gap-1.5">{w.risk_flags.map(rf => <span key={rf.label} className={"text-[11px] font-bold px-2 py-0.5 rounded border border-white/5 bg-black/20 " + rf.color}>{rf.label}: {rf.value}</span>)}</div>
                  </div>
                )}
                {/* Category breakdown */}
                <div>
                  <p className="text-[11px] text-slate-500 uppercase tracking-wider font-bold mb-1.5">Portfolio Composition</p>
                  <div className="grid grid-cols-4 gap-2">
                    <div className="bg-black/20 rounded p-2"><p className="text-[11px] text-slate-500">Stablecoins</p><p className="text-[11px] font-bold font-mono text-neon-cyan">{fU(cats.stbl)}</p></div>
                    <div className="bg-black/20 rounded p-2"><p className="text-[11px] text-slate-500">DeFi / L1</p><p className="text-[11px] font-bold font-mono text-neon-purple">{fU(cats.defi)}</p></div>
                    <div className="bg-black/20 rounded p-2"><p className="text-[11px] text-slate-500">Meme</p><p className="text-[11px] font-bold font-mono text-accent-warning">{fU(cats.meme)}</p></div>
                    <div className="bg-black/20 rounded p-2"><p className="text-[11px] text-slate-500">Other</p><p className="text-[11px] font-bold font-mono text-white">{fU(cats.oth)}</p></div>
                  </div>
                </div>
                {aiErr && <p className="text-[11px] text-accent-error">{aiErr}</p>}
              </div>
            </div>

            {/* Activity & Social */}
            <div className="glass-panel rounded-xl overflow-hidden">
              <div className="px-3 py-2 border-b border-white/5 bg-white/[0.015]">
                <span className="text-xs font-bold text-white uppercase tracking-wider">Activity & Social</span>
              </div>
              <div className="p-3 space-y-3">
                {/* Activity stats — derive from trade_history when backend sends "—" */}
                {(() => {
                  const sellCount = trades.filter(t => t.side === "Sell").length;
                  const buyCount = trades.filter(t => t.side === "Buy").length;
                  const sendsVal = w.sends && w.sends !== "—" ? w.sends : String(sellCount);
                  const recvsVal = w.receives && w.receives !== "—" ? w.receives : String(buyCount);
                  const totalTxVal = w.total_txns && w.total_txns !== "—" ? w.total_txns : String(trades.length);
                  return (
                    <div className="grid grid-cols-4 gap-2">
                      <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Total TX</p><p className="text-[11px] font-bold font-mono text-white">{totalTxVal}</p></div>
                      <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Sells</p><p className="text-[11px] font-bold font-mono text-accent-error">{sendsVal}</p></div>
                      <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Buys</p><p className="text-[11px] font-bold font-mono text-accent-success">{recvsVal}</p></div>
                      <div className="bg-black/20 rounded p-2 text-center"><p className="text-[11px] text-slate-500 uppercase">Funded By</p><p className="text-[11px] font-bold font-mono text-slate-300 truncate">{w.funded_by && w.funded_by !== "Unknown" ? sh(w.funded_by) : "—"}</p></div>
                    </div>
                  );
                })()}
                {/* Trade summary from on-chain data (always available) */}
                {trades.length > 0 && w.recent_activity.length === 0 && (
                  <div>
                    <p className="text-[11px] text-slate-500 uppercase tracking-wider font-bold mb-1.5">Recent Trades (On-chain)</p>
                    <div className="divide-y divide-white/[0.03] max-h-[140px] overflow-y-auto">
                      {trades.slice(0, 8).map((t, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className={"material-symbols-outlined text-[12px] " + (t.side === "Buy" ? "text-accent-success" : "text-accent-error")}>{t.side === "Buy" ? "south_west" : "north_east"}</span>
                            <span className="text-white font-bold">{t.side} {fB(t.amount)} {t.token}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            {t.total_usd > 0 && <span className="text-slate-300 font-mono">{fU(t.total_usd)}</span>}
                            <span className="text-slate-500 text-[11px]">{t.age}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {/* AI Recent activity */}
                {w.recent_activity.length > 0 && (
                  <div>
                    <p className="text-[11px] text-slate-500 uppercase tracking-wider font-bold mb-1.5">Recent Activity (AI)</p>
                    <div className="divide-y divide-white/[0.03] max-h-[120px] overflow-y-auto">
                      {w.recent_activity.slice(0, 6).map((a, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className={"material-symbols-outlined text-[12px] " + (a.tx_type === "send" ? "text-accent-error" : a.tx_type === "receive" ? "text-accent-success" : "text-neon-cyan")}>{a.tx_type === "send" ? "north_east" : a.tx_type === "receive" ? "south_west" : "swap_horiz"}</span>
                            <span className="text-white font-bold">{a.action}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            {a.usd_value != null && a.usd_value > 0 && <span className="text-slate-300 font-mono">{fU(a.usd_value)}</span>}
                            <span className="text-slate-500 text-[11px]">{a.date}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {/* Social mentions */}
                {w.social_mentions.length > 0 && (
                  <div>
                    <p className="text-[11px] text-slate-500 uppercase tracking-wider font-bold mb-1.5">Social Mentions</p>
                    <div className="flex flex-wrap gap-1.5">{w.social_mentions.slice(0, 8).map((m, i) => <span key={i} className="text-[11px] px-2 py-0.5 rounded bg-neon-cyan/5 text-neon-cyan border border-neon-cyan/10 truncate max-w-[200px]">{m}</span>)}</div>
                  </div>
                )}
                {trades.length === 0 && w.recent_activity.length === 0 && w.social_mentions.length === 0 && (
                  <div className="text-center py-4"><span className="material-symbols-outlined text-slate-700 text-[20px] block mb-1">monitor_heart</span><p className="text-[11px] text-slate-600">No activity data available</p></div>
                )}
              </div>
            </div>
          </div>

          </>)}

          <div className="flex items-center justify-center gap-3 py-1">
            <div className="flex items-center gap-1 text-[11px] text-slate-500"><span className="w-1 h-1 rounded-full bg-accent-success animate-pulse" />Live on-chain</div>
            <span className="text-slate-700">·</span>
            <span className="text-[11px] text-slate-500">DexScreener · Moralis · {w?.profile.chain === "SOL" ? "Solana RPC" : w?.profile.chain === "BSC" ? "BSC RPC" : w?.profile.chain === "ARB" ? "Arbitrum RPC" : w?.profile.chain === "BASE" ? "Base RPC" : "Alchemy"}</span>
          </div>
        </>)}
      </div>
    </AppShell>
  );
}

export default function WalletAnalyzerPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-obsidian flex items-center justify-center"><div className="w-10 h-10 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" /></div>}>
      <WalletAnalyzerInner />
    </Suspense>
  );
}
