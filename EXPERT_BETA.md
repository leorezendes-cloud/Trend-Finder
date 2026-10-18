# The Plug / Expert local beta handoff

Release assessment: **NOT READY for public Expert launch** (October 17, 2026).

The actual Flask application now has an opt-in integrated Plug dashboard, stable game pages, protected Expert HTML/API views, immutable forecast versions, sourced-final grading, archive navigation, and first-version performance counts. Original Scout calculations are imported unchanged. No model fitting, prediction-method changes, production deployment, live-server restart, payment activation, or paid AI call was performed.

## What is available

- `/the-plug`: responsive compact slate with scores, market expiry, conditional leans, uncertainty, and game links. No fixed game count. Current local import has 13 games.
- `/the-plug/2026/6/HOU-JAX`: example game page. The original Scout snapshot, sources, assumptions and revisions remain available independently of Expert access.
- `/the-plug/archive`: recorded games and performance counts separated by record type. First recorded version per game/type is the cohort; revisions do not replace losing originals.
- `/api/the-plug`: public Scout data and only permitted brief Expert summaries; no full reports.
- `/api/the-plug/<season>/<week>/<away>-<home>/expert`: requires free-feature eligibility or authenticated premium entitlement. Unauthorized callers receive 403. Missing AI report returns 503.
- Existing `/sunday-scout` and other site features remain available. With the beta flag absent, `/the-plug` continues its original behavior.

## Release blockers and limitations

1. **No genuine AI provider is connected.** `generate_draft(scout, provider)` is a reusable offline callable interface. It supplies only the saved pregame evidence and explicitly marks output pending. No template masquerades as AI. Provider/model provenance, exact Scout digest, six sections with evidence IDs, counterargument, uncertainty, distinct wagering assessment, and explicit review are required before publication. Citation validation does not prove factual correctness: a named grounding review is required. Actual provider generation, factual quality, and two complete featured real reports remain untested/unavailable. No API credits or credentials were used.
2. **Automatic beta refresh is not integrated into the hosted scheduler.** Existing production updates run every six hours, which cannot keep 15-minute quotes continuously current. No scheduler was changed or duplicated. The beta currently imports verified lab release packages manually; expired markets become unavailable at request time. Fresh inputs and material QB/personnel changes must first produce a new lab release using the existing `scout_release.py`, followed by import. Imports preserve old versions. This is not a claim of automatic live operation. Hosted persistence, source dependency packaging, bounded refresh, failure recovery and AI regeneration still need end-to-end operational verification.
3. **Historical checks are software fixtures, not a 2025 accuracy evaluation.** The test includes a synthetic 2025 pregame record and sourced-final fixture to exercise chronology, pages, grading and missing odds. It is not an actual football result or independently verified historical evidence. No genuine 2025 Expert reconstruction or independent predictive validation was completed. Previously disclosed lab diagnostics used oracle QB identities and mixed results; they do not establish superiority to the deployed predictor.
4. Entitlements are operator-configured existing member IDs, suitable for development; no billing or paid plan administration. Archive authorization is enforced. Two free slots for 2026 Week 6 are frozen to HOU-JAX and CHI-ATL, but their real Expert reports are pending.
5. Local archive writes are append-only with SHA-256 checks and exclusive creation, not an external tamper-proof backup. Keep private backups and filesystem permissions. Records preserve the imported evidence metadata and original sources in the lab; the imported package is not a standalone copy of every raw upstream source. Do not delete the source release/lab evidence.
6. Grading runs on verified final import / page read, not a new automatic final collector. Operator-supplied source contents still require verification. It separates Scout and Expert selections and computes flat one-unit returns at recorded American odds; missing odds yield no return estimate. No implication that a directional selection was an actual wager. Aggregate archive UI currently summarizes Scout ATS and score errors; full Expert/OU/ROI aggregate reporting remains unfinished.

## Local operation

Run from the project root using its existing `.venv/bin/python`. Do not run `wsgi.py` with production update flags for a local preview.

```sh
TREND_FINDAH_EXPERT_BETA=1 \
TREND_FINDAH_DATABASE=/tmp/expert-beta-preview-members.sqlite3 \
TREND_FINDAH_SECRET_KEY=isolated-preview-only \
.venv/bin/python -c "from app import app; app.run(host='127.0.0.1', port=5017, debug=False, use_reloader=False)"
```

The temporary database keeps preview accounts separate. Use a real secret for any nonlocal service. `TREND_FINDAH_EXPERT_STORE` selects a private archive directory; default is `instance/expert_beta`. Never put this directory under `static` or a public file server. To test premium access, register in the temporary preview database, obtain that account's ID with a local database query, and set `TREND_FINDAH_EXPERT_MEMBERS` to the comma-separated IDs for the separate preview process. Do not grant production entitlements as part of a preview.

Import an existing verified lab package without changing its projections or generation time:

