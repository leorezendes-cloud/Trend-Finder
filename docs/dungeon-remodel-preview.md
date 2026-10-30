# Dungeon investigation preview — October 30, 2026

Local review only. Nothing pushed, no PR opened, no production deployment or collector run.

Preview target: http://127.0.0.1:5001/conspiracy-dungeon?panel=anomalies&mobile_results=1

## Integrated research follow-up

- Added the Ditka memorial game as the fourteenth case, linked to its unchanged original event ID. Rechecked the Bears tribute and recap sources on October 30.
- Replaced the main library's separate original-research entrance with three compact links: International field notes, By the numbers, and Sourced event log. Old research URLs remain supported.
- International records retain pregame team ATS history, venue, kickoff, rest, and following-game details. Statistical records retain scoring baselines, penalties, referee context, and source links. Existing event notes and entry permissions remain available.
- Research is calculated only when requested, cached with a two-entry limit and file-version keys, and paginated at twelve records. No live finals feed or collectors are called.
- Reconnection validation: 37 relevant tests passed, including research filters, pagination, lazy loading, old links, and immutable CSV checks.
- Preview restart is currently blocked by the execution sandbox: Flask socket binding returns `Operation not permitted`. Browser reconnection also failed with a browser-session error. The URL above has not been verified reachable during this reconnection; start the documented preview command in a regular local terminal using port 5001.

## Files and architecture

- `app.py`: register read-only investigation blueprint and choose the lightweight library for the default anomalies view. Old category deep links retain their meaning.
- `dungeon_results.py`: shared editable section title only; calculations and records preserved.
- `dungeon_investigations.py`: category/search/season/order filtering, stable case routes; summaries only in the index; one detail file loaded on a case request.
- `templates/conspiracy_dungeon.html`: library styling and shared label; restores the market-card surface from upstream commit `224a769` because this local checkout predates it. Only the market CSS/card section is taken from that commit, preserving the rest of the local template.
- `templates/anomalies_section.html`: library/archive switch. Existing contents preserved verbatim in `templates/anomalies_research_archive.html`.
- `templates/_investigation_library.html`, `_investigation_card.html`, `investigation_case.html`: server-rendered library and case pages. Native details work without JavaScript.
- `static/investigations.css`: scoped dark editorial surface, 3/2/1 columns; leaves market and Primetime styles separate.
- `research/investigations/index.json` and 13 case JSON files: editorial evidence, not a replacement NFL game or betting-results database.
- `test_dungeon_investigations.py`: 12 regression tests.

`anomaly_analysis.py`, `anomaly_store.py`, CSVs, predictive models, authentication handlers, collectors, and scheduler code were not changed by this work. Existing event-entry functionality remains in the original research archive; no new submissions or moderation system was added.

## Research catalogue

| Date | Teams | Case | Evidence scope |
|---|---|---|---|
| 2026-10-29 | CAR / GB | Drone interruption and trophy night | Yahoo broadcast report and Post trophy report. Coincidence only; no established causal connection. |
| 2026-10-25 | GB / DET | Wyatt dead-ball dispute | Team reporting includes player accounts and referee pool-report explanation; no league reversal asserted. |
| 2026-10-25 | TEN / CLE | Five late winning scores | NFL Communications / Hall of Fame comparison, attributed rather than claimed as an independently rebuilt all-time statistic. |
| 2026-10-18 | HOU / JAX | Hunter touchdown plus interception | Jaguars report, Reuters corroboration, NFL interception video. |
| 2026-10-11 | NYG / WAS | Overtime clock expires | NFL sequence and Giants final-score notes. |
| 2026-10-11 | PHI / JAX | Returnable final kickoff | Eagles coach explanation and NFL game recap. Return distance differs between sources; exact yardage omitted. |
| 2026-10-11 | DEN / LAC | Failed fourth-and-1 | Chargers recap and Harbaugh's explanation. No unverified analytics recommendation or win probability. |
| 2026-10-11 | SF / SEA | Late-half fumble touchdown | Seahawks recap and official play-by-play. Starting spot differs between accounts; uncertainty disclosed. |
| 2026-10-11 | CIN / MIA | Missed PAT and +6.5 | Dolphins scoring report, CBS game tracker, SI pregame FanDuel line. Final margin 7; +6.5 loses, +7 pushes. |
| 2026-10-04 | ARI / NYG | Official disciplined after confrontation | NFL league announcement. Suspension concerns conduct, not proof that a coverage ruling was intentionally incorrect. |
| 2026-10-04 | MIA / MIN | Hockenson's slide | Vikings sequence, Yahoo spread reporting. Team says 2-yard line; betting accounts say 1. Difference disclosed. |
| 2026-09-27 | NE / JAX | Lawrence stops short | CBS explanation and Jaguars account. Disputed in-play score omitted. No verified prop price: not categorized as a graded bad beat. |
| 2024-12-19 | DEN / LAC | Fair-catch kick | Chargers explanation and Hall of Fame rule/record confirmation. Historical archive. |

