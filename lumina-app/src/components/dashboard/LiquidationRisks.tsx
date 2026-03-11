const positions = [
  {
    label: "ETH Short",
    leverage: "10x",
    liqPrice: "$1,920.50",
    currentPrice: "$1,854",
    distance: "3.5%",
    distanceColor: "text-accent-warning",
    barWidth: 80,
    liqMarkerLeft: "85%",
    gradient: "from-accent-success to-accent-warning",
    btnStyle: "bg-accent-error/10 hover:bg-accent-error/20 text-accent-error border-accent-error/30",
    isUrgent: true,
  },
  {
    label: "SOL Long",
    leverage: "5x",
    liqPrice: "$28.40",
    currentPrice: "$32.40",
    distance: "12%",
    distanceColor: "text-accent-success",
    barWidth: 100,
    barMarginLeft: "35%",
    liqMarkerLeft: "20%",
    gradient: "from-accent-warning to-accent-success",
    btnStyle: "bg-white/5 hover:bg-white/10 text-slate-300 border-white/10",
    isUrgent: false,
  },
];

export default function LiquidationRisks() {
  return (
    <div className="glass-panel rounded-xl p-6 flex-1 flex flex-col relative overflow-hidden">
      <div className="absolute -right-10 -top-10 w-40 h-40 bg-accent-error/10 rounded-full blur-3xl pointer-events-none"></div>
      <div className="flex items-center justify-between mb-4 relative z-10">
        <h3 className="text-white text-lg font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-accent-error text-[20px] animate-pulse">warning</span>
          Liquidation Risks
        </h3>
        <span className="text-xs text-slate-400">Near Levels</span>
      </div>
      <div className="space-y-6 relative z-10 flex-1">
        {positions.map((p, i) => (
          <div
            key={i}
            className={`group bg-white/5 p-3 rounded-lg border border-white/5 transition-colors ${
              p.isUrgent ? "hover:border-accent-error/30" : "hover:border-accent-success/30"
            }`}
          >
            <div className="flex justify-between text-xs mb-1.5">
              <span className="text-white font-medium flex items-center gap-1">
                {p.label}{" "}
                <span className="text-slate-500 font-mono text-[11px] bg-black/30 px-1 rounded">{p.leverage}</span>
              </span>
              <span className={`font-bold ${p.isUrgent ? "text-accent-error" : "text-accent-error"}`} style={p.isUrgent ? { textShadow: "0 0 10px rgba(255,51,51,0.5)" } : {}}>
                Liq: {p.liqPrice}
              </span>
            </div>
            <div className="relative w-full h-2 bg-slate-800 rounded-full overflow-hidden mb-3">
              <div
                className="absolute top-0 bottom-0 w-0.5 bg-accent-error z-20"
                style={{ left: p.liqMarkerLeft, boxShadow: "0 0 5px #ff3333" }}
              ></div>
              <div
                className={`bg-gradient-to-r ${p.gradient} h-full rounded-full`}
                style={{
                  width: `${p.barWidth}%`,
                  marginLeft: p.barMarginLeft || "0",
                }}
              ></div>
            </div>
            <div className="flex justify-between items-center mb-2 text-[11px] text-slate-500">
              {p.isUrgent ? (
                <>
                  <span>Current: {p.currentPrice}</span>
                  <span className={`${p.distanceColor} font-bold`}>{p.distance} Away</span>
                </>
              ) : (
                <>
                  <span className={`${p.distanceColor} font-bold`}>{p.distance} Away</span>
                  <span>Current: {p.currentPrice}</span>
                </>
              )}
            </div>
            <button
              className={`w-full py-1.5 border text-[11px] font-bold rounded transition-colors flex items-center justify-center gap-1 cursor-pointer ${p.btnStyle}`}
            >
              <span className="material-symbols-outlined text-[12px]">{p.isUrgent ? "add_card" : "settings"}</span>
              Manage Margin
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
