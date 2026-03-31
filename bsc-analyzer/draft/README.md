# Draft / legacy (unmaintained)

This tree holds **optional** tooling that is **not** part of the supported KOL workflow documented in the repo root [`README.md`](../README.md).

| Path | Contents |
|------|----------|
| [`scripts/`](scripts/) | Ad-hoc analytics (`analyze_*`, `filter_*`), Moralis/Tier2 helpers, old Pancake `build_deployer_db.py`, pipeline tests |
| [`ml/`](ml/) | Older training/feature pipelines (`train_model*.py`, `fetch_features.py`, Moralis fixes, etc.) |
| [`services/`](services/) | Legacy collectors / label workers (not the live KOL dataset collector) |
| [`notebooks/`](notebooks/) | Exploratory notebooks |
| [`root/`](root/) | One-off HTML reports and notes moved from repo root |

If you use a draft script, run it from the **`bsc-analyzer`** directory and fix paths (e.g. `python3 draft/scripts/analyze_backtest.py …`).

**Four.meme deployer reputation** for production uses `scripts/compute_deployer_reputation.py` and `data/deployers_fourmeme.csv`, not `draft/scripts/build_deployer_db.py` (Pancake PairCreated–based).
