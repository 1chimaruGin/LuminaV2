# KOL dataset — label and entry definitions (frozen for train / backtest / live join)

Use this spec whenever you **build historical CSVs**, **label live rows**, or **compare metrics**. If definitions drift, OOF AUC and live PnL will not be comparable.

## Entry event

- **Entry** is defined at the **second KOL buy** (kol2 / slot 2) on the token, consistent with `kol_count_at_entry >= 2` rows in the training slice (`kol_dataset_90d_full_kol2plus.csv`).
- **Features** must be computable from chain/RPC state **at or before** that event (no future peaks, no post-entry holder counts unless explicitly defined as “at entry”).

## Primary label: `peak_mult_vs_slot2_entry`

- **Meaning**: Peak price multiple **after** the slot-2 entry, relative to the **entry price at slot 2** (same baseline as the historical enrichment pipeline).
- **Training target** (default): `peak_mult_vs_slot2_entry >= 2.0` → positive class for `train_kol_scorer.py` (`--target 2x`).
- **Source of truth for historical data**: the script / pipeline that produced [`backtest_results/kol_dataset_90d.csv`](../backtest_results/kol_dataset_90d.csv) and filtered slices — keep the same peak window and price source when refreshing.

## Secondary outcomes (rows may be empty until labeled)

- **`graduated`**: bonding curve / Four.meme graduation flag per your enricher.
- **Live rows** from [`services/live_dataset_collector.py`](../services/live_dataset_collector.py): outcome columns start empty; **backfill** using the same formulas as the 90d builder before appending to the training CSV.

## Schema

- Column order and names for live append should match [`scripts/kol_dataset_schema.py`](../scripts/kol_dataset_schema.py) (`live_csv_columns`).

## Growing the dataset

1. Run historical build periodically → new labeled rows.
2. Append **live** CSV/JSONL rows only **after** backfilling `peak_mult_vs_slot2_entry` (and related fields) with the same definitions.
3. Use [`scripts/merge_kol_labeled_csv.py`](../scripts/merge_kol_labeled_csv.py) to merge CSVs and dedupe on `(token_address, create_block)`.
