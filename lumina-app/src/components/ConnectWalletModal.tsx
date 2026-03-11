"use client";

import { useState, useRef, useEffect } from "react";
import type { WalletState } from "@/context/WalletContext";

/* ── Chain ID → name mapping ── */
const CHAIN_NAMES: Record<string, string> = {
  "0x1": "Ethereum", "0x38": "BSC", "0x89": "Polygon", "0xa": "Optimism",
  "0xa4b1": "Arbitrum", "0x2105": "Base", "0xa86a": "Avalanche",
  "0xe708": "Linea", "0x64": "Gnosis",
};

const shortAddr = (addr: string) =>
  addr.length > 12 ? addr.slice(0, 6) + "…" + addr.slice(-4) : addr;

/* ── Wallet providers config ── */
interface WalletProvider {
  name: string;
  icon: string;
  type: "evm" | "solana";
  detect: () => boolean;
  installUrl: string;
}

const PROVIDERS: WalletProvider[] = [
  {
    name: "MetaMask", icon: "🦊", type: "evm",
    detect: () => typeof window !== "undefined" && !!(window as any).ethereum?.isMetaMask,
    installUrl: "https://metamask.io/download/",
  },
  {
    name: "Phantom", icon: "👻", type: "solana",
    detect: () => typeof window !== "undefined" && !!(window as any).solana?.isPhantom,
    installUrl: "https://phantom.app/download",
  },
  {
    name: "Rabby", icon: "🐰", type: "evm",
    detect: () => typeof window !== "undefined" && !!(window as any).ethereum?.isRabby,
    installUrl: "https://rabby.io/",
  },
  {
    name: "Coinbase Wallet", icon: "🔵", type: "evm",
    detect: () => typeof window !== "undefined" && !!(window as any).ethereum?.isCoinbaseWallet,
    installUrl: "https://www.coinbase.com/wallet",
  },
  {
    name: "OKX Wallet", icon: "⚫", type: "evm",
    detect: () => typeof window !== "undefined" && !!(window as any).okxwallet,
    installUrl: "https://www.okx.com/web3",
  },
];

/* ── EVM helpers ── */
async function connectEVM(providerName: string): Promise<{ address: string; chain: string; balance: string }> {
  let eth: any;

  if (providerName === "OKX Wallet") {
    eth = (window as any).okxwallet;
  } else {
    eth = (window as any).ethereum;

    // If multiple providers injected, try to find the right one
    if (eth?.providers?.length) {
      const match = eth.providers.find((p: any) => {
        if (providerName === "MetaMask") return p.isMetaMask && !p.isRabby;
        if (providerName === "Rabby") return p.isRabby;
        if (providerName === "Coinbase Wallet") return p.isCoinbaseWallet;
        return false;
      });
      if (match) eth = match;
    }
  }

  if (!eth) throw new Error(`${providerName} not found. Please install it.`);

  // Request accounts (triggers popup)
  const accounts: string[] = await eth.request({ method: "eth_requestAccounts" });
  if (!accounts.length) throw new Error("No accounts returned");

  const address = accounts[0];

  // Get chain ID
  const chainId: string = await eth.request({ method: "eth_chainId" });
  const chain = CHAIN_NAMES[chainId] || `Chain ${parseInt(chainId, 16)}`;

  // Get balance
  const rawBal: string = await eth.request({ method: "eth_getBalance", params: [address, "latest"] });
  const ethBal = parseInt(rawBal, 16) / 1e18;
  const balance = ethBal >= 0.001 ? `${ethBal.toFixed(4)} ETH` : `${ethBal.toFixed(6)} ETH`;

  return { address, chain, balance };
}

/* ── Solana helpers ── */
async function connectSolana(): Promise<{ address: string; chain: string; balance: string }> {
  const sol = (window as any).solana;
  if (!sol?.isPhantom) throw new Error("Phantom not found. Please install it.");

  const resp = await sol.connect();
  const address = resp.publicKey.toString();

  // Fetch SOL balance via public RPC
  let balance = "—";
  try {
    const rpcResp = await fetch("https://api.mainnet-beta.solana.com", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "getBalance", params: [address] }),
    });
    const data = await rpcResp.json();
    const lamports = data?.result?.value || 0;
    const solBal = lamports / 1e9;
    balance = `${solBal.toFixed(4)} SOL`;
  } catch { /* silent — balance just shows "—" */ }

  return { address, chain: "Solana", balance };
}

/* ── Props ── */
interface Props {
  wallet: WalletState;
  setWallet: (w: WalletState) => void;
}

