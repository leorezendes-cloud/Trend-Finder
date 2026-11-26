# ATS research results

Retrospective corrected inputs and archived closing lines. Original pregame quote capture times are NOT verified; this is not an official or timestamp-certified betting record.

Baseline and enhancement are independent research models, not ATS v5 or live Plug picks. Uses unchanged margin formulas and chronological fitting, with the same archived closing line for both models. No edge threshold was searched.

| Season | Baseline W–L–P | Baseline cover | Enhanced W–L–P | Enhanced cover | Changed decisions |
|---|---:|---:|---:|---:|---:|
| 2023 | 96–114–11 | 45.71% | 95–118–11 | 44.60% | 5 |
| 2024 | 104–117–3 | 47.06% | 102–119–3 | 46.15% | 6 |
| 2025 | 120–103–1 | 53.81% | 117–106–1 | 52.47% | 3 |
| 2026 | 18–11–2 | 62.07% | 18–11–2 | 62.07% | 0 |

2023 baseline additionally has three exact model/market agreements (No Call). Enhanced model takes those games. The JSON also reports the matched cohort where both models make a call. Pushes and No Calls are excluded from cover percentage.

2026 is only the original October 14 cached cohort: 31 eligible games after warmup, not the latest season record. Both models chose identical ATS sides in that cohort. In 2023–2025 the enhancement reduced cover rate. No live model changes are justified.

Reproduction:

```sh
python -m research.player_scheme.ats --db /tmp/player-audit/features.sqlite \
  --schedule research/checklist_runs/20261014T191622Z/schedule_input.csv \
  --output /tmp/ats_results.json
python -m unittest research.player_scheme.test_engine research.player_scheme.test_ats -q
```

The game-level ledger in `ats_results.games.csv` preserves source hash, prediction cutoff, both model margins, shared line, picked sides and outcomes. Replay MAEs were checked against the original experiment to 1e-9. Twenty-one tests pass locally, including spread signs, favorites/underdogs, pick’em, pushes, no-calls, and invariance to future outcomes or market inputs.