Full source URLs are stored with each case and linked on the case pages. Links were checked through search retrieval and page opens; some publishers throttle direct fetches (notably Yahoo 429 and PFR 403). No claim that all publishers consistently return HTTP 200. PFR is not required by any published case. Editorial disagreements remain visible rather than filling gaps from local CSVs.

Isaac Punts discovery: located the October 25, 2026 video “This is Unbelievably Bad for the NFL” (GIuGD9W2ZLQ) through its indexed metadata. YouTube playback/transcript was unavailable in the research tool. Its assertions were not used as evidence and no claim of having watched it is made. Historical fair-catch-kick coverage was a useful additional lead, independently verified with team/Hall sources.

Deferred: additional cases toward 15–25; verified total/prop bad beats (no supported prices found in this pass); unresolved drone operator and official enforcement outcome; deeper independent all-time statistical rebuilds. No screenshots, videos, or raw scraped pages are stored for cases.

## Verification

- 31 tests passed: investigations, anomaly sections/badges, penalties, reverse-line analysis.
- 3 Primetime-night integration tests passed separately.
- 5 other ATS-study tests passed. One existing ATS study test, `test_wednesday_rollover_and_archive`, fails with both the original untouched local module and the remodel. The fixture expects a Wednesday-noon rollover while the current shared site-week behavior has changed. No unrelated week logic was modified to satisfy an obsolete expectation.
- Browser: desktop 1280px shows 3 columns; phone 390px shows 1; neither overflows horizontally. Category navigation, native expand/collapse, case routing, betting arithmetic display, archive, back links, and mobile results mode checked.
- Request tests confirm existing CSV bytes unchanged; case requests do not invoke historical scans or collectors.
- Local 40-request repeated library/detail sample: 4.286 seconds total; traced memory retained 0.084 MiB, peak 23.995 MiB (includes existing global site-week CSV context).
- Separate comparison: existing `/backtests` request traced peak 23.89 MiB; library 24.10 MiB. Approximate incremental traced peak 0.21 MiB. Editorial index parse peak 143.8 KiB. Mac Python process high-water RSS 135.5 MiB. These are local measurements, not a Render load-test guarantee.
- Case JSON storage: 32,041 bytes before documentation/tests; no dependencies, workers, timers, web scrapes at request time, videos or generated model runs.

## Local branch and safe preview

The workspace already had many unrelated changes. The original `.git` is read-only in this session. To retain local edits and avoid changing main's Git metadata, development branch `dev/conspiracy-investigations` was created in a copy at `/tmp/trend-dungeon-dev-git`, with this existing repository as its work tree. Inspect it with:

```sh
git --git-dir=/tmp/trend-dungeon-dev-git --work-tree="$PWD" branch --show-current
```

The original repo's ordinary `git branch` still shows main; do not mistake that for a production branch mutation. All remodel work is local and uncommitted pending design approval. Preexisting touched-file snapshots are in `/tmp/dungeon-before`; these are recovery/reference files, not a second app.

Server uses the existing `.venv`, `app` directly (not `wsgi`), no reloader, localhost only, and a separate `/tmp/dungeon-preview-members.sqlite3` membership database. To restart if needed:

```sh
TREND_FINDAH_AUTO_UPDATE=0 TREND_FINDAH_DYNAMIC_RESEARCH=0 TREND_FINDAH_EXPERT_AUTO_DRAFT=0 TREND_FINDAH_CONTEXT_RESEARCH=0 TREND_FINDAH_EXPERT_BETA=0 TREND_FINDAH_ENV=development TREND_FINDAH_DATABASE=/tmp/dungeon-preview-members.sqlite3 .venv/bin/python -c "from app import app; app.run(host='127.0.0.1',port=5001,debug=False,use_reloader=False)"
```

Do not push or open a PR until Leo explicitly approves the design. A later focused PR must start from current upstream and apply only this remodel's delta, preserving all intervening and preexisting work.