export default function ConnectWalletButton({ wallet, setWallet }: Props) {
  const [open, setOpen] = useState(false);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
        setError(null);
      }
    };
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const handleConnect = async (provider: WalletProvider) => {
    setConnecting(provider.name);
    setError(null);

    // If wallet not installed, open install page
    if (!provider.detect()) {
      window.open(provider.installUrl, "_blank", "noopener,noreferrer");
      setConnecting(null);
      setError(`${provider.name} not detected. Install it and refresh.`);
      return;
    }

    try {
      let result: { address: string; chain: string; balance: string };
      if (provider.type === "solana") {
        result = await connectSolana();
      } else {
        result = await connectEVM(provider.name);
      }

      setWallet({
        connected: true,
        address: result.address,
        chain: result.chain,
        balance: result.balance,
        provider: provider.name,
      });
      setOpen(false);
    } catch (e: any) {
      const msg = e?.message || "Connection failed";
      // User rejected = not an error to show persistently
      if (msg.includes("User rejected") || msg.includes("user rejected")) {
        setError(null);
      } else {
        setError(msg.length > 80 ? msg.slice(0, 80) + "…" : msg);
      }
    }
    setConnecting(null);
  };

  const handleDisconnect = () => {
    // Disconnect Phantom if applicable
    if (wallet.provider === "Phantom") {
      try { (window as any).solana?.disconnect(); } catch {}
    }
    setWallet({ connected: false, address: "", chain: "", balance: "" });
    try { localStorage.removeItem("lumina_wallet"); } catch {}
    setOpen(false);
  };

  const handleCopy = () => {
    navigator.clipboard?.writeText(wallet.address);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  /* ── Connected state ── */
  if (wallet.connected) {
    return (
      <div className="relative" ref={panelRef}>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-2 px-3 py-1.5 bg-white/5 border border-white/10 hover:border-neon-cyan/30 rounded-lg transition-all cursor-pointer"
        >
          <div className="w-2 h-2 rounded-full bg-accent-success" />
          <span className="text-xs font-medium text-slate-300 font-mono hidden sm:inline">{shortAddr(wallet.address)}</span>
          <span className="material-symbols-outlined text-[14px] text-slate-400">expand_more</span>
        </button>

        {open && (
          <div className="absolute right-0 top-11 w-72 glass-panel rounded-xl shadow-2xl z-50 border border-white/10 overflow-hidden animate-fade-in-up">
            <div className="p-4 border-b border-white/5 bg-white/[0.03]">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-full bg-gradient-to-br from-neon-cyan/20 to-neon-purple/20 flex items-center justify-center border border-neon-cyan/15">
                  <span className="material-symbols-outlined text-neon-cyan text-[20px]">account_balance_wallet</span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-white text-xs font-bold font-mono truncate">{shortAddr(wallet.address)}</div>
                  <div className="text-[11px] text-slate-500 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-accent-success" />
                    {wallet.chain} · {wallet.provider}
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Balance</span>
                <span className="text-white font-bold font-mono">{wallet.balance}</span>
              </div>
            </div>
            <div className="p-2">
              <button
                onClick={handleCopy}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors cursor-pointer"
              >
                <span className="material-symbols-outlined text-[14px]">{copied ? "check" : "content_copy"}</span>
                {copied ? "Copied!" : "Copy Address"}
              </button>
              {wallet.chain !== "Solana" && (
                <a
                  href={`https://etherscan.io/address/${wallet.address}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[14px]">open_in_new</span>
                  View on Explorer
                </a>
              )}
              {wallet.chain === "Solana" && (
                <a
                  href={`https://solscan.io/account/${wallet.address}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[14px]">open_in_new</span>
                  View on Solscan
                </a>
              )}
              <button
                onClick={handleDisconnect}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-accent-error hover:bg-accent-error/10 transition-colors cursor-pointer"
              >
                <span className="material-symbols-outlined text-[14px]">logout</span>
                Disconnect
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  /* ── Disconnected state ── */
  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => { setOpen((o) => !o); setError(null); }}
        className="flex items-center gap-2 px-3 sm:px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-white text-sm font-bold rounded-lg transition-colors cursor-pointer"
      >
        <span className="material-symbols-outlined text-[18px]">account_balance_wallet</span>
        <span className="hidden sm:inline">Connect</span>
      </button>

      {open && (
        <div className="absolute right-0 top-12 w-80 glass-panel rounded-xl shadow-2xl z-50 border border-white/10 overflow-hidden animate-fade-in-up">
          <div className="p-4 border-b border-white/5 bg-white/[0.03]">
            <h3 className="text-white text-sm font-bold">Connect Wallet</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">Select a wallet provider to connect</p>
          </div>

          {error && (
            <div className="mx-3 mt-3 px-3 py-2 rounded-lg bg-accent-error/10 border border-accent-error/20 flex items-start gap-2">
              <span className="material-symbols-outlined text-accent-error text-[14px] mt-0.5">error</span>
              <span className="text-[11px] text-accent-error leading-relaxed">{error}</span>
            </div>
          )}

          <div className="p-2 space-y-0.5">
            {PROVIDERS.map((p) => {
              const installed = p.detect();
              return (
                <button
                  key={p.name}
                  onClick={() => handleConnect(p)}
                  disabled={connecting !== null}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-all cursor-pointer group disabled:opacity-50"
                >
                  <span className="text-xl">{p.icon}</span>
                  <div className="flex-1 text-left">
                    <div className="text-white text-xs font-bold group-hover:text-neon-cyan transition-colors flex items-center gap-1.5">
                      {p.name}
                      {installed && <span className="w-1.5 h-1.5 rounded-full bg-accent-success" />}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {installed ? (p.type === "solana" ? "Solana" : "EVM Chains") : "Not installed"}
                    </div>
                  </div>
                  {connecting === p.name ? (
                    <span className="material-symbols-outlined text-[16px] text-neon-cyan animate-spin">progress_activity</span>
                  ) : (
                    <span className="material-symbols-outlined text-[16px] text-slate-600 group-hover:text-slate-400 transition-colors">
                      {installed ? "chevron_right" : "download"}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <div className="px-4 py-3 border-t border-white/5 bg-white/[0.02]">
            <p className="text-[11px] text-slate-600 text-center">By connecting, you agree to our Terms of Service</p>
          </div>
        </div>
      )}
    </div>
  );
}
