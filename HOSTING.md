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

Password recovery is implemented for local testing only. Public email delivery and newsletter delivery remain inactive. Choose a transactional email provider and verify a sending address/domain, then implement and test its recovery delivery with a configured trusted public origin. Do not present the current local-only recovery screen as a completed public recovery feature.

Before public launch: reconcile current Scout work, confirm the release-data manifest, choose the host and email provider, configure HTTPS/proxy/storage/backups, test email recovery, and approve the deployment. No user account or local session secret is included in the release.


## Site structure

Gravy Train is the umbrella brand. `/` now shows Upcoming Matchups with links to the three primary sections: `/trend-finder`, `/the-plug`, and `/conspiracy-dungeon`. Discover Trends (`/trends`) and Backtests sit under Trend Finder. Stats, ratings, and Forecast Tracker sit under The Plug. Results is linked from Home. Existing `/sunday`, `/sunday-scout`, stats and trend-detail URLs remain available. Old POST forms targeting `/` redirect with HTTP 307 to `/trend-finder`, preserving their submitted fields. No predictive logic or data files were changed by this reorganization.

Static files use Werkzeug middleware with one-hour public caching and bypass Flask session/page work. CSS and JavaScript URLs contain content versions. Four request threads allow assets and health checks to respond while page analysis runs.