```sh
.venv/bin/python expert_beta_cli.py --store instance/expert_beta import-package /absolute/path/to/launch_package
.venv/bin/python expert_beta_cli.py --store instance/expert_beta feature 2026 6 HOU-JAX CHI-ATL
```

Imported packages are always development records, even when imported before kickoff. They are never relabeled genuine prospective forecasts. Free choices are frozen per week; attempting to change them fails. Importing identical inputs is idempotent.

For a reviewed genuine provider report, use `publish-reviewed VERSION REPORT.json`. This writes a new development/reconstruction version, never overwrites the original or retroactively claims prospective AI analysis. Use `generate_draft` only after the provider and any costs have been explicitly approved. No provider is implicitly chosen.

For an operator-verified result JSON, use `final FILE.json`. Required fields: `game_id`, `status: "final"`, integer `away_score` / `home_score`, `source_url` (HTTPS), and timezone-aware `observed_at` after kickoff and not in the future. Corrections append a new source-stamped result. Original forecast records remain unchanged.

## Checks

57 tests passed across `test_membership`, `test_hosting`, `test_page_layouts`, `test_site_sections`, `test_plug_always_pick`, `test_hosted_updates`, and `test_expert_beta`. Twelve new tests cover actual Flask routes, two featured reports using explicit test doubles, premium denial/grant, session revocation, private API data, expired markets, immutable versions/tamper failure, unavailable provider, unsupported references, pregame chronology, historical fixture grading, returns/pushes/ties/missing odds, and legacy fallback. Test reports are test doubles, never presented as real AI outputs.

Browser verification: localhost-only preview rendered the imported 13-game slate and individual game page. A 390×844 phone viewport displayed stacked readable cards and the game link worked. No full device/browser matrix was run. Production deployment remains untested.

## Deployment and rollback

Do not deploy as a finished Expert product while these blockers remain. Once resolved, prepare a separate reviewed release with the existing release builder, private persistent archive storage, explicit beta flag, real session secret and verified account entitlements. Keep current production schedulers disabled from local verification. Test package completeness and storage recovery in staging, then ask for approval before production deployment or restart.

Rollback toggle: omit `TREND_FINDAH_EXPERT_BETA` (or set it to `0`) for the next separately authorized application restart/deploy. The original Plug route resumes; beta endpoints return 404. Keep archives intact. No account migration was added.

Pre-edit source rollback snapshot: `backups/expert-beta-20261017T195629Z/`. It includes original `app.py`, release-builder source, checksums and initial Git status. The checkout already had substantial unrelated changes: do not use `git reset --hard` or restore the entire repository. Restore only the beta additions after checking later edits; preserve current CSVs, account databases and archived records. New files are `expert_beta.py`, `expert_beta_cli.py`, `test_expert_beta.py`, `templates/expert_*.html`, `static/expert_beta.css`, and this document. The only changed original application file is `app.py` (blueprint registration and opt-in route dispatch).


## Provider and refresh implementation update

The OpenAI Responses adapter now exists in `expert_provider.py`, following the official structured-output interface: https://developers.openai.com/api/docs/guides/structured-outputs . No SDK installation is needed. It uses HTTPS with redirects disabled, JSON-schema output, `store: false`, a 40 KB evidence bound, 6,000 output-token limit, 120-second timeout and no automatic retries. These are request bounds, not a dollar-budget guarantee. A provider/model must be explicitly selected and authorized before any paid call. No key is configured in the current environment.

The offline `draft VERSION --approve-paid-call --model MODEL` subcommand requires `OPENAI_API_KEY` in the local process environment. Do not paste secrets in chat or store them in source files. It reserves an attempt before sending; a failed or timed-out attempt requires operator review before retrying, because the provider may already have billed it. Successful drafts stay private with `review_status: pending`; existing approved reports and forecasts remain unchanged. Actual API generation and football-quality review remain blockers. Tests use mocked responses only.

`expert_refresh.py --lab /absolute/path/to/team_profiles --store /absolute/private/store` is a one-shot bridge to the existing `scout_release.py`. It locks against overlapping beta refreshes, requires a newly completed release, verifies its package hash, imports unchanged forecasts, and records failures separately without clearing old records. It creates no scheduler and makes no AI calls. It has not been run against the actual external collectors or wired into production; hosted refresh remains a blocker. The lab dependencies and raw source evidence must remain available. Do not schedule it until runtime/storage constraints are verified.


## Gemini free-tier setup (current preferred provider)

Gemini is now implemented and is the default provider for the `draft` CLI command. The default model is `gemini-2.5-flash`; only it and `gemini-2.5-flash-lite` are allowed by this reviewed configuration. Official pricing currently lists free-tier text usage for those models: https://ai.google.dev/gemini-api/docs/pricing . Model eligibility and quotas can change. There is no automatic upgrade, paid fallback, or retry on a 429 quota response. No external tools or web-search charges are enabled.

