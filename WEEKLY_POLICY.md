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

## Weekly page score freshness

The weekly results page uses the shared cached ESPN scoreboard for provider-confirmed finals while the dual-source canonical CSV update catches up. Only completed postgame events with exact team identities and scheduled kickoff matches are eligible. Invalid or conflicting scores are rejected and existing saved finals take precedence. The overlay is read-only, clearly labeled, and all ATS/total grades continue to use the original frozen prediction lines. Refreshing the weekly page checks the shared feed cache (normally 60 seconds after games finish). The canonical update and persistent model record workflows remain unchanged.

Confirmed finals are now shared across hosted score-based views through the read-only effective row layer: Trend Finder, Discover Trends, matchup comparisons, weekly results, model records, and member-pick grading. The scoreboard itself bypasses this layer while constructing its snapshot to avoid recursive fetches. The snapshot is reused within each request and the existing feed cache is reused across requests. Discover Trends cache keys include the confirmed-final signature so newly finished games invalidate stale trend summaries. Scores, margins, totals and confirmed overtime flags are applied together. This is hosted-request behavior only; offline research and sealed prediction generation continue to use the untouched saved files.
