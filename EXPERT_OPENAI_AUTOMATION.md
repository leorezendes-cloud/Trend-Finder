# OpenAI Expert automation — release review

This change does not deploy itself, generate forecasts, approve reports, or modify
existing reports. All tests use synthetic stores and mocked HTTP. No paid request
was made while preparing this branch.

## Scheduling and editorial flow

The existing Gunicorn post-worker hook starts the single-leader scheduler when
`TREND_FINDAH_AUTO_UPDATE=1`. Successful Scout publication invokes the queue. The
existing lightweight Expert-only job also checks every five minutes, under the
same persistent update lock, so processing continues without Render Shell work.
One request per pass is the default; an entire new slate is deliberately paced.
Existing leadership, job reservations, worker deadlines and recovery leases stay
in place. A real-thread leader/worker integration test verifies this path.

Only future, sealed `production_import` forecasts are eligible. Any saved draft or
published report for that game blocks generation, even if a new Scout version
appears. Original provider attribution is preserved. New drafts remain `pending`
in the existing drafts directory and have OpenAI response ID, model and usage.
The existing editorial review process is still required; no review/approval is
synthesized or persisted. If review publication is already enabled, only separately
human-approved review files can be published. Pending drafts never become public.

## Configuration for a later, separately approved deployment

Existing hosted flags and storage paths are retained. Credentials stay solely in
Render environment variables, never in this repository, logs or status files.

| Setting | Meaning / default |
| --- | --- |
| `OPENAI_API_KEY` | Already configured by owner; required for OpenAI calls |
| `EXPERT_AI_MODEL` | Already configured by owner; never silently replaced |
| `TREND_FINDAH_EXPERT_AUTO_DRAFT` | Existing opt-in; must be `1` |
| `TREND_FINDAH_EXPERT_AUTO_PROVIDER` | Defaults to `openai` |
| `TREND_FINDAH_EXPERT_WEEKLY_BUDGET_USD` | Defaults to `1`; accepted range `0..1` USD |
| `TREND_FINDAH_EXPERT_WEEKLY_REQUEST_LIMIT` | Defaults to 32 attempts per NFL season/week; maximum 32 |
| `TREND_FINDAH_EXPERT_DAILY_LIMIT` | Defaults to 16 attempts per rolling 24 hours; maximum 16 |
| `TREND_FINDAH_EXPERT_RUN_LIMIT` | Defaults to 1; maximum 4 |
| `TREND_FINDAH_EXPERT_FALLBACK_PROVIDER` | Unset by default; `gemini` permits fallback only before any transmission when the OpenAI key is absent |

Gemini is never an implicit fallback after a timeout or rejection. Explicit Gemini
selection/fallback still requires its existing free-tier confirmation and quota
guards. This branch does not alter Render configuration or enable any flags.

## Conservative estimated spending

Before sending a request, reserve its full worst-case estimated cost atomically
and fsync it to the persistent disk. Count one input token per serialized UTF-8
request byte plus 1,024 framing tokens, the entire 6,000-token output allowance,
and a 2x cost margin. Force standard service tier; enable no paid tools, stored
responses, conversation history or external lookups. Request bodies are capped at
64,000 bytes and evidence at 40,000 bytes.

No reservation is refunded, including rejected, invalid, interrupted and uncertain
calls. Both a failed attempt and its permitted retry consume budget. Cost limits
are keyed to the forecast's NFL season/week, not calendar day or worker lifetime.
A pre-existing unpriced OpenAI reservation consumes the full $1 allowance for its
NFL week; corrupt/unattributable reservations stop requests for operator review.
This controls this automation's conservative estimate, not unrelated manual API
use, other applications, provider price changes or taxes.

Built-in uncached input/output USD per million token rates (verified 2026-10-22):
- GPT-4.1 mini: 0.40 / 1.60
- GPT-5 mini: 0.25 / 2.00
- GPT-4o mini: 0.15 / 0.60

Sources:
https://developers.openai.com/api/docs/models/gpt-4.1-mini
https://developers.openai.com/api/docs/models/gpt-5-mini
https://developers.openai.com/api/docs/models/gpt-4o-mini

The configured model is never changed to fit this table. Unknown models stop
before a paid call. If another model is configured, an operator must verify its
standard rates and set `TREND_FINDAH_EXPERT_OPENAI_PRICING` to a JSON object with
`model` (exact configured name), `input` and `output` (USD per million tokens).
That configuration must be reviewed before deployment. Budget exhaustion can
leave games without a draft; the system does not bypass the cap to finish a slate.

## Recovery and protection

Only explicit HTTP 429 rejection gets one deferred retry (at least five minutes,
respecting a bounded numeric Retry-After up to one hour). The next scheduler pass
performs that retry after reserving its cost. A second rejection stops. Timeouts,
network errors, other HTTP errors, malformed reports, unknown billing outcomes,
changed retry models and interrupted requests require operator review; no blind
retry, reservation clearing or provider switch occurs. Requests require at least
125 seconds before kickoff; late completions are never saved as pregame drafts.

Drafts and request reservations are create-only and atomic. Queue locking is
nonblocking, and process exits release locks without deleting reservations. Full
schema, section order, selections and evidence references are validated before a
pending draft is saved. Status stores only safe types/counts, never prompts, keys,
provider error bodies or report text.

## Validation command

```bash
python -m unittest test_openai_expert_queue test_expert_auto_queue \
  test_expert_provider test_expert_automation test_expert_pipeline_e2e \
  test_expert_gemini test_expert_review_publication \
  test_hosted_scheduler test_scheduler_runtime -q
```

The tests cover a synthetic 14-report Week 7 archive byte-for-byte, duplicate/new
seal runs, credentials and pricing failures, weekly/daily caps, persistent unknown
outcomes, delayed/rate-limit retries, malformed evidence/schema, kickoff timing,
lock contention, Gemini fallback gating, and actual automatic scheduler execution.
Production scheduler activation and the owner's configured model cannot be
verified live before the separately approved deployment; the equivalent path is
verified locally without production data or paid requests.
