const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export async function apiFetch<T>(path: string, options?: RequestInit & { timeoutMs?: number; retries?: number }): Promise<T> {
  const maxRetries = options?.retries ?? 1;
  const timeoutMs = options?.timeoutMs ?? 30_000;
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...options,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...options?.headers,
        },
      });
      if (!res.ok) {
        let detail = res.statusText;
        try { const body = await res.json(); detail = body?.detail || body?.message || detail; } catch {}
        throw new Error(`API error ${res.status}: ${detail}`);
      }
      return res.json();
    } catch (e) {
      lastError = e instanceof Error ? e : new Error(String(e));
      if (lastError.name === "AbortError") {
        lastError = new Error("Request timed out — backend may be slow or unavailable");
      } else if (lastError.message?.includes("fetch failed") || lastError.message?.includes("ECONNREFUSED") || lastError.message?.includes("Failed to fetch")) {
        lastError = new Error("Cannot connect to backend — is the server running?");
      }
      if (attempt < maxRetries) {
        await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
    } finally {
      clearTimeout(timeout);
    }
  }
  throw lastError ?? new Error("Request failed");
}

/* ── Market ── */

export async function fetchTickers(exchange?: string, limit = 100) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (exchange) params.set("exchange", exchange);
  return apiFetch<{ data: Ticker[]; total: number }>(`/market/tickers?${params}`);
}

export async function fetchTickerBySymbol(symbol: string, exchange = "binance") {
  return apiFetch<{ data: Ticker | null }>(`/market/tickers/${symbol}?exchange=${exchange}`);
}

export async function fetchMarketOverview() {
  return apiFetch<MarketOverview>(`/market/overview`);
}

export async function fetchFundingRates(exchange?: string, limit = 50) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (exchange) params.set("exchange", exchange);
  return apiFetch<{ data: FundingRate[]; total: number }>(`/market/funding?${params}`);
}

export async function fetchOpenInterest(exchange = "binance", symbols?: string) {
  const params = new URLSearchParams({ exchange });
  if (symbols) params.set("symbols", symbols);
  return apiFetch<{ data: OpenInterestData[]; total: number }>(`/market/open-interest?${params}`);
}

export async function fetchOrderFlow(symbol: string, exchange = "binance") {
  return apiFetch<{ data: OrderFlowData | null }>(`/market/order-flow/${encodeURIComponent(symbol)}?exchange=${exchange}`);
}

export async function fetchWhaleTrades(symbol: string, exchange = "binance", minUsd = 100000, limit = 50) {
  const params = new URLSearchParams({ exchange, min_usd: String(minUsd), limit: String(limit) });
  return apiFetch<{ data: WhaleTrade[]; total: number }>(`/market/whale-trades/${encodeURIComponent(symbol)}?${params}`);
}

export async function fetchAllWhaleTrades(limit = 100) {
  return apiFetch<{ data: WhaleTrade[]; total: number }>(`/market/whale-trades-all?limit=${limit}`);
}

export async function fetchAllTickers(limit = 2000) {
  return apiFetch<{ data: Ticker[]; total: number }>(`/market/tickers?limit=${limit}`);
}

export async function fetchOHLCV(symbol: string, exchange = "binance", timeframe = "1h", limit = 100) {
  const params = new URLSearchParams({ exchange, timeframe, limit: String(limit) });
  return apiFetch<{ data: Candle[]; total: number }>(`/market/ohlcv/${symbol}?${params}`);
}

/* ── Token ── */

export interface TokenAnalysis {
  address: string;
  symbol: string;
  name: string;
  logo: string;
  header: string;
  price_usd: number;
  price_native: number;
  price_change_5m: number;
  price_change_1h: number;
  price_change_6h: number;
  price_change_24h: number;
  volume_5m: number;
  volume_1h: number;
  volume_6h: number;
  volume_24h: number;
  liquidity_usd: number;
  liquidity_base: number;
  liquidity_quote: number;
  fdv: number;
  market_cap: number;
  pair_created_at: number;
  txns_24h_buys: number;
  txns_24h_sells: number;
  txns_1h_buys: number;
  txns_1h_sells: number;
  holder_count: number | null;
  dex_id: string;
  pair_address: string;
  chain_id: string;
  quote_token: { symbol: string; name: string; address: string };
  websites: { label?: string; url: string }[];
  socials: { type?: string; url: string }[];
  dex_url: string;
}

