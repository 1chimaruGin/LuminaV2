# Narrowing the KOL edge — run outputs and rubric

Generated from `kol_backtest_30d_latest.jsonl` (813 tokens). Raw script outputs:

| Phase | File |
|-------|------|
| 1 — first-KOL baseline | `narrowing_phase1_analyze_backtest.txt` |
| 2 — slots 1 / 2 / 3 | `narrowing_phase2_slots_123.txt` |
| 3 — per-KOL × slot | `narrowing_phase3_analyze_by_slot.txt` |
| 4 — `kol_count >= 3` subset, slots 2 & 3 | `narrowing_phase4_kol_gte3_slots23.txt` |

Subset file: `kol_count_gte3.jsonl` (72 rows).

## Commands (repeat anytime)

```bash
cd bsc-analyzer
python3 scripts/analyze_backtest.py backtest_results/kol_backtest_30d_latest.jsonl top.json

for s in 1 2 3; do python3 scripts/analyze_after_kol_slot.py backtest_results/kol_backtest_30d_latest.jsonl --slot $s; done

python3 scripts/analyze_by_slot.py backtest_results/kol_backtest_30d_latest.jsonl top.json

python3 scripts/filter_kol_jsonl.py backtest_results/kol_backtest_30d_latest.jsonl backtest_results/kol_count_gte3.jsonl --min 3
python3 scripts/analyze_after_kol_slot.py backtest_results/kol_count_gte3.jsonl --slot 2
python3 scripts/analyze_after_kol_slot.py backtest_results/kol_count_gte3.jsonl --slot 3
```

## Snapshot findings (this run)

### Phase 1 — first buyer (`peak_x` vs first KOL entry)

- Best **Win≥2x** among listed first-buyer cohorts: **0x2ce9…3373** at **33%** (90 tokens); strong **AvgPeakX** 2.79x.
- **KOL count** matters strongly: 1 KOL **9%** Win≥2x vs **4+ KOLs ~94%** (small n=34).
- **Combined signal**: early entry + 3+ KOLs → **82%** Win≥2x (55 tokens) — headline first-touch stats, not sniper-after-slot.

### Phase 2 — sniper after KOL #1 / #2 / #3 (`plus_1_block`)

| Slot | n | Median peak_x | ≥2x hit | low_x &lt; 0.5 share |
|------|---|----------------|---------|----------------------|
| 1 | 813 | 1.16x | 14.9% | **41.2%** |
| 2 | 194 | 1.22x | 15.5% | **74.7%** |
| 3 | 72 | 1.35x | 20.8% | **72.2%** |

- After **KOL #1**, drawdowns are **less** frequent than after #2/#3 by this metric.
- After **KOL #2**, **≥2x** rate is not higher than slot 1 on the full set, but **median low_x is worse** (more path risk).

### Phase 4 — only tokens with **3+ KOLs** (72 rows), after KOL #2

- **Median peak_x** rises to **~1.64x**; **≥2x** about **35–38%** (`plus_1_block` / `plus_2_block`).
- **low_x &lt; 0.5** still **~72%** — upside can improve when you restrict to multi-KOL names, but **deep drawdowns remain common**.

### Phase 3 — who fills slot 2 (n≥17 for stability)

- **0x0851…5d3a**: slot_2 Win≥2x **24–29%**, AvgPx ~2.6x (n=17).
- **0xfe63…87b9**: slot_2 n=55, Win≥2x **22–24%**, AvgPx ~2.3x.
- **0x7a23…d2e6** as **2nd KOL**: slot_2 Win≥2x only **6%** (n=54) — weak in this slice.

Treat **n&lt;10** per-KOL lines as anecdotal.

## Rubric application (decide-slices)

| Criterion | Verdict |
|-----------|---------|
| Conditional hit rate vs global | **Yes** for “3+ KOLs” restriction on slot_2: **~35% ≥2x** vs **~15%** unconditional slot_2 on full 813. |
| Median peak_x | Moves up for **slot_3** vs **slot_2** on same 72 rows, and for **slot_2** on **kol_count≥3** vs all 194. |
| low_x / dump share | **Does not improve** meaningfully: **~72–75%** still hit low_x &lt; 0.5 after KOL #2/#3 in these slices. |
| Sample size | **72** tokens for gte3 is usable; per-KOL slot_2 **n** often **&lt;30** — use caution. |

**Conclusion:** The data support **narrowing** to **multi-KOL** situations for **better peak multiples and hit rates**, but **not** a free lunch: **path risk stays severe** in the same backtest. Live trading still depends on stops, size, liquidity, and execution — not in the JSONL.
