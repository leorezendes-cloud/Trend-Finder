# Gravy Train membership

Public trend, matchup, results, and Scout pages remain available without an account. Members can register, log in, log out with a POST form, and save explicit newsletter consent and weekly/monthly preferences. Newsletter delivery and comments are not implemented.

Accounts use SQLite, Werkzeug scrypt password hashes, unique case-insensitive email addresses, parameterized queries, and session rotation at login/registration/logout. Membership POST forms require session-bound CSRF tokens. Existing Scout and analysis POST endpoints retain their existing behavior; this module does not secure or change those endpoints.

## Configuration

Use the project's existing Python environment and Flask dependencies. Membership adds no third-party dependencies.

- `TREND_FINDAH_SECRET_KEY`: Set a long random secret for hosted use. In local development, a persistent key is generated with owner-only permissions in `instance/session.key`.
- `TREND_FINDAH_ENV=production`: Requires the explicit secret and enables secure cookies; serve over HTTPS.
- `TREND_FINDAH_DATABASE`: Optional absolute SQLite file path. Defaults to `instance/members.sqlite3`. Its parent directory must exist and be writable. Keep this file on durable storage and back it up; exclude accounts and keys from source control.

Schema version 2 initializes automatically at startup. Re-running `python -m flask --app app init-membership-db` is safe and preserves members. Future versions must add a sequential migration in `membership.migrate`; newer database versions are rejected.

Start locally using `python app.py` (port 5001), then visit `/members/register`. Membership does not run collectors, refresh data, or send email. Password recovery and login rate limiting are implemented. Email delivery and email verification remain unconfigured.

## Verification

Run with the project's existing Python environment:

```sh
python -m unittest test_membership test_page_layouts test_trend_filters -v
```

Membership tests cover validation, duplicate emails, hashed passwords, login failures/success, consent defaults and opt-out, preference persistence, schema re-initialization, CSRF rejection and token rotation, logout semantics, public access, and production secret requirements. The existing page-layout and trend-filter tests verify browsing and analysis still behave as before.


## Password recovery and request limits

The login page now links to `/members/forgot-password`. Until an email provider is configured, that page clearly states that no email is sent and returns the same response for existing and unknown accounts. It does not expose reset tokens.

For local testing, create an account and then run this from the membership checkout using the project Python environment:

```sh
python -m flask --app app membership-reset-link YOUR_ACCOUNT_EMAIL
```

Open the printed localhost:5002 link and choose a new password. Treat that URL as a secret. This operator command is disabled when `TREND_FINDAH_ENV=production`. Reset tokens are random, stored only as SHA-256 hashes, expire after 15 minutes, and can be used once. Issuing a new link replaces previous links. A successful reset invalidates existing login sessions and directs the user to log in again. Existing accounts are preserved by the version 1 → 2 migration.

Login and recovery are each limited to 5 requests per normalized email and 30 requests per peer IP per 15-minute window. Counters reside in SQLite and survive worker/server restarts. The app does not trust forwarded IP headers. On a host behind a proxy, configure the known proxy chain before relying on per-user IP limits; otherwise users behind that proxy share the IP limit. Limits include successful attempts.

## Persistent storage and backups

Local account storage already persists in `instance/members.sqlite3`. On a host, mount durable storage and set `TREND_FINDAH_DATABASE` to a file on that mount. Keep the session secret stable across deployments. A host and email provider still need to be selected; neither has been provisioned or contacted.

Create a consistent backup to a new file with:

```sh
python -m flask --app app backup-membership-db /absolute/path/to/new-backup.sqlite3
```

The command uses SQLite's backup API, restricts the new file to its owner, and refuses to overwrite existing files. Store backups separately from the host's main disk and arrange a retention schedule during hosting setup. Backups contain private account data; don't commit or upload them to public repositories. To restore, stop the membership app, preserve the existing database, copy the backup to the configured database path, then restart. No scheduled backup job is installed.

Before public release, connect a transactional email provider to recovery, use a trusted configured public origin for reset URLs, apply the host's trusted-proxy settings, and test real delivery. Newsletter email remains disabled.
