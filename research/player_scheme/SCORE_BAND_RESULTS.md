# Threshold-based projected-score adjustments

This explicitly changes each team’s predicted points, then recomputes margin and total. Research only; no production formula, schedule, selection or published pick changes.

## Fixed experiment

Qualifying passing/rushing mismatch requires the opponent-adjusted offensive residual and opponent defensive-allowance residual to agree in sign. Strength is the weaker absolute residual. Fixed EPA/opportunity bands: below 0.025 = none; 0.025–0.075 = moderate; 0.075–0.15 = strong; 0.15+ = exceptional. Unfavorable bands subtract points. No target-season threshold tuning.

Point values are learned from earlier team-score residuals, scaled by relative pass/rush volume. Minimum 20 prior team observations per magnitude band; ridge penalty 30. Nonnegative coefficients enforce the intended direction, with symmetric favorable/adverse magnitudes. Each passing/rushing adjustment is capped at 3 points; the combined adjustment at 4 points. These are experimental constraints, not validated universal football values. The combined model jointly fits six coefficients to avoid adding overlapping independently estimated effects. No extra home-field bonus is introduced.

2022 supplies warmup; every 2023–2026 game in the unchanged original eligible cohort is reported. Scores are generated before outcomes enter calibration; availability delay is 48 hours after a six-hour estimated game end, with the target week’s earliest kickoff as cutoff. This is retrospective corrected-source research, and original closing-line capture times remain unverified.

## ATS W–L–P

| Season | Basic baseline | Passing bonus | Rushing bonus | Combined bonus |
|---|---:|---:|---:|---:|
| 2023 | 96–114–11 (45.71%) | 93–117–11 (44.29%) | 96–116–11 (45.28%) | 94–118–11 (44.34%) |
| 2024 | 104–117–3 (47.06%) | 108–113–3 (48.87%) | 101–120–3 (45.70%) | 110–111–3 (49.77%) |
| 2025 | 120–103–1 (53.81%) | 118–105–1 (52.91%) | 117–106–1 (52.47%) | 116–107–1 (52.02%) |
| 2026 | 18–11–2 (62.07%) | 18–11–2 (62.07%) | 18–11–2 (62.07%) | 18–11–2 (62.07%) |

2023 No Calls: baseline 3, passing 3, rushing 1, combined 1. Other seasons have none. Pushes/No Calls are excluded from cover percentage. The original baseline ATS records reproduce exactly.

## Totals W–L–P

| Season | Basic baseline | Passing bonus | Rushing bonus | Combined bonus |
|---|---:|---:|---:|---:|
| 2023 | 113–109–2 (50.90%) | 118–104–2 (53.15%) | 111–111–2 (50.00%) | 117–105–2 (52.70%) |
| 2024 | 119–102–3 (53.85%) | 117–104–3 (52.94%) | 117–104–3 (52.94%) | 115–106–3 (52.04%) |
| 2025 | 108–116–0 (48.21%) | 114–110–0 (50.89%) | 104–120–0 (46.43%) | 109–115–0 (48.66%) |
| 2026 | 10–21–0 (32.26%) | 10–21–0 (32.26%) | 8–23–0 (25.81%) | 9–22–0 (29.03%) |

The partial 2026 cohort remains 31 games from the October 14 cache, not the latest season record. Combined bonuses changed projected scores in 24 games but changed zero ATS sides and five totals sides. ATS remained 18–11–2; totals worsened from 10–21 to 9–22. Across years, combined ATS improved in 2024 and worsened in 2023/2025. This fixed design does not establish improvement.

## Learned point values used at the last available 2026 cutoff

At unit volume multiplier; negative mismatch bands reverse the sign. These values were learned only from earlier outcomes, not fitted to the target game.

| Mismatch magnitude | Passing-only points | Rushing-only points | Joint passing points | Joint rushing points |
|---|---:|---:|---:|---:|
| Moderate | 1.644 | 0.884 | 1.615 | 0.784 |
| Strong | 1.170 | 1.052 | 1.067 | 0.895 |
| Exceptional | 0.254 | 0.000 | 0.150 | 0.000 |

The learned point schedule is not monotonic: larger EPA mismatches did not consistently support larger score bonuses. Exceptional rushing has zero prior observations and therefore no bonus. Forcing larger bonuses after seeing results would introduce hindsight selection.

Example (2026 Week 4 LAC at SEA): baseline LAC 19.77, SEA 23.85; combined adjustments −2.08 and −0.74 produce LAC 17.70, SEA 23.10. The ATS choice stays LAC +7 (Push), while the total flips from Over 42.5 (Win) to Under (Loss). This illustrates actual score changes, not a selected successful forecast.

## Reproduction and validation

```sh
python -m research.player_scheme.score_bands --db /tmp/player-scheme-full.sqlite \
  --schedule research/checklist_runs/20261014T191622Z/schedule_input.csv \
  --output /tmp/score_bands_results.json
python -m unittest research.player_scheme.test_engine research.player_scheme.test_ats research.player_scheme.test_full_ats research.player_scheme.test_score_bands -q
```

32 tests pass locally. Tests cover gates, signs, exact boundaries, sample minimum, learned versus forced point values, joint cap, totals grading, and future-outcome/line invariance with an actively adjusting calibration model. Full calibration histories and source-line hash are in `score_bands_results.json`; every projected score, adjustment, band and ATS/O-U decision is preserved in its companion hashed CSV. No raw data/database is committed.

Replay elapsed 30.767 seconds; peak RSS 76,218,368 bytes locally. Inputs reuse the existing full cached research DB and source manifests; no downloads or AI generation. Results are exploratory, not an official betting record or a production promotion recommendation.
