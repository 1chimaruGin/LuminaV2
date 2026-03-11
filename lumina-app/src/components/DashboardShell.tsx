"use client";

import { useState, useEffect, useRef, type ReactNode } from "react";
import Sidebar from "@/components/Sidebar";
import PageTransition from "@/components/PageTransition";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

interface AppShellProps {
  header: ReactNode;
  children: ReactNode;
}

export default function AppShell({ header, children }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [prices, setPrices] = useState<{ eth: number; btc: number; sol: number; block: number } | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const priceRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancel = false;
    const fetchPrices = async () => {
      try {
        const r = await fetch(`${API_BASE}/market/tickers?exchange=binance&limit=50`);
        if (!cancel && r.ok) {
          const json = await r.json();
          const tickers = json.data || [];
          const find = (base: string) => {
            const t = tickers.find((t: { base: string; quote: string }) => t.base === base && t.quote === "USDT");
            return t?.price || 0;
          };
          setPrices({ btc: find("BTC"), eth: find("ETH"), sol: find("SOL"), block: Math.floor(Date.now() / 400) });
          setLastUpdate(new Date());
        }
      } catch { /* silent */ }
    };
    fetchPrices();
    priceRef.current = setInterval(fetchPrices, 15_000);
    return () => { cancel = true; if (priceRef.current) clearInterval(priceRef.current); };
  }, []);

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div
        className={`fixed lg:static inset-y-0 left-0 z-50 transform transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Sidebar onClose={() => setSidebarOpen(false)} />
      </div>

      {/* Main content */}
      <main className="flex-1 flex flex-col h-full overflow-hidden relative bg-obsidian">
        {/* Header with mobile menu injected */}
        <div className="border-b border-white/5 bg-obsidian/90 backdrop-blur-md flex flex-col justify-center px-4 shrink-0 z-20">
          <div className="flex items-center gap-2 py-2.5">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden h-9 w-9 rounded-lg hover:bg-white/5 flex items-center justify-center text-slate-400 hover:text-white transition-colors cursor-pointer"
            >
              <span className="material-symbols-outlined text-[22px]">menu</span>
            </button>
            <div className="flex-1">{header}</div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-3 md:p-4 scroll-smooth">
          <div className="max-w-[1920px] mx-auto">
            <PageTransition>{children}</PageTransition>
          </div>
        </div>

        {/* Status bar */}
        <div className="border-t border-white/[0.08] bg-obsidian/95 backdrop-blur-md px-4 py-1.5 flex items-center justify-between shrink-0 z-20">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-success animate-pulse"></span>
              <span className="text-[11px] text-slate-300 font-medium">Live</span>
            </div>
            <div className="w-px h-3.5 bg-white/10 hidden sm:block"></div>
            <div className="hidden sm:flex items-center gap-1">
              <span className="text-[11px] text-slate-400 font-medium">Block</span>
              <span className="text-[11px] text-white font-mono font-bold">{prices ? prices.block.toLocaleString() : "—"}</span>
            </div>
            <div className="w-px h-3.5 bg-white/10 hidden lg:block"></div>
            <div className="hidden lg:flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-violet-500/80"></span>
              <span className="text-[11px] text-slate-300 font-medium">SOL</span>
              <span className="text-[12px] text-violet-400 font-mono font-bold">{prices && prices.sol ? "$" + prices.sol.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}</span>
            </div>
            <div className="w-px h-3.5 bg-white/10 hidden lg:block"></div>
            <div className="hidden lg:flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-blue-400/80"></span>
              <span className="text-[11px] text-slate-300 font-medium">ETH</span>
              <span className="text-[12px] text-blue-400 font-mono font-bold">{prices && prices.eth ? "$" + prices.eth.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}</span>
            </div>
            <div className="w-px h-3.5 bg-white/10 hidden lg:block"></div>
            <div className="hidden lg:flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-amber-400/80"></span>
              <span className="text-[11px] text-slate-300 font-medium">BTC</span>
              <span className="text-[12px] text-amber-400 font-mono font-bold">{prices && prices.btc ? "$" + prices.btc.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—"}</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdate && (
              <span className="text-[11px] text-slate-500 font-mono hidden md:inline">
                Updated {lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
            )}
            <span className="text-[11px] text-slate-400 font-medium">Lumina v2.5</span>
          </div>
        </div>
      </main>
    </div>
  );
}
