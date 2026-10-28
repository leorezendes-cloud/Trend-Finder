# Site week and locked forecasts

The site's current regular-season NFL week changes Wednesday at **8 a.m. America/New_York** (including daylight-saving changes). The saved schedule determines that window's season/week. Homepage scores, upcoming matchups, market, member picks, The Plug, weekly results, upcoming trend previews, Dungeon weekly pages and automatic weekly newsletter drafts share this boundary. Explicit historical week/season selections remain available. Historical manual research filters remain user-selected.

Member sheets publish automatically from an immutable market snapshot. A separate hosted timer checks the Eastern week boundary every 30 seconds and starts a market capture at Wednesday 8 a.m. Completion may take a few minutes; actual observation and freezing times are retained. All unstarted games must have verified spreads and totals before publication. Schedule-only fallbacks are not used for member picks. Captures completing in the ten-minute boundary window must have quotes observed at or after the scheduled cutoff; later catch-up can only use saved quotes observed on/before that cutoff, at most 24 hours old. If evidence is missing, publication stays pending rather than substituting later lines.

For **2026 Week 6 only**, `member_lines_exception.json` contains the latest verified saved quotes frozen October 14 at 1:43 p.m. Eastern. Deployment uses that reviewed snapshot automatically. It cannot apply to another week. Already published sheets and saved picks are never replaced.

`/picks/` opens the current sheet from the saved snapshot without running collectors. Owner `/picks/admin` is a read-only list; cancellation/void controls remain. Each game locks at kickoff. Shortcuts appear on the homepage, Upcoming Matchups, matchup details, team comparison and market. Manual searches can be saved to My Watchlist.

`/market` and Upcoming Matchups read the latest valid saved spread and total for each unstarted game in the current week. Quote identity, kickoff, observation time and line structure must match. These are saved quotes, not streaming odds. Schedule lines are an explicitly labelled fallback; unavailable lines stay unavailable. Original forecast quotes never override the market display or change for grading.

On Render, the existing `TREND_FINDAH_AUTO_UPDATE=1` worker refreshes saved inputs every six hours. Eligible Plug predictions are captured once before kickoff and remain locked against their original lines through grading. Daily revisions are no longer generated or displayed. Previously recorded research evidence is preserved; no model retraining or historical source edits are introduced.

Weekly Results defaults to the current week. Upcoming games show “Not played yet”; past kickoff without verified finals shows “Awaiting verified final score”. A link leads to the latest week with completed games, and the historical week selector remains available.

Weekly evidence persists under `/var/data/site-data/data/member_lines/`. Check `logs/weekly_lines_status.json` for ready/pending state. `TREND_FINDAH_AUTO_UPDATE=1` and a running Render instance with its existing persistent disk are required for the scheduled capture.

The weekly matchup table separates **ATS as Dog** (current-season regular-season cover–loss–push record entering the selected week, excluding favorites, pick’em, missing lines and unfinished games) from **Result** (that matchup’s underdog ATS outcome). Saved final Scores are not a live status feed. Plug ATS/total pick outcomes share the Plug Result column; original grading lines remain unchanged.

Starting with automatic configuration `scout4-plug-margin-blend-3-always-pick`, new forecasts always select a side when valid inputs exist. Ordinary ATS edges keep the same direction. Exact ATS ties choose the underdog (home at pick’em); exact totals ties choose Under. Model coefficients are unchanged. Original sealed forecasts and historical grading are preserved. The older points-only preview no longer uses its three-point abstention band; it picks by the edge’s sign, with the underdog at zero. This display preview does not change historical saved forecast records.

## Version 4 original points ATS baseline

`plug-points-only-4` publishes new ATS predictions from the original points-for/points-allowed margin. Existing sealed forecasts retain their old formula and original lines; they are not regenerated on deployment. The prior 50/50 recipe and fixed net-EPA Recent Form are saved and graded separately as research benchmarks on each new forecast's same cutoff and spread. Published totals retain the frozen Scout totals model. Exact-tie selection and always-pick behavior remain unchanged. No injury/weather penalty is added to published forecasts.

## Independent Plug O/U selections (2026)

Scout's original sealed totals forecast, quote, historical line, and grading
remain unchanged. After forecast staging, the scheduled update worker attempts
a separate immutable Plug O/U receipt in
`data/scout4/blend/plug_ou/<game_id>.json` (persistent disk). The receipt
is issued only before kickoff and tied to the saved source forecast SHA-256,
quote and actual issue timestamp. The source cannot be changed and no old game
receives a new official selection.

Independent Vegas reconstruction **v14** is trained to previously completed
seasons' market totals using pre-week team form and prior-known QB history.
The current game's market quote is *not* an input into this model. For 2026
posted total >=48: follow v14 when the projection differs by less than 1
point; fade v14 when it differs by at least 1 point. An exact tie retains
the original selection. For totals below 48, keep the original selection.
If independent projection inputs are absent, do not issue a new Plug receipt.
The Plug's graded result uses that receipt's original frozen market total,
not a current/closing quote.

The website separately shows Scout O/U, Plug O/U and Expert O/U. Expert
drafts may include the previously issued final Plug O/U as independent
context, without changing the immutable Scout source or forcing agreement.
Earlier Expert reports remain archived unchanged. Any missing/corrupt
receipt is not reconstructed from hindsight.

