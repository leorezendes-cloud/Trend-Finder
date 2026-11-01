# Actual ATS v5 with player and scheme residual features

This tests the full supported player concept directly against the frozen PR #36 v5 model, not the earlier PF/PA baseline. Production v5 is unchanged. The v5 source is hash-checked against commit `cd491df29ebedd9ca626e879731261b26c05e613` using the existing loader. All 703 modern baseline projections and game identities exactly reproduce the prior v5 audit.

## Fixed experiment

Candidate margin = v5 away margin + a ridge adjustment trained on earlier actual scoring margin minus earlier v5 margin. V5 itself remains unchanged, including its original prior-season market-label training. The separate residual layer uses penalty 100, minimum 32 released training targets and the previously specified fixed features. Weekly predictions precede target release; earlier targets become eligible only after the stored six-hour game-end proxy plus 48 hours. No parameter search, pace, transferred score-band bonuses, or present-game market line in the adjustment fitting.

Variants progressively add eight team matchup features, then individual QB/WR/RB/TE production and positional matchups, then neutral PBP/protection proxies, then verified pressure/man/zone interactions. Player roles use prior historical usage, not confirmed future availability. Missing scheme samples are gated, not fabricated. Current cached seasons have no verified scheme exposure; full_available equals the PBP arm there. Historical charted evaluation uses a separate 2019 warmup.

## Modern cohort: ATS wins–losses–pushes

| Season | Games | Actual v5 | + team features | + players | + players/PBP | + all available scheme |
|---|---:|---|---|---|---|---|
| 2023 | 224 | 103–110–11 (48.36%) | 103–110–11 (48.36%) | 105–108–11 (49.30%) | 105–108–11 (49.30%) | 105–108–11 (49.30%) |
| 2024 | 224 | 118–103–3 (53.39%) | 118–103–3 (53.39%) | 112–109–3 (50.68%) | 112–109–3 (50.68%) | 112–109–3 (50.68%) |
| 2025 | 224 | 112–111–1 (50.22%) | 111–112–1 (49.78%) | 117–106–1 (52.47%) | 114–109–1 (51.12%) | 114–109–1 (51.12%) |
| 2026 | 31 | 19–10–2 (65.52%) | 18–11–2 (62.07%) | 18–11–2 (62.07%) | 19–10–2 (65.52%) | 19–10–2 (65.52%) |

## Historical verified charting cohort

All 655 evaluated games have verified pressure, man and zone interaction exposure on both sides. These older seasons are a separate diagnostic and do not override 2026 research priority.

| Season | Games | Actual v5 | + team features | + players | + players/PBP | + all available scheme |
|---|---:|---|---|---|---|---|
| 2020 | 208 | 119–89–0 (57.21%) | 119–89–0 (57.21%) | 118–90–0 (56.73%) | 119–89–0 (57.21%) | 119–89–0 (57.21%) |
| 2021 | 224 | 104–116–4 (47.27%) | 101–119–4 (45.91%) | 106–114–4 (48.18%) | 105–115–4 (47.73%) | 105–115–4 (47.73%) |
| 2022 | 223 | 107–108–8 (49.77%) | 111–104–8 (51.63%) | 109–106–8 (50.70%) | 108–107–8 (50.23%) | 107–108–8 (49.77%) |

## Same original v5-selected games

The original qualifying set stays fixed: absolute market spread >7 and strictly nonzero model/market gap <1. These are only selections within the eligible research cohort, not complete annual official records. No candidate-specific reselection is substituted.

| Season | Games | v5 | + players | + players/PBP | + all available scheme |
|---|---:|---|---|---|---|
| 2023 | 9 | 4–5–0 (44.44%) | 4–5–0 (44.44%) | 4–5–0 (44.44%) | 4–5–0 (44.44%) |
| 2024 | 11 | 7–4–0 (63.64%) | 6–5–0 (54.55%) | 5–6–0 (45.45%) | 5–6–0 (45.45%) |
| 2025 | 17 | 11–6–0 (64.71%) | 11–6–0 (64.71%) | 12–5–0 (70.59%) | 12–5–0 (70.59%) |
| 2026 | 2 | 1–1–0 (50.00%) | 1–1–0 (50.00%) | 1–1–0 (50.00%) | 1–1–0 (50.00%) |
| 2020 | 18 | 12–6–0 (66.67%) | 9–9–0 (50.00%) | 9–9–0 (50.00%) | 9–9–0 (50.00%) |
| 2021 | 21 | 9–11–1 (45.00%) | 8–12–1 (40.00%) | 9–11–1 (45.00%) | 9–11–1 (45.00%) |
| 2022 | 12 | 6–5–1 (54.55%) | 7–4–1 (63.64%) | 6–5–1 (54.55%) | 6–5–1 (54.55%) |

## Interpretation and limitations

No consistent ATS improvement. In the 31-game partial 2026 sample, v5 is 19–10–2; player features alone are 18–11–2, while adding PBP returns to 19–10–2. The full available model does not improve 2026 or the same two original selected games (both arms 1–1). Across 2023–25, players add two wins, lose six, then add five; PBP adds two, loses six, then adds two. Scheme charting provides no net win improvement over PBP in 2020/2021 and loses one in 2022. Keep the production model unchanged.

These are exploratory retrospective comparisons using corrected historical snapshots and archived closing spreads whose original quote capture times are not certified. The modern cohort is the original October 14 cache with 31 eligible 2026 games, not the latest/full season. First three team games are omitted for feature warmup. No X/Z/slot, YPRR, current coverage assignments, or individual WR-CB matching exists in these free cached inputs. Multiple exploratory variants have been examined; no claim of statistical significance or confirmed betting edge.

## Validation and resources

45 regression tests pass, including frozen v5 golden projections and source integrity; sign and weekly-cache behavior; exact replacement of the PF/PA baseline; nonfinite rejection; earlier-feature invariance; and a 45-week synthetic replay that verifies both the 32-target warmup and that changed future outcomes cannot affect their own/earlier predictions but do affect later trained predictions. Existing shared-engine regressions still pass. Modern cohort identity and all 703 baseline projections were independently checked against the prior saved v5 ledger. All per-game predictions, sides, results and scheme exposure are in hashed CSV ledgers.

- `v5_full_main`: 39.941 seconds; 94,027,776 bytes local process peak RSS; 22,474,752 bytes existing compact database.
- `v5_full_charted`: 37.259 seconds; 93,569,024 bytes local process peak RSS; 22,474,752 bytes existing compact database.

Both replays ran locally from existing caches, with no downloads or AI calls and no added production RAM/storage. These peak RSS values measure local offline processing, not a Render stress test. No production files, schedulers, forecasts or historical receipts were modified.

```sh
python -m research.player_scheme.v5_full --db /tmp/player-scheme-full.sqlite \
  --schedule research/checklist_runs/20261014T191622Z/schedule_input.csv \
  --model plug_ats_v5_model.py --output /tmp/v5_full_main.json
# For verified historical charting, add: --train-season 2019 --last-season 2022
```
