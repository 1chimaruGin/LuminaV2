export default function WalletStatCards() {
  return (
    <div className="col-span-12 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      {/* Total Value */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-neon-cyan/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up">
        <div className="flex justify-between items-start mb-2">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">Cross-Chain Value</p>
            <h3 className="text-2xl font-bold text-white mt-1">$248,420</h3>
          </div>
          <span className="flex items-center text-accent-success text-xs font-bold bg-accent-success/10 px-1.5 py-0.5 rounded border border-accent-success/20">+12.4%</span>
        </div>
        <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500">
          <span>On-chain: <span className="text-white font-mono">$182K</span></span>
          <span className="w-px h-3 bg-white/10"></span>
          <span>CEX: <span className="text-neon-cyan font-mono">$66K</span></span>
        </div>
        <div className="h-8 w-full mt-2 relative">
          <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 30">
            <path className="sparkline-fill" d="M0,30 L0,22 L10,20 L20,18 L30,20 L40,15 L50,12 L60,14 L70,8 L80,10 L90,6 L100,4 L100,30 Z" fill="rgba(0, 240, 255, 0.15)" />
            <path className="sparkline-path" d="M0,22 L10,20 L20,18 L30,20 L40,15 L50,12 L60,14 L70,8 L80,10 L90,6 L100,4" stroke="#00f0ff" />
          </svg>
        </div>
      </div>

      {/* Unrealized PnL */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-accent-success/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up" style={{ animationDelay: "0.05s" }}>
        <div className="flex justify-between items-start mb-2">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">Unrealized PnL</p>
            <h3 className="text-2xl font-bold text-accent-success mt-1">+$34,218</h3>
          </div>
          <span className="material-symbols-outlined text-accent-success">trending_up</span>
        </div>
        <div className="flex items-center gap-4 mt-4 text-xs">
          <div>
            <span className="text-slate-500">Win Rate</span>
            <span className="text-white font-bold ml-1.5">68%</span>
          </div>
          <div className="w-px h-3 bg-white/10"></div>
          <div>
            <span className="text-slate-500">Across</span>
            <span className="text-neon-cyan font-bold ml-1.5">6 chains</span>
          </div>
        </div>
      </div>

      {/* Active Positions */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-neon-purple/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up" style={{ animationDelay: "0.1s" }}>
        <div className="flex justify-between items-start mb-2">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">Active Positions</p>
            <h3 className="text-2xl font-bold text-white mt-1">38</h3>
          </div>
          <span className="material-symbols-outlined text-neon-purple">layers</span>
        </div>
        <div className="flex items-center gap-3 mt-4 text-xs">
          <span className="text-accent-success">22 profit</span>
          <span className="w-px h-3 bg-white/10"></span>
          <span className="text-accent-error">8 loss</span>
          <span className="w-px h-3 bg-white/10"></span>
          <span className="text-neon-purple">6 DeFi LP</span>
          <span className="w-px h-3 bg-white/10"></span>
          <span className="text-slate-400">2 staked</span>
        </div>
      </div>

      {/* Wallet Health */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-neon-lime/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up" style={{ animationDelay: "0.15s" }}>
        <div className="flex justify-between items-start mb-2">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">Wallet Health</p>
            <h3 className="text-2xl font-bold text-neon-lime mt-1 text-glow-lime">A+</h3>
          </div>
          <span className="material-symbols-outlined text-neon-lime animate-pulse">shield</span>
        </div>
        <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-500">
          <span>DeFi exposure: <span className="text-white font-mono">$42K</span></span>
          <span className="w-px h-3 bg-white/10"></span>
          <span>Protocols: <span className="text-neon-purple font-mono">8</span></span>
        </div>
        <div className="h-1.5 w-full bg-slate-800 rounded-full mt-3 overflow-hidden">
          <div className="h-full bg-gradient-to-r from-neon-cyan to-neon-lime w-[92%] rounded-full" style={{ boxShadow: "0 0 10px rgba(204,255,0,0.5)" }}></div>
        </div>
        <div className="flex justify-between text-[11px] text-slate-500 mt-1">
          <span>Risk</span>
          <span>92/100</span>
        </div>
      </div>
    </div>
  );
}
