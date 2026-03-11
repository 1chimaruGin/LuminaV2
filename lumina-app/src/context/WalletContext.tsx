"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";

export interface WalletState {
  connected: boolean;
  address: string;
  chain: string;
  balance: string;
  provider?: string;
}

interface WalletCtx {
  wallet: WalletState;
  setWallet: (w: WalletState) => void;
  disconnect: () => void;
}

const EMPTY: WalletState = { connected: false, address: "", chain: "", balance: "" };
const STORAGE_KEY = "lumina_wallet";

const WalletContext = createContext<WalletCtx>({
  wallet: EMPTY,
  setWallet: () => {},
  disconnect: () => {},
});

export function WalletProvider({ children }: { children: ReactNode }) {
  const [wallet, setWalletRaw] = useState<WalletState>(EMPTY);

  const setWallet = useCallback((w: WalletState) => {
    setWalletRaw(w);
    if (w.connected) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ provider: w.provider, chain: w.chain })); } catch {}
    }
  }, []);

  const disconnect = useCallback(() => {
    setWalletRaw(EMPTY);
    try { localStorage.removeItem(STORAGE_KEY); } catch {}
  }, []);

  // Listen for account/chain changes from EVM wallets
  useEffect(() => {
    const eth = typeof window !== "undefined" ? (window as any).ethereum : null;
    if (!eth) return;

    const handleAccountsChanged = (accounts: string[]) => {
      if (accounts.length === 0) {
        disconnect();
      } else if (wallet.connected && wallet.provider !== "Phantom") {
        setWalletRaw((prev) => ({ ...prev, address: accounts[0] }));
      }
    };

    const handleChainChanged = () => {
      // Reload balance on chain change
      if (wallet.connected && wallet.provider !== "Phantom") {
        window.location.reload();
      }
    };

    eth.on?.("accountsChanged", handleAccountsChanged);
    eth.on?.("chainChanged", handleChainChanged);
    return () => {
      eth.removeListener?.("accountsChanged", handleAccountsChanged);
      eth.removeListener?.("chainChanged", handleChainChanged);
    };
  }, [wallet.connected, wallet.provider, disconnect]);

  return (
    <WalletContext.Provider value={{ wallet, setWallet, disconnect }}>
      {children}
    </WalletContext.Provider>
  );
}

export function useWallet() {
  return useContext(WalletContext);
}
