"use client";

import { useState } from "react";
import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";

/* ── Types ── */
type Strategy = "dca" | "grid" | "sniper";
type BotStatus = "running" | "paused" | "stopped";

interface Bot {
  id: string;
  name: string;
  strategy: Strategy;
  pair: string;
  status: BotStatus;
  pnl: number;
  trades: number;
  invested: number;
  createdAt: number;
}

const STRATEGIES: { key: Strategy; label: string; icon: string; desc: string; color: string }[] = [
  { key: "dca", label: "DCA", icon: "event_repeat", desc: "Dollar-cost average into a token on a schedule", color: "text-emerald-400" },
  { key: "grid", label: "Grid", icon: "grid_4x4", desc: "Auto buy low / sell high within a price range", color: "text-violet-400" },
  { key: "sniper", label: "Sniper", icon: "target", desc: "Instantly buy new token launches on Solana", color: "text-rose-400" },
];

const STRAT_TAG: Record<Strategy, string> = {
  dca: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  grid: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  sniper: "bg-rose-500/10 text-rose-400 border-rose-500/20",
};

const STATUS_DOT: Record<BotStatus, string> = { running: "bg-emerald-400", paused: "bg-amber-400", stopped: "bg-slate-500" };

function fUsd(v: number) {
  if (Math.abs(v) >= 1e6) return (v < 0 ? "-" : "+") + "$" + (Math.abs(v) / 1e6).toFixed(2) + "M";
  if (Math.abs(v) >= 1e3) return (v < 0 ? "-" : "+") + "$" + (Math.abs(v) / 1e3).toFixed(1) + "K";
  return (v < 0 ? "-" : "+") + "$" + Math.abs(v).toFixed(2);
}

function timeSince(ts: number) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/* ── Header ── */
function Header() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-3">
        <h2 className="text-white text-sm font-bold tracking-tight">Trading Bots</h2>
        <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-violet-500/20 text-violet-400 border border-violet-500/30">BETA</span>
      </div>
      <div className="flex items-center gap-2 sm:gap-4 shrink-0">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

