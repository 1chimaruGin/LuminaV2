const bars = [
  { label: "1H", buy: 60, sell: 40 },
  { label: "4H", buy: 75, sell: 30 },
  { label: "12H", buy: 45, sell: 55 },
  { label: "24H", buy: 80, sell: 20, highlight: true },
];

export default function SmartMoneyPressure() {
  return (
    <div className="glass-panel rounded-xl p-5 flex flex-col h-[280px]">
      <h4 className="text-white text-sm font-bold mb-4 flex items-center gap-2">
        <span className="material-symbols-outlined text-[16px] text-neon-cyan">bar_chart</span>
        Smart Money Pressure
      </h4>
      <div className="flex items-center gap-3 mb-3 text-[11px]">
        <span className="flex items-center gap-1 text-slate-400">
          <span className="w-2.5 h-2.5 rounded-sm bg-neon-cyan/80"></span> Buy
        </span>
        <span className="flex items-center gap-1 text-slate-400">
          <span className="w-2.5 h-2.5 rounded-sm bg-neon-magenta/80"></span> Sell
        </span>
      </div>
      <div className="flex-1 flex items-end justify-between px-2 gap-3">
        {bars.map((bar) => (
          <div key={bar.label} className="flex flex-col items-center gap-1.5 w-full h-full justify-end group">
            <div className="w-full flex gap-1 h-[80%] items-end">
              <div
                className={`w-1/2 bg-neon-cyan/80 rounded-t-sm hover:bg-neon-cyan transition-colors ${bar.highlight ? "shadow-neon-glow" : ""}`}
                style={{ height: `${bar.buy}%` }}
                title="Buy Volume"
              ></div>
              <div
                className="w-1/2 bg-neon-magenta/80 rounded-t-sm hover:bg-neon-magenta transition-colors"
                style={{ height: `${bar.sell}%` }}
                title="Sell Volume"
              ></div>
            </div>
            <span className={`text-[11px] ${bar.highlight ? "text-white font-bold" : "text-slate-500"}`}>
              {bar.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
