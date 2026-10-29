# Dynamic Scout: isolated, disabled rollout

## Audit and scope

The deployed public Scout forecast is `automatic_model.json` / `plug-points-only-4`:
zero Scout-scoring weight and one points-only weight. `scout4.blend.run` seals the
first eligible forecast; the hosted staging pipeline deliberately skips sealed
games. Public cards, comparisons, archived Expert reports and legacy results read
those original files. The independent Scout scoring component is retained as a
separate research component; it is not silently substituted for public scores.

The totals model is the existing **Market + statistics** model. Its frozen
`market_total` coefficient is a real model input. Total projections can therefore
change with a total-line change under the existing formula. Independent team
points/margins do not move merely because a sportsbook changes its line. This
adapter does not add a new market adjustment or pretend that this totals model is
independent of the market.

Scout 4.1's local `research/scout41_prediction_experiment/role_pipeline.py`,
`evaluate_prospective.py`, and the QB score-shadow documentation describe separate,
prospective/private research cohorts, with their own issuance and outcome rules.
They are not deployed in GitHub main. They remain untouched and are not imported,
renamed as 4.0, automatically promoted, or exposed as official forecasts. Nothing
compares 2024/2025 performance to override the research priority of 2026. No new
player/injury/QB adjustments or model weights are introduced.

## Implementation

* Reuse the existing six-hour updater and 15-minute hosted market job. No new
  permanent worker, timer, provider fetch, model fit or AI call is introduced.
* A new `scout_dynamic` directory is linked to `/var/data/site-data/scout_dynamic`.
  The old Scout directories, Plug stores and Expert publication sources are never
  written by this feature. Conflicting persistence copies stop initialization.
* A game requires its existing verified, approved pregame seal. Only prior-week
  schedule/team statistics pass the existing statistics gate. Config/code hashes,
  team/kickoff identity, quote timestamps and plausible projections must validate.
* Independent projections are recalculated only when eligible inputs change.
  Identical retrievals or quotes create no duplicate revision. A changed line or
  recommendation creates a new revision, even if the projection is unchanged.
* Each mutable per-game revision file retains at most **32** entries and is capped
  at **512 KiB**. Updates use atomic replacement and the shared per-game file lock.
  The cycle evaluates at most 32 upcoming games. Existing archives are not pruned.
* At/after kickoff the next existing worker tick writes one immutable, standalone
  closing snapshot. Finalization runs before checking new model/market inputs, so
  an outage cannot skip closing. The commit clock rejects writes after kickoff.
  A missing closing receipt renders review/pending rather than a live pick.
* Public reads only attach a separate `scout_dynamic` field. Original `scout`,
  `saved_picks`, Expert references and all Plug fields retain their prior values.
  Explicit archive-version and saved-forecast URLs still show original snapshots.
* Dynamic ATS/SU/O/U results use the closing snapshot's selections and exact lines,
  with confirmed canonical finals. The dynamic results cohort is separate from
  original first-issued Scout records; there is no addition to legacy totals.

## Approval and activation

The PR changes no Render settings and does not deploy or merge itself. Both new
flags default off, so deploying the code alone leaves public behavior unchanged.
Only after explicit approval:

1. Verify actual Render disk/headroom. The adapter pauses new revisions below
   128 MiB free; closing is still attempted. Run the Linux benchmark and normal
   regression workflow before permitting publication.
2. Deploy the approved code with `TREND_FINDAH_SCOUT_DYNAMIC_RESEARCH=1` and leave
   `TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC` unset/zero. Wait for a real scheduler cycle.
3. Run `python -m scout_dynamic_cli` on Render. It checks the mounted persistent
   root, link, fresh worker status, current-slate coverage and due closing receipts.
4. After review passes, run `python -m scout_dynamic_cli --activate` once and set
   `TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC=1`. A subsequent worker must freshly validate
   each game and issue a prospective receipt before it can appear dynamically.
   Neither the flag alone nor old research automatically publishes historical picks.
5. Check the dashboard, a detail/comparison page and dynamic results after the next
   scheduled cycle. Restart/recheck persistence. Keep the original Plug flags as-is.

Turning only the Scout public flag off restores original-snapshot presentation;
all Scout closing receipts and original records remain on disk. No Plug setting
needs to change. Do not reset an existing activation receipt to backfill results.

## Validation and resource measurements

`test_scout_dynamic.py` exercises the real frozen production functions against
synthetic prior-week data, including parity, changed/unchanged inputs, line moves,
market outages, kickoff races, frozen grading, bounded retention, persistence,
public render consistency, archive links and unchanged Plug artifacts.

`scripts/benchmark_scout_dynamic.py` runs a 14-game synthetic slate through three
cycles with the real saved-market adapter and frozen formulas. It writes only a
temporary fixture. On the local Mac: **46.16 MiB peak RSS**, **33,038 bytes** for the
new 14-game store, and approximately **630 GiB** actual local disk free. This is
not a Render benchmark or a measurement of the full hosted application. CI also
runs `/usr/bin/time -v` to capture Linux peak RSS and available runner disk space.

The Render console could not be read during this pass because the Mac was locked.
Actual current Render free disk and a combined hosted-worker peak remain rollout
gates; the earlier Plug-only memory measurement is not reused as Scout evidence.
The feature is suitable for review/merge with publication disabled. Enablement
requires the approved staged checks above; no live resource claim is inferred
from the small synthetic benchmark.
