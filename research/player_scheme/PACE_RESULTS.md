# Pace and projected-score experiment

Research only. No Scout/Plug formulas, published picks, receipts, schedulers or UI changes. Uses existing checksum-verified cached PBP, with no new downloads. All 703 original games have sufficient earlier pace data; no games were dropped. Original baseline and matchup-only ATS/O-U records reproduce exactly.

## Fixed calculation

Cadence is neutral **game-clock seconds between consecutive scrimmage snaps**, not tracking-derived time-to-snap. Only same offense/drive/quarter pairs, quarters 1–3, both preplay win probabilities 20–80%, outside the half’s final two minutes, with a 1–60 second clock gap are admitted. Timeouts, intervening penalty/stoppage rows, incompletions, visible out-of-bounds plays, kneels and spikes break pairs. The lead operation runs on all events before filtering. Unknown drive IDs never count as possessions.

Each team cadence is shrunk with 60 league-average pairs. League-average possessions are scaled by league cadence / the average cadence of the two teams. This is a structural hypothesis, not a fitted or validated causal law. Baseline embedded possessions are the average of the offense’s prior drives and opponent-defense drives allowed, each shrunk with four league games. At least three prior games and 20 neutral pairs are required. All use the same pregame cutoff and conservative availability delay as earlier research.

The pace multiplier divides projected possessions by each side’s embedded historical possession rate, capped at 0.85–1.15. Baseline points are multiplied by that ratio; **only excess/deficit relative to embedded baseline pace is applied**. Conservative variants use half the deviation from 1. Combined variants scale both the baseline score and existing learned matchup bonus. No cutoff, cap or shrinkage strength was selected using the resulting records.

Effective points per possession include defensive/special-teams scoreboard points and therefore are not isolated offensive efficiency estimates. Offensive drives omit kneel/spike-only possessions and overtime. Neutral cadence excludes fourth-quarter strategy, while possession projection extrapolates to regulation; that approximation is explicitly experimental. Raw historical publication and original market quote times are not certified.

## ATS W–L–P

| Season | Baseline | Matchup only | Pace direct | Pace conservative | Pace + matchup | Conservative + matchup |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | 96–114–11 (45.71%) | 94–118–11 (44.34%) | 96–117–11 (45.07%) | 95–118–11 (44.60%) | 96–117–11 (45.07%) | 96–117–11 (45.07%) |
| 2024 | 104–117–3 (47.06%) | 110–111–3 (49.77%) | 107–114–3 (48.42%) | 105–116–3 (47.51%) | 111–110–3 (50.23%) | 112–109–3 (50.68%) |
| 2025 | 120–103–1 (53.81%) | 116–107–1 (52.02%) | 119–104–1 (53.36%) | 120–103–1 (53.81%) | 116–107–1 (52.02%) | 115–108–1 (51.57%) |
| 2026 | 18–11–2 (62.07%) | 18–11–2 (62.07%) | 18–11–2 (62.07%) | 18–11–2 (62.07%) | 19–10–2 (65.52%) | 18–11–2 (62.07%) |

2023 baseline has 3 No Calls; matchup-only has 1. Other 2023 pace variants have none. Other seasons have none. Pushes and No Calls are excluded from cover percentage. These are research-model records, not official Plug/ATS v5 records.

## Totals W–L–P

| Season | Baseline | Matchup only | Pace direct | Pace conservative | Pace + matchup | Conservative + matchup |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | 113–109–2 (50.90%) | 117–105–2 (52.70%) | 112–110–2 (50.45%) | 114–108–2 (51.35%) | 108–114–2 (48.65%) | 117–105–2 (52.70%) |
| 2024 | 119–102–3 (53.85%) | 115–106–3 (52.04%) | 118–103–3 (53.39%) | 116–105–3 (52.49%) | 118–103–3 (53.39%) | 119–102–3 (53.85%) |
| 2025 | 108–116–0 (48.21%) | 109–115–0 (48.66%) | 109–115–0 (48.66%) | 108–116–0 (48.21%) | 115–109–0 (51.34%) | 113–111–0 (50.45%) |
| 2026 | 10–21–0 (32.26%) | 9–22–0 (29.03%) | 8–23–0 (25.81%) | 9–22–0 (29.03%) | 10–21–0 (32.26%) | 8–23–0 (25.81%) |

## How much did the score change?

| Season | Pace alone: mean absolute points/team | Pace + matchup: mean absolute points/team |
|---|---:|---:|
| 2023 | 0.485 | 0.779 |
| 2024 | 0.629 | 0.947 |
| 2025 | 0.578 | 0.966 |
| 2026 | 0.437 | 0.873 |

The same partial 2026 October 14 cohort has 31 games. Pace-only moves a team projection by 0.437 points on average (largest absolute change 1.374 points). Adding pace to matchup bonuses moves scores by 0.873 points on average relative to baseline and changes one ATS side: DEN at LAC, Week 5, from LAC +2.5 (Loss) to DEN −2.5 (Win). Example baseline scores DEN 22.80 / LAC 21.62 become DEN 22.74 / LAC 19.97 with pace plus bonuses. This is one net win in an exploratory small sample, not confirmation of an edge.

Direct pace + matchup totals in 2026 remain 10–21, equal to baseline; conservative + matchup is 8–23. Across 2023–2025 the direct combined model improves ATS in 2024, worsens in 2025 and takes losing calls on games the baseline passed in 2023. No consistent advantage or production promotion is established. Six predeclared variants are fully reported; none is promoted based on its best year.

## Reproduction and validation

```sh
python -m research.player_scheme.prepare_pace_cached --repository /path/to/Trend-Finder \
  --source-db /tmp/player-scheme-full.sqlite --output /tmp/player-pace.sqlite
python -m research.player_scheme.pace_experiment --db /tmp/player-pace.sqlite \
  --source research/player_scheme/score_bands_results.games.csv --output /tmp/pace_results.json
python -m unittest research.player_scheme.test_engine research.player_scheme.test_ats research.player_scheme.test_full_ats research.player_scheme.test_score_bands research.player_scheme.test_pace -q
```

36 tests pass locally. Pace tests cover intervening timeouts/stoppages, incompletions, out-of-bounds, possession changes, garbage time, final-two-minute exclusion, duplicate play keys, sample minimums, future-data exclusion, and avoiding pace double-counting. Every game’s cadence, baseline/expected possessions, ratios, projected scores and ATS/O-U outcomes are in the hashed CSV. JSON includes the exact specification, score-ledger hash and season summaries; `pace_sources.json` preserves source hashes. Raw archives/databases remain external to git.

Replay took 0.887 seconds with 31,096,832 bytes peak RSS. Expanded database: 22,990,848 bytes. These local measurements are not a Render stress test; no production changes were made.