## Plug O/U selective shortlist (v2, prospective only)

Version 1 generated an independent **direction** for each eligible game, not a
selection shortlist. Its immutable per-game receipts remain in their original
location and are never rewritten or retroactively converted to Stay Away.

Version 2 uses a *separate* immutable weekly receipt at
`data/scout4/blend/plug_ou/weekly_v2/YYYY_WW.json`. The hosted update worker
waits until every scheduled regular-season game in that week has its own
verified v1 receipt, and the earliest kickoff is still in the future.
Only then can it freeze and publish one whole-week selection:

- Candidate games have an originally sealed total of at least 48 with a
  nonzero independent v14-minus-market gap; below-48 Scout fallbacks and
  exact ties are automatically Stay Away.
- Rank candidates by descending **absolute** saved v14-versus-market gap;
  tie-break using ascending game ID. Select at most
  `ceil(number_of_candidates / 4)`. All others are **Stay Away**.
- The v1 record fixes the selected Over/Under **direction**, frozen line and
  quote. V2 determines shortlist **membership** only; it never reissues or
  changes Scout, Plug v1, or Expert records.
- The selected count and grades are official only for v2 prospective shortlists.
  Original all-game v1 picks remain viewable as a separately labeled legacy
  cohort, not silently added to the new selective record.
- Partial slates, missing v14 signals, or a kickoff already underway never
  produce a retroactive v2 shortlist. A corrupt or conflicting receipt fails
  closed instead of regenerating it.

The top-quarter budget intentionally parallels Plug ATS. It has **not** been
demonstrated to produce a positive betting edge: research on reconstruction
disagreements is exploratory. Prospective outcomes must be measured before
making any success claims or tuning the rule.

## The Plug ATS independent market-model v5 (prospective v2)

This is a **new independent policy**, separate from Scout 4.0's all-game
forecast, The Plug's original points-only ATS prediction, and The Plug O/U v14.
The original top-quarter ATS publication remains immutable under
`/var/data/plug_ats_selections/*_plug-ats-top-quarter-v1.json` and retains its
original results. The v5 ATS policy does **not** edit those receipts.

The original independent **spread reconstruction v5**, reproduced from the
2026-10-27 frozen market-model research, predicts *away-team spread* using
older seasons' bookmaker spreads as regression labels; the current game's
market spread is never a feature. Its Elo, scoring, opponent adjustment,
prior-year team-strength and prior-known QB proxy features can only use
games from earlier weeks. Fitting for season Y uses 2016 through Y-1.

A game receives a **Plug ATS selected** recommendation exactly when:

- The frozen bookmaker's **absolute away spread exceeds 7.0** (strictly).
- The absolute independent **v5 projected away spread minus that exact
  frozen line is strictly greater than 0 and strictly less than 1 point**.
- The sign gives v5's ATS side: v5 away spread below the market away
  spread selects the away team; above selects the home team.
- Zero gap, exactly one-point gap, exactly seven-point favorites, missing
  evidence, or nonfinite inputs are **Stay Away**. No top-quarter quota,
  ranking or forced picks. It may select zero or many games.

Before publishing, the worker requires **every** scheduled game in the
regular-season week, a matching immutable approved points-only pregame
forecast for each game, and the original sealed spread quote observed
before issuance. It stops entirely for partial slates or if any game
has already kicked off. A separate v2 weekly receipt is first-written to
`/var/data/plug_ats_selections/YYYY_WW_plug-ats-independent-v5-favorite-near-market-v2.json`
with immutable game IDs, original quote lines, source hashes, saved v5
predictions, selection flags and actual publication time.

The public pages read-only show the v2 policy when it exists; they do not
create either v1 or v2 on a page request. The existing published v1 record
is used for historical weeks without a v2 receipt, while all existing
v1 files remain intact. Live historical grades are calculated against
the original receipt's saved line, not a refreshed market line.
An absent prospective v2 means **Awaiting weekly picks**, not a fictional
Stay Away or retroactively inferred pick.

The original research outcome is retrospective, was examined during
development, and cannot establish forward-looking profitability.

## Weekly page score freshness

The weekly results page uses the shared cached ESPN scoreboard for provider-confirmed finals while the dual-source canonical CSV update catches up. Only completed postgame events with exact team identities and scheduled kickoff matches are eligible. Invalid or conflicting scores are rejected and existing saved finals take precedence. The overlay is read-only, clearly labeled, and all ATS/total grades continue to use the original frozen prediction lines. Refreshing the weekly page checks the shared feed cache (normally 60 seconds after games finish). The canonical update and persistent model record workflows remain unchanged.

Confirmed finals are now shared across hosted score-based views through the read-only effective row layer: Trend Finder, Discover Trends, matchup comparisons, weekly results, model records, and member-pick grading. The scoreboard itself bypasses this layer while constructing its snapshot to avoid recursive fetches. The snapshot is reused within each request and the existing feed cache is reused across requests. Discover Trends cache keys include the confirmed-final signature so newly finished games invalidate stale trend summaries. Scores, margins, totals and confirmed overtime flags are applied together. This is hosted-request behavior only; offline research and sealed prediction generation continue to use the untouched saved files.
