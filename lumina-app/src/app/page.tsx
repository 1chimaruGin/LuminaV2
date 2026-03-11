"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import GlobalSearch from "@/components/GlobalSearch";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import DashboardStatCards from "@/components/dashboard/DashboardStatCards";
import MarketSentimentHero from "@/components/dashboard/MarketSentimentHero";
import MarketPulse from "@/components/dashboard/MarketPulse";
import ActionableAlerts from "@/components/dashboard/ActionableAlerts";
import ExchangeVolume from "@/components/dashboard/ExchangeVolume";
import TopMovers from "@/components/dashboard/TopMovers";
import WhaleMovementTracker from "@/components/dashboard/WhaleMovementTracker";
import { fetchMarketOverview, fetchAllTickers, fetchAllWhaleTrades, fetchFundingRates, type Ticker, type MarketOverview, type FundingRate, type WhaleTrade } from "@/lib/api";

function DashboardHeader({ pairCount, lastUpdate, refreshing }: { pairCount: number; lastUpdate: Date | null; refreshing: boolean }) {
  const { wallet, setWallet } = useWallet();

  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-4">
        <h2 className="text-white text-sm font-bold tracking-tight">Market Intelligence</h2>
        <div className="h-4 w-px bg-white/10 mx-1 hidden md:block"></div>
        <div className="items-center gap-2 hidden md:flex">
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-neon-cyan/8 border border-neon-cyan/20">
            <span className={`w-1.5 h-1.5 rounded-full ${refreshing ? "bg-amber-400 animate-pulse" : "bg-neon-cyan animate-pulse"}`}></span>
            <span className="text-[11px] text-neon-cyan font-bold font-mono">8 exchanges</span>
          </span>
          <span className="text-[11px] text-slate-400">
            <span className="text-neon-lime font-mono font-bold">{pairCount.toLocaleString()}</span> pairs
          </span>
          {lastUpdate && (
            <span className="text-[11px] text-slate-500 font-mono">
              {lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-4">
        <div className="hidden lg:block">
          <GlobalSearch />
        </div>
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function Home() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [whaleTrades, setWhaleTrades] = useState<WhaleTrade[]>([]);
  const [fundingRates, setFundingRates] = useState<FundingRate[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const fetchCountRef = useRef(0);
  // Keep previous data fingerprints to avoid re-renders when data hasn't changed
  const prevHashRef = useRef({ tickers: "", whale: "", funding: "" });

  const fetchData = useCallback(async () => {
    fetchCountRef.current++;
    const isRefresh = fetchCountRef.current > 1;
    if (isRefresh) setRefreshing(true);
    try {
      // 3 fast cached endpoints instead of 8+ separate calls
      const [ovRes, tickRes, frRes, whaleRes] = await Promise.allSettled([
        fetchMarketOverview(),
        fetchAllTickers(500),
        fetchFundingRates("binance", 50),
        fetchAllWhaleTrades(100),
      ]);

      if (ovRes.status === "fulfilled") setOverview(ovRes.value);

      if (tickRes.status === "fulfilled") {
        const newData = tickRes.value.data || [];
        const hash = newData.slice(0, 10).map(t => `${t.symbol}:${t.price}`).join("|");
        if (hash !== prevHashRef.current.tickers) {
          prevHashRef.current.tickers = hash;
          setTickers(newData);
        }
      }
      if (frRes.status === "fulfilled") {
        const newData = frRes.value.data || [];
        const hash = newData.slice(0, 5).map(f => `${f.symbol}:${f.rate}`).join("|");
        if (hash !== prevHashRef.current.funding) {
          prevHashRef.current.funding = hash;
          setFundingRates(newData);
        }
      }
      if (whaleRes.status === "fulfilled") {
        const allWhale = (whaleRes.value.data || []) as WhaleTrade[];
        const whaleHash = allWhale.slice(0, 5).map(t => `${t.symbol}:${t.usd_value}:${t.timestamp}`).join("|");
        if (whaleHash !== prevHashRef.current.whale) {
          prevHashRef.current.whale = whaleHash;
          setWhaleTrades(allWhale);
        }
      }

      setLastUpdate(new Date());
    } catch { /* keep existing */ }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 60_000);
    return () => clearInterval(iv);
  }, [fetchData]);

  return (
    <AppShell header={<DashboardHeader pairCount={overview?.active_pairs || 0} lastUpdate={lastUpdate} refreshing={refreshing} />}>
      <div className="grid grid-cols-12 gap-3">
        <DashboardStatCards overview={overview} loading={loading} />

        {/* Sentiment Hero — full width */}
        <div className="col-span-12">
          <MarketSentimentHero overview={overview} tickers={tickers} fundingRates={fundingRates} whaleTrades={whaleTrades} />
        </div>

        {/* Main content */}
        <div className="col-span-12 grid grid-cols-12 gap-3">
          {/* Left column */}
          <div className="col-span-12 xl:col-span-8 flex flex-col gap-3">
            <ActionableAlerts tickers={tickers} whaleTrades={whaleTrades} fundingRates={fundingRates} />
            <TopMovers tickers={tickers} loading={loading} />
          </div>

          {/* Right column */}
          <div className="col-span-12 xl:col-span-4 flex flex-col gap-3">
            <MarketPulse tickers={tickers} fundingRates={fundingRates} whaleTrades={whaleTrades} />
            <ExchangeVolume tickers={tickers} loading={loading} />
          </div>
        </div>

        {/* Bottom row — full width */}
        <div className="col-span-12">
          <WhaleMovementTracker trades={whaleTrades} loading={loading} />
        </div>
      </div>
    </AppShell>
  );
}
