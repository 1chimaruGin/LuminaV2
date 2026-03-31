#!/usr/bin/env bash
# DEPRECATED: Use scripts/run.sh --shadow instead.
echo "DEPRECATED: Use 'bash scripts/run.sh --shadow' instead." >&2
SDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SDIR/run.sh" --shadow "$@"
