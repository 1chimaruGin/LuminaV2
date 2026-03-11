"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";

interface SearchResult {
  type: "token" | "pair" | "wallet" | "exchange" | "page";
  icon: string;
  label: string;
  sub: string;
  route: string;
}

const allResults: SearchResult[] = [
  { type: "token", icon: "token", label: "Bitcoin (BTC)", sub: "Top cryptocurrency by market cap", route: "/token-analyzer" },
  { type: "token", icon: "token", label: "Ethereum (ETH)", sub: "Smart contract platform", route: "/token-analyzer" },
  { type: "token", icon: "token", label: "Solana (SOL)", sub: "High-speed L1 blockchain", route: "/token-analyzer" },
  { type: "token", icon: "token", label: "Dogecoin (DOGE)", sub: "Popular memecoin", route: "/token-analyzer" },
  { type: "token", icon: "token", label: "Chainlink (LINK)", sub: "Oracle network", route: "/token-analyzer" },
  { type: "token", icon: "token", label: "Arbitrum (ARB)", sub: "Ethereum L2 rollup", route: "/token-analyzer" },
  { type: "token", icon: "token", label: "Sui (SUI)", sub: "Move-based L1", route: "/token-analyzer" },
  { type: "pair", icon: "swap_horiz", label: "BTC/USDT", sub: "Spot · 8 exchanges", route: "/markets/spot" },
  { type: "pair", icon: "swap_horiz", label: "ETH/USDT", sub: "Spot · 8 exchanges", route: "/markets/spot" },
  { type: "pair", icon: "swap_horiz", label: "SOL/USDT", sub: "Spot · 8 exchanges", route: "/markets/spot" },
  { type: "pair", icon: "swap_horiz", label: "BTC-PERP", sub: "Derivatives · Perpetual", route: "/markets/derivatives" },
  { type: "pair", icon: "swap_horiz", label: "ETH-PERP", sub: "Derivatives · Perpetual", route: "/markets/derivatives" },
  { type: "exchange", icon: "account_balance", label: "Binance", sub: "CEX · Largest by volume", route: "/markets/spot" },
  { type: "exchange", icon: "account_balance", label: "Hyperliquid", sub: "DEX · Perpetuals", route: "/markets/derivatives" },
  { type: "exchange", icon: "account_balance", label: "Bybit", sub: "CEX · Derivatives", route: "/markets/derivatives" },
  { type: "page", icon: "dashboard", label: "Dashboard", sub: "Market Intelligence Hub", route: "/" },
  { type: "page", icon: "water", label: "Whale Activity", sub: "Track whale movements live", route: "/whale-activity" },
  { type: "page", icon: "insights", label: "Trading Insight", sub: "Funding, OI, Heatmap, Liquidations", route: "/insight" },
  { type: "page", icon: "show_chart", label: "Spot Markets", sub: "Cross-exchange spot charts", route: "/markets/spot" },
  { type: "page", icon: "waterfall_chart", label: "Derivatives", sub: "Futures & perpetuals", route: "/markets/derivatives" },
  { type: "page", icon: "token", label: "Token Analyzer", sub: "Whale-powered token analysis", route: "/token-analyzer" },
  { type: "page", icon: "account_balance_wallet", label: "Wallet Analyzer", sub: "Analyze any wallet", route: "/wallet-analyzer" },
  { type: "page", icon: "smart_toy", label: "Trading Bots", sub: "Automated strategies", route: "/bots/trading" },
  { type: "page", icon: "psychology", label: "AI Copilot", sub: "AI-powered analysis", route: "/ai-copilot" },
];

const typeColors: Record<string, string> = {
  token: "text-accent-warning",
  pair: "text-neon-cyan",
  wallet: "text-neon-purple",
  exchange: "text-neon-lime",
  page: "text-slate-400",
};

const typeLabels: Record<string, string> = {
  token: "TOKEN",
  pair: "PAIR",
  wallet: "WALLET",
  exchange: "EXCHANGE",
  page: "PAGE",
};

interface Props {
  placeholder?: string;
  className?: string;
}

