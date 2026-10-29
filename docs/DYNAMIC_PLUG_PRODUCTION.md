# Dynamic Plug production verification

The research collector follows every successful primary or price-only backup
capture. The existing 15-minute market job now captures all week, including
non-game days. It runs under the shared updater lock, with no AI or model rebuild.
A completed capture evaluates using the actual clock; journal writes check the
clock again under the journal lock. Identical selections/lines do not add a
revision. Kickoff selects the last saved pregame revision; the next market tick
installs its immutable closing receipt. No market lookup is involved in grading.
A missing receipt remains unavailable; invalid stored evidence fails visibly.

`initialize_data` links `plug_dynamic_research`, `plug_dynamic_closing`, and
`plug_dynamic_official` to `/var/data/site-data`. Existing copies are preserved;
conflicting copies stop migration for review. Pending QB cases appear as warnings
in the full updater status and cannot block predictions. Other verifier errors
remain failures.

## Official policy boundary

Keep `TREND_FINDAH_DYNAMIC_RESEARCH=1` and `TREND_FINDAH_DYNAMIC_OFFICIAL=0`
until verification succeeds. The official toggle alone cannot publish research.
Activation requires a recent successful full update from this pipeline, a real
successful unattended market timer tick, valid model/journal/closing evidence,
and protected historical bytes verified after an actual web-worker restart.
Partial coverage is reported per game; it never fabricates the missing v5 receipt.

Activation saves a prospective immutable boundary. A subsequent fresh verified
observation enrolls each future game; unchanged decisions can enroll without
rewriting their historical timestamp or adding duplicate journal revisions.
Already-started games cannot enroll. Model receipt identity and saved decisions
are verified again when official cards/records are read. Dynamic records have a
separate table and tally from all legacy weekly records. Scout forecasts, Expert
reports, ATS v5/O-U v14 receipts, and published newsletter snapshots stay intact.
Pinned archive URLs retain their original snapshots; current dynamic dashboard
links open the current detail view. Dashboard/API, detail, team comparison,
weekly results, combined records, and newly drafted newsletters share the same
selection/grade source. An invalid official receipt shows review/unavailable,
not a silently substituted legacy recommendation.

## Render commands after deploying the PR

Run once to verify the patched full updater (optional AI/context work disabled
for this invocation only):

```sh
TREND_FINDAH_EXPERT_AUTO_DRAFT=0 TREND_FINDAH_CONTEXT_RESEARCH=0 python hosted_updates.py --once
python -m plug_dynamic_readiness --checkpoint /var/data/site-data/logs/dynamic-pre-restart.json
```

Restart the Render web service. Let its market timer complete one successful
unattended tick (within 15 minutes; do not substitute a manual capture).
Then run:

```sh
python -m plug_dynamic_readiness --verify-checkpoint /var/data/site-data/logs/dynamic-pre-restart.json
python -m plug_dynamic_readiness --activate
```

The last command exits nonzero and lists exact blockers unless all safeguards
pass. It does not change environment variables. Only after it succeeds may
`TREND_FINDAH_DYNAMIC_OFFICIAL` be changed to `1`. Its activation receipt and
per-game issuance receipts survive that restart. Rerun without `--activate` for
a read-only audit. Checkpoint verification allows new records and append-only
journal additions, but rejects any changed preexisting historical bytes.

## Validation

Local validation: **139 tests passed**, all **83 Jinja templates parsed**, and
the largest local test process peaked at **111.7 MiB RSS**.

The PR workflow runs the entire existing ATS v5/O-U v14/dynamic regression group
plus full weekly-results, Expert pipeline, prediction-card, hosted updater,
scheduler/runtime and new production/capture integration suites. Production
fixtures cover real decision threshold changes, unchanged quote retries, kickoff
write races, immutable closing prices, grades, prospective enrollment, separate
legacy records, dashboard/detail/weekly rendering, newsletter selections,
persistence conflict handling and actual restart checkpoint requirements.

An additional broad audit on the unmodified `91bdc63` baseline reproduced eleven
preexisting failures in six older modules (`test_qb_verification` UI assertion,
`test_odds_backup` old price-only expectation, `test_plug_publication` incomplete
fixture, `test_record_merge_release` old copy assertion, `test_plug_dashboard`
old layout/fixture expectations, and `test_newsletter_draft` old copy/route
fixtures). The same eleven occurred on this branch; no new failures appeared.
They are outside the focused workflow and were left unchanged.

The local test process is not a Render memory benchmark. Production still uses
one worker/four threads, bounded sequential refreshes, and no extra long-lived
worker or model/AI task. The live disk/restart/timer checks must run on Render.