/* ── Main Page ── */
export default function TradingBotsPage() {
  const { wallet } = useWallet();
  const [bots, setBots] = useState<Bot[]>([]);
  const [creating, setCreating] = useState<Strategy | null>(null);
  const [formName, setFormName] = useState("");
  const [formPair, setFormPair] = useState("SOL/USDT");

  const toggleBot = (id: string) => {
    setBots((p) => p.map((b) => b.id === id ? { ...b, status: b.status === "running" ? "paused" as const : "running" as const } : b));
  };
  const deleteBot = (id: string) => setBots((p) => p.filter((b) => b.id !== id));
  const createBot = () => {
    if (!formName.trim() || !creating) return;
    setBots((p) => [...p, { id: String(Date.now()), name: formName.trim(), strategy: creating, pair: formPair, status: "paused", pnl: 0, trades: 0, invested: 0, createdAt: Date.now() }]);
    setFormName(""); setFormPair("SOL/USDT"); setCreating(null);
  };

  const running = bots.filter((b) => b.status === "running").length;
  const totalPnl = bots.reduce((a, b) => a + b.pnl, 0);

  return (
    <AppShell header={<Header />}>
      <div className="space-y-6 max-w-5xl mx-auto">

        {/* ── Not Connected State ── */}
        {!wallet && (
          <div className="glass-panel rounded-xl p-10 text-center space-y-4">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
              <span className="material-symbols-outlined text-violet-400 text-[28px]">smart_toy</span>
            </div>
            <h3 className="text-white text-lg font-bold">Connect Wallet to Start</h3>
            <p className="text-slate-400 text-sm max-w-md mx-auto">Connect your wallet to create and manage automated trading bots. DCA, Grid, and Sniper strategies available.</p>
          </div>
        )}

        {/* ── Connected: Strategy Cards + Bot List ── */}
        {wallet && (
          <>
            {/* Stats bar */}
            {bots.length > 0 && (
              <div className="flex items-center gap-6 px-1">
                <div>
                  <span className="text-[11px] uppercase tracking-wider text-slate-500">Bots</span>
                  <p className="text-white text-sm font-bold font-mono">{bots.length}</p>
                </div>
                <div>
                  <span className="text-[11px] uppercase tracking-wider text-slate-500">Running</span>
                  <p className="text-emerald-400 text-sm font-bold font-mono">{running}</p>
                </div>
                <div>
                  <span className="text-[11px] uppercase tracking-wider text-slate-500">Total PnL</span>
                  <p className={`text-sm font-bold font-mono ${totalPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{fUsd(totalPnl)}</p>
                </div>
              </div>
            )}

            {/* Strategy Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {STRATEGIES.map((s) => (
                <button
                  key={s.key}
                  onClick={() => { setCreating(creating === s.key ? null : s.key); setFormName(""); }}
                  className={`glass-panel rounded-xl p-5 text-left transition-all duration-200 cursor-pointer group ${
                    creating === s.key
                      ? "ring-1 ring-white/20 bg-white/[0.04]"
                      : "hover:bg-white/[0.03] hover:-translate-y-0.5"
                  }`}
                >
                  <div className="flex items-center gap-3 mb-3">
                    <div className="w-10 h-10 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center">
                      <span className={`material-symbols-outlined text-[20px] ${s.color}`}>{s.icon}</span>
                    </div>
                    <div>
                      <h4 className="text-white text-sm font-bold">{s.label}</h4>
                      <span className="text-[11px] text-slate-500 font-mono">{bots.filter((b) => b.strategy === s.key).length} active</span>
                    </div>
                  </div>
                  <p className="text-slate-400 text-xs leading-relaxed">{s.desc}</p>
                  <div className="mt-3 flex items-center gap-1.5 text-[11px] font-bold text-slate-500 group-hover:text-white/60 transition-colors">
                    <span className="material-symbols-outlined text-[14px]">{creating === s.key ? "close" : "add"}</span>
                    {creating === s.key ? "Cancel" : "Create Bot"}
                  </div>
                </button>
              ))}
            </div>

            {/* Create Form (inline) */}
            {creating && (
              <div className="glass-panel rounded-xl p-4 border border-white/10 space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
                <h4 className="text-white text-sm font-bold flex items-center gap-2">
                  <span className={`material-symbols-outlined text-[16px] ${STRATEGIES.find((s) => s.key === creating)?.color}`}>
                    {STRATEGIES.find((s) => s.key === creating)?.icon}
                  </span>
                  New {STRATEGIES.find((s) => s.key === creating)?.label} Bot
                </h4>
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    autoFocus
                    className="flex-1 min-w-[180px] bg-black/30 border border-white/10 text-white text-sm rounded-lg px-3 py-2.5 focus:ring-1 focus:ring-violet-500 focus:border-violet-500 placeholder-slate-600 outline-none"
                    placeholder="Bot name (e.g. SOL Weekly DCA)"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && createBot()}
                  />
                  <input
                    className="w-36 bg-black/30 border border-white/10 text-white text-sm rounded-lg px-3 py-2.5 focus:ring-1 focus:ring-violet-500 focus:border-violet-500 placeholder-slate-600 outline-none font-mono"
                    placeholder="Pair"
                    value={formPair}
                    onChange={(e) => setFormPair(e.target.value)}
                  />
                  <button
                    onClick={createBot}
                    disabled={!formName.trim()}
                    className="px-5 py-2.5 bg-violet-500 hover:bg-violet-400 disabled:bg-slate-700 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-all cursor-pointer disabled:cursor-not-allowed"
                  >
                    Create
                  </button>
                </div>
              </div>
            )}

            {/* Bot List */}
            {bots.length > 0 && (
              <div className="glass-panel rounded-xl overflow-hidden">
                <div className="p-4 border-b border-white/5 bg-white/[0.02]">
                  <h3 className="text-white text-sm font-bold">Your Bots</h3>
                </div>
                <div className="divide-y divide-white/5">
                  {bots.map((bot) => (
                    <div key={bot.id} className="flex items-center gap-4 px-4 py-3.5 group hover:bg-white/[0.02] transition-colors">
                      {/* Status + Name */}
                      <div className={`w-2 h-2 rounded-full shrink-0 ${STATUS_DOT[bot.status]} ${bot.status === "running" ? "animate-pulse" : ""}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-white text-xs font-bold truncate">{bot.name}</span>
                          <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded border ${STRAT_TAG[bot.strategy]}`}>
                            {bot.strategy.toUpperCase()}
                          </span>
                        </div>
                        <span className="text-[11px] text-slate-500 font-mono">{bot.pair} · {timeSince(bot.createdAt)} ago</span>
                      </div>
                      {/* PnL */}
                      <div className="text-right hidden sm:block">
                        <span className={`text-xs font-bold font-mono ${bot.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {fUsd(bot.pnl)}
                        </span>
                        <div className="text-[11px] text-slate-500">{bot.trades} trades</div>
                      </div>
                      {/* Actions */}
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => toggleBot(bot.id)}
                          title={bot.status === "running" ? "Pause" : "Start"}
                          className="h-7 w-7 rounded-lg hover:bg-white/10 flex items-center justify-center text-slate-400 hover:text-white cursor-pointer transition-colors"
                        >
                          <span className="material-symbols-outlined text-[16px]">{bot.status === "running" ? "pause" : "play_arrow"}</span>
                        </button>
                        <button
                          onClick={() => deleteBot(bot.id)}
                          title="Delete"
                          className="h-7 w-7 rounded-lg hover:bg-rose-500/15 flex items-center justify-center text-slate-400 hover:text-rose-400 cursor-pointer transition-colors"
                        >
                          <span className="material-symbols-outlined text-[16px]">delete</span>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Empty state */}
            {bots.length === 0 && !creating && (
              <div className="text-center py-10">
                <span className="material-symbols-outlined text-slate-600 text-[32px] mb-2 block">smart_toy</span>
                <p className="text-slate-500 text-sm">No bots yet. Pick a strategy above to get started.</p>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