export default function GlobalSearch({ placeholder = "Search any token, pair, exchange...", className = "w-64" }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const q = query.trim().toLowerCase();
  const isWalletLike = query.trim().length >= 32 || (query.trim().startsWith("0x") && query.trim().length >= 10);
  const isPairLike = /^[a-z]{2,10}\s*[\/\-]\s*[a-z]{2,10}$/i.test(query.trim());
  const isTokenLike = q.length >= 2 && !isWalletLike && !isPairLike;

  const staticResults = q.length > 0
    ? allResults.filter((r) =>
        r.label.toLowerCase().includes(q) ||
        r.sub.toLowerCase().includes(q) ||
        r.type.toLowerCase().includes(q)
      ).slice(0, 6)
    : [];

  // Dynamic suggestions for queries that don't match static results
  const dynamicResults: SearchResult[] = [];
  if (q.length > 0 && staticResults.length < 3) {
    if (isWalletLike) {
      dynamicResults.push({
        type: "wallet",
        icon: "account_balance_wallet",
        label: `Analyze ${query.trim().slice(0, 12)}...`,
        sub: "Open in Wallet Analyzer",
        route: `/wallet-analyzer?address=${encodeURIComponent(query.trim())}`,
      });
    }
    if (isPairLike || isTokenLike) {
      const tokenName = query.trim().split(/[\/\-]/)[0].trim().toUpperCase();
      dynamicResults.push({
        type: "token",
        icon: "token",
        label: `Search "${tokenName}"`,
        sub: "Open in Token Analyzer",
        route: `/token-analyzer?q=${encodeURIComponent(tokenName)}`,
      });
    }
    if (isPairLike) {
      dynamicResults.push({
        type: "pair",
        icon: "swap_horiz",
        label: `Find "${query.trim().toUpperCase()}"`,
        sub: "Search in Spot Markets",
        route: `/markets/spot`,
      });
    }
  }

  const filtered = [...staticResults, ...dynamicResults].slice(0, 8);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query]);

  const handleSelect = (result: SearchResult) => {
    setQuery("");
    setOpen(false);
    router.push(result.route);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((prev) => Math.min(prev + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((prev) => Math.max(prev - 1, 0));
    } else if (e.key === "Enter" && filtered[selectedIdx]) {
      handleSelect(filtered[selectedIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 material-symbols-outlined text-[18px] pointer-events-none">search</span>
      <input
        ref={inputRef}
        className={`bg-white/[0.04] border border-white/[0.08] text-white text-[13px] rounded-lg pl-9 pr-4 py-2 focus:ring-1 focus:ring-neon-cyan/50 focus:border-neon-cyan/40 focus:bg-white/[0.06] placeholder-slate-500 transition-all outline-none ${className}`}
        placeholder={placeholder}
        type="text"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => { if (query.trim()) setOpen(true); }}
        onKeyDown={handleKeyDown}
      />

      {/* Keyboard shortcut hint */}
      {!query && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] text-slate-600 font-mono border border-white/10 rounded px-1 py-px">⌘K</span>
      )}

      {open && filtered.length > 0 && (
        <div className="absolute left-0 top-10 w-96 glass-panel rounded-xl shadow-2xl z-50 border border-white/10 overflow-hidden animate-fade-in-up">
          <div className="p-2 border-b border-white/5 flex items-center justify-between">
            <span className="text-[11px] text-slate-500">{filtered.length} results</span>
            <span className="text-[11px] text-slate-600">↑↓ navigate · ↵ select · esc close</span>
          </div>
          <div className="max-h-[360px] overflow-y-auto">
            {filtered.map((r, i) => (
              <button
                key={`${r.type}-${r.label}`}
                onClick={() => handleSelect(r)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors cursor-pointer ${
                  i === selectedIdx ? "bg-white/[0.06]" : "hover:bg-white/[0.03]"
                }`}
              >
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${i === selectedIdx ? "bg-neon-cyan/10" : "bg-white/5"}`}>
                  <span className={`material-symbols-outlined text-[16px] ${typeColors[r.type]}`}>{r.icon}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-white text-xs font-bold truncate">{r.label}</span>
                    <span className={`text-[11px] font-bold px-1 py-px rounded ${typeColors[r.type]} bg-white/5`}>{typeLabels[r.type]}</span>
                  </div>
                  <span className="text-[11px] text-slate-500 truncate block">{r.sub}</span>
                </div>
                <span className="material-symbols-outlined text-[14px] text-slate-600">arrow_forward</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {open && query.trim().length > 0 && filtered.length === 0 && (
        <div className="absolute left-0 top-10 w-80 glass-panel rounded-xl shadow-2xl z-50 border border-white/10 overflow-hidden animate-fade-in-up p-6 text-center">
          <span className="material-symbols-outlined text-[32px] text-slate-600 mb-2">search_off</span>
          <p className="text-xs text-slate-400">No results for &ldquo;{query}&rdquo;</p>
          <p className="text-[11px] text-slate-600 mt-1">Try searching for a token, pair, exchange, or wallet</p>
        </div>
      )}
    </div>
  );
}
