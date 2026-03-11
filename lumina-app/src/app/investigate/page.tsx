"use client";

import { useState, useCallback, useEffect, useMemo, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import {
  analyzeToken,
  fetchInvestigateOHLCV,
  scanTokenActivity,
  type TokenAnalysis,
  type TokenPair,
  type InvestigateCandle,
  type InvestigateWallet,
  type CandleFlow,
} from "@/lib/api";

/* ── Helpers ── */
const fmt = (n: number, d = 2) => {
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(d)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(d)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(d)}K`;
  return `$${n.toFixed(d)}`;
};
const fmtPrice = (n: number) => {
  if (n === 0) return "$0";
  if (n < 0.0001) return `$${n.toExponential(3)}`;
  if (n < 1) return `$${n.toFixed(6)}`;
  if (n < 100) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
};
const fmtTime = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const fmtDate = (ts: number) => new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric" }) + " " + fmtTime(ts);
const TF_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400 };

const TAG_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  whale: { bg: "bg-neon-cyan/10", text: "text-neon-cyan", border: "border-neon-cyan/20" },
  smart: { bg: "bg-neon-lime/10", text: "text-neon-lime", border: "border-neon-lime/20" },
  sell: { bg: "bg-red-500/10", text: "text-red-400", border: "border-red-500/20" },
  bot: { bg: "bg-neon-purple/10", text: "text-neon-purple", border: "border-neon-purple/20" },
  degen: { bg: "bg-amber-500/10", text: "text-amber-400", border: "border-amber-500/20" },
};

/* ── Header ── */
function Header({ query, setQuery, chain, setChain, onSearch, loading }: {
  query: string; setQuery: (v: string) => void;
  chain: string; setChain: (v: string) => void;
  onSearch: () => void; loading: boolean;
}) {
  const { wallet, setWallet } = useWallet();
  const [showNotif, setShowNotif] = useState(false);
  return (
    <div className="flex items-center justify-between gap-3 w-full">
      <div className="flex items-center gap-2 flex-1 max-w-2xl">
        <div className="relative flex-1">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-[18px]">search</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && onSearch()}
            placeholder="Token address…"
            className="w-full pl-10 pr-3 py-2 bg-white/[0.04] border border-white/[0.06] rounded-lg text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-neon-cyan/30" />
        </div>
        <select value={chain} onChange={(e) => setChain(e.target.value)} className="bg-white/[0.04] border border-white/[0.06] rounded-lg text-white text-xs px-2 py-2 focus:outline-none">
          <option value="solana">Solana</option>
          <option value="ethereum">Ethereum</option>
          <option value="bsc">BSC</option>
          <option value="base">Base</option>
          <option value="arbitrum">Arbitrum</option>
        </select>
        <button onClick={onSearch} disabled={loading || !query.trim()}
          className="px-4 py-2 bg-neon-cyan/20 hover:bg-neon-cyan/30 border border-neon-cyan/20 rounded-lg text-neon-cyan text-sm font-medium transition-all disabled:opacity-30 cursor-pointer">
          {loading ? <span className="w-4 h-4 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin inline-block" /> : "Investigate"}
        </button>
      </div>
      <div className="flex items-center gap-2">
        <div className="relative">
          <button onClick={() => setShowNotif(!showNotif)} className="h-9 w-9 rounded-lg bg-white/[0.04] border border-white/[0.06] flex items-center justify-center text-slate-400 hover:text-white transition-colors cursor-pointer">
            <span className="material-symbols-outlined text-[18px]">notifications</span>
          </button>
          {showNotif && <NotificationPanel />}
        </div>
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

/* ── SVG Chart with auto-overlaid wallet flow ── */
const CW = 960, CH = 400, PX = 55, PY = 20, VOL_H = 50, FLOW_H = 40;

function InvestigateChart({ candles, flowMap, hoverIdx, setHoverIdx }: {
  candles: InvestigateCandle[];
  flowMap: Record<string, CandleFlow>;
  hoverIdx: number | null;
  setHoverIdx: (i: number | null) => void;
}) {
  const n = candles.length;
  if (n === 0) return null;

  const prices = candles.flatMap((c) => [c.high, c.low]);
  const minP = Math.min(...prices), maxP = Math.max(...prices), pRange = maxP - minP || 1;
  const maxVol = Math.max(...candles.map((c) => c.volume)) || 1;
  const cW = (CW - PX * 2) / n;
  const bodyW = Math.max(cW * 0.6, 2);
  const priceH = CH - PY * 2 - VOL_H - FLOW_H;
  const yP = (p: number) => PY + priceH - ((p - minP) / pRange) * priceH;
  const volTop = PY + priceH + 4;
  const yV = (v: number) => volTop + VOL_H - (v / maxVol) * VOL_H;
  const flowTop = volTop + VOL_H + 4;
  const cx = (i: number) => PX + i * cW + cW / 2;

  const maxFlowUsd = useMemo(() => {
    let m = 1;
    for (const f of Object.values(flowMap)) m = Math.max(m, f.buy_usd, f.sell_usd);
    return m;
  }, [flowMap]);

  const gridYs = Array.from({ length: 5 }, (_, i) => ({ y: PY + (i / 4) * priceH, price: maxP - (i / 4) * pRange }));

  return (
    <svg viewBox={`0 0 ${CW} ${CH}`} className="w-full select-none">
      <defs>
        <linearGradient id="buyG" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#00ff88" stopOpacity="0.6" /><stop offset="100%" stopColor="#00ff88" stopOpacity="0.1" /></linearGradient>
        <linearGradient id="sellG" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ff5050" stopOpacity="0.6" /><stop offset="100%" stopColor="#ff5050" stopOpacity="0.1" /></linearGradient>
        <filter id="ws"><feDropShadow dx="0" dy="0" stdDeviation="2" floodColor="#00f0ff" floodOpacity="0.6" /></filter>
      </defs>

      {gridYs.map((g, i) => (
        <g key={i}>
          <line x1={PX} y1={g.y} x2={CW - PX} y2={g.y} stroke="rgba(255,255,255,0.04)" />
          <text x={PX - 5} y={g.y + 3} textAnchor="end" fill="rgba(255,255,255,0.3)" fontSize="9" fontFamily="monospace">{fmtPrice(g.price)}</text>
        </g>
      ))}
      <text x={PX - 5} y={volTop + 8} textAnchor="end" fill="rgba(255,255,255,0.15)" fontSize="7">VOL</text>
      <text x={PX - 5} y={flowTop + 8} textAnchor="end" fill="rgba(255,255,255,0.15)" fontSize="7">FLOW</text>
      <line x1={PX} y1={volTop - 2} x2={CW - PX} y2={volTop - 2} stroke="rgba(255,255,255,0.04)" />
      <line x1={PX} y1={flowTop - 2} x2={CW - PX} y2={flowTop - 2} stroke="rgba(255,255,255,0.04)" />

      {candles.filter((_, i) => i % Math.max(1, Math.ceil(n / 8)) === 0).map((c) => {
        const idx = candles.indexOf(c);
        return <text key={idx} x={cx(idx)} y={CH - 2} textAnchor="middle" fill="rgba(255,255,255,0.2)" fontSize="8" fontFamily="monospace">{fmtTime(c.ts)}</text>;
      })}

      {candles.map((c, i) => {
        const isUp = c.close >= c.open;
        const top = isUp ? yP(c.close) : yP(c.open);
        const bot = isUp ? yP(c.open) : yP(c.close);
        const h = Math.max(bot - top, 1);
        const color = isUp ? "#00ff88" : "#ff5050";
        const isH = hoverIdx === i;
        const flow = flowMap[String(c.ts)];
        const hasFlow = flow && (flow.buy_count + flow.sell_count) > 0;
        const hasWhale = flow && (flow.whale_buy + flow.whale_sell) > 0;
        const buyBarH = flow ? (flow.buy_usd / maxFlowUsd) * (FLOW_H / 2 - 2) : 0;
        const sellBarH = flow ? (flow.sell_usd / maxFlowUsd) * (FLOW_H / 2 - 2) : 0;
        const flowMid = flowTop + FLOW_H / 2;

        return (
          <g key={i} onMouseEnter={() => setHoverIdx(i)} onMouseLeave={() => setHoverIdx(null)}>
            <rect x={cx(i) - cW / 2} y={PY} width={cW} height={CH - PY - 12} fill="transparent" />
            {isH && <rect x={cx(i) - cW / 2} y={PY} width={cW} height={CH - PY - 12} fill="rgba(0,240,255,0.03)" stroke="rgba(0,240,255,0.1)" strokeWidth="0.5" rx="2" />}
            <rect x={cx(i) - bodyW / 2} y={yV(c.volume)} width={bodyW} height={volTop + VOL_H - yV(c.volume)} fill={isUp ? "rgba(0,255,136,0.12)" : "rgba(255,80,80,0.12)"} rx="1" />
            <line x1={cx(i)} y1={yP(c.high)} x2={cx(i)} y2={yP(c.low)} stroke={color} strokeWidth={1} opacity={isH ? 1 : 0.5} />
            <rect x={cx(i) - bodyW / 2} y={top} width={bodyW} height={h} fill={color} opacity={isH ? 1 : 0.7} rx="1" />
            {hasFlow && (
              <>
                {buyBarH > 0 && <rect x={cx(i) - bodyW / 2} y={flowMid - buyBarH} width={bodyW} height={buyBarH} fill="url(#buyG)" rx="1" />}
                {sellBarH > 0 && <rect x={cx(i) - bodyW / 2} y={flowMid} width={bodyW} height={sellBarH} fill="url(#sellG)" rx="1" />}
                <line x1={cx(i) - bodyW / 2} y1={flowMid} x2={cx(i) + bodyW / 2} y2={flowMid} stroke="rgba(255,255,255,0.08)" strokeWidth="0.5" />
              </>
            )}
            {hasWhale && (
              <g transform={`translate(${cx(i)}, ${yP(c.high) - 8})`} filter="url(#ws)">
                <polygon points="0,-4 3,0 0,4 -3,0" fill="#00f0ff" opacity="0.9" />
              </g>
            )}
            {flow && Math.abs(flow.net_usd) > 100 && (
              <text x={cx(i)} y={flow.net_usd > 0 ? yP(c.high) - 14 : yP(c.low) + 18} textAnchor="middle" fill={flow.net_usd > 0 ? "#00ff88" : "#ff5050"} fontSize="8" opacity="0.7">
                {flow.net_usd > 0 ? "▲" : "▼"}
              </text>
            )}
          </g>
        );
      })}

      {hoverIdx !== null && candles[hoverIdx] && (() => {
        const c = candles[hoverIdx];
        const flow = flowMap[String(c.ts)];
        const isUp = c.close >= c.open;
        const tx = Math.min(Math.max(cx(hoverIdx), PX + 90), CW - PX - 90);
        const ty = PY + 8;
        const hh = flow && (flow.buy_count + flow.sell_count) > 0 ? 72 : 42;
        return (
          <g>
            <rect x={tx - 85} y={ty} width={170} height={hh} rx="6" fill="rgba(10,10,18,0.92)" stroke="rgba(0,240,255,0.15)" strokeWidth="1" />
            <text x={tx} y={ty + 12} textAnchor="middle" fill="white" fontSize="8" fontFamily="monospace" fontWeight="bold">{fmtDate(c.ts)}</text>
            <text x={tx - 75} y={ty + 24} fill="rgba(255,255,255,0.5)" fontSize="7" fontFamily="monospace">O:{fmtPrice(c.open)}</text>
            <text x={tx - 20} y={ty + 24} fill="rgba(255,255,255,0.5)" fontSize="7" fontFamily="monospace">H:{fmtPrice(c.high)}</text>
            <text x={tx + 30} y={ty + 24} fill="rgba(255,255,255,0.5)" fontSize="7" fontFamily="monospace">C:{fmtPrice(c.close)}</text>
            <text x={tx} y={ty + 36} textAnchor="middle" fill={isUp ? "#00ff88" : "#ff5050"} fontSize="8" fontFamily="monospace" fontWeight="bold">
              {isUp ? "+" : ""}{((c.close - c.open) / (c.open || 1) * 100).toFixed(2)}% · Vol {fmt(c.volume, 1)}
            </text>
            {flow && (flow.buy_count + flow.sell_count) > 0 && (
              <>
                <line x1={tx - 75} y1={ty + 42} x2={tx + 75} y2={ty + 42} stroke="rgba(255,255,255,0.06)" />
                <text x={tx - 75} y={ty + 54} fill="#00ff88" fontSize="7" fontFamily="monospace">BUY: {flow.buy_count}tx · {fmt(flow.buy_usd, 1)}</text>
                <text x={tx - 75} y={ty + 64} fill="#ff5050" fontSize="7" fontFamily="monospace">SELL: {flow.sell_count}tx · {fmt(flow.sell_usd, 1)}</text>
                <text x={tx + 75} y={ty + 54} textAnchor="end" fill={flow.net_usd >= 0 ? "#00ff88" : "#ff5050"} fontSize="8" fontFamily="monospace" fontWeight="bold">
                  Net: {flow.net_usd >= 0 ? "+" : ""}{fmt(flow.net_usd, 1)}
                </text>
                {(flow.whale_buy + flow.whale_sell) > 0 && (
                  <text x={tx + 75} y={ty + 64} textAnchor="end" fill="#00f0ff" fontSize="7" fontFamily="monospace">◆ {flow.whale_buy + flow.whale_sell} whale txns</text>
                )}
              </>
            )}
          </g>
        );
      })()}

      <g transform={`translate(${CW - PX - 2}, ${PY + 2})`}>
        <rect x={-105} y={0} width={105} height={38} rx="4" fill="rgba(10,10,18,0.7)" stroke="rgba(255,255,255,0.05)" />
        <polygon points="-95,9 -92,6 -89,9 -92,12" fill="#00f0ff" />
        <text x={-85} y={11} fill="rgba(255,255,255,0.4)" fontSize="7">Whale Activity</text>
        <text x={-95} y={21} fill="#00ff88" fontSize="7">▲ Buy Flow</text>
        <text x={-40} y={21} fill="#ff5050" fontSize="7">▼ Sell Flow</text>
        <text x={-95} y={31} fill="rgba(255,255,255,0.3)" fontSize="6">Auto-scanned via Moralis</text>
      </g>
    </svg>
  );
}

/* ── Wallet Card ── */
function WalletCard({ w, rank, onViewWallet }: { w: InvestigateWallet; rank: number; onViewWallet: (addr: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const tagStyle = TAG_COLORS[w.tag] || TAG_COLORS.degen;
  const isBuyer = w.net_usd > 0;
  const buyPct = w.total_volume > 0 ? (w.buy_usd / w.total_volume) * 100 : 50;
  return (
    <div className="glass-panel rounded-xl border border-white/[0.06] hover:border-white/[0.12] transition-all">
      <div className="p-3 flex items-start gap-3">
        <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold ${rank <= 3 ? "bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/20" : "bg-white/[0.04] text-slate-500 border border-white/[0.06]"}`}>#{rank}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <button onClick={() => onViewWallet(w.address)} className="text-white text-sm font-mono hover:text-neon-cyan transition-colors cursor-pointer truncate" title={w.address}>{w.short_addr}</button>
            <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded-full border ${tagStyle.bg} ${tagStyle.text} ${tagStyle.border}`}>{w.label}</span>
          </div>
          <div className="flex items-center gap-2 mb-2">
            <div className="flex-1 h-1.5 rounded-full bg-white/[0.04] overflow-hidden"><div className="h-full rounded-full bg-gradient-to-r from-green-500 to-green-400" style={{ width: `${buyPct}%` }} /></div>
            <span className="text-[11px] text-slate-500 font-mono">{buyPct.toFixed(0)}% buy</span>
          </div>
          <div className="grid grid-cols-4 gap-2 text-[11px]">
            <div><span className="text-slate-500 block">Buys</span><span className="text-green-400 font-bold">{w.buys}</span></div>
            <div><span className="text-slate-500 block">Sells</span><span className="text-red-400 font-bold">{w.sells}</span></div>
            <div><span className="text-slate-500 block">Volume</span><span className="text-white font-bold">{fmt(w.total_volume)}</span></div>
            <div><span className="text-slate-500 block">Net</span><span className={`font-bold ${isBuyer ? "text-green-400" : "text-red-400"}`}>{isBuyer ? "+" : ""}{fmt(w.net_usd)}</span></div>
          </div>
        </div>
        <div className="flex-shrink-0 text-right">
          <div className={`text-xs font-bold ${isBuyer ? "text-green-400" : "text-red-400"}`}>{isBuyer ? "▲" : "▼"} {fmt(w.abs_impact)}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">impact</div>
        </div>
      </div>
      {w.txns.length > 0 && (
        <>
          <button onClick={() => setExpanded(!expanded)} className="w-full px-3 py-1.5 flex items-center justify-center gap-1 text-[11px] text-slate-500 hover:text-white border-t border-white/[0.04] transition-colors cursor-pointer">
            <span className="material-symbols-outlined text-[12px]">{expanded ? "expand_less" : "expand_more"}</span>
            {expanded ? "Hide" : "Show"} {w.txns.length} txns
          </button>
          {expanded && (
            <div className="px-3 pb-3 space-y-1">
              {w.txns.map((tx, i) => (
                <div key={i} className="flex items-center gap-2 text-[11px] py-1 border-t border-white/[0.02]">
                  <span className={`w-8 text-center font-bold ${tx.side === "buy" ? "text-green-400" : "text-red-400"}`}>{tx.side === "buy" ? "BUY" : "SELL"}</span>
                  <span className="text-white font-mono">{fmt(tx.usd_value)}</span>
                  <span className="text-slate-500 flex-1 text-right">{tx.timestamp ? fmtDate(tx.timestamp) : "—"}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── Aggregate Stats Panel ── */
function AggregatePanel({ wallets, totalSwaps }: { wallets: InvestigateWallet[]; totalSwaps: number }) {
  const totalBuyUsd = wallets.reduce((s, w) => s + w.buy_usd, 0);
  const totalSellUsd = wallets.reduce((s, w) => s + w.sell_usd, 0);
  const totalVol = totalBuyUsd + totalSellUsd;
  const netFlow = totalBuyUsd - totalSellUsd;
  const buyP = totalVol > 0 ? (totalBuyUsd / totalVol) * 100 : 50;
  const whaleCount = wallets.filter((w) => w.tag === "whale" || w.tag === "smart").length;
  return (
    <div className="glass-panel rounded-xl border border-white/[0.06] p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <span className="material-symbols-outlined text-neon-cyan text-[16px]">analytics</span>
        <span className="text-white text-xs font-bold">Activity Summary</span>
        <span className="text-[11px] text-slate-500 ml-auto">{totalSwaps} swaps</span>
      </div>
      <div>
        <div className="flex justify-between text-[11px] mb-1"><span className="text-green-400">Buy {fmt(totalBuyUsd)}</span><span className="text-red-400">Sell {fmt(totalSellUsd)}</span></div>
        <div className="h-2 rounded-full bg-red-500/20 overflow-hidden"><div className="h-full rounded-full bg-gradient-to-r from-green-500 to-green-400 transition-all" style={{ width: `${buyP}%` }} /></div>
        <div className="text-center text-[11px] text-slate-500 mt-1">{buyP.toFixed(1)}% buy pressure</div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-white/[0.02] rounded-lg p-2 text-center"><div className="text-[11px] text-slate-500">Net Flow</div><div className={`text-sm font-bold ${netFlow >= 0 ? "text-green-400" : "text-red-400"}`}>{netFlow >= 0 ? "+" : ""}{fmt(netFlow)}</div></div>
        <div className="bg-white/[0.02] rounded-lg p-2 text-center"><div className="text-[11px] text-slate-500">Volume</div><div className="text-sm font-bold text-white">{fmt(totalVol)}</div></div>
        <div className="bg-white/[0.02] rounded-lg p-2 text-center"><div className="text-[11px] text-slate-500">Wallets</div><div className="text-sm font-bold text-white">{wallets.length}</div></div>
        <div className="bg-white/[0.02] rounded-lg p-2 text-center"><div className="text-[11px] text-slate-500">Whales</div><div className="text-sm font-bold text-neon-cyan">{whaleCount}</div></div>
      </div>
      <div className="text-[11px] text-slate-600 text-center pt-1 border-t border-white/[0.04]">Moralis · GeckoTerminal · Auto-scanned</div>
    </div>
  );
}

/* ── Main Inner Component ── */
function InvestigateInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [chain, setChain] = useState("solana");
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [token, setToken] = useState<TokenAnalysis | null>(null);
  const [pairs, setPairs] = useState<TokenPair[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [candles, setCandles] = useState<InvestigateCandle[]>([]);
  const [timeframe, setTimeframe] = useState("5m");
  const [flowMap, setFlowMap] = useState<Record<string, CandleFlow>>({});
  const [wallets, setWallets] = useState<InvestigateWallet[]>([]);
  const [totalSwaps, setTotalSwaps] = useState(0);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  useEffect(() => {
    const addr = searchParams.get("address");
    const ch = searchParams.get("chain");
    if (addr) { setQuery(addr); if (ch) setChain(ch); handleSearch(addr, ch || "solana"); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runScan = useCallback(async (tokenAddr: string, pairAddr: string, ch: string, candleList: InvestigateCandle[], tf: string) => {
    setScanning(true);
    try {
      const res = await scanTokenActivity({
        token_address: tokenAddr, pair_address: pairAddr, chain: ch,
        candle_timestamps: candleList.map((c) => c.ts),
        timeframe_seconds: TF_SECONDS[tf] || 300,
      });
      if (res.candle_flow) setFlowMap(res.candle_flow);
      if (res.wallets) setWallets(res.wallets);
      setTotalSwaps(res.total_swaps || 0);
      if (res.error) setError(res.error);
    } catch (e: unknown) { setError(e instanceof Error ? e.message : "Scan failed"); }
    finally { setScanning(false); }
  }, []);

  const handleSearch = useCallback(async (address?: string, ch?: string) => {
    const addr = (address || query).trim();
    const c = ch || chain;
    if (!addr) return;
    setLoading(true); setError(null); setToken(null); setPairs([]); setCandles([]); setFlowMap({}); setWallets([]); setTotalSwaps(0);
    try {
      const tokenRes = await analyzeToken(addr, c);
      if (tokenRes.error || !tokenRes.token) { setError(tokenRes.error || "Token not found"); setLoading(false); return; }
      setToken(tokenRes.token); setPairs(tokenRes.pairs);
      const pairAddr = tokenRes.token.pair_address;
      if (pairAddr) {
        const ohlcvRes = await fetchInvestigateOHLCV(pairAddr, c, timeframe);
        if (ohlcvRes.candles?.length) {
          setCandles(ohlcvRes.candles);
          setLoading(false);
          runScan(tokenRes.token.address, pairAddr, c, ohlcvRes.candles, timeframe);
        } else { setError("No chart data available"); }
      }
    } catch (e: unknown) { setError(e instanceof Error ? e.message : "Failed to load token"); }
    finally { setLoading(false); }
  }, [query, chain, timeframe, runScan]);

  const handleViewWallet = useCallback((addr: string) => { router.push(`/wallet-analyzer?address=${addr}`); }, [router]);

  const handleChangeTimeframe = useCallback(async (tf: string) => {
    setTimeframe(tf);
    if (!token?.pair_address) return;
    setCandles([]); setFlowMap({}); setWallets([]);
    try {
      const ohlcvRes = await fetchInvestigateOHLCV(token.pair_address, chain, tf);
      if (ohlcvRes.candles?.length) { setCandles(ohlcvRes.candles); runScan(token.address, token.pair_address, chain, ohlcvRes.candles, tf); }
    } catch {}
  }, [token, chain, runScan]);

  return (
    <AppShell header={<Header query={query} setQuery={setQuery} chain={chain} setChain={setChain} onSearch={() => handleSearch()} loading={loading} />}>
      <div className="space-y-3">
        {error && (
          <div className="glass-panel rounded-xl border border-red-500/20 p-3 flex items-center gap-2">
            <span className="material-symbols-outlined text-red-400 text-[16px]">error</span>
            <span className="text-red-400 text-sm">{error}</span>
            <button onClick={() => setError(null)} className="ml-auto text-slate-500 hover:text-white cursor-pointer"><span className="material-symbols-outlined text-[14px]">close</span></button>
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="flex flex-col items-center gap-3">
              <div className="w-10 h-10 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" />
              <span className="text-slate-500 text-sm">Loading token data…</span>
            </div>
          </div>
        )}

        {!loading && !token && !error && (
          <div className="flex flex-col items-center justify-center py-24 gap-4">
            <div className="w-16 h-16 rounded-2xl bg-neon-cyan/5 border border-neon-cyan/10 flex items-center justify-center">
              <span className="material-symbols-outlined text-neon-cyan text-3xl">query_stats</span>
            </div>
            <div className="text-center">
              <h3 className="text-white text-lg font-bold mb-1">Chart Investigation</h3>
              <p className="text-slate-500 text-sm max-w-md">Enter a token address to auto-scan wallet activity. Buy/sell flow, whale markers, and net flow arrows are drawn directly on the chart.</p>
            </div>
          </div>
        )}

        {token && !loading && (
          <>
            {/* Token header */}
            <div className="glass-panel rounded-xl border border-white/[0.06] p-3">
              <div className="flex items-center gap-3">
                {token.logo && <img src={token.logo} alt="" className="w-8 h-8 rounded-full bg-white/[0.04]" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="text-white text-base font-bold">{token.symbol}</h2>
                    <span className="text-slate-500 text-xs truncate">{token.name}</span>
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-white/[0.04] text-slate-400 font-mono">{chain}</span>
                    {scanning && <span className="text-[11px] px-1.5 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20 flex items-center gap-1"><span className="w-2 h-2 rounded-full border border-neon-cyan/40 border-t-neon-cyan animate-spin" />Scanning wallets…</span>}
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 text-xs">
                    <span className="text-white font-bold">{fmtPrice(token.price_usd)}</span>
                    <span className={token.price_change_24h >= 0 ? "text-green-400" : "text-red-400"}>{token.price_change_24h >= 0 ? "+" : ""}{token.price_change_24h.toFixed(2)}%</span>
                    <span className="text-slate-500">Vol: {fmt(token.volume_24h)}</span>
                    <span className="text-slate-500">Liq: {fmt(token.liquidity_usd)}</span>
                    <span className="text-slate-500">MCap: {fmt(token.market_cap || token.fdv)}</span>
                  </div>
                </div>
                <div className="flex gap-1">
                  {["1m", "5m", "15m", "1h", "4h"].map((tf) => (
                    <button key={tf} onClick={() => handleChangeTimeframe(tf)}
                      className={`px-2 py-1 rounded text-[11px] font-bold transition-all cursor-pointer ${timeframe === tf ? "bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/20" : "bg-white/[0.03] text-slate-500 hover:text-white border border-transparent"}`}>
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Chart with auto-overlaid wallet activity */}
            {candles.length > 0 && (
              <div className="glass-panel rounded-xl border border-white/[0.06] p-2 overflow-hidden">
                <InvestigateChart candles={candles} flowMap={flowMap} hoverIdx={hoverIdx} setHoverIdx={setHoverIdx} />
              </div>
            )}

            {/* Wallet results — 2 columns: list + aggregate */}
            {wallets.length > 0 && (
              <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-3">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 px-1">
                    <span className="material-symbols-outlined text-neon-cyan text-[16px]">group</span>
                    <span className="text-white text-sm font-bold">Top Wallets <span className="text-slate-500 text-xs font-normal ml-1">({wallets.length} found)</span></span>
                  </div>
                  {wallets.map((w, i) => <WalletCard key={w.address} w={w} rank={i + 1} onViewWallet={handleViewWallet} />)}
                </div>
                <div className="space-y-3">
                  <AggregatePanel wallets={wallets} totalSwaps={totalSwaps} />
                  <div className="glass-panel rounded-xl border border-white/[0.06] p-3">
                    <div className="text-white text-xs font-bold mb-2">Wallet Types</div>
                    <div className="space-y-1.5">
                      {Object.entries(wallets.reduce<Record<string, number>>((acc, w) => { acc[w.label] = (acc[w.label] || 0) + 1; return acc; }, {})).sort((a, b) => b[1] - a[1]).map(([label, count]) => {
                        const tag = wallets.find((w) => w.label === label)?.tag || "degen";
                        const s = TAG_COLORS[tag] || TAG_COLORS.degen;
                        return <div key={label} className="flex items-center gap-2 text-[11px]"><span className={`w-2 h-2 rounded-full ${s.bg} border ${s.border}`} /><span className={`${s.text} flex-1`}>{label}</span><span className="text-white font-bold">{count}</span></div>;
                      })}
                    </div>
                  </div>
                  <div className="glass-panel rounded-xl border border-white/[0.06] p-3">
                    <div className="text-white text-xs font-bold mb-2">Impact Leaderboard</div>
                    <div className="space-y-1">
                      {wallets.slice(0, 5).map((w, i) => (
                        <div key={w.address} className="flex items-center gap-2 text-[11px]">
                          <span className={`font-bold w-4 ${i < 3 ? "text-neon-cyan" : "text-slate-500"}`}>#{i + 1}</span>
                          <button onClick={() => handleViewWallet(w.address)} className="text-white font-mono hover:text-neon-cyan transition-colors cursor-pointer flex-1 text-left truncate">{w.short_addr}</button>
                          <span className={`font-bold ${w.net_usd >= 0 ? "text-green-400" : "text-red-400"}`}>{fmt(w.abs_impact)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {scanning && wallets.length === 0 && (
              <div className="glass-panel rounded-xl border border-white/[0.06] p-8 flex flex-col items-center gap-3">
                <div className="w-8 h-8 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" />
                <span className="text-slate-500 text-xs">Scanning wallet activity via Moralis…</span>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

export default function InvestigatePage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-obsidian flex items-center justify-center"><div className="w-10 h-10 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" /></div>}>
      <InvestigateInner />
    </Suspense>
  );
}
