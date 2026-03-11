const swaps = [
  { side: "Buy", sideColor: "text-accent-success", amount: "$124.5k", size: "38.2 ETH", time: "1m ago" },
  { side: "Sell", sideColor: "text-neon-magenta", amount: "$542.1k", size: "165.4 ETH", time: "3m ago" },
  { side: "Buy", sideColor: "text-accent-success", amount: "$89.2k", size: "27.1 ETH", time: "5m ago" },
  { side: "Buy", sideColor: "text-accent-success", amount: "$2.1M", size: "642.5 ETH", time: "12m ago" },
  { side: "Sell", sideColor: "text-neon-magenta", amount: "$45.2k", size: "13.8 ETH", time: "14m ago" },
  { side: "Buy", sideColor: "text-accent-success", amount: "$310k", size: "95.2 ETH", time: "18m ago" },
  { side: "Sell", sideColor: "text-neon-magenta", amount: "$1.4M", size: "428.1 ETH", time: "22m ago" },
];

export default function RecentLargeSwaps() {
  return (
    <div className="glass-panel rounded-xl p-0 flex flex-col flex-1 min-h-[300px] overflow-hidden">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03]">
        <h3 className="text-white text-sm font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-accent-warning text-[18px]">swap_horiz</span>
          Recent Large Swaps
        </h3>
        <div className="flex items-center gap-1">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-cyan opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-neon-cyan"></span>
          </span>
          <span className="text-[11px] text-slate-500 ml-1">Live</span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-left border-collapse">
          <tbody className="text-xs divide-y divide-white/5">
            {swaps.map((s, i) => (
              <tr key={i} className="hover:bg-white/5 transition-colors group cursor-pointer">
                <td className="p-3">
                  <span className={`${s.sideColor} font-bold`}>{s.side}</span>
                </td>
                <td className="p-3 text-right">
                  <div className="text-white font-mono">{s.amount}</div>
                  <div className="text-[11px] text-slate-500">{s.size}</div>
                </td>
                <td className="p-3 text-right">
                  <div className="text-slate-400">{s.time}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
