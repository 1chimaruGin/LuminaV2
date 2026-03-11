const metrics = [
  { label: "Concentration Risk", value: "Medium", valueColor: "text-accent-warning", desc: "55% in single asset (ETH)", icon: "warning", pct: 55 },
  { label: "Liquidity Risk", value: "Low", valueColor: "text-accent-success", desc: "92% in high-liquidity tokens", icon: "water_drop", pct: 92 },
  { label: "Smart Contract Risk", value: "Low", valueColor: "text-accent-success", desc: "All tokens audited", icon: "security", pct: 88 },
  { label: "Volatility Exposure", value: "High", valueColor: "text-accent-error", desc: "5% in meme tokens", icon: "bolt", pct: 35 },
];

export default function RiskMetrics() {
  return (
    <div className="glass-panel rounded-xl p-5 flex flex-col gap-4">
      <h3 className="text-white text-sm font-bold flex items-center gap-2">
        <span className="material-symbols-outlined text-accent-warning text-[18px]">monitoring</span>
        Risk Assessment
      </h3>
      <div className="space-y-3">
        {metrics.map((m) => (
          <div key={m.label} className="bg-black/20 rounded-lg p-3 border border-white/5 hover:border-white/10 transition-colors">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-slate-400 text-[14px]">{m.icon}</span>
                <span className="text-xs text-slate-300">{m.label}</span>
              </div>
              <span className={`text-xs font-bold ${m.valueColor}`}>{m.value}</span>
            </div>
            <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden mb-1.5">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  m.pct >= 80 ? "bg-accent-success" : m.pct >= 50 ? "bg-accent-warning" : "bg-accent-error"
                }`}
                style={{ width: `${m.pct}%` }}
              ></div>
            </div>
            <div className="text-[11px] text-slate-500">{m.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
