const holders = [
  { label: "Whales (>0.1%)", pct: 42.5, change: "+1.2%", changeColor: "text-neon-cyan", barColor: "bg-neon-purple", icon: "water", iconColor: "text-neon-purple", note: "Top 100 wallets control supply" },
  { label: "Exchanges", pct: 15.8, change: "-0.5%", changeColor: "text-neon-magenta", barColor: "bg-accent-warning", icon: "account_balance", iconColor: "text-accent-warning", note: "Held in hot/cold exchange wallets" },
  { label: "Retail", pct: 41.7, change: "~0.0%", changeColor: "text-slate-400", barColor: "bg-accent-success", icon: "groups", iconColor: "text-accent-success", note: "Distributed among smaller holders" },
];

export default function HolderDistribution() {
  return (
    <div className="glass-panel rounded-xl p-6">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-white text-lg font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-neon-purple text-[20px]">pie_chart</span>
          Holder Distribution
        </h3>
        <div className="flex items-center gap-2 px-3 py-1 bg-white/5 rounded border border-white/10">
          <span className="text-[11px] text-slate-400 uppercase tracking-wide">Gini Coefficient</span>
          <span className="text-sm font-bold text-accent-warning">0.82 (High Risk)</span>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {holders.map((h) => (
          <div key={h.label} className="bg-black/20 rounded-lg p-4 border border-white/5 flex flex-col gap-3 relative overflow-hidden group hover:border-white/10 transition-colors">
            <div className="absolute top-0 right-0 p-2 opacity-10">
              <span className={`material-symbols-outlined text-4xl ${h.iconColor}`}>{h.icon}</span>
            </div>
            <span className="text-slate-400 text-xs font-medium uppercase">{h.label}</span>
            <div className="flex items-end gap-2">
              <span className="text-2xl font-bold text-white">{h.pct}%</span>
              <span className={`text-xs ${h.changeColor} mb-1.5`}>{h.change}</span>
            </div>
            <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
              <div className={`${h.barColor} h-full rounded-full transition-all duration-500`} style={{ width: `${h.pct}%` }}></div>
            </div>
            <div className="text-[11px] text-slate-500 mt-1">{h.note}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
