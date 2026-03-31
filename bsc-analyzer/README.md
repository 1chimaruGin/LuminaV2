# Lumina BSC — KOL Monitor, Dataset & ML Scorer

## What This Does

Monitors BSC blockchain for KOL (Key Opinion Leader) wallet buys on Four.meme tokens. When a KOL buys:
1. **Scores** the token with ML model (probability of 2x return)
2. **Assigns mode**: PROBE (kc=2, ml≥0.5), CONFIRMED (kc=3), STRONG (kc≥4)
3. **Logs** to dataset CSV/JSONL for training
4. **Paper trades** — records "would enter" signals when thresholds met

---

## Complete Setup (5 minutes)

### Step 1: Install dependencies

```bash
sudo apt-get install -y build-essential cmake libssl-dev libcurl4-openssl-dev
```

### Step 2: Build

```bash
cd /home/kyi/LuminaV2/bsc-analyzer
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
cd ..
```

### Step 3: Configure .env

```bash
cp .env.example .env
nano .env  # or vim .env
```

**Required:**
```
QUICK_NODE_BSC_RPC=https://your-bsc-rpc-endpoint
```

**Optional (auto-derived from RPC if unset):**
```
BSC_WS_URL=wss://your-bsc-websocket
```

### Step 4: Verify KOL wallet list

```bash
cat top.json | head -20
```

Should contain KOL wallet addresses with labels A, B, C, etc.

---

## Live Testing & Data Collection

### Run live monitor (one command)

```bash
cd /home/kyi/LuminaV2/bsc-analyzer
bash scripts/run.sh --fresh-output
```

**What happens:**
- Connects to BSC via WebSocket
- Subscribes to Transfer events → KOL wallets
- Subscribes to TokenCreate events → Four.meme proxy
- When KOL buys a Four.meme token:
  - Fetches mcap, holders, dev sells via RPC
  - Computes ML score (54 features → LightGBM)
  - Evaluates mode (PROBE/CONFIRMED/STRONG)
  - Writes row to dataset CSV/JSONL
  - If mode ≥ 2 and ml ≥ 0.5 → writes to paper_hits.csv

**Output files:**

| File | What |
|------|------|
| `backtest_results/kol_dataset_live.csv` | Training data (81 columns) |
| `backtest_results/kol_dataset_live.jsonl` | Same as CSV, JSON format |
| `backtest_results/paper_hits.csv` | Signals that pass paper gate |
| `backtest_results/kol_live.log` | Session log |

**Console output:**
```
[kol_monitor] Loaded 11 KOL wallets from top.json
[kol_monitor] Loaded 552 deployer rows from data/deployers_fourmeme.csv
[kol_monitor] Live BNB/USD: $605.32
[writer] CSV: backtest_results/kol_dataset_live.csv | JSONL: backtest_results/kol_dataset_live.jsonl | Paper: backtest_results/paper_hits.csv | 81 cols
[klines] BTC 4h: +0.42%  BNB 4h: +0.15%
[kol_monitor] Live WSS mode — sub-second KOL detection
[14:32:15] KOL B (#2) PROBE ml=0.52 mcap=$8420 age=31 holders=26 0x1234 MyToken
[STATS 1m] tokens=3 signals=1 rows=1 paper=0 P/C/S=1/0/0
```

### Stop the monitor

Press `Ctrl+C`. Shows session summary:

```
── Session Summary ──
  Runtime:    5m
  Tokens:     42
  Signals:    8
  Rows:       5
  Paper hits: 2
  Modes:      PROBE=3  CONFIRMED=1  STRONG=1
```

---

## Understanding the Output

### Signal modes (how aggressive to trade)

| Mode | Name | When | Risk |
|------|------|------|------|
| 0 | NONE | kol_count < 2 or ml_score low | No trade |
| 1 | PROBE | kol_count = 2, ml ≥ 0.5, age < 2000 | Small position |
| 2 | CONFIRMED | kol_count = 3, mcap < 50k, dev_sell < 5k | Medium position |
| 3 | STRONG | kol_count ≥ 4 or special KOL (H) | Larger position |

### Paper hits (simulated trades)

