"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";

interface SidebarProps {
  onClose?: () => void;
}

interface NavItem {
  icon: string;
  label: string;
  href: string;
  badge?: string;
  badgeColor?: string;
}

const coreNav: NavItem[] = [
  { icon: "grid_view", label: "Dashboard", href: "/" },
  { icon: "tsunami", label: "Whale Activity", href: "/whale-activity" },
  { icon: "account_balance_wallet", label: "Wallet Analyzer", href: "/wallet-analyzer" },
  { icon: "token", label: "Token Analyzer", href: "/token-analyzer" },
];

const marketsNav: NavItem[] = [
  { icon: "show_chart", label: "Spot Charts", href: "/markets/spot" },
  { icon: "waterfall_chart", label: "Derivatives", href: "/markets/derivatives" },
];

const insightNav: NavItem[] = [
  { icon: "insights", label: "Trading Insight", href: "/insight", badge: "LIVE", badgeColor: "bg-neon-cyan" },
  { icon: "stacked_line_chart", label: "Trading Strategy", href: "/insight/strategy", badge: "NEW", badgeColor: "bg-neon-lime" },
];

const botsNav: NavItem[] = [
  { icon: "precision_manufacturing", label: "Trading Bots", href: "/bots/trading" },
];

function SectionLabel({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-3 pt-3.5 pb-1">
      <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-slate-600">{label}</span>
      <div className="flex-1 h-px bg-white/5"></div>
    </div>
  );
}

function NavLink({
  item,
  isActive,
  onClose,
  compact = false,
}: {
  item: NavItem;
  isActive: boolean;
  onClose?: () => void;
  compact?: boolean;
}) {
  return (
    <Link
      href={item.href}
      onClick={onClose}
      className={`flex items-center gap-2.5 rounded-lg transition-all duration-200 group relative ${
        compact ? "px-2 py-1.5" : "px-2.5 py-[7px]"
      } ${
        isActive
          ? "bg-neon-cyan/8 text-white"
          : "text-slate-400 hover:bg-white/[0.04] hover:text-white"
      }`}
    >
      {/* Active indicator bar */}
      {isActive && (
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-neon-cyan shadow-[0_0_8px_rgba(0,240,255,0.4)]" />
      )}

      <span
        className={`material-symbols-outlined text-[18px] transition-colors duration-200 ${
          isActive ? "text-neon-cyan" : "group-hover:text-neon-cyan/70"
        }`}
      >
        {item.icon}
      </span>

      <span className={`text-[12px] font-medium flex-1 ${isActive ? "text-white" : ""}`}>{item.label}</span>

      {/* Badge */}
      {item.badge && (
        <span
          className={`text-[11px] font-bold px-1.5 py-0.5 rounded-full ${
            item.badge === "LIVE"
              ? `${item.badgeColor} text-white animate-pulse`
              : `${item.badgeColor}/15 text-white/70`
          }`}
        >
          {item.badge}
        </span>
      )}

      {isActive && !item.badge && (
        <span className="w-1.5 h-1.5 rounded-full bg-neon-cyan animate-pulse" />
      )}
    </Link>
  );
}

export default function Sidebar({ onClose }: SidebarProps) {
  const pathname = usePathname();

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <aside className="w-52 flex-shrink-0 flex flex-col border-r border-white/[0.06] bg-[#0a0a0f] h-full relative z-30">
      {/* Logo */}
      <div className="px-4 pt-4 pb-1.5 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="relative">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-neon-cyan/20 to-neon-purple/20 flex items-center justify-center border border-neon-cyan/15 group-hover:border-neon-cyan/30 transition-colors">
              <span className="material-symbols-outlined text-neon-cyan text-base">diamond</span>
            </div>
            <div className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full bg-accent-success border-2 border-[#0a0a0f]" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-white text-[13px] font-bold tracking-wide leading-none">Lumina</h1>
            <p className="text-slate-500 text-[11px] font-medium mt-0.5">Pro Plan</p>
          </div>
        </Link>
        {onClose && (
          <button
            onClick={onClose}
            className="lg:hidden h-8 w-8 rounded-lg hover:bg-white/10 flex items-center justify-center text-slate-400 hover:text-white transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        )}
      </div>

      {/* Scrollable nav */}
      <nav className="flex-1 overflow-y-auto px-2 pb-2 space-y-px sidebar-scroll">
        {/* Analytics */}
        <SectionLabel label="Analytics" />
        {coreNav.map((item) => (
          <NavLink key={item.href} item={item} isActive={isActive(item.href)} onClose={onClose} />
        ))}

        {/* Markets */}
        <SectionLabel label="Markets" />
        {marketsNav.map((item) => (
          <NavLink key={item.href} item={item} isActive={isActive(item.href)} onClose={onClose} />
        ))}

        {/* Trading Insight */}
        <SectionLabel label="Trading Insight" />
        {insightNav.map((item) => (
          <NavLink key={item.href} item={item} isActive={isActive(item.href)} onClose={onClose} />
        ))}

        {/* Bots */}
        <SectionLabel label="Bots" />
        {botsNav.map((item) => (
          <NavLink key={item.href} item={item} isActive={isActive(item.href)} onClose={onClose} />
        ))}

        {/* AI Copilot — special link */}
        <SectionLabel label="Intelligence" />
        <Link
          href="/ai-copilot"
          onClick={onClose}
          className={`flex items-center gap-2.5 px-2.5 py-[7px] rounded-lg transition-all duration-200 group relative ${
            isActive("/ai-copilot")
              ? "bg-gradient-to-r from-neon-cyan/10 to-neon-purple/10 text-white border border-neon-cyan/15"
              : "text-slate-400 hover:bg-white/[0.04] hover:text-white"
          }`}
        >
          {isActive("/ai-copilot") && (
            <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-neon-cyan shadow-[0_0_8px_rgba(0,240,255,0.4)]" />
          )}
          <span
            className={`material-symbols-outlined text-[18px] transition-colors ${
              isActive("/ai-copilot") ? "text-neon-cyan" : "group-hover:text-neon-cyan/70"
            }`}
          >
            smart_toy
          </span>
          <span className="text-[12px] font-medium flex-1">AI Copilot</span>
          <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-neon-purple/20 text-neon-purple border border-neon-purple/20">
            AI
          </span>
        </Link>
      </nav>

      {/* Bottom CTA */}
      <div className="px-2 pb-3 pt-1.5">
        <div className="p-2.5 rounded-lg bg-gradient-to-br from-neon-cyan/[0.06] to-neon-purple/[0.04] border border-white/[0.06] hover:border-neon-cyan/15 transition-all duration-300">
          <div className="flex items-center gap-2 mb-1.5">
            <div className="h-5 w-5 rounded bg-neon-cyan/15 flex items-center justify-center">
              <span className="material-symbols-outlined text-neon-cyan text-[12px]">auto_awesome</span>
            </div>
            <div>
              <p className="text-white text-[11px] font-bold leading-none">Upgrade to Pro+</p>
              <p className="text-slate-500 text-[11px] mt-0.5">Advanced analytics</p>
            </div>
          </div>
          <button className="w-full py-1 rounded-md bg-neon-cyan hover:bg-cyan-400 text-black text-[11px] font-bold transition-all duration-300 shadow-neon-glow cursor-pointer hover:scale-[1.02] active:scale-[0.98]">
            Upgrade
          </button>
        </div>
      </div>
    </aside>
  );
}
