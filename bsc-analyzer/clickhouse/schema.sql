-- ============================================================
-- Lumina BSC Sniper v2 - ClickHouse Schema
-- KOL-Based ML Pipeline
-- ============================================================

-- 1. Raw swaps from KOL wallets (source of truth)
CREATE TABLE IF NOT EXISTS lumina.kol_swaps (
    wallet_address     LowCardinality(String),
    token_address      LowCardinality(String),
    token_symbol       String,
    token_name         String,
    token_logo         String DEFAULT '',
    side               Enum8('buy' = 1, 'sell' = 2),
    token_amount       Float64,
    quote_amount       Float64 DEFAULT 0,
    usd_value          Float64,
    tx_hash            String,
    block_timestamp    UInt64,
    chain              LowCardinality(String) DEFAULT 'BSC',
    pair_label         String DEFAULT '',
    ingested_at        DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (wallet_address, token_address, tx_hash, side);

-- 2. Per-token trade summary per KOL wallet
CREATE TABLE IF NOT EXISTS lumina.kol_token_trades (
    wallet_address     LowCardinality(String),
    token_address      LowCardinality(String),
    token_symbol       String,
    token_name         String,
    chain              LowCardinality(String) DEFAULT 'BSC',
    buy_count          UInt32,
    sell_count         UInt32,
    total_buy_usd      Float64,
    total_sell_usd     Float64,
    total_buy_tokens   Float64,
    total_sell_tokens   Float64,
    avg_buy_price      Float64,
    avg_sell_price     Float64,
    first_buy_ts       UInt64,
    last_buy_ts        UInt64,
    first_sell_ts      UInt64,
    last_sell_ts       UInt64,
    hold_duration_sec  UInt64,
    realized_pnl_usd   Float64,
    realized_pnl_pct   Float32,
    exit_type          LowCardinality(String) DEFAULT '',  -- sell_all, gradual, partial, none
    updated_at         DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (wallet_address, token_address);

-- 3. Token features snapshot (captured at time KOL first bought)
CREATE TABLE IF NOT EXISTS lumina.token_features (
    token_address      LowCardinality(String),
    pair_address       LowCardinality(String) DEFAULT '',
    token_symbol       String,
    token_name         String,
    chain              LowCardinality(String) DEFAULT 'BSC',

    -- Timing
    pair_created_block UInt64 DEFAULT 0,
    pair_created_ts    UInt64 DEFAULT 0,
    first_kol_buy_ts   UInt64 DEFAULT 0,
    token_age_at_buy_sec UInt64 DEFAULT 0,  -- seconds between pair creation and KOL buy

    -- Liquidity at entry
    initial_liq_bnb    Float64 DEFAULT 0,
    initial_liq_usd    Float64 DEFAULT 0,
    price_at_entry     Float64 DEFAULT 0,

    -- GoPlus security
    is_open_source     UInt8 DEFAULT 0,
    is_proxy           UInt8 DEFAULT 0,
    is_honeypot        UInt8 DEFAULT 0,
    buy_tax            Float32 DEFAULT 0,
    sell_tax           Float32 DEFAULT 0,
    is_mintable        UInt8 DEFAULT 0,
    has_blacklist      UInt8 DEFAULT 0,
    can_take_ownership UInt8 DEFAULT 0,
    owner_change_balance UInt8 DEFAULT 0,
    hidden_owner       UInt8 DEFAULT 0,
    selfdestruct       UInt8 DEFAULT 0,
    external_call      UInt8 DEFAULT 0,
    is_renounced       UInt8 DEFAULT 0,

    -- Holder data
    holder_count       UInt32 DEFAULT 0,
    top10_holder_pct   Float32 DEFAULT 0,
    creator_pct        Float32 DEFAULT 0,

    -- LP data
    lp_locked          UInt8 DEFAULT 0,
    lp_lock_pct        Float32 DEFAULT 0,

    -- Early trading activity (first 5 min after pair creation)
    buy_count_5m       UInt32 DEFAULT 0,
    sell_count_5m      UInt32 DEFAULT 0,
    unique_buyers_5m   UInt32 DEFAULT 0,
    volume_usd_5m      Float64 DEFAULT 0,

    -- Deployer profile
    deployer_address   LowCardinality(String) DEFAULT '',
    deployer_total_tokens    UInt32 DEFAULT 0,
    deployer_rug_count       UInt32 DEFAULT 0,
    deployer_avg_lifespan_h  Float32 DEFAULT 0,

    -- KOL consensus
    kol_buyer_count    UInt8 DEFAULT 0,   -- how many KOLs bought this token
    kol_wallets        String DEFAULT '', -- comma-separated wallet addresses

    -- Honeypot.is
    honeypot_sim_success UInt8 DEFAULT 0,  -- 1 = sim buy+sell succeeded
    honeypot_buy_tax   Float32 DEFAULT 0,
    honeypot_sell_tax  Float32 DEFAULT 0,

    updated_at         DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (token_address);

-- 4. Labels (ground truth from KOL outcomes)
CREATE TABLE IF NOT EXISTS lumina.token_labels (
    token_address      LowCardinality(String),

    -- Aggregated across all KOLs who traded this token
    total_kol_buyers   UInt8 DEFAULT 0,
    avg_pnl_pct        Float32 DEFAULT 0,
    max_pnl_pct        Float32 DEFAULT 0,
    min_pnl_pct        Float32 DEFAULT 0,
    avg_hold_sec       UInt64 DEFAULT 0,

    -- Binary label
    label              Enum8('WIN_BIG' = 1, 'WIN' = 2, 'BREAKEVEN' = 3, 'LOSS' = 4, 'RUG' = 5),
    -- WIN_BIG: avg PnL > 100%
    -- WIN: avg PnL > 20%
    -- BREAKEVEN: avg PnL -20% to +20%
    -- LOSS: avg PnL < -20%
    -- RUG: token went to 0 or couldn't sell

    -- For binary classification
    is_profitable      UInt8 DEFAULT 0,  -- 1 if label in (WIN_BIG, WIN)

    labeled_at         DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(labeled_at)
ORDER BY (token_address);

-- 5. KOL signals (backtest + live unified table)
CREATE TABLE IF NOT EXISTS lumina.kol_signals (
    token_address      LowCardinality(String),
    token_name         String DEFAULT '',
    token_symbol       String DEFAULT '',
    kol_count          UInt8 DEFAULT 0,
    kol_names          Array(String),
    kol_combo          String DEFAULT '',
    mode               UInt8 DEFAULT 0,       -- 0=none, 1=probe, 2=confirmed, 3=strong
    entry_mcap_usd     Float64 DEFAULT 0,
    peak_mcap_usd      Float64 DEFAULT 0,
    low_mcap_usd       Float64 DEFAULT 0,
    current_mcap_usd   Float64 DEFAULT 0,
    holder_proxy       UInt32 DEFAULT 0,
    dev_sell_usd       Float64 DEFAULT 0,
    dev_sell_tokens    Float64 DEFAULT 0,
    creator            String DEFAULT '',
    create_block       UInt64 DEFAULT 0,
    age_blocks         UInt64 DEFAULT 0,
    graduated          UInt8 DEFAULT 0,
    peak_x             Float64 DEFAULT 0,
    low_x              Float64 DEFAULT 0,
    kol_buy_speed_blocks UInt64 DEFAULT 0,
    first_buyer        String DEFAULT '',
    source             Enum8('backtest' = 0, 'live' = 1),
    created_at         DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (token_address, source);

-- 6. Training dataset (materialized join of features + labels)
CREATE TABLE IF NOT EXISTS lumina.training_dataset (
    token_address      LowCardinality(String),
    token_symbol       String,

    -- Features (from token_features)
    token_age_at_buy_sec UInt64,
    initial_liq_usd    Float64,
    price_at_entry     Float64,
    is_open_source     UInt8,
    is_proxy           UInt8,
    is_honeypot        UInt8,
    buy_tax            Float32,
    sell_tax           Float32,
    is_mintable        UInt8,
    has_blacklist      UInt8,
    can_take_ownership UInt8,
    owner_change_balance UInt8,
    hidden_owner       UInt8,
    selfdestruct       UInt8,
    external_call      UInt8,
    is_renounced       UInt8,
    holder_count       UInt32,
    top10_holder_pct   Float32,
    creator_pct        Float32,
    lp_locked          UInt8,
    lp_lock_pct        Float32,
    buy_count_5m       UInt32,
    sell_count_5m      UInt32,
    unique_buyers_5m   UInt32,
    volume_usd_5m      Float64,
    deployer_total_tokens UInt32,
    deployer_rug_count UInt32,
    deployer_avg_lifespan_h Float32,
    kol_buyer_count    UInt8,
    honeypot_sim_success UInt8,
    honeypot_buy_tax   Float32,
    honeypot_sell_tax  Float32,

    -- Label
    label              LowCardinality(String),
    is_profitable      UInt8,
    avg_pnl_pct        Float32,

    created_at         DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (token_address);
