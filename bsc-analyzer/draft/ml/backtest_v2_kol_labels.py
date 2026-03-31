"""
Backtest v2: attach KOL-derived outcomes from ClickHouse (not DexScreener).

Reads token addresses from a file (e.g. backtest_results/tokens_*.txt) or stdin,
joins lumina.token_labels (from ml/compute_trades.py) and optional kol_swaps aggregates.

Usage:
  python ml/backtest_v2_kol_labels.py backtest_results/tokens_20260325_034824.txt
  cat addresses.txt | python ml/backtest_v2_kol_labels.py -

Requires: clickhouse-bin in PATH or CLICKHOUSE_BIN; populated lumina.kol_swaps + run compute_trades.py first.

Output: TSV to stdout with columns:
  token_address, label, total_kol_buyers, avg_pnl_pct, is_profitable, kol_swaps_rows, sample_logo
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")


def ch_query(clickhouse_bin: str, query: str) -> list[dict]:
    cmd = [clickhouse_bin, "client", "--query", f"{query} FORMAT JSONEachRow"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        sys.stderr.write(f"ClickHouse error: {result.stderr[:600]}\n")
        return []
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line:
            rows.append(json.loads(line))
    return rows


def extract_addresses_from_text(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in ADDR_RE.finditer(text):
        seen[m.group(0).lower()] = None
    return list(seen.keys())


def main() -> None:
    ap = argparse.ArgumentParser(description="Join token list with KOL outcome labels (ClickHouse)")
    ap.add_argument(
        "input",
        nargs="?",
        default="-",
        help="File path or - for stdin (tokens_*.txt or one address per line)",
    )
    ap.add_argument(
        "--clickhouse-bin",
        default=None,
        help="Default: CLICKHOUSE_BIN env or ./clickhouse-bin under project root",
    )
    args = ap.parse_args()
    ch_bin = args.clickhouse_bin or __import__("os").environ.get(
        "CLICKHOUSE_BIN", str(PROJECT_ROOT / "clickhouse-bin")
    )

    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text()

    tokens = extract_addresses_from_text(text)
    if not tokens:
        sys.stderr.write("No 0x addresses found in input.\n")
        sys.exit(1)

    quoted = ",".join(f"'{t}'" for t in tokens)
    # Labels
    q_labels = f"""
    SELECT
        lower(token_address) AS token_address,
        toString(label) AS label,
        total_kol_buyers,
        avg_pnl_pct,
        is_profitable
    FROM lumina.token_labels
    WHERE lower(token_address) IN ({quoted})
    """
    label_rows = {r["token_address"]: r for r in ch_query(ch_bin, q_labels)}

    # Swap coverage: row count + any logo
    q_swaps = f"""
    SELECT
        lower(token_address) AS token_address,
        count() AS kol_swap_rows,
        anyLast(token_logo) AS sample_logo
    FROM lumina.kol_swaps
    WHERE lower(token_address) IN ({quoted})
    GROUP BY token_address
    """
    swap_rows = {r["token_address"]: r for r in ch_query(ch_bin, q_swaps)}

    sys.stdout.write(
        "token_address\tlabel\ttotal_kol_buyers\tavg_pnl_pct\tis_profitable\tkol_swap_rows\tsample_logo\n"
    )
    for t in tokens:
        lb = label_rows.get(t, {})
        sw = swap_rows.get(t, {})
        sys.stdout.write(
            f"{t}\t{lb.get('label', 'NO_LABEL')}\t{lb.get('total_kol_buyers', 0)}\t"
            f"{lb.get('avg_pnl_pct', 0)}\t{lb.get('is_profitable', 0)}\t"
            f"{sw.get('kol_swap_rows', 0)}\t{(sw.get('sample_logo') or '')}\n"
        )

    sys.stderr.write(
        f"Joined {len(tokens)} tokens; labeled={len(label_rows)} with lumina.token_labels.\n"
        "If NO_LABEL for all, run: python ml/fetch_kol_swaps.py && python ml/compute_trades.py\n"
    )


if __name__ == "__main__":
    main()
