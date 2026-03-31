#!/usr/bin/env bash
# Four.meme TokenCreate replay over the last N BSC blocks (default ~24h). Prints JSON summary to stdout.
# Requires: lumina_replay_fourmeme built, QUICK_NODE_BSC_RPC.
#
#   export QUICK_NODE_BSC_RPC=https://...
#   ./scripts/backtest_fourmeme_24h.sh [blocks]
#
# Env: REPLAY_CHUNK_BLOCKS (default 1 in binary; script matches), REPLAY_PROGRESS_CHUNKS (default 200, 0=off),
#      ALCHEMY_BSC_RPC, DEPLOYER_CSV

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${ROOT}/build/lumina_replay_fourmeme"
BLOCKS="${1:-115200}"
export REPLAY_CHUNK_BLOCKS="${REPLAY_CHUNK_BLOCKS:-1}"
export REPLAY_PROGRESS_CHUNKS="${REPLAY_PROGRESS_CHUNKS:-200}"

if [[ ! -x "$BIN" ]]; then
  echo "Build first: cd ${ROOT}/build && cmake .. && make lumina_replay_fourmeme" >&2
  exit 1
fi
if [[ -z "${QUICK_NODE_BSC_RPC:-}" ]]; then
  echo "QUICK_NODE_BSC_RPC is not set" >&2
  exit 1
fi

TMP="$(mktemp)"
ERR="$(mktemp)"
trap 'rm -f "$TMP" "$ERR"' EXIT

echo "Replay last ${BLOCKS} blocks (chunk=${REPLAY_CHUNK_BLOCKS}, progress every ${REPLAY_PROGRESS_CHUNKS} chunks)…" >&2
echo "  JSONL -> ${TMP} (quiet if few TokenCreates); stderr buffer -> ${ERR}" >&2
set +e
"$BIN" --recent "$BLOCKS" >"$TMP" 2>"$ERR"
set -e
if grep -q '\[replay\]' "$ERR" 2>/dev/null; then
  echo "Last progress lines:" >&2
  grep '\[replay\]' "$ERR" | tail -3 >&2 || true
fi
grep '^{"summary"' "$ERR" | tail -1 || echo '{"summary":null}'
echo "JSONL lines: $(wc -l <"$TMP" | tr -d ' ')" >&2
