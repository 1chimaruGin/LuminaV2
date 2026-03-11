export default function TokenStatCards() {
  return (
    <div className="col-span-12 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      {/* Price */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-neon-cyan/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up">
        <div className="flex justify-between items-start mb-2 relative z-10">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">Price (USD)</p>
            <h3 className="text-2xl font-bold text-white mt-1">$3,245.80</h3>
          </div>
          <span className="flex items-center text-neon-cyan text-xs font-bold bg-neon-cyan/10 px-1.5 py-0.5 rounded border border-neon-cyan/20">+2.45%</span>
        </div>
        <div className="h-10 w-full mt-2 relative">
          <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 30">
            <path className="sparkline-fill" d="M0,30 L0,20 L10,18 L20,22 L30,15 L40,18 L50,12 L60,16 L70,8 L80,12 L90,5 L100,10 L100,30 Z" fill="rgba(0, 240, 255, 0.2)" />
            <path className="sparkline-path" d="M0,20 L10,18 L20,22 L30,15 L40,18 L50,12 L60,16 L70,8 L80,12 L90,5 L100,10" stroke="#00f0ff" />
          </svg>
        </div>
      </div>

      {/* 24h Volume */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-neon-magenta/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up" style={{ animationDelay: "0.05s" }}>
        <div className="flex justify-between items-start mb-2 relative z-10">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">24h Volume</p>
            <h3 className="text-2xl font-bold text-white mt-1">$12.8B</h3>
          </div>
          <span className="flex items-center text-neon-magenta text-xs font-bold bg-neon-magenta/10 px-1.5 py-0.5 rounded border border-neon-magenta/20">-5.12%</span>
        </div>
        <div className="h-10 w-full mt-2 relative">
          <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 30">
            <path className="sparkline-fill" d="M0,30 L0,10 L10,12 L20,8 L30,15 L40,10 L50,20 L60,18 L70,25 L80,22 L90,28 L100,24 L100,30 Z" fill="rgba(255, 0, 255, 0.2)" />
            <path className="sparkline-path" d="M0,10 L10,12 L20,8 L30,15 L40,10 L50,20 L60,18 L70,25 L80,22 L90,28 L100,24" stroke="#ff00ff" />
          </svg>
        </div>
      </div>

      {/* Market Cap */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-neon-purple/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up" style={{ animationDelay: "0.1s" }}>
        <div className="flex justify-between items-start mb-2 relative z-10">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">Market Cap</p>
            <h3 className="text-2xl font-bold text-white mt-1">$384.2B</h3>
          </div>
          <span className="flex items-center text-slate-300 text-xs font-bold bg-white/5 px-1.5 py-0.5 rounded border border-white/10">Rank #2</span>
        </div>
        <div className="h-10 w-full mt-2 relative">
          <svg className="w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 30">
            <path className="sparkline-fill" d="M0,30 L0,25 L10,24 L20,20 L30,22 L40,18 L50,20 L60,15 L70,12 L80,10 L90,8 L100,5 L100,30 Z" fill="rgba(188, 19, 254, 0.2)" />
            <path className="sparkline-path" d="M0,25 L10,24 L20,20 L30,22 L40,18 L50,20 L60,15 L70,12 L80,10 L90,8 L100,5" stroke="#bc13fe" />
          </svg>
        </div>
      </div>

      {/* Social Sentiment */}
      <div className="glass-panel rounded-xl p-5 relative overflow-hidden group hover:border-neon-lime/30 hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up" style={{ animationDelay: "0.15s" }}>
        <div className="flex justify-between items-start mb-2 relative z-10">
          <div>
            <p className="text-slate-400 text-xs font-medium uppercase tracking-wide">Social Sentiment</p>
            <h3 className="text-2xl font-bold text-neon-lime mt-1 text-glow-lime">78/100</h3>
          </div>
          <span className="material-symbols-outlined text-neon-lime animate-pulse">campaign</span>
        </div>
        <div className="h-1.5 w-full bg-slate-800 rounded-full mt-6 overflow-hidden">
          <div className="h-full bg-gradient-to-r from-neon-cyan to-neon-lime w-[78%] rounded-full" style={{ boxShadow: "0 0 10px rgba(204,255,0,0.5)" }}></div>
        </div>
        <div className="flex justify-between text-[11px] text-slate-500 mt-1">
          <span>Bearish</span>
          <span>Bullish</span>
        </div>
      </div>
    </div>
  );
}
