#!/usr/bin/env python3
"""
Point-in-time Four.meme deployer reputation on an existing dataset CSV/Parquet.

Fixes missing/wrong deployer_prior_* columns and the empty CSV header for
deployer_prior_launches. Optionally writes data/deployers_fourmeme.csv for C++.

Usage:
  python scripts/compute_deployer_reputation.py \\
    --input backtest_results/kol_dataset_90d_full.csv \\
    --output backtest_results/kol_dataset_90d_full.csv

  python scripts/compute_deployer_reputation.py -i data.csv -o out.csv \\
    --also-write-deployers-csv data/deployers_fourmeme.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)


def _load_repo_dotenv() -> None:
    path = os.path.join(_REPO_ROOT, ".env")
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
    except ImportError:
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as ef:
            for line in ef:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v


from deployer_reputation import (  # noqa: E402
    apply_point_in_time_to_records,
    cpp_csv_row_from_snapshots,
    load_csv_records,
    row_to_snapshot,
)


def dataframe_to_records(df) -> list:
    import pandas as pd

    df = df.replace({pd.NA: None})
    return df.to_dict(orient="records")


def records_to_dataframe(records: list, original_columns: list | None):
    import pandas as pd

    df = pd.DataFrame(records)
    extra = [
        "deployer_prior_avg_peak_mult",
        "deployer_prior_win_rate",
        "deployer_rug_proxy_rate",
        "deployer_reputation_score",
    ]
    if original_columns:
        for c in extra:
            if c not in original_columns:
                original_columns.append(c)
        cols = [c for c in original_columns if c in df.columns]
        rest = [c for c in df.columns if c not in cols]
        df = df[cols + rest]
    return df


def merge_column_order(orig_cols: list[str], records: list[dict]) -> list[str]:
    extra = [
        "deployer_prior_avg_peak_mult",
        "deployer_prior_win_rate",
        "deployer_rug_proxy_rate",
        "deployer_reputation_score",
    ]
    order: list[str] = []
    seen: set[str] = set()
    for c in orig_cols:
        if c not in seen:
            order.append(c)
            seen.add(c)
    keys_in_data: set[str] = set()
    for r in records:
        keys_in_data.update(r.keys())
    for c in extra:
        if c in keys_in_data and c not in seen:
            order.append(c)
            seen.add(c)
    for c in sorted(keys_in_data - seen):
        order.append(c)
    return order


def fmt_csv_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


def write_csv_output(path: str, records: list[dict], column_order: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=column_order, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow({k: fmt_csv_cell(r.get(k)) for k in column_order})


def write_deployers_csv(path: str, records: list) -> None:
    by_c: dict[str, list] = defaultdict(list)
    for rec in records:
        c = (rec.get("creator") or "").lower()
        if c:
            by_c[c].append(row_to_snapshot(rec))

    fieldnames = [
        "deployer",
        "total_tokens",
        "rugged",
        "honeypots",
        "successful",
        "avg_lifespan_hours",
        "success_rate",
        "rug_rate",
        "score",
        "first_seen_block",
        "last_seen_block",
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for addr in sorted(by_c.keys()):
            w.writerow(cpp_csv_row_from_snapshots(addr, by_c[addr]))
    print(f"Wrote {path} ({len(by_c)} deployers)", file=sys.stderr)


def load_input(inp: str) -> tuple[list, list[str]]:
    if inp.lower().endswith(".parquet"):
        try:
            import pandas as pd
        except ImportError as e:
            print("Parquet input requires pandas: pip install pandas", file=sys.stderr)
            raise SystemExit(1) from e
        df = pd.read_parquet(inp)
        new_cols = []
        for c in df.columns:
            if c == "" or (isinstance(c, str) and c.strip() == ""):
                new_cols.append("deployer_prior_launches")
            else:
                new_cols.append(c)
        df.columns = new_cols
        orig_cols = list(df.columns)
        return dataframe_to_records(df), orig_cols
    records, orig_cols = load_csv_records(inp)
    return records, orig_cols


def main():
    p = argparse.ArgumentParser(description="Four.meme point-in-time deployer reputation")
    p.add_argument("--input", "-i", required=True, help="Input CSV or Parquet")
    p.add_argument("--output", "-o", required=True, help="Output CSV or Parquet")
    p.add_argument(
        "--also-write-deployers-csv",
        default="",
        help="Also write C++-compatible deployers CSV (aggregate over full input)",
    )
    _load_repo_dotenv()
    args = p.parse_args()

    inp = args.input
    records, orig_cols = load_input(inp)
    print(f"Loaded {len(records)} rows", file=sys.stderr)
    apply_point_in_time_to_records(records)

    outp = args.output
    same = os.path.abspath(inp) == os.path.abspath(outp)

    if outp.lower().endswith(".parquet"):
        try:
            import pandas as pd
        except ImportError as e:
            print("Parquet output requires pandas", file=sys.stderr)
            raise SystemExit(1) from e
        out_df = records_to_dataframe(records, orig_cols)
        if same:
            tmp = outp + ".tmp"
            out_df.to_parquet(tmp, index=False)
            os.replace(tmp, outp)
        else:
            out_df.to_parquet(outp, index=False)
    else:
        col_order = merge_column_order(orig_cols, records)
        if same:
            tmp = outp + ".tmp"
            write_csv_output(tmp, records, col_order)
            os.replace(tmp, outp)
        else:
            write_csv_output(outp, records, col_order)

    print(f"Wrote {outp}", file=sys.stderr)

    if args.also_write_deployers_csv:
        write_deployers_csv(args.also_write_deployers_csv, records)


if __name__ == "__main__":
    main()
