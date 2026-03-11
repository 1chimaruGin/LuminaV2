const transactions = [
  { type: "Swap", typeIcon: "swap_horiz", typeColor: "text-accent-warning", token: "ETH → USDC", amount: "$12,450", time: "2h ago", chain: "Ethereum", status: "Confirmed", statusColor: "text-accent-success" },
  { type: "Transfer", typeIcon: "send", typeColor: "text-neon-cyan", token: "SOL", amount: "$8,200", time: "5h ago", chain: "Solana", status: "Confirmed", statusColor: "text-accent-success" },
  { type: "Stake", typeIcon: "lock", typeColor: "text-neon-purple", token: "ETH", amount: "$32,000", time: "1d ago", chain: "Ethereum", status: "Confirmed", statusColor: "text-accent-success" },
  { type: "Swap", typeIcon: "swap_horiz", typeColor: "text-accent-warning", token: "USDC → ARB", amount: "$5,000", time: "1d ago", chain: "Arbitrum", status: "Confirmed", statusColor: "text-accent-success" },
  { type: "Buy", typeIcon: "add_circle", typeColor: "text-accent-success", token: "PEPE", amount: "$4,260", time: "2d ago", chain: "Ethereum", status: "Confirmed", statusColor: "text-accent-success" },
  { type: "Claim", typeIcon: "redeem", typeColor: "text-neon-lime", token: "OP", amount: "$1,840", time: "3d ago", chain: "Optimism", status: "Confirmed", statusColor: "text-accent-success" },
  { type: "Swap", typeIcon: "swap_horiz", typeColor: "text-accent-warning", token: "AAVE → ETH", amount: "$6,120", time: "4d ago", chain: "Ethereum", status: "Confirmed", statusColor: "text-accent-success" },
  { type: "Sell", typeIcon: "remove_circle", typeColor: "text-neon-magenta", token: "DOGE", amount: "$2,100", time: "5d ago", chain: "Ethereum", status: "Confirmed", statusColor: "text-accent-success" },
];

export default function TransactionHistory() {
  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03]">
        <h3 className="text-white text-lg font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-accent-warning text-[20px]">receipt_long</span>
          Transaction History
        </h3>
        <span className="text-[11px] text-slate-500">Last 30 days</span>
      </div>
      <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-obsidian-light z-10">
            <tr className="text-[11px] uppercase text-slate-500 border-b border-white/5">
              <th className="px-3 md:px-4 py-3 font-medium">Type</th>
              <th className="px-3 md:px-4 py-3 font-medium hidden sm:table-cell">Token</th>
              <th className="px-3 md:px-4 py-3 font-medium text-right">Amount</th>
              <th className="px-3 md:px-4 py-3 font-medium text-right hidden md:table-cell">Chain</th>
              <th className="px-3 md:px-4 py-3 font-medium text-right">Time</th>
            </tr>
          </thead>
          <tbody className="text-xs divide-y divide-white/5">
            {transactions.map((tx, i) => (
              <tr key={i} className="hover:bg-white/5 transition-colors group cursor-pointer">
                <td className="px-3 md:px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className={`material-symbols-outlined text-[16px] ${tx.typeColor}`}>{tx.typeIcon}</span>
                    <div>
                      <span className="text-white font-medium block">{tx.type}</span>
                      <span className="text-[11px] text-slate-500 sm:hidden">{tx.token}</span>
                    </div>
                  </div>
                </td>
                <td className="px-3 md:px-4 py-3 text-white font-mono hidden sm:table-cell">{tx.token}</td>
                <td className="px-3 md:px-4 py-3 text-right text-white font-bold">{tx.amount}</td>
                <td className="px-3 md:px-4 py-3 text-right hidden md:table-cell">
                  <span className="px-2 py-0.5 rounded bg-white/5 text-slate-300 text-[11px]">{tx.chain}</span>
                </td>
                <td className="px-3 md:px-4 py-3 text-right text-slate-400">{tx.time}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