`paper_hits.csv` contains signals where you "would have entered":
- mode ≥ 2 (CONFIRMED or STRONG)
- ml_score ≥ 0.5
- kol_count ≥ 2
- create_block is known

To change thresholds:
```bash
bash scripts/run.sh --paper-min-mode 1 --paper-min-ml 0.4
```

---

## Workflow: Collect Data → Train Model → Deploy

### Phase 1: Collect live data

```bash
# Run for several hours/days
bash scripts/run.sh --fresh-output
# Ctrl+C when done
```

### Phase 2: Label outcomes (wait 4+ hours)

```bash
# Fetches current mcap for each token, computes peak_mult
python3 ml/label_live_data.py --min-age-hours 4
```

Creates `backtest_results/kol_dataset_live_labeled.csv` with:
- `peak_mcap_usd` — highest mcap observed
- `peak_mult_vs_slot2_entry` — peak / entry mcap
- `graduated` — whether token graduated bonding curve

### Phase 3: Retrain model with live data

```bash
# Merges historical + live labeled data, trains v2 model
python3 ml/retrain_and_deploy.py --auto-build
```

This:
1. Merges `kol_dataset_90d_full_kol2plus.csv` + `kol_dataset_live_labeled.csv`
2. Trains new LightGBM model
3. Exports C header to `include/lumina/ml/kol_scorer.h`
4. Rebuilds the C++ binary

### Phase 4: Resume live with new model

```bash
bash scripts/run.sh
```

---

## Common Commands

```bash
# Fresh start (clears old data)
bash scripts/run.sh --fresh-output

# Append to existing data
bash scripts/run.sh

# Shadow mode (position_bnb=0, no IPC)
bash scripts/run.sh --shadow

# Lower paper gate threshold
bash scripts/run.sh --paper-min-mode 1 --paper-min-ml 0.3

# View live log
tail -f backtest_results/kol_live.log

# View paper hits
cat backtest_results/paper_hits.csv | column -t -s,

# Count rows collected
wc -l backtest_results/kol_dataset_live.csv
```

---

## Troubleshooting

### "Set QUICK_NODE_BSC_RPC"

The `.env` file is not being sourced. Use the wrapper:
```bash
bash scripts/run.sh
```

Or manually:
```bash
set -a && source .env && set +a
./build/lumina_kol_monitor ...
```

### "WSS connect failed"

Your RPC provider may not support WebSocket, or the URL is wrong. The monitor falls back to HTTP polling (slower but works).

### "0 KOL wallets loaded"

Check `top.json` exists and contains valid JSON:
```bash
cat top.json
```

### No signals appearing

KOL buys are infrequent. During quiet periods you may see nothing for hours. Check the log:
```bash
tail -f backtest_results/kol_live.log
```

### "BTC: 0 candles, BNB: 0 candles"

Binance API may be geo-blocked. Set override:
```bash
export BINANCE_SPOT_API_BASE=https://api.binance.us
bash scripts/run.sh
```

---

## File Layout

| Path | Purpose |
|------|---------|
| `scripts/run.sh` | **Start here** — one command to run live |
| `bench/kol_monitor.cpp` | Main C++ binary |
| `include/lumina/ml/kol_scorer.h` | Auto-generated ML model |
| `top.json` | KOL wallet list |
| `data/deployers_fourmeme.csv` | Deployer reputation DB |
| `.env` | RPC endpoints |
| `backtest_results/` | All output data |
| `ml/train_kol_scorer_v2.py` | Train improved model |
| `ml/label_live_data.py` | Label live tokens |
| `ml/retrain_and_deploy.py` | Retrain + deploy |

---

## Configuration (.env)

| Variable | Required | Purpose |
|----------|----------|---------|
| `QUICK_NODE_BSC_RPC` | Yes | BSC HTTP RPC (QuickNode, Alchemy, etc.) |
| `BSC_WS_URL` | No | WebSocket URL (auto-derived if unset) |
| `ALCHEMY_BSC_RPC` | No | Fallback RPC |
| `KOL_FILE` | No | Path to KOL list (default: `top.json`) |
| `BINANCE_SPOT_API_BASE` | No | Override Binance API (for geo-blocks) |
