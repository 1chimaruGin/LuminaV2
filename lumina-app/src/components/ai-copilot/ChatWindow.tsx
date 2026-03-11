"use client";

import { useState, useRef, useEffect } from "react";
import { sendChatMessage, type ChatMessage } from "@/lib/api";

interface Message {
  role: "user" | "ai";
  content: string;
  time: string;
}

const suggestions = [
  "What's the market sentiment right now?",
  "Top gainers and losers today",
  "Is BTC overbought?",
  "Funding rate arbitrage opportunities",
];

type AIModel = "grok" | "claude";
const MODEL_META: Record<AIModel, { label: string; color: string; icon: string }> = {
  grok: { label: "Grok", color: "text-neon-cyan", icon: "bolt" },
  claude: { label: "Claude", color: "text-violet-400", icon: "psychology" },
};

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "ai",
      content: "Welcome to Lumina AI Copilot. I have access to real-time market data — prices, funding rates, Fear & Greed index, and more. Ask me anything about the crypto market.",
      time: new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [model, setModel] = useState<AIModel>("grok");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || sending) return;
    const now = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg, time: now }]);
    setSending(true);

    try {
      // Build history for context
      const history: ChatMessage[] = messages
        .filter((m) => m.role === "user" || m.role === "ai")
        .map((m) => ({ role: m.role === "ai" ? "assistant" as const : "user" as const, content: m.content }));

      const res = await sendChatMessage(userMsg, history, model);
      const aiTime = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
      setMessages((prev) => [...prev, { role: "ai", content: res.reply, time: aiTime }]);
    } catch (e) {
      const aiTime = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
      setMessages((prev) => [
        ...prev,
        { role: "ai", content: "Sorry, I couldn't process that request. Please check that the backend is running.", time: aiTime },
      ]);
    }
    setSending(false);
  };

  const meta = MODEL_META[model];

  return (
    <div className="glass-panel rounded-xl flex flex-col h-full overflow-hidden">
      {/* Chat header */}
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-neon-cyan/30 to-neon-purple/30 flex items-center justify-center border border-neon-cyan/20 shadow-neon-glow">
            <span className={`material-symbols-outlined ${meta.color} text-[16px]`}>{meta.icon}</span>
          </div>
          <div>
            <h3 className="text-white text-sm font-bold">Lumina AI</h3>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-success animate-pulse"></span>
              <span className="text-[11px] text-slate-400">Online • {meta.label}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Model selector */}
          <div className="flex bg-white/[0.04] rounded-lg p-0.5 border border-white/[0.06]">
            {(["grok", "claude"] as AIModel[]).map((m) => (
              <button
                key={m}
                onClick={() => setModel(m)}
                className={`px-2 py-1 text-[11px] rounded-md font-bold cursor-pointer transition-all ${model === m ? `${MODEL_META[m].color} bg-white/10 shadow-sm` : "text-slate-500 hover:text-white"}`}
              >
                {MODEL_META[m].label}
              </button>
            ))}
          </div>
          <button className="h-7 w-7 rounded-lg hover:bg-white/5 flex items-center justify-center text-slate-400 hover:text-white transition-colors cursor-pointer">
            <span className="material-symbols-outlined text-[16px]">history</span>
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
            <div
              className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                msg.role === "ai"
                  ? "bg-gradient-to-br from-neon-cyan/30 to-neon-purple/30 border border-neon-cyan/20"
                  : "bg-white/10 border border-white/10"
              }`}
            >
              <span className="material-symbols-outlined text-[14px] text-white">
                {msg.role === "ai" ? "smart_toy" : "person"}
              </span>
            </div>
            <div
              className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "ai"
                  ? "bg-white/5 border border-white/5 text-slate-200"
                  : "bg-neon-cyan/10 border border-neon-cyan/20 text-white"
              }`}
            >
              {msg.content.split("\n").map((line, j) => (
                <p key={j} className={j > 0 ? "mt-1.5" : ""}>
                  {line.split("**").map((segment, k) =>
                    k % 2 === 1 ? (
                      <strong key={k} className="text-white font-bold">
                        {segment}
                      </strong>
                    ) : (
                      <span key={k}>{segment}</span>
                    )
                  )}
                </p>
              ))}
              <div className={`text-[11px] mt-2 ${msg.role === "ai" ? "text-slate-500" : "text-neon-cyan/50"}`}>
                {msg.time}
              </div>
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-neon-cyan/30 to-neon-purple/30 flex items-center justify-center border border-neon-cyan/20 shrink-0">
              <span className="material-symbols-outlined text-[14px] text-white">smart_toy</span>
            </div>
            <div className="bg-white/5 border border-white/5 rounded-xl px-4 py-3 flex items-center gap-2">
              <div className="w-3 h-3 rounded-full border-2 border-neon-cyan/20 border-t-neon-cyan animate-spin" />
              <span className="text-sm text-slate-400">Thinking…</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      <div className="px-4 py-2 border-t border-white/5 flex gap-2 overflow-x-auto shrink-0">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => setInput(s)}
            className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-slate-400 hover:text-white hover:bg-white/10 hover:border-neon-cyan/30 whitespace-nowrap cursor-pointer transition-all"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="p-4 border-t border-white/5 bg-white/[0.02] shrink-0">
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <input
              className="w-full bg-black/30 border border-white/10 text-white text-sm rounded-xl pl-4 pr-12 py-3 focus:ring-1 focus:ring-neon-cyan focus:border-neon-cyan placeholder-slate-600 transition-all outline-none"
              placeholder="Ask about markets, tokens, wallets, or strategies..."
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
            />
            <button
              onClick={handleSend}
              disabled={sending}
              className={`absolute right-2 top-1/2 -translate-y-1/2 h-8 w-8 rounded-lg flex items-center justify-center transition-colors cursor-pointer shadow-neon-glow ${sending ? "bg-slate-600 cursor-not-allowed" : "bg-neon-cyan hover:bg-cyan-400"}`}
            >
              <span className="material-symbols-outlined text-black text-[18px]">send</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
