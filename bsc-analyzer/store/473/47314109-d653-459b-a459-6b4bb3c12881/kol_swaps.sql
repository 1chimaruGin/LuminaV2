ATTACH TABLE _ UUID 'ecae80f5-881c-4381-b7f6-7680b8f6a9a7'
(
    `wallet_address` LowCardinality(String),
    `token_address` LowCardinality(String),
    `token_symbol` String,
    `token_name` String,
    `token_logo` String DEFAULT '',
    `side` Enum8('buy' = 1, 'sell' = 2),
    `token_amount` Float64,
    `quote_amount` Float64 DEFAULT 0,
    `usd_value` Float64,
    `tx_hash` String,
    `block_timestamp` UInt64,
    `chain` LowCardinality(String) DEFAULT 'BSC',
    `pair_label` String DEFAULT '',
    `ingested_at` DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (wallet_address, token_address, tx_hash, side)
SETTINGS index_granularity = 8192
