const posts = [
  { author: "@CryptoWhale", time: "2m ago", text: "Just loaded up more $ETH bags. The accumulation phase on the 4H chart looks pristine. 🚀", borderColor: "border-neon-cyan" },
  { author: "@DefiLlama", time: "15m ago", text: "Protocol revenue for Ethereum L2s reached a new ATH yesterday.", borderColor: "border-slate-700" },
  { author: "@OnChainWizard", time: "32m ago", text: "Smart money wallets accumulated 12k ETH in the last 4 hours. Bullish divergence forming.", borderColor: "border-accent-success" },
  { author: "@TokenTerminal", time: "1h ago", text: "ETH staking yields now at 4.2% APR — highest since the Merge.", borderColor: "border-neon-purple" },
];

export default function SocialPulse() {
  return (
    <div className="glass-panel rounded-xl p-5 flex flex-col relative overflow-hidden">
      <h3 className="text-white text-sm font-bold mb-4 flex items-center gap-2">
        <span className="material-symbols-outlined text-neon-cyan text-[18px]">hub</span>
        Social Pulse
      </h3>
      <div className="flex gap-3 mb-4">
        <div className="flex-1 bg-white/5 rounded-lg p-3 text-center hover:bg-white/10 transition-colors cursor-pointer border border-transparent hover:border-white/10">
          <span className="block text-slate-400 text-[11px] uppercase">Twitter/X</span>
          <span className="block text-white font-bold text-lg mt-1">24k</span>
          <span className="text-accent-success text-[11px] font-bold">↑ High</span>
        </div>
        <div className="flex-1 bg-white/5 rounded-lg p-3 text-center hover:bg-white/10 transition-colors cursor-pointer border border-transparent hover:border-white/10">
          <span className="block text-slate-400 text-[11px] uppercase">Telegram</span>
          <span className="block text-white font-bold text-lg mt-1">8.2k</span>
          <span className="text-slate-400 text-[11px]">→ Normal</span>
        </div>
        <div className="flex-1 bg-white/5 rounded-lg p-3 text-center hover:bg-white/10 transition-colors cursor-pointer border border-transparent hover:border-white/10">
          <span className="block text-slate-400 text-[11px] uppercase">Discord</span>
          <span className="block text-white font-bold text-lg mt-1">15k</span>
          <span className="text-neon-cyan text-[11px] font-bold">↑ Rising</span>
        </div>
      </div>
      <div className="space-y-3 flex-1 overflow-y-auto max-h-[200px] pr-1">
        {posts.map((p, i) => (
          <div key={i} className={`text-xs p-2.5 rounded bg-black/20 border-l-2 ${p.borderColor} hover:bg-black/30 transition-colors`}>
            <div className="flex justify-between text-[11px] text-slate-500 mb-1">
              <span className="font-medium">{p.author}</span>
              <span>{p.time}</span>
            </div>
            <p className="text-slate-300 line-clamp-2 leading-relaxed">{p.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
