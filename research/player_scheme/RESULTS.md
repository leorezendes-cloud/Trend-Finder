# Cached-cohort evaluation

Exploratory retrospective evaluation of corrected nflverse archives. Negative MAE delta is better. Baselines are independent research models, not production Scout/Plug forecasts. The 2026 cohort is partial (79 imported games; 31 after warmup), from the existing October 14 cache.

| Season | Margin n | Margin delta | Total delta | Passing yards delta | Rushing yards delta | Receiving yards delta |
|---|---:|---:|---:|---:|---:|---:|
| 2023 | 224 | -0.0087 | +0.0032 | +0.0004 | +0.0233 | -0.0934 |
| 2024 | 224 | -0.0266 | -0.0031 | -0.0342 | -0.0086 | -0.0684 |
| 2025 | 224 | -0.0377 | -0.0188 | +0.2942 | -0.0128 | -0.1016 |
| 2026 | 31 | -0.0691 | +0.0055 | +0.3839 | -0.0097 | -0.0964 |

No convincing improvement in scoring margins or totals. Receiving-yard deltas are small and exploratory; passing-yard changes worsen in 2025 and 2026. No production promotion is justified. Full sample counts, MAEs, positional breakdowns and bootstrap intervals are in `evaluation.json`. PBP and optional charting diagnostics are implemented, but their incremental predictive benefit is not evaluated by this fixed feature subset.

Local macOS measurements: database 11,816,960 bytes; fresh offline import plus evaluation 19.099 seconds, peak RSS 197,066,752 bytes. Reader benchmark: 24,543,232 additional peak bytes across ten current/full-season reads (25 MiB target). No Render deployment or production stress test.

Separate real-cache 2022 participation validation: 1,206 compact summaries, 17,979 known-coverage dropbacks (5,169 man), 18,008 known-pressure dropbacks. Provider enum values and mixed integer/float play keys normalize before exact joins. This schema check is not evidence of current-season scheme availability.

17 regression/integration tests pass locally. CI independently checks the same suite and verifies no production application modules or Polars load through core research imports.
