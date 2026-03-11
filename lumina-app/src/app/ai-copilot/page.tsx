"use client";

import AppShell from "@/components/DashboardShell";
import NotificationPanel from "@/components/NotificationPanel";
import ConnectWalletButton from "@/components/ConnectWalletModal";
import { useWallet } from "@/context/WalletContext";
import ChatWindow from "@/components/ai-copilot/ChatWindow";
import QuickInsights from "@/components/ai-copilot/QuickInsights";
import MarketPulse from "@/components/ai-copilot/MarketPulse";

function CopilotHeader() {
  const { wallet, setWallet } = useWallet();
  return (
    <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-4">
        <h2 className="text-white text-sm font-bold tracking-tight">AI Copilot</h2>
        <div className="h-5 w-px bg-white/10 mx-2 hidden md:block"></div>
        <div className="items-center gap-2 hidden md:flex">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-neon-cyan opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-neon-cyan"></span>
          </span>
          <span className="text-slate-400 text-xs">
            Powered by <span className="text-neon-cyan font-bold">Lumina AI</span>
          </span>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <NotificationPanel />
        <ConnectWalletButton wallet={wallet} setWallet={setWallet} />
      </div>
    </div>
  );
}

export default function AICopilotPage() {
  return (
    <AppShell header={<CopilotHeader />}>
      <div className="grid grid-cols-12 gap-4 md:gap-6 xl:h-[calc(100vh-160px)]">
        {/* Left: Chat */}
        <div className="col-span-12 xl:col-span-8 h-[500px] sm:h-[600px] xl:h-full">
          <ChatWindow />
        </div>

        {/* Right: Insights + Market Pulse */}
        <div className="col-span-12 xl:col-span-4 flex flex-col gap-4 md:gap-6 xl:h-full overflow-hidden">
          <div className="flex-1 min-h-0 overflow-hidden">
            <div className="h-full overflow-y-auto">
              <QuickInsights />
            </div>
          </div>
          <div className="shrink-0">
            <MarketPulse />
          </div>
        </div>
      </div>
    </AppShell>
  );
}
