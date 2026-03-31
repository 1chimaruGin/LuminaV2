#!/usr/bin/env bash
# DEPRECATED: Use scripts/run.sh instead.
# The C++ binary now handles CSV, JSONL, and paper CSV output directly.
# This script is kept for backward compatibility.
#
# Old: Pipe lumina_kol_monitor → live_dataset_collector (sources .env for QUICK_NODE_BSC_RPC).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
MON="$ROOT/build/lumina_kol_monitor"
if [[ ! -x "$MON" ]]; then
  echo "Missing $MON — build: (cd build && cmake --build . --target lumina_kol_monitor)" >&2
  exit 1
fi

PAPER=false
BOTH=false
COLLECTOR_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --paper)  PAPER=true ;;
    --both)   BOTH=true ;;
    *)        COLLECTOR_ARGS+=("$arg") ;;
  esac
done

if [[ "$PAPER" == true && "$BOTH" == true ]]; then
  echo "Use either --paper or --both, not both." >&2
  exit 1
fi

MON_ARGS=(--format json --no-ipc)

# Drop --output / --csv (and values) so we can set paths explicitly.
strip_out_csv() {
  local out=() i=0
  while [[ $i -lt ${#COLLECTOR_ARGS[@]} ]]; do
    local a="${COLLECTOR_ARGS[i]}"
    if [[ "$a" == "--output" || "$a" == "--csv" ]]; then
      i=$((i + 2))
      continue
    fi
    out+=("$a")
    i=$((i + 1))
  done
  COLLECTOR_ARGS=("${out[@]}")
}

if [[ "$PAPER" == true ]]; then
  MON_ARGS+=(--shadow)
  LOG="${KOL_PAPER_STDERR:-$ROOT/backtest_results/kol_paper_stderr.log}"
  PAPER_CSV="${PAPER_HITS_CSV:-$ROOT/backtest_results/paper_hits.csv}"
  mkdir -p "$(dirname "$LOG")" "$(dirname "$PAPER_CSV")"
  exec "$MON" "${MON_ARGS[@]}" 2>>"$LOG" | python3 "$ROOT/services/paper_signal_gate.py" \
    --paper-csv "$PAPER_CSV" --shadow-only \
    | python3 "$ROOT/services/live_dataset_collector.py" "${COLLECTOR_ARGS[@]}"
fi

if [[ "$BOTH" == true ]]; then
  strip_out_csv
  LOG="${KOL_LIVE_STDERR:-$ROOT/backtest_results/kol_live_stderr.log}"
  PAPER_CSV="${PAPER_HITS_CSV:-$ROOT/backtest_results/paper_hits.csv}"
  LIVE_JSON="${LIVE_JSONL:-$ROOT/backtest_results/kol_dataset_live.jsonl}"
  LIVE_CSV="${LIVE_CSV_OUT:-$ROOT/backtest_results/kol_dataset_live.csv}"
  mkdir -p "$(dirname "$LOG")" "$(dirname "$PAPER_CSV")" "$(dirname "$LIVE_JSON")"
  "$MON" "${MON_ARGS[@]}" 2>>"$LOG" | tee >(
    python3 "$ROOT/services/live_dataset_collector.py" "${COLLECTOR_ARGS[@]}" \
      --output "$LIVE_JSON" --csv "$LIVE_CSV"
  ) | python3 "$ROOT/services/paper_signal_gate.py" --paper-csv "$PAPER_CSV" >/dev/null
  exit $?
fi

LOG="${KOL_LIVE_STDERR:-$ROOT/backtest_results/kol_live_stderr.log}"
mkdir -p "$(dirname "$LOG")"
exec "$MON" "${MON_ARGS[@]}" 2>>"$LOG" | python3 "$ROOT/services/live_dataset_collector.py" "${COLLECTOR_ARGS[@]}"