export interface TokenPair {
  pair_address: string;
  dex: string;
  base_symbol: string;
  quote_symbol: string;
  price_usd: number;
  volume_24h: number;
  liquidity_usd: number;
}

export interface TokenAnalysisResponse {
  token: TokenAnalysis | null;
  pairs: TokenPair[];
  total_pairs: number;
  error?: string;
}

export async function analyzeToken(address: string, chain = "auto") {
  const params = new URLSearchParams({ address, chain });
  return apiFetch<TokenAnalysisResponse>(`/token/analyze?${params}`);
}

/* ── Wallet-Token Trades (for chart overlay) ── */

export interface WalletTokenTrade {
  ts: number;
  side: "buy" | "sell";
  usd: number;
  amount: number;
  symbol: string;
  tx_hash: string;
}

export interface WalletTokenTradesResponse {
  trades: WalletTokenTrade[];
  wallet_address: string;
  token_address: string;
  chain: string;
  total_trades: number;
  error?: string;
}

export async function fetchWalletTokenTrades(walletAddress: string, tokenAddress: string, chain = "bsc") {
  return apiFetch<WalletTokenTradesResponse>(`/investigate/wallet-token-trades`, {
    method: "POST",
    body: JSON.stringify({ wallet_address: walletAddress, token_address: tokenAddress, chain }),
  });
}

/* ── AI Analysis ── */

export interface AISignal {
  direction: "LONG" | "SHORT" | "NEUTRAL";
  confidence: number;
  entry_zone: string;
  targets: string[];
  stop_loss: string;
  reasoning: string;
  leverage_suggestion?: string;
}

export interface AIAnalysis {
  narrative: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "EXTREME";
  risk_factors: string[];
  spot_signal: AISignal;
  perp_signal: AISignal;
  whale_verdict: string;
  key_levels: { support: string[]; resistance: string[] };
  tldr: string;
}

export async function fetchAIAnalysis(
  token_data: Record<string, unknown>,
  wallets: Record<string, unknown>[],
  candle_summary: Record<string, unknown>,
  flow_summary: Record<string, unknown>,
) {
  return apiFetch<{ analysis: AIAnalysis | null; error?: string }>("/token/ai-analysis", {
    method: "POST",
    body: JSON.stringify({ token_data, wallets, candle_summary, flow_summary }),
  });
}

/* ── Investigate ── */

