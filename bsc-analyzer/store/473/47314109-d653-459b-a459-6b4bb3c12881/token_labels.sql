ATTACH TABLE _ UUID 'c3fa4962-d0ac-4698-8c7d-3ed75ed212f4'
(
    `token_address` LowCardinality(String),
    `total_kol_buyers` UInt8 DEFAULT 0,
    `avg_pnl_pct` Float32 DEFAULT 0,
    `max_pnl_pct` Float32 DEFAULT 0,
    `min_pnl_pct` Float32 DEFAULT 0,
    `avg_hold_sec` UInt64 DEFAULT 0,
    `label` Enum8('WIN_BIG' = 1, 'WIN' = 2, 'BREAKEVEN' = 3, 'LOSS' = 4, 'RUG' = 5),
    `is_profitable` UInt8 DEFAULT 0,
    `labeled_at` DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(labeled_at)
ORDER BY token_address
SETTINGS index_granularity = 8192
