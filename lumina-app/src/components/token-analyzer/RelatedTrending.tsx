const tokens = [
  { ticker: "OP", name: "Optimism", category: "L2 Rollup", price: "$1.85", change: "+5.2%", changeColor: "text-accent-success" },
  { ticker: "ARB", name: "Arbitrum", category: "L2 Rollup", price: "$1.12", change: "+3.8%", changeColor: "text-accent-success" },
  { ticker: "LDO", name: "Lido", category: "Liquid Staking", price: "$2.15", change: "-1.2%", changeColor: "text-neon-magenta" },
  { ticker: "RPL", name: "Rocket Pool", category: "Liquid Staking", price: "$28.40", change: "+2.1%", changeColor: "text-accent-success" },
  { ticker: "SSV", name: "SSV Network", category: "DVT", price: "$24.80", change: "+8.4%", changeColor: "text-neon-lime" },
];

export default function RelatedTrending() {
  return (
    <div className="glass-panel rounded-xl p-5 flex flex-col h-[280px]">
      <h4 className="text-white text-sm font-bold mb-4 flex items-center gap-2">
        <span className="material-symbols-outlined text-[16px] text-accent-warning">trending_up</span>
        Related Trending
      </h4>
      <div className="flex flex-col gap-1 overflow-y-auto pr-1">
        {tokens.map((t) => (
          <div key={t.ticker} className="flex items-center justify-between p-2 rounded hover:bg-white/5 cursor-pointer group transition-colors">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-[11px] font-bold text-slate-400 group-hover:text-white transition-colors">
                {t.ticker}
              </div>
              <div>
                <div className="text-white text-sm font-bold group-hover:text-neon-cyan transition-colors">{t.name}</div>
                <div className="text-[11px] text-slate-500">{t.category}</div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-white text-sm font-bold">{t.price}</div>
              <div className={`text-[11px] ${t.changeColor}`}>{t.change}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
