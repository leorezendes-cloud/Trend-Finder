# Player and scheme matchup research

Independent, offline research only. Nothing imports this package from the application.
No Scout/Plug formula, receipt, selection, publication, scheduler, or UI changes. No automatic
model promotion or change in research priority for 2026. No AI generation or paid APIs.

## Sources and existing integrations

Reuses the same nflverse player/team weekly schema already used by `player_team_stats.py`
and existing Scout 4.1 research, without importing or modifying either system. `run_cached`
reads existing local CSV/Parquet snapshots, checks the PBP sidecar SHA-256, and records
source URLs, capture times, hashes, season, and admitted row counts. It never downloads,
mutates those inputs, or copies full PBP into the database. The CSV source cohort and its
folder timestamp are declared provenance, **not independently verified publication dates**.

Primary references:

- [nflverse datasets](https://github.com/nflverse/nflverse-data/releases): weekly player/team
  production, schedule, play-by-play, optional participation. Existing repository cached
  inputs are the source of the checked-in evaluation, not a new current-feed capture.
- [Player stats](https://nflreadr.nflverse.com/reference/load_player_stats.html) and
  [play-by-play](https://nflreadr.nflverse.com/reference/load_pbp.html).
- [Availability schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html):
  corrections arrive after games; participation from 2023 onward is released after the
  postseason, not during the season. Never infer live scheme coverage from those files.
- [Participation dictionary](https://nflreadr.nflverse.com/articles/dictionary_participation.html):
  verified `was_pressure`, number of pass rushers, man/zone, with exact game/play joins.
  Attribute historical participation to NFL Next Gen Stats via nflverse (through 2022),
  or FTN Data via nflverse (2023+), under its CC-BY-SA 4.0 terms. Review each dataset's
  upstream license before distributing derived exports. No raw datasets are committed.

Optional NGS/PFR datasets are useful future extensions; they are **not ingested** by this
foundation. No automatic web scraping, recurring download job, or new worker is installed.
Operators can supply new local source snapshots to the explicit ingest command.

## Supported measurements

- Stable GSIS player IDs; team/opponent checked against the schedule; no fuzzy name joins.
  Historical team aliases normalize explicitly. Prior players transfer only after observed
  new-team participation; availability/injury status is always unknown.
- QB passing yards, completions, attempts, EPA/attempt; RB carries/rushing yards; WR/RB/TE
  targets, receptions, receiving yards, target share, yards/target and catch rate.
- Last four player-game averages; last three team-game efficiency versus season-window
  efficiency. Window is 180 days, preventing indefinitely stale profiles.
- Team passing/rushing tendencies, offensive EPA/attempt or carry, defensive EPA allowed,
  sample counts and shrinkage toward league levels. Opponent adjustments subtract the
  opposing unit's prior-window rate and shrink residuals with 40 opportunities.
- Position-group receiving production and yards allowed per defense game (QB/RB/WR/TE),
  shrunk with four league-average game equivalents. Position allowances are descriptive
  shrunk rates, not independently opponent-adjusted causal estimates.
- PBP neutral situations: first three quarters, preplay win probability 20–80%, valid
  run/pass plays. EPA/dropback, EPA/run, CPOE, sack rates, QB-hit rates, QB-hit EPA response.
  **QB hits and sacks are protection/pass-rush proxies, not complete pressure counts.**
- Optional historical participation: verified pressure EPA, man rate, five-plus-rusher
  rate. Missing charting produces zero exposure, not a claim that no pressure occurred.
  Five-plus rushers is a measurable count and is not renamed "blitz".

Rates return exposure, admitted games, and missing-game counts. With zero exposure the
numeric value is a prior only and must never be presented as measured evidence. The CLI
provides numeric diagnostics rather than unvalidated betting picks or mismatch thresholds.

Unavailable: receiver X/Z/slot alignment, full routes-run denominators/YPRR, individual
WR–CB assignments, verified current blitz rates, current scheme coverage without a source,
pass-block win rates, and injury/availability projections. Pass location does not identify
receiver alignment. Team TE allowance does not identify the responsible defender.

## Cutoffs and evaluation

`observed` is the default. Observations must precede the cutoff by both their recorded
capture time and a conservative availability delay: kickoff + six hours estimated game
end + 48 hours. Same-game, future, unknown kickoff, non-final and late-captured facts are
excluded. Capture timestamps are caller-attested provenance, not proof of original
publication. The output never claims certified historical publication.

`retrospective` must be explicitly chosen to evaluate corrected historical archives. It
uses the same event delay but cannot reconstruct original publication/correction vintages.
The checked-in backtest is explicitly **retrospective**, not a timestamp-certified replay.

2022 warms up the expanding residual models; every available 2023–2026 REG season is
reported, with three prior team games required. Features use the earliest kickoff in a
week, conservatively excluding even earlier games in the same week. Outcomes only enter
training after the delay (and after recorded capture in observed mode). Models never fit
on the game being predicted. Coefficients carry forward across years without target-year
selection or tuning. No 2024/2025 performance overrides 2026 research priority.

Baseline: an independent shrunk points-for/points-allowed team model, not a replay of
production ATS v5, O/U v14, or saved Scout forecasts. Enhancement: fixed ridge penalty
100 on away/home opponent-adjusted pass/rush EPA, recent pass EPA delta, and TE allowance
residual. PBP/charting features are diagnostic outputs; **their incremental predictive
value has not yet been evaluated**. Do not generalize the evaluated subset to all scheme
features. Player baseline: four prior games; residual features use the matchup and target
share. Player outcomes are conditional on a target-game boxscore being present, with
missing candidates reported. This is not an unconditional player availability forecast.
All positional breakdowns are reported to expose zero-heavy rushing/receiving cohorts.

Margins, totals, passing/rushing/receiving yards have separate MAEs, paired deltas and
exploratory week-block bootstrap intervals (300 resamples, seed 17). Negative deltas mean
improvement. No multiple-comparison correction or independent confirmatory holdout is
claimed. Tiny deltas are insufficient grounds for changing production.

## Use

Run from repository root; stdlib for CSV/store/features/evaluation, optional `polars==2.0.0`
for offline Parquet aggregation and its integration test. No application dependencies load.

```sh
python -m unittest research.player_scheme.test_engine -v
python -m research.player_scheme --db /tmp/player-research.sqlite ingest schedule schedule.csv \
  --season 2026 --captured-at 2026-10-29T12:00:00Z --url https://github.com/nflverse/nflverse-data
python -m research.player_scheme --db /tmp/player-research.sqlite ingest player players.csv \
  --season 2026 --captured-at 2026-10-29T12:00:00Z --url https://github.com/nflverse/nflverse-data
# Import team CSV and optional PBP Parquet with the same command shape.
python -m research.player_scheme --db /tmp/player-research.sqlite matchup NE BUF \
  --cutoff 2026-10-29T12:00:00Z
python -m research.player_scheme --db /tmp/player-research.sqlite evaluate --mode observed
python -m research.player_scheme --db /tmp/player-research.sqlite maintain --keep-seasons 8
# Optional verified charting: ingest charting participation.parquet --pbp-path pbp.parquet ...
```

Reproduce the repository's existing local snapshot cohort without downloads:

```sh
python -m research.player_scheme.run_cached --repository /path/to/Trend-Finder --output /tmp/player-audit
python -m research.player_scheme.benchmark_reader --db /tmp/player-audit/features.sqlite
```

That cache is external to this PR and may not exist in a clean checkout. `evaluation.json`
includes input hashes; results must be tied to those exact bytes. No database or raw archive
is committed. CLI matchup JSON can be precomputed by a future separately approved offline
job; nothing calculates these features on public requests in this phase.

## Storage and safety

One compact observation per kind/game/team/player; corrected files replace only their
own season inside an atomic transaction. Unchanged SHA-256 inputs skip processing.
Unchanged weekly rows retain their original captured-at when another row changes; changed
rows receive the new capture time. Optional aggregate PBP/charting refreshes conservatively
move that season's capture forward. No original forecast or existing research file is altered.
This store keeps the latest correction, not an archive of historical data vintages; preserve
external source snapshots for reproducibility.

The database cap is 64 MiB. With a worst-case rollback journal, it stays below 150 MB.
SQLite cache is 2 MiB and temporary work uses disk. Import rejects duplicate identities,
nonfinite values, impossible counts, mismatched opponents and excessive seasonal rows.
Explicit maintenance retains the latest eight research seasons by default, deletes only
this package's SQLite rows and uses incremental vacuum. It never deletes upstream data.

Polars processing and backtesting are offline only. `benchmark_reader` measures additional
peak RSS in a fresh process, across ten read-only feature builds; it fails above 25 MiB.
See `reader_resources.json` and `evaluation.json` for actual measurements. These local
macOS measurements are not a production Render stress test. There is no production RAM
or disk impact unless an operator separately installs/copies and invokes this package.

## Expanded ATS follow-up

See [FULL_ATS_RESULTS.md](FULL_ATS_RESULTS.md) for fixed player/PBP/charting ablations, 2020–2022 verified scheme coverage, the same 2023–2026 modern cohort, reproducible game ledgers and 27 tests. Modern cached scheme coverage remains unavailable. The updated reader benchmark includes a full charted historical season. Nothing is integrated into production.