export interface InvestigateCandle {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface InvestigateTxn {
  side: "buy" | "sell";
  usd_value: number;
  timestamp: number | null;
  tx_hash: string;
}

export interface InvestigateWallet {
  address: string;
  short_addr: string;
  label: string;
  tag: string;
  buys: number;
  sells: number;
  buy_usd: number;
  sell_usd: number;
  net_usd: number;
  abs_impact: number;
  total_volume: number;
  first_tx: number;
  last_tx: number;
  txns: InvestigateTxn[];
}

export interface InvestigateOHLCVResponse {
  candles: InvestigateCandle[];
  pair_address: string;
  chain: string;
  timeframe: string;
  error?: string;
}

export interface InvestigateWalletsResponse {
  wallets: InvestigateWallet[];
  token_address: string;
  pair_address: string;
  chain: string;
  timestamp: number;
  window_minutes: number;
  window_start: number;
  window_end: number;
  total_wallets: number;
  error?: string;
}

export async function fetchInvestigateOHLCV(pairAddress: string, chain = "solana", timeframe = "5m") {
  const params = new URLSearchParams({ pair_address: pairAddress, chain, timeframe });
  return apiFetch<InvestigateOHLCVResponse>(`/investigate/ohlcv?${params}`);
}

export async function investigateWallets(body: {
  token_address: string;
  pair_address: string;
  chain?: string;
  timestamp: number;
  window_minutes?: number;
  token_symbol?: string;
  token_name?: string;
}) {
  return apiFetch<InvestigateWalletsResponse>(`/investigate/wallets`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface CandleFlow {
  buy_count: number;
  sell_count: number;
  buy_usd: number;
  sell_usd: number;
  net_usd: number;
  whale_buy: number;
  whale_sell: number;
  top_wallet: string;
  top_usd: number;
}

export interface RawSwap {
  wallet: string;
  side: "buy" | "sell";
  usd: number;
  ts: number;
  tx: string;
}

export interface BigMove {
  ts: number;
  side: "buy" | "sell";
  pct_move: number;
  volume: number;
  type: "big_move";
}

export interface ScanResponse {
  candle_flow: Record<string, CandleFlow>;
  wallets: InvestigateWallet[];
  raw_swaps: RawSwap[];
  big_moves: BigMove[];
  total_swaps: number;
  total_wallets: number;
  error?: string;
}

export async function scanTokenActivity(body: {
  token_address: string;
  pair_address: string;
  chain?: string;
  candle_timestamps: number[];
  timeframe_seconds: number;
  timeframe?: string;
}) {
  return apiFetch<ScanResponse>(`/investigate/scan`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/* ── Wallet ── */

export async function analyzeWallet(address: string, chain?: string) {
  return apiFetch<WalletAnalysis>(`/wallet/analyze`, {
    method: "POST",
    body: JSON.stringify({ address, chain }),
    timeoutMs: 60_000,
    retries: 2,
  });
}

export interface AiAnalysisResult {
  profile: WalletAnalysis["profile"];
  recent_activity: WalletAnalysis["recent_activity"];
  top_counterparties: WalletAnalysis["top_counterparties"];
  risk_flags: WalletAnalysis["risk_flags"];
  social_mentions: WalletAnalysis["social_mentions"];
}

export async function aiAnalyzeWallet(address: string, chain?: string) {
  return apiFetch<AiAnalysisResult>(`/wallet/ai-analyze`, {
    method: "POST",
    body: JSON.stringify({ address, chain }),
    timeoutMs: 45_000,
  });
}

/* ── Types ── */

export interface Ticker {
  symbol: string;
  base: string;
  quote: string;
  price: number;
  price_change_24h: number;
  volume_24h: number;
  high_24h: number;
  low_24h: number;
  market_cap: number | null;
  exchange: string;
  timestamp: string;
}

export interface MarketOverview {
  total_market_cap: number;
  total_volume_24h: number;
  btc_dominance: number;
  eth_dominance: number;
  fear_greed_index: number;
  fear_greed_label: string;
  active_pairs: number;
  exchanges_count: number;
  chains_count: number;
  top_gainers: Ticker[];
  top_losers: Ticker[];
}

export interface FundingRate {
  symbol: string;
  exchange: string;
  rate: number;
  predicted_rate: number | null;
  next_funding_time: string | null;
  annualized: number | null;
  timestamp: string;
}

export interface OpenInterestData {
  symbol: string;
  exchange: string;
  open_interest: number;
  open_interest_usd: number;
  long_short_ratio: number | null;
  timestamp: string;
}

export interface OrderFlowData {
  symbol: string;
  exchange: string;
  bid_volume: number;
  ask_volume: number;
  spread: number;
  spread_pct: number;
  buy_pressure: number;
  top_bids: [number, number][];
  top_asks: [number, number][];
}

export interface WhaleTrade {
  symbol: string;
  exchange: string | null;
  chain: string | null;
  tx_hash: string | null;
  from_address: string | null;
  to_address: string | null;
  amount: number;
  usd_value: number;
  side?: string;
  tx_type?: string;
  is_smart_money?: boolean;
  label: string | null;
  timestamp: string;
}

export interface Candle {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface WalletHolding {
  token: string;
  name?: string;
  logo?: string;
  mint?: string;
  amount: number | string;
  amount_fmt?: string;
  value: string;
  usd_value?: number;
  price?: number;
  pct: number;
  chain?: string;
}

export interface ChainPortfolio {
  chain: string;
  chain_name: string;
  native_symbol: string;
  native_balance: number;
  native_usd: number;
  portfolio_usd: number;
  token_count: number;
  txn_count: number;
}

export interface TradeHistoryEntry {
  signature: string;
  token: string;
  mint: string;
  side: "Buy" | "Sell";
  amount: number;
  price: number;
  total_usd: number;
  timestamp: number;
  age: string;
  maker: string;
}

export interface WalletPnL {
  realized: number;
  unrealized: number;
  total_revenue: number;
  total_spent: number;
}

export interface WalletActivity {
  tx_type: string;
  action: string;
  date: string;
  usd_value?: number;
}

export interface WalletCounterparty {
  name: string;
  txns: number;
  volume: string;
}

export interface RiskFlag {
  label: string;
  value: string;
  color: string;
}

export interface ConnectedWallet {
  address: string;
  short: string;
  txns: number;
}

export interface WalletAnalysis {
  profile: {
    address: string;
    chain: string;
    chains?: string[];
    label: string | null;
    entity: string | null;
    role: string | null;
    risk_level: string;
    risk_note: string | null;
    portfolio_value: number | null;
    tags: string[];
    is_smart_money: boolean;
  };
  sol_balance: string | null;
  sol_balance_raw?: number;
  sol_value: string | null;
  sol_price?: number;
  net_worth_sol?: number;
  token_count: string | number | null;
  total_txns: string | null;
  sends: string | null;
  receives: string | null;
  portfolio_value: string | null;
  portfolio_value_raw?: number;
  portfolio_change: string | null;
  status: string;
  funded_by: string | null;
  top_holdings: WalletHolding[];
  chain_portfolios?: ChainPortfolio[];
  first_seen?: number;
  last_seen?: number;
  connected_wallets?: ConnectedWallet[];
  recent_activity: WalletActivity[];
  top_counterparties: WalletCounterparty[];
  risk_flags: RiskFlag[];
  social_mentions: string[];
  trade_history: TradeHistoryEntry[];
  activity_heatmap: number[][];
  pnl: WalletPnL;
}

/* ── Trader Mode ── */

export interface TokenTradeStats {
  token_address: string;
  token_symbol: string;
  token_name: string;
  token_logo: string;
  chain: string;
  buys: number;
  sells: number;
  total_buy_usd: number;
  total_sell_usd: number;
  avg_buy_price: number;
  avg_sell_price: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
  remaining_tokens: number;
  current_price: number;
  current_balance_usd: number;
  hold_duration_seconds: number;
  first_buy_ts: number;
  last_active_ts: number;
  status: "holding" | "closed";
  exit_type: "none" | "sell_all" | "gradual_exit" | "partial_exit" | "unknown";
  is_win: boolean;
  pair_label: string;
}

export interface CumulativePnLPoint {
  ts: number;
  pnl: number;
}

export interface TraderProfile {
  address: string;
  chains_scanned: string[];
  time_range: string;
  total_tokens_traded: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_pnl: number;
  total_cost: number;
  total_revenue: number;
  win_rate: number;
  wins: number;
  losses: number;
  avg_hold_duration_seconds: number;
  trading_style: string;
  best_trade: { token: string; pnl: number; pnl_pct: number } | null;
  worst_trade: { token: string; pnl: number; pnl_pct: number } | null;
  token_stats: TokenTradeStats[];
  cumulative_pnl: CumulativePnLPoint[];
  total_swaps: number;
  fetch_time_ms: number;
}

export async function fetchTraderProfile(address: string, chains?: string[], timeRange = "all") {
  return apiFetch<TraderProfile>(`/wallet/trader-profile`, {
    method: "POST",
    body: JSON.stringify({ address, chains, time_range: timeRange }),
    timeoutMs: 90_000,
    retries: 1,
  });
}

/* ── AI Copilot ── */

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface QuickInsight {
  icon: string;
  iconColor: string;
  title: string;
  desc: string;
  tag: string;
  tagColor: string;
}

export interface MarketPulseItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changeColor: string;
  sentiment: string;
  sentColor: string;
}

export async function sendChatMessage(message: string, history: ChatMessage[] = [], model: "grok" | "claude" = "grok") {
  return apiFetch<{ reply: string; context_used: boolean }>("/chat", {
    method: "POST",
    body: JSON.stringify({ message, history, model }),
  });
}

export async function fetchQuickInsights() {
  return apiFetch<{ data: QuickInsight[] }>("/chat/insights");
}

export async function fetchMarketPulse() {
  return apiFetch<{ data: MarketPulseItem[] }>("/chat/market-pulse");
}

/* ── Strategy Scanner (God of Scalper — Overlap Spike) ── */

export interface OverlapSpikeAlert {
  symbol: string;
  base: string;
  price: number;
  vol_24h: number;
  vol_1h_est: number;
  change_24h: number;
  ratio_5m: number;
  ratio_1m: number;
  vol_5m_cur: number;
  vol_5m_prev: number;
  vol_1m_cur: number;
  vol_1m_ma: number;
  candle_open: number;
  candle_close: number;
  candle_high: number;
  candle_low: number;
  is_bullish: boolean;
  body_pct: number;
  zone_high: number;
  zone_low: number;
  zone_mid: number;
  timestamp: number;
  scan_ts: number;
  added_ts?: number;
}

export async function fetchSpikeAlerts(limit = 50) {
  return apiFetch<{ data: OverlapSpikeAlert[]; total: number; scanner_active: boolean }>(
    `/strategy/alerts?limit=${limit}`
  );
}

export async function fetchWatchlist() {
  return apiFetch<{ data: OverlapSpikeAlert[] }>(`/strategy/watchlist`);
}

export async function addToWatchlist(symbol: string) {
  return apiFetch<{ data: OverlapSpikeAlert[] }>(
    `/strategy/watchlist/add?symbol=${encodeURIComponent(symbol)}`,
    { method: "POST" }
  );
}

export async function removeFromWatchlist(symbol: string) {
  return apiFetch<{ data: OverlapSpikeAlert[] }>(
    `/strategy/watchlist/remove?symbol=${encodeURIComponent(symbol)}`,
    { method: "POST" }
  );
}

export interface ScannerConfig {
  vol_1h_min: number;
  vol_1h_max: number;
  spike_5m: number;
  spike_1m: number;
  ma_window: number;
}

export interface ScannerStatus {
  active: boolean;
  total_alerts: number;
  watchlist_count: number;
  pairs_total: number;
  pairs_filtered: number;
  pairs_checked: number;
  spikes_found: number;
  errors: number;
  last_scan_ts: number;
  scan_duration_ms: number;
  config: ScannerConfig;
}

export async function fetchScannerStatus() {
  return apiFetch<ScannerStatus>(`/strategy/scanner-status`);
}

export async function fetchScannerConfig() {
  return apiFetch<ScannerConfig>(`/strategy/config`);
}

export interface StrategyCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export async function fetchStrategyOHLCV(symbol: string, timeframe = "5m", limit = 300) {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit) });
  return apiFetch<{ data: StrategyCandle[]; symbol: string; timeframe: string }>(
    `/strategy/ohlcv?${params}`
  );
}

export async function updateScannerConfig(config: Partial<ScannerConfig>) {
  const params = new URLSearchParams();
  if (config.vol_1h_min !== undefined) params.set("vol_1h_min", String(config.vol_1h_min));
  if (config.vol_1h_max !== undefined) params.set("vol_1h_max", String(config.vol_1h_max));
  if (config.spike_5m !== undefined) params.set("spike_5m", String(config.spike_5m));
  if (config.spike_1m !== undefined) params.set("spike_1m", String(config.spike_1m));
  if (config.ma_window !== undefined) params.set("ma_window", String(config.ma_window));
  return apiFetch<ScannerConfig>(`/strategy/config?${params}`, { method: "POST" });
}
