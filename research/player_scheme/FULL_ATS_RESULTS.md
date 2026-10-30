# Expanded player and scheme ATS experiment

Research only. All comparisons use identical archived closing spreads and pregame-cutoff features. Corrected historical data and original quote times are not independently certified. No Scout, Plug or official forecast is changed.

Fixed ablations: baseline; original limited team features; individual player production and positional mismatches; neutral PBP/protection proxies; then verified pressure/man/zone interactions. Prior QB selection uses recent attempts, WR/TE roles use recent targets, RB roles use recent carries. These are historical role proxies, not injury reports or confirmed future starters. No penalty, edge threshold or feature subset was selected using these results.

## Same original modern cohort

| Season | Baseline W–L–P | Limited | + Players | + PBP | + Available charting |
|---|---:|---:|---:|---:|---:|
| 2023 | 96–114–11 (45.71%) | 95–118–11 (44.60%) | 103–110–11 (48.36%) | 103–110–11 (48.36%) | 103–110–11 (48.36%) |
| 2024 | 104–117–3 (47.06%) | 102–119–3 (46.15%) | 113–108–3 (51.13%) | 111–110–3 (50.23%) | 111–110–3 (50.23%) |
| 2025 | 120–103–1 (53.81%) | 117–106–1 (52.47%) | 107–116–1 (47.98%) | 107–116–1 (47.98%) | 107–116–1 (47.98%) |
| 2026 | 18–11–2 (62.07%) | 18–11–2 (62.07%) | 19–10–2 (65.52%) | 19–10–2 (65.52%) | 19–10–2 (65.52%) |

2023 baseline has three No Calls. All other modern variant/season combinations have none. Pushes and No Calls are excluded from cover rate. All four modern seasons have zero fully charted games: the final column is a missing-scheme fallback, not evidence that 2026 coverage schemes were observed. PBP exists for every eligible game. 2026 is only the original 31-game October 14 cache cohort; the increased record is one additional win, not validated live improvement.

## Independently charted historical cohort

2019 is training warmup; 2020–2022 are chronological evaluations. This is a different training start from the modern experiment. All evaluated games have both offenses/defenses covered for the three charted interactions.

| Season | Games | Baseline | Players + PBP | + Verified pressure/man/zone |
|---|---:|---:|---:|---:|
| 2020 | 208 | 118–89–0 (57.00%) | 122–86–0 (58.65%) | 122–86–0 (58.65%) |
| 2021 | 224 | 108–112–4 (49.09%) | 104–116–4 (47.27%) | 105–115–4 (47.73%) |
| 2022 | 223 | 118–96–8 (55.14%) | 116–99–8 (53.95%) | 117–98–8 (54.42%) |

Historical baseline additionally has one No Call in 2020 and one in 2022. Charting adds no wins over PBP in 2020, one in 2021 and one in 2022. The combined model still trails the basic baseline in 2021 and 2022. Results are mixed; there is no reliable across-season ATS improvement or basis for production promotion. No significance, profit, or pristine holdout claim is made.

## Coverage, resources and reproduction

Verified charting terms: prior QB EPA under pressure × opponent five-plus-rusher rate; prior QB EPA against man × opponent man rate; prior QB EPA against zone × opponent zone rate. Every interaction needs both player and opponent observed samples; otherwise it contributes zero and coverage is marked unavailable. Five-plus rushers is not relabeled as a verified blitz. The earlier 20/30/40-opportunity shrinkage priors and ridge penalty 100 remain fixed.

Unsupported: current-season blitz/man/zone without a source, X/Z/slot alignment, YPRR, individual WR–CB assignments and expected injury availability. This evaluates every supported concept, not these missing statistics. Cached participation is from 2019–2022; no current-season scheme fields were invented.

Modern replay: 34.66 seconds, 77,725,696 bytes peak RSS.
Historical charted replay: 33.854 seconds, 73,908,224 bytes peak RSS.

Eight-season compact store: 22,474,752 bytes. Additional reader peak: 24,707,072 bytes, below 25 MiB across 12 current/full-season/full-charted reads. Historical charting processing stays offline; no Render deployment was performed. The reader was optimized to retain league team/player rows but only relevant PBP/charting units and known player IDs (including prior-team history).

27 regression tests pass locally. Numerical equivalence of cached ridge to the original solver is tested. Original modern baseline/limited ATS records reproduce exactly, and complete game ledgers before/after the memory filter are byte-identical.

```sh
python -m research.player_scheme.prepare_full_cached --repository /path/to/Trend-Finder \
  --source-db /tmp/player-audit/features.sqlite --output /tmp/player-full.sqlite
python -m research.player_scheme.full_ats --db /tmp/player-full.sqlite \
  --schedule research/checklist_runs/20261014T191622Z/schedule_input.csv \
  --train-season 2022 --last-season 2026 --output /tmp/modern.json
# Repeat with --train-season 2019 --last-season 2022 for historical verified charting.
python -m unittest research.player_scheme.test_engine research.player_scheme.test_ats research.player_scheme.test_full_ats -q
```

Full specifications, season counts, exposure coverage and separate charted-cohort records are in `full_ats_main.json` / `full_ats_charted.json`. Game ledgers and their hashes accompany each JSON; source hashes are in `full_sources.json`. Raw data and databases remain external to git.
