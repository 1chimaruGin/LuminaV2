const chains = [
  { ticker: "ETH", name: "Ethereum", pct: 65, value: "$161,473", color: "bg-indigo-500", tickerBg: "bg-indigo-900/30", tickerBorder: "border-indigo-500/30", tickerText: "text-indigo-300" },
  { ticker: "SOL", name: "Solana", pct: 25, value: "$62,105", color: "bg-purple-500", tickerBg: "bg-purple-900/30", tickerBorder: "border-purple-500/30", tickerText: "text-purple-300" },
  { ticker: "ARB", name: "Arbitrum", pct: 10, value: "$24,842", color: "bg-blue-400", tickerBg: "bg-blue-900/30", tickerBorder: "border-blue-500/30", tickerText: "text-blue-300" },
];

export default function ChainExposure() {
  return (
    <div className="glass-panel rounded-xl p-5 flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <h4 className="text-white text-sm font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-[18px] text-neon-cyan">hub</span>
          Chain Exposure
        </h4>
        <button className="text-[11px] text-neon-cyan hover:underline cursor-pointer">Rebalance</button>
      </div>
      <div className="flex-1 flex flex-col justify-center gap-4">
        {chains.map((c) => (
          <div key={c.ticker} className="flex items-center gap-3 group">
            <div className={`w-8 h-8 rounded-lg ${c.tickerBg} flex items-center justify-center shrink-0 border ${c.tickerBorder}`}>
              <span className={`text-xs font-bold ${c.tickerText}`}>{c.ticker}</span>
            </div>
            <div className="flex-1">
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-300">{c.name}</span>
                <span className="text-white font-mono">{c.pct}%</span>
              </div>
              <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                <div className={`h-full ${c.color} group-hover:brightness-125 transition-all rounded-full`} style={{ width: `${c.pct}%` }}></div>
              </div>
            </div>
            <div className="text-right w-20">
              <span className="block text-xs font-bold text-white">{c.value}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
