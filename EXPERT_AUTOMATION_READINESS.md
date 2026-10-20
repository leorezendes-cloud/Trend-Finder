# Expert automation readiness — 2026-10-20

Scope: existing integration only. No Scout model/config edits, production seals, rollover, API requests, drafting activation or Render environment changes were performed. Deployment of the verified fixes is separately authorized by the user. Tests use temporary stores, synthetic 2030 forecasts and mocked Gemini HTTP responses; socket connections and Scout forecast generation are explicitly forbidden in the new integration tests.

## Verified workflow

`expert_automation.execute_once` -> existing `plug_publication.publish` imports already-sealed approved forecasts -> `expert_auto_queue.bounded_run` -> existing Gemini provider/CLI saves pending drafts -> human creates approved review metadata -> `expert_review_publication.run` appends immutable reports and freezes two free games -> existing Flask HTML/API enforces access.

The worker dynamically discovers eligible future production imports. There is no fixed NFL game count. New end-to-end coverage tests 0, 1, 3, 7, 13, 16 and 20 synthetic eligible games. The 20-game case makes 16 mock requests in four four-request runs, makes no further calls while the rolling quota is full, then finishes four after capacity expires. This does not imply every arbitrary slate finishes in one day: production is still limited to 16 requests per rolling 24 hours, four per run and future kickoffs.

Pending drafts do not publish. Simulated human approvals publish all 20 once, exactly two featured games are public, remaining reports require premium beta entitlement. Anonymous visitors and ordinary signed-in users get HTTP 403 from premium Expert API routes; their HTML excludes private prose. Premium accounts receive it. Responses are private/no-store. Saved report/forecast bytes remain unchanged on reruns; completed responses are reused without loading credentials or calling Gemini.

## Confirmed fixes (local, not deployed)

- Direct Gemini draft CLI now shares persistent rolling 24-hour and minute caps across processes using a dedicated reservation lock. Scheduled queue locking remains intact. Failures/timeouts consume reservations; there is no automatic retry or paid fallback.
- Existing complete Gemini drafts are reused after matching their Scout digest. New drafts after kickoff are rejected.
- Manual Gemini default now matches the worker's `gemini-2.5-flash` instead of `gemini-3.8-flash`.
- Hosted Expert-only timeout increased from 480 to 900 seconds. Four 120-second calls plus three 75-second pacing intervals can take 705 seconds before overhead. No timing/rollover logic for Scout changed.
- Worker status continues showing `needs_review` while an uncertain prior attempt remains, even after later games finish.
- Archive reads validate published Expert report grounding/schema as well as the Scout snapshot and file digest.

## Validation and known pre-existing test issue

86 Expert/editorial/integration tests pass, with real network connections blocked. The previously failing byte-equality assertion has been replaced by rendered functionality checks. Desktop and mobile templates both provide the correctly targeted View Team Comparison link, picks, report sections, preserved versions, return navigation and premium protection; intentional layout/HTML differences are allowed. The mobile template received only the missing comparison-link block; no CSS/layout changes. Browser rendering checked at a 390px iframe viewport before commit.

## Human intervention and safest streamlining

Editorial approval is deliberately manual. For each `drafts/<version>.json`, a reviewer must check claims against the exact archived Scout evidence, unsupported roster/trend claims, disagreement, prices, uncertainty and counterarguments. Create `drafts/<version>.review.json` containing identical AI claims and only `review_status="approved"`, a named `reviewer`, and actual `reviewed_at` changed/added. Publication rejects altered prose/evidence. Revisions require a separately verified draft; do not delete attempt reservations to blindly retry.

Safest practical streamlining: use one human review inbox/checklist with source links and a metadata-only Approve/Reject action, then let the existing hourly publication worker publish approved files and choose two free reports automatically. No second Gemini approval call is needed. An authenticated reviewer UI is a future convenience, not a prerequisite, and is not implemented here. Do not auto-approve merely because JSON/citation syntax validates.

Premium is currently enforced through the server's existing owner/premium-member allowlist, not automatic payment/subscription verification. The owner must provision the intended premium member IDs. A week with fewer than two published upcoming reports leaves featured selection absent until two exist; no fake reports are created. Once selected, featured games are immutable for the week.

## Exact remaining activation sequence (requires authorization)

1. Review and deploy these narrowly scoped fixes with approval. Do not change the approved Scout configuration/fingerprints.
2. Let the existing Wednesday 8 a.m. America/New_York rollover occur normally. Generate/seal the intended week's production forecasts only under separate authorization; these tests did not create Week 7 forecasts.
3. Verify the persistent Expert store and publication status contain the complete eligible sealed slate. Preview only:
   `python expert_auto_queue.py --store /var/data/expert_beta --model gemini-2.5-flash --daily-limit 16 --run-limit 4`
4. Owner verifies the Gemini project's actual current quota/free-tier eligibility and disabled billing, and confirms the private key is configured. The local safeguards cannot infer billing status or account for calls made outside this shared store/project workflow.
5. With authorization, make ONE controlled manual request for one exact imported version while automatic drafting stays off:
   `python expert_beta_cli.py --store /var/data/expert_beta draft <version> --provider gemini --model gemini-2.5-flash`
   Requires `EXPERT_GEMINI_FREE_TIER_CONFIRMED=1`. It counts against the persistent daily budget. Check saved draft/attempt and provider usage; do not blindly retry a timeout.
6. Human reviews that draft and writes its metadata-only approval file. Preview publication:
   `python expert_review_publication.py --store /var/data/expert_beta`
   Execute publication only when authorized: same command plus `--execute`. Two approved upcoming reports are required before two free features can be frozen.
7. With authorization, enable `TREND_FINDAH_EXPERT_AUTO_DRAFT=1` and (for reviewed-file publication) `TREND_FINDAH_EXPERT_AUTO_PUBLISH=1`. Verify existing `TREND_FINDAH_EXPERT_DAILY_LIMIT=16`, `TREND_FINDAH_EXPERT_RUN_LIMIT=4`, `TREND_FINDAH_EXPERT_GEMINI_MODEL=gemini-2.5-flash`, store path and free-tier attestation. Do not duplicate the existing worker. Daily limits use rolling 24 hours, not midnight reset.
8. Monitor automation status, queue counts, pending reviews, uncertain attempts and HTML/API access as anonymous, ordinary member and premium member. Approve reports before kickoff; publication excludes completed/started games. Normal website requests reuse stored reports and never call Gemini.
