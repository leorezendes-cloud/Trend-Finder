# Unchanged ATS v5 plus one fixed matchup adjustment

This is the first experiment in this package using the user’s actual PR #36 v5 model as baseline. Earlier experiments used an independent PF/PA research baseline. No production module/formula, selection policy, receipt, publication or scheduler is modified.

## Frozen baseline and fixed candidate

Baseline commit: `cd491df29ebedd9ca626e879731261b26c05e613`. The model source is byte-identical to that PR36 file and is guarded by SHA-256 `0ff7b68e6b0a6649e7f0be9da08cd872c6a0d9274c207b1a6f13f80c213e25fe`. Original golden predictions reproduce for 2024 BUF–BAL, 2025 BAL–KC, and 2026 HOU–JAX / CAR–PHI. The test invokes the unchanged `projections` function once per target week; no reimplementation or new v5 training is substituted.

Candidate = unchanged v5 predicted away margin + previously tested combined passing/rushing away-score bonus − home-score bonus. No pace. No new fitting, threshold/bonus search, or choice based on which variant performs best here. Those pregame bonuses were already learned from earlier PF/PA score residuals, **not** from v5 residuals. This tests transfer of one fixed design and does not invalidate all possible player/matchup approaches.

V5 predicts market spread, not absolute team scores. Its returned away-spread sign is negated to obtain projected away margin before adding the score-bonus difference. Same archived line and final margin grade both predictions. Bonus ledger and schedule hashes must match their saved experiment manifest.

## All 703 original matchup-eligible games: ATS W–L–P

| Season | Games | Unchanged v5 | V5 + fixed matchup bonus | Changed decisions |
|---|---:|---:|---:|---:|
| 2023 | 224 | 103–110–11 (48.36%) | 99–114–11 (46.48%) | 32 |
| 2024 | 224 | 118–103–3 (53.39%) | 117–104–3 (52.94%) | 19 |
| 2025 | 224 | 112–111–1 (50.22%) | 112–111–1 (50.22%) | 38 |
| 2026 | 31 | 19–10–2 (65.52%) | 17–12–2 (58.62%) | 2 |

No No Calls occur in either full-cohort arm. Pushes are excluded from cover percentage. The added bonus loses four net wins in 2023, one in 2024, none in 2025, and two in the partial 2026 sample. This specific transfer does not improve v5.

## Same original v5-selected games

Freeze the original qualifying set: Vegas favorite >7 points, nonzero model/market difference strictly below 1 point. Compare candidate sides on exactly that set. This is an apples-to-apples prediction comparison, not a new published selection strategy; the candidate may no longer satisfy the selection gate after adjustment.

| Season | Original selected games in this cohort | Unchanged v5 | Fixed bonus, same games | Still qualify after bonus |
|---|---:|---:|---:|---:|
| 2023 | 9 | 4–5–0 (44.44%) | 5–4–0 (55.56%) | 7 |
| 2024 | 11 | 7–4–0 (63.64%) | 4–7–0 (36.36%) | 7 |
| 2025 | 17 | 11–6–0 (64.71%) | 12–5–0 (70.59%) | 3 |
| 2026 | 2 | 1–1–0 (50.00%) | 0–2–0 (0.00%) | 2 |

A secondary report in JSON reapplies the unchanged selection rule independently to adjusted predictions. That uses different cohorts, so it is not substituted for the fixed-game comparison or used to select a winning method.

## Every changed 2026 pick

| Game | Original v5 | Adjusted pick | V5 margin (away − home) | Bonus to margin | Adjusted margin | Original selected? |
|---|---|---|---:|---:|---:|---|
| 2026_04_TEN_BAL | TEN +11.5 (Win) | BAL -11.5 (Loss) | -10.810 | -1.382 | -12.192 | True |
| 2026_05_LV_NE | NE -3.5 (Win) | LV +3.5 (Loss) | -4.791 | +1.483 | -3.308 | False |

2026 is still the same 31-game October 14 cache, not the latest season/full-year record. The primary cohort omits the first three team games needed for matchup inputs. These are retrospective research comparisons, **not official Plug records**. Corrected historical inputs and original closing-quote capture times are not timestamp-certified. This experiment does not alter 2026 research priority based on earlier seasons.

## Reproduction and validation

```sh
python -m research.player_scheme.v5_matchup --model plug_ats_v5_model.py \
  --schedule research/checklist_runs/20261014T191622Z/schedule_input.csv \
  --source research/player_scheme/score_bands_results.games.csv \
  --output /tmp/v5_matchup_results.json
python -m unittest research.player_scheme.test_engine research.player_scheme.test_ats research.player_scheme.test_full_ats research.player_scheme.test_score_bands research.player_scheme.test_pace research.player_scheme.test_v5_matchup -q
```

External local model/schedule paths may be supplied for tests using V5_MODEL_PATH / V5_SCHEDULE_PATH. CI uses repository files. The frozen model hash gate fails closed if a future version differs. Forty tests pass locally, including four golden model predictions, no-effect zero bonus, spread signs, strict selection boundaries, pushes/no-calls, model integrity, and invariance when target-week/future results, QB labels and market lines are changed. All changed games are listed by season in JSON, and every projection, bonus, side and outcome is in the hashed CSV.

Replay took 5.484 seconds with 89,325,568 bytes local peak RSS. No downloads, AI generation, production deployment or schema changes. Recommendation: retain unchanged v5; do not promote this fixed bonus transfer.
