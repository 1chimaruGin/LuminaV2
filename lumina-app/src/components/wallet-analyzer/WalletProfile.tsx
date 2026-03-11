const tags = [
  { label: "Smart Money", color: "bg-neon-cyan/10 text-neon-cyan border-neon-cyan/30" },
  { label: "DeFi Degen", color: "bg-neon-purple/10 text-neon-purple border-neon-purple/30" },
  { label: "Diamond Hands", color: "bg-neon-lime/10 text-neon-lime border-neon-lime/30" },
  { label: "Multi-Chain", color: "bg-accent-warning/10 text-accent-warning border-accent-warning/30" },
];

const chains = [
  { name: "Ethereum", pct: 45, color: "bg-indigo-500" },
  { name: "Solana", pct: 20, color: "bg-neon-purple" },
  { name: "Arbitrum", pct: 12, color: "bg-neon-cyan" },
  { name: "Base", pct: 8, color: "bg-blue-400" },
  { name: "BSC", pct: 7, color: "bg-accent-warning" },
  { name: "Optimism", pct: 5, color: "bg-accent-error" },
  { name: "Avalanche", pct: 3, color: "bg-red-400" },
];

const exchanges = [
  { name: "Binance", value: "$42K", connected: true },
  { name: "Coinbase", value: "$18K", connected: true },
  { name: "OKX", value: "$6K", connected: true },
  { name: "Bybit", value: "—", connected: false },
];

export default function WalletProfile() {
  return (
    <div className="glass-panel rounded-xl p-5 flex flex-col gap-5">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-full bg-gradient-to-br from-neon-cyan/30 to-neon-purple/30 flex items-center justify-center border border-neon-cyan/20 shadow-neon-glow">
            <span className="material-symbols-outlined text-neon-cyan text-xl">account_balance_wallet</span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold font-mono text-sm">0x4a8b...2f91</span>
              <button className="h-5 w-5 rounded hover:bg-white/10 flex items-center justify-center cursor-pointer transition-colors">
                <span className="material-symbols-outlined text-slate-500 text-[14px] hover:text-white">content_copy</span>
              </button>
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5">First seen 248 days ago</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-accent-success"></span>
          <span className="text-accent-success text-[11px] font-medium">Active</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {tags.map((t) => (
          <span key={t.label} className={`px-2 py-0.5 rounded-full text-[11px] font-bold border ${t.color}`}>
            {t.label}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-4 gap-2">
        <div className="bg-black/20 rounded-lg p-2.5 text-center border border-white/5">
          <div className="text-[11px] text-slate-500 uppercase">Txns</div>
          <div className="text-white font-bold text-sm mt-0.5">342</div>
        </div>
        <div className="bg-black/20 rounded-lg p-2.5 text-center border border-white/5">
          <div className="text-[11px] text-slate-500 uppercase">Tokens</div>
          <div className="text-white font-bold text-sm mt-0.5">38</div>
        </div>
        <div className="bg-black/20 rounded-lg p-2.5 text-center border border-white/5">
          <div className="text-[11px] text-slate-500 uppercase">Chains</div>
          <div className="text-neon-cyan font-bold text-sm mt-0.5">7</div>
        </div>
        <div className="bg-black/20 rounded-lg p-2.5 text-center border border-white/5">
          <div className="text-[11px] text-slate-500 uppercase">DeFi</div>
          <div className="text-neon-purple font-bold text-sm mt-0.5">8</div>
        </div>
      </div>

      {/* Exchange Connections */}
      <div>
        <h4 className="text-xs text-slate-400 font-medium mb-2 uppercase tracking-wide">Exchange Balances</h4>
        <div className="space-y-1.5">
          {exchanges.map((ex) => (
            <div key={ex.name} className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-black/20 border border-white/5">
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full ${ex.connected ? "bg-accent-success" : "bg-slate-600"}`}></span>
                <span className="text-xs text-white font-medium">{ex.name}</span>
                <span className="text-[11px] font-bold px-1 py-px rounded bg-neon-cyan/10 text-neon-cyan/70">CEX</span>
              </div>
              <span className={`text-xs font-mono ${ex.connected ? "text-white" : "text-slate-600"}`}>{ex.value}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h4 className="text-xs text-slate-400 font-medium mb-2 uppercase tracking-wide">Chain Exposure</h4>
        <div className="h-2 w-full rounded-full bg-slate-800 flex overflow-hidden">
          {chains.map((c) => (
            <div key={c.name} className={`${c.color} h-full`} style={{ width: `${c.pct}%` }}></div>
          ))}
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
          {chains.map((c) => (
            <div key={c.name} className="flex items-center gap-1.5 text-[11px]">
              <span className={`w-2 h-2 rounded-full ${c.color}`}></span>
              <span className="text-slate-400">{c.name}</span>
              <span className="text-white font-bold">{c.pct}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
