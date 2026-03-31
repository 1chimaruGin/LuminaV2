#!/usr/bin/env bash
# Single command to run live KOL monitor with dataset + paper trading output.
# Sources .env for RPC keys (C++ binary cannot read .env natively).
#
# Usage:  bash scripts/run.sh [--fresh-output] [extra kol_monitor flags...]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; source "$ROOT/.env"; set +a; }

MON="$ROOT/build/lumina_kol_monitor"
if [[ ! -x "$MON" ]]; then
  echo "Build first: cd build && cmake --build . --target lumina_kol_monitor -j\$(nproc)" >&2
  exit 1
fi

exec "$MON" --format json --no-ipc \
  --deployers "$ROOT/data/deployers_fourmeme.csv" \
  --csv "$ROOT/backtest_results/kol_dataset_live.csv" \
  --jsonl "$ROOT/backtest_results/kol_dataset_live.jsonl" \
  --paper-csv "$ROOT/backtest_results/paper_hits.csv" \
  --log-file "$ROOT/backtest_results/kol_live.log" \
  --first-signal-min-kol-count 2 \
  --tokens-newer-than-session-start \
  "$@"
