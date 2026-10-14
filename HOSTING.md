# Hosting preparation

This checkout now combines the website and membership changes with the original project, including its newer matchup and Scout presentation changes. Scout code and historical data were preserved. Nothing has been uploaded or deployed.

## What is prepared

- `requirements.txt`: Flask, Werkzeug and Gunicorn dependencies for public browsing and membership. Collectors and data refresh are intentionally not part of the hosted runtime.
- `wsgi.py`: production entry point, project-relative working directory, `/healthz`, and configurable trusted proxy count.
- `gunicorn.conf.py`: host-provided port (default 8000), one worker with four request threads for SQLite, and no access logs containing reset-link secrets.
- `render.yaml`: optional Render template with a persistent 1 GB disk and generated session secret. It selects a paid service; review pricing in your account before applying. Nothing has been provisioned.
- `scripts/prepare_release.py`: assembles a clean website snapshot in `dist/website` and writes a file fingerprint manifest. It excludes account databases, secrets, backups, raw personnel downloads and experiment outputs not read by public pages.

Source documentation: https://render.com/docs/deploy-flask, https://render.com/docs/disks, https://render.com/docs/blueprint-spec, https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/

## Local production-style verification

Use Python 3.14 and a separate environment. Run these in the prepared website directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest test_membership test_hosting test_page_layouts test_trend_filters test_site_sections -v
.venv/bin/gunicorn --config gunicorn.conf.py wsgi:app
```

This local check uses automatically generated local session keys. It does not send email. For hosting, configure the production environment below. Keep the local research server and hosted runtime separate.

## Public hosting settings

Create a Web Service from the reviewed Git branch or from the clean release repository. A GitHub connection and deploying are separate steps that have not been performed. The service's source root must contain `app.py`, `templates`, `static`, `data`, `requirements.txt`, and `wsgi.py`; do not select the scripts folder as the source root.

In the host's setup form:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --config gunicorn.conf.py wsgi:app`
- Health check: `/healthz`
- Python: `3.14.7`
- Attach persistent storage at `/var/data` before starting.

In the host's Environment settings, enter these once as NAME / VALUE pairs:

| Name | Value |
| --- | --- |
| TREND_FINDAH_ENV | production |
| TREND_FINDAH_SECRET_KEY | a long generated secret, kept stable across deployments |
| TREND_FINDAH_DATABASE | /var/data/members.sqlite3 |
| TREND_FINDAH_PROXY_HOPS | 0 initially; set to the verified number of trusted proxy hops |

`0` deliberately ignores forwarded address headers. Do not guess the proxy count: setting it too high would let clients forge their IP, while keeping it at zero behind a proxy shares rate limits across visitors. Verify the host's chain before public launch. Serve through the host's HTTPS address; do not expose Gunicorn directly to the internet.

The account database initializes automatically. Keep its contents on the disk, outside Git, and back it up using the documented membership command. A persistent disk is not itself a backup. Configure separate backup storage and a schedule after choosing the host.

## Research operations

The hosted WSGI entry point blocks all write requests except membership routes and Trend Finder's read-only analysis form (and legacy home POST redirects). This includes results refresh, anomaly editing and Scout captures. These continue to work in the local research app when launched with `app.py`; no collectors are run by preparation, startup or page viewing. Some existing research pages still show local-operation controls; on the hosted service they return an explanatory 403 response. Hosting does not automatically update historical data: publish a newly reviewed data snapshot when needed.

## Email and release prerequisites

Password recovery sends transactional email through Resend when `RESEND_API_KEY` is set. Set that private key in Render Environment settings. `TREND_FINDAH_EMAIL_FROM` defaults to `Trend Findah <noreply@mail.trendfindah.com>`; that sending domain must be verified in Resend. `TREND_FINDAH_PUBLIC_ORIGIN` defaults to `https://trendfindah.com` and must be an HTTPS origin without a path. Never generate links from incoming Host headers. Without the key, recovery clearly reports temporary unavailability. Provider failures are logged without recipients, tokens, keys, or response bodies. Gunicorn access logs omit URL paths to protect reset tokens. Test actual inbox delivery after deployment; automated checks mock Resend. Newsletter delivery is separately disabled by default. See NEWSLETTER.md for owner drafts, unsubscribe, mailing-address settings, and explicit delivery commands.

Before public launch: reconcile current Scout work, confirm the release-data manifest, choose the host and email provider, configure HTTPS/proxy/storage/backups, test email recovery, and approve the deployment. No user account or local session secret is included in the release.


## Site structure

Gravy Train is the umbrella brand. `/` now shows Upcoming Matchups with links to the three primary sections: `/trend-finder`, `/the-plug`, and `/conspiracy-dungeon`. Discover Trends (`/trends`) and Backtests sit under Trend Finder. Stats, ratings, and Forecast Tracker sit under The Plug. Results is linked from Home. Existing `/sunday`, `/sunday-scout`, stats and trend-detail URLs remain available. Old POST forms targeting `/` redirect with HTTP 307 to `/trend-finder`, preserving their submitted fields. No predictive logic or data files were changed by this reorganization.

Static files use Werkzeug middleware with one-hour public caching and bypass Flask session/page work. CSS and JavaScript URLs contain content versions. Four request threads allow assets and health checks to respond while page analysis runs.

## Scores and fan-facing statistics

The homepage loads `/scores.json` separately and polls it every minute while visible. The server caches the read-only ESPN scoreboard for 60 seconds and labels retained scores as delayed if retrieval fails. Scoreboard requests do not alter the CSV or saved predictions. Team/player statistics remain reviewed nflverse snapshots and display retrieval time. Matchup comparisons include only completed regular-season games before that matchup's week. Fantasy uses recorded PPR offensive production, explicitly before fumble deductions and without return scores, two-point conversions, bonuses, kickers or defenses; it is not a weekly projection.

## Automatic hosted updates

Set `TREND_FINDAH_AUTO_UPDATE=1` on the existing Render web service after deploying the updater. On startup, public CSV files and Scout data are seeded once into `/var/data/site-data` and linked into the checkout. Existing persistent data and sealed predictions are retained on redeploys. A daemon scheduler runs a separate bounded updater process at startup and every six hours; locking prevents overlapping runs. Finals require matching nflverse and ESPN scores, current-season stats import atomically, quote capture retains source evidence, and eligible predictions use the frozen automatic model configuration. Predictions are skipped if a required input update fails. Already saved game predictions are never replaced. Grading reads saved finals. Status appears on the homepage; failures retain the previous published data. Monitor persistent disk usage as evidence accumulates. Before the next season, verify that the schedule and reviewed model support it. Disable the environment flag to stop scheduling; persistent data is preserved.

## Automatic member pick lines

The same `TREND_FINDAH_AUTO_UPDATE=1` setting also enables a separate Wednesday 8 a.m. Eastern market capture and automatic shared-line publication. The timer checks every 30 seconds; capture completion takes a few minutes. Weekly snapshots persist separately under `/var/data/site-data/data/member_lines/`. Missing verified quotes leave publication pending. View `/picks/admin` to review frozen lines without entering them. See WEEKLY_POLICY.md for the one-time 2026 Week 6 snapshot and catch-up rules.

Owner **Manage Weekly Picks → Site health** shows whether a recent backup has passed restore verification and whether automatic data updates are healthy. Restore checks include member pick and newsletter tables when present. This panel reports saved status only; it does not run jobs on visits. Production health still needs to be checked after deployment on the actual Render disk.
