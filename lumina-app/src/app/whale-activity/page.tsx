"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import GlobalSearch from "@/components/GlobalSearch";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import StatCards from "@/components/StatCards";
import WhaleFeed from "@/components/WhaleFeed";
import { WhaleRetailVolChart, NetFlowChart } from "@/components/Charts";
import SmartMoney from "@/components/SmartMoney";
import BuyWalls from "@/components/BuyWalls";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface RawWhaleTrade {
  symbol: string;
  exchange: string;
  side: string;
  amount: number;
  price: number;
  usd_value: number;
  timestamp: string;
}

export interface WhaleStats {
  totalVolume: number;
  buyVolume: number;
  sellVolume: number;
  buyPct: number;
  sellPct: number;
  tradeCount: number;
  largestTrade: RawWhaleTrade | null;
  bySymbol: Record<string, { buy: number; sell: number; count: number }>;
}

function computeStats(trades: RawWhaleTrade[]): WhaleStats {
  let totalVolume = 0, buyVolume = 0, sellVolume = 0;
  let largestTrade: RawWhaleTrade | null = null;
  const bySymbol: Record<string, { buy: number; sell: number; count: number }> = {};

  for (const t of trades) {
    totalVolume += t.usd_value;
    if (t.side === "buy") buyVolume += t.usd_value;
    else sellVolume += t.usd_value;
    if (!largestTrade || t.usd_value > largestTrade.usd_value) largestTrade = t;

    const base = t.symbol.split("/")[0];
    if (!bySymbol[base]) bySymbol[base] = { buy: 0, sell: 0, count: 0 };
    bySymbol[base].count++;
    if (t.side === "buy") bySymbol[base].buy += t.usd_value;
    else bySymbol[base].sell += t.usd_value;
  }

  const total = buyVolume + sellVolume || 1;
  return {
    totalVolume,
    buyVolume,
    sellVolume,
    buyPct: Math.round((buyVolume / total) * 100),
    sellPct: Math.round((sellVolume / total) * 100),
    tradeCount: trades.length,
    largestTrade,
    bySymbol,
  };
}

const chains = ["All", "BTC", "ETH", "SOL", "XRP", "ARB", "AVAX", "OP"];

interface HeaderProps {
  tradeCount: number;
  lastRefresh: number;
  activeChain: string;
  setActiveChain: (c: string) => void;
  minValue: number;
  setMinValue: (v: number) => void;
}

function WhaleHeader({ tradeCount, lastRefresh, activeChain, setActiveChain, minValue, setMinValue }: HeaderProps) {
  const { wallet, setWallet } = useWallet();

  const formatValue = (val: number) => {
    if (val >= 1000000) return `$${(val / 1000000).toFixed(0)}M+`;
    return `$${(val / 1000).toFixed(0)}K+`;
  };

  const timeSince = lastRefresh ? `${Math.floor((Date.now() - lastRefresh) / 1000)}s ago` : "—";

  return (
    <div className="flex flex-col gap-3 w-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 min-w-0">
          <h2 className="text-white text-sm font-bold tracking-tight shrink-0">Whale Activity</h2>
          <div className="h-4 w-px bg-white/10 mx-1 hidden md:block" />
          <div className="hidden md:flex items-center gap-2">
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-neon-cyan/10 border border-neon-cyan/20 text-[11px] text-neon-cyan font-bold">
              <span className="w-1.5 h-1.5 rounded-full bg-neon-cyan animate-pulse" />
              LIVE
            </span>
            <span className="text-[11px] text-slate-500 font-mono">{tradeCount} trades · updated {timeSince}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-4 shrink-0">
          <div className="hidden lg:block">
            <GlobalSearch placeholder="Search wallet or token..." />
          </div>
          <NotificationPanel />
          <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
        </div>
      </div>
      <div className="flex items-center gap-3 sm:gap-6 text-sm overflow-x-auto">
        <div className="flex items-center gap-2">
          <span className="text-slate-500 text-xs font-medium uppercase tracking-wider">Token</span>
          <div className="flex gap-1">
            {chains.map((chain) => (
              <button
                key={chain}
                onClick={() => setActiveChain(chain)}
                className={`px-2 py-0.5 rounded text-xs font-medium transition-colors cursor-pointer ${
                  activeChain === chain
                    ? "bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/30"
                    : "hover:bg-white/5 text-slate-400 hover:text-white border border-transparent"
                }`}
              >
                {chain}
              </button>
            ))}
          </div>
        </div>
        <div className="w-px h-4 bg-white/10 hidden md:block" />
        <div className="hidden md:flex items-center gap-3 flex-1 max-w-sm">
          <span className="text-slate-500 text-xs font-medium uppercase tracking-wider whitespace-nowrap">Min</span>
          <input
            className="w-full accent-[#00f0ff]"
            max={5000000}
            min={10000}
            step={10000}
            type="range"
            value={minValue}
            onChange={(e) => setMinValue(Number(e.target.value))}
          />
          <span className="text-white font-mono text-xs whitespace-nowrap">{formatValue(minValue)}</span>
        </div>
      </div>
    </div>
  );
}

export default function WhaleActivityPage() {
  const [allTrades, setAllTrades] = useState<RawWhaleTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(0);
  const [activeChain, setActiveChain] = useState("All");
  const [minValue, setMinValue] = useState(20000);
  const prevHashRef = useRef("");

  const fetchAll = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/market/whale-trades-all?limit=200`);
      if (!res.ok) throw new Error("fetch failed");
      const data = await res.json();
      const all = ((data.data || []) as RawWhaleTrade[]).sort(
        (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
      );

      const hash = all.slice(0, 8).map(t => `${t.symbol}:${t.usd_value}:${t.side}`).join("|");
      if (hash !== prevHashRef.current) {
        prevHashRef.current = hash;
        setAllTrades(all);
      }
      setLastRefresh(Date.now());
    } catch {
      // keep existing data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 45_000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  // Apply filters from header
  const trades = useMemo(() => {
    let filtered = allTrades;
    if (activeChain !== "All") {
      filtered = filtered.filter((t) => t.symbol.split("/")[0] === activeChain);
    }
    if (minValue > 20000) {
      filtered = filtered.filter((t) => t.usd_value >= minValue);
    }
    return filtered;
  }, [allTrades, activeChain, minValue]);

  const stats = useMemo(() => computeStats(trades), [trades]);

  return (
    <AppShell header={
      <WhaleHeader
        tradeCount={stats.tradeCount}
        lastRefresh={lastRefresh}
        activeChain={activeChain}
        setActiveChain={setActiveChain}
        minValue={minValue}
        setMinValue={setMinValue}
      />
    }>
      <div className="grid grid-cols-12 gap-3">
        <StatCards stats={stats} loading={loading} />

        <div className="col-span-12">
          <WhaleFeed trades={trades} loading={loading} />
        </div>

        <div className="col-span-12 grid grid-cols-1 md:grid-cols-2 gap-3" style={{ minHeight: 280 }}>
          <WhaleRetailVolChart stats={stats} />
          <NetFlowChart stats={stats} />
        </div>

        <div className="col-span-12 grid grid-cols-1 lg:grid-cols-2 gap-3">
          <SmartMoney trades={trades} />
          <BuyWalls />
        </div>
      </div>
    </AppShell>
  );
}
