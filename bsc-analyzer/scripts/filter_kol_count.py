#!/usr/bin/env python3
"""Filter KOL dataset CSV/Parquet to rows with kol_count_final >= threshold (default 2)."""

import argparse
import sys

import pandas as pd


def main() -> None:
    p = argparse.ArgumentParser(description="Filter dataset by kol_count_final")
    p.add_argument(
        "--input",
        default="backtest_results/kol_dataset_90d_full.csv",
        help="Input CSV or Parquet path",
    )
    p.add_argument(
        "--output",
        default="",
        help="Output path (.csv or .parquet). Default: <input_stem>_kol2plus.<ext>",
    )
    p.add_argument(
        "--min-kol-count",
        type=int,
        default=2,
        help="Keep rows where kol_count_final >= this value (default: 2)",
    )
    args = p.parse_args()

    path = args.input
    if path.lower().endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    if "kol_count_final" not in df.columns:
        print("ERROR: column kol_count_final not found", file=sys.stderr)
        sys.exit(1)

    before = len(df)
    mask = pd.to_numeric(df["kol_count_final"], errors="coerce").fillna(0) >= args.min_kol_count
    out = df.loc[mask].copy()
    after = len(out)

    if args.output:
        out_path = args.output
    else:
        stem = path.rsplit(".", 1)[0]
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else "csv"
        if ext not in ("csv", "parquet"):
            ext = "csv"
        out_path = f"{stem}_kol{args.min_kol_count}plus.{ext}"

    if out_path.lower().endswith(".parquet"):
        out.to_parquet(out_path, index=False)
    else:
        out.to_csv(out_path, index=False)

    print(f"Read {before} rows from {path}")
    print(f"Wrote {after} rows (kol_count_final >= {args.min_kol_count}) to {out_path}")


if __name__ == "__main__":
    main()
