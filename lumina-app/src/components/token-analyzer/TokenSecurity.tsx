const checks = [
  { icon: "check_circle", label: "Honeypot Check", value: "PASSED", valueColor: "text-accent-success" },
  { icon: "lock", label: "Liquidity Lock", value: "12 MONTHS", valueColor: "text-accent-success" },
  { icon: "description", label: "Contract Audit", value: "Certik", valueColor: "text-white", underline: true },
  { icon: "verified", label: "Proxy Contract", value: "NO", valueColor: "text-accent-success" },
  { icon: "shield", label: "Mint Function", value: "DISABLED", valueColor: "text-accent-success" },
];

export default function TokenSecurity() {
  return (
    <div className="glass-panel rounded-xl p-5 relative overflow-hidden">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-white text-sm font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-accent-success text-[18px]">security</span>
          Token Security
        </h3>
        <span className="bg-accent-success/10 text-accent-success text-[11px] font-bold px-2 py-0.5 rounded border border-accent-success/20">
          AUDITED
        </span>
      </div>
      <div className="space-y-2">
        {checks.map((c) => (
          <div key={c.label} className="flex items-center justify-between p-2 bg-black/20 rounded border border-white/5 hover:border-white/10 transition-colors">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-slate-400 text-[16px]">{c.icon}</span>
              <span className="text-slate-300 text-xs">{c.label}</span>
            </div>
            <span className={`text-xs font-bold ${c.valueColor} ${c.underline ? "underline cursor-pointer decoration-slate-600" : ""}`}>
              {c.value}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-4 pt-3 border-t border-white/5">
        <div className="flex justify-between items-center text-xs mb-1">
          <span className="text-slate-500">Security Score</span>
          <span className="text-white font-bold">92/100</span>
        </div>
        <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
          <div className="bg-gradient-to-r from-accent-success to-neon-cyan h-full w-[92%] rounded-full" style={{ boxShadow: "0 0 8px rgba(11,218,94,0.5)" }}></div>
        </div>
      </div>
    </div>
  );
}