Create a key in https://aistudio.google.com/api-keys for a project shown as **Free Tier**, with billing disabled. Do not enable billing or paste the key into chat. Free-tier inputs/outputs may be used by Google to improve its products; this workflow sends football evidence, not member data. The API key does not reveal its billing tier, so the program cannot independently guarantee that a key belongs to a free project. `EXPERT_GEMINI_FREE_TIER_CONFIRMED=1` records the operator's verification; it does not switch a paid project to free.

In the same local terminal used to run the offline command, set `GEMINI_API_KEY` securely through your preferred secret/environment setup and set `EXPERT_GEMINI_FREE_TIER_CONFIRMED=1`. Then run:

```sh
.venv/bin/python expert_beta_cli.py --store instance/expert_beta draft VERSION --provider gemini
```

Replace VERSION with an archived forecast hash. No paid-approval flag is needed for Gemini. An attempt is reserved before the call to avoid duplicate generation. Successful reports are saved privately under `drafts`, remain pending review, and cannot appear publicly through that command. Review must check factual support, chronology, citations, uncertainty and the preserved Scout scores before publishing a new version. Do not issue calls until the Free Tier status is verified.

24 focused provider/refresh/Flask tests pass, using mocked provider responses. These include absent-key/billing-confirmation rejection, structured Gemini request/response handling, quota stopping without OpenAI fallback, blocked/truncated outputs and the model allowlist. No genuine Gemini call or real Expert report has been generated yet: local credentials and project-tier verification remain required.


## First real Gemini connection test

The configured local key authenticated successfully. Google still lists Gemini 2.5 Flash in model discovery but rejects generation for new users with HTTP 404. The default is now `gemini-3.8-flash`, whose standard text input/output are explicitly listed as free on the Free Tier at https://ai.google.dev/gemini-api/docs/pricing.md . Retired-model attempts remain archived separately; no paid fallback was used. Diagnostic errors include HTTP status and redact the key. The saved Week 6 inputs are expired development snapshots, not current market recommendations.


## Hosted beta activation

The code ships disabled until Render has `TREND_FINDAH_EXPERT_BETA=1`. Set `TREND_FINDAH_EXPERT_STORE=/var/data/expert_beta` on the existing persistent disk. Transfer the private archive through the operator's authenticated channel; never commit `instance`, credentials, review drafts, or member data. Import preserved forecasts and the frozen two-game featured selection. Publish only factually reviewed reports through `publish-reviewed`, which appends a version without rewriting old records. Pending local draft previews are not public reports. No Gemini key or new generation is required to serve saved approved reports.

Card Expert picks use the same entitlement check as report access. Saved Plug selections remain visible independently of live quote freshness. Source IDs and raw snapshots remain internal. No new automatic forecast refresh or AI scheduler is enabled by this release.


## Automatic approved production publication

`plug_publication.publish` runs inside the existing hosted update worker, after prediction capture. It copies only already sealed `plug-points-only-4` forecasts whose configuration hash matches `automatic_model.json` and whose points-only weights and pregame chronology validate. It does not call the lab release bridge, experimental models or AI providers. Old blend records remain locked and are excluded from this importer, never relabeled or recalculated.

Render stores the archive by default at `/var/data/expert_beta`. A custom `TREND_FINDAH_EXPERT_STORE` remains supported. In production with the existing `TREND_FINDAH_AUTO_UPDATE=1`, the beta page is enabled by default unless explicitly disabled with `TREND_FINDAH_EXPERT_BETA=0`. An empty archive retains the existing Plug page until eligible production seals arrive. No weekly transfers or Git deployments are needed after this one-time installation. Publication follows the existing capture cadence and cutoff rules; it does not change locked lines or game-week timing.

Imports are labeled `production_import`, keep the original seal as `generated_at`, retain the original cutoff, source bytes, SHA-256 and configuration hash, and have immutable per-game receipts. They are not relabeled as newly generated prospective forecasts. Complete files are linked atomically after fsync; an existing differing receipt or damaged archive stops publication rather than replacing history. Repeated runs recover missing receipts without duplicate forecasts. Publication failures are reported by the existing updater; prior public records remain available. `last_publication.json` contains publication counts, exclusions and the actual check time separately from original forecast timestamps.

Gemini reports are never generated, imported from review folders, or approved by this publisher. The existing explicit named-review requirement and access controls still apply. Approved reports are preserved. No automatic paid API calls are configured.


## Combined public Plug page

The main page combines saved Expert-archive forecasts with existing locked public forecasts, deduplicated by game identity. Upcoming games appear first; played/underway games appear below. Distinct older locked selections remain expandable on their matchup card. No forecast is recalculated or rewritten. `/sunday-scout` opens the combined page when Beta is enabled; its snapshot-download route remains unchanged. The archive link is on The Plug’s Record page.

Current market snapshots are read separately from original prediction quotes, using existing identity, timestamp and source validation. Their capture time remains visible; old prediction-quote age no longer produces a blanket statement that market lines are unavailable. Expert entitlements remain enforced in the backend, independently of membership marketing text.
