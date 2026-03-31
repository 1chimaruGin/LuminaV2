# Shadow Mode & Paper Trading

## Overview

`lumina_kol_monitor` handles dataset writing and paper trading natively in C++. No Python pipeline needed.

## Live + Paper (default)

```bash
bash scripts/run.sh
```

Outputs:
- `backtest_results/kol_dataset_live.csv` — 81-column dataset (training-compatible)
- `backtest_results/kol_dataset_live.jsonl` — same data as JSON
- `backtest_results/paper_hits.csv` — signals that pass the paper gate (mode >= 2, ml >= 0.5)
- `backtest_results/kol_live.log` — stderr log

## Shadow Mode

```bash
bash scripts/run.sh --shadow
```

All signals emitted with `position_bnb=0` and `"shadow": true`. IPC disabled.

## Fresh Start

```bash
bash scripts/run.sh --fresh-output
```

Truncates output files on startup. Without this flag, data appends to existing files (dedup prevents duplicate tokens).

## Token Age Accuracy

- **`recent_creates`** (WSS TokenCreate) may miss tokens created before the monitor started
- The monitor **HTTP backfills** TokenCreate via `eth_getLogs`, scanning up to `--create-backfill-blocks` (default 500000; 0 = off)
- JSON includes `create_block_known` (true/false) and `age_blocks` (number or null)
- `evaluate_mode()` returns no mode (0) when `create_block_known` is false unless `--allow-unknown-create`

## Paper Gate Thresholds

Embedded in C++ after `evaluate_mode()`. Configurable via CLI:

| Flag | Default | Meaning |
|------|---------|---------|
| `--paper-min-mode N` | 2 | Minimum mode (1=PROBE, 2=CONFIRMED, 3=STRONG) |
| `--paper-min-ml N` | 0.5 | Minimum ml_score |
| `--paper-csv PATH` | (set by run.sh) | Paper hits CSV output |
| `--first-signal-min-kol-count N` | 2 | One row per token at kol_count >= N |
| `--tokens-newer-than-session-start` | (flag) | Skip tokens older than session start block |

## Online Learning

Label live-captured tokens and retrain:

```bash
# 1. Label outcomes (wait ≥4h after capture)
python3 ml/label_live_data.py

# 2. Retrain with merged data
python3 ml/retrain_and_deploy.py --auto-build
```

## Legacy (deprecated)

The Python pipeline (`live_dataset_collector.py`, `paper_signal_gate.py`, `run_live_dataset_collect.sh`) is deprecated. All functionality is now in the C++ binary.
