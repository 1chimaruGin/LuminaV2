"use client";

import { useState, useEffect, useCallback } from "react";
import { fetchQuickInsights, type QuickInsight } from "@/lib/api";

export default function QuickInsights() {
  const [insights, setInsights] = useState<QuickInsight[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetchQuickInsights();
      setInsights(res.data || []);
      setLastUpdate(new Date());
    } catch { /* keep existing */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 60_000);
    return () => clearInterval(iv);
  }, [load]);

  return (
    <div className="glass-panel rounded-xl flex flex-col overflow-hidden">
      <div className="p-4 border-b border-white/5 flex justify-between items-center bg-white/[0.03] shrink-0">
        <h3 className="text-white text-sm font-bold flex items-center gap-2">
          <span className="material-symbols-outlined text-neon-lime text-[18px]">auto_awesome</span>
          AI Quick Insights
        </h3>
        <div className="flex items-center gap-1">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-lime opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-neon-lime"></span>
          </span>
          <span className="text-[11px] text-slate-500 ml-1">
            {lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "Live Feed"}
          </span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-white/5">
        {loading ? (
          <div className="p-8 flex items-center justify-center gap-2">
            <div className="w-4 h-4 rounded-full border-2 border-neon-lime/20 border-t-neon-lime animate-spin" />
            <span className="text-[11px] text-slate-600">Loading insights…</span>
          </div>
        ) : insights.length === 0 ? (
          <div className="p-8 text-center text-[11px] text-slate-600">No insights available yet</div>
        ) : (
          insights.map((ins, i) => (
            <div key={i} className="p-4 hover:bg-white/[0.03] transition-colors cursor-pointer group">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center shrink-0 group-hover:bg-white/10 transition-colors">
                  <span className={`material-symbols-outlined text-[16px] ${ins.iconColor}`}>{ins.icon}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-white text-xs font-bold group-hover:text-neon-cyan transition-colors">{ins.title}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[11px] font-bold border ${ins.tagColor}`}>{ins.tag}</span>
                  </div>
                  <p className="text-slate-400 text-[11px] leading-relaxed line-clamp-2">{ins.desc}</p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
