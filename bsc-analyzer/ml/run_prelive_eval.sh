#!/usr/bin/env bash
# Recommended pre-live evaluation: time-ordered CV + chronological holdout + honest OOF backtest.
# Run from repo root:  bash ml/run_prelive_eval.sh
# Or from bsc-analyzer: bash ml/run_prelive_eval.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
CSV="${KOL_CSV:-backtest_results/kol_dataset_90d_full_kol2plus.csv}"

echo "=== Phase 1 research (existing script) ==="
python3 ml/research_90d_strategy.py --input "$CSV" --min-n 3

echo ""
echo "=== Phase 2 train: time CV + 15% chronological holdout (strict tail never in CV folds) ==="
python3 ml/train_kol_scorer.py --input "$CSV" --cv time --holdout-pct 0.15

echo ""
echo "=== Phase 3 backtest (OOF from kol_oof_predictions.csv) ==="
python3 ml/backtest_kol_strategy.py --input "$CSV" --capture-pct 0.60 --sensitivity

echo ""
echo "Done. Review ml/kol_scorer_config.json (chronological_holdout), ml/backtest_results_90d.json, ml/backtest_sensitivity.json"
