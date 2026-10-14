# Gravy Train membership

Public trend, matchup, results, and Scout pages remain available without an account. Members can register, log in, log out with a POST form, and save explicit newsletter consent and weekly/monthly preferences. Newsletter delivery and comments are not implemented.

Accounts use SQLite, Werkzeug scrypt password hashes, unique case-insensitive email addresses, parameterized queries, and session rotation at login/registration/logout. Membership POST forms require session-bound CSRF tokens. Existing Scout and analysis POST endpoints retain their existing behavior; this module does not secure or change those endpoints.

## Configuration

Use the project's existing Python environment and Flask dependencies. Membership adds no third-party dependencies.

- `TREND_FINDAH_SECRET_KEY`: Set a long random secret for hosted use. In local development, a persistent key is generated with owner-only permissions in `instance/session.key`.
- `TREND_FINDAH_ENV=production`: Requires the explicit secret and enables secure cookies; serve over HTTPS.
- `TREND_FINDAH_DATABASE`: Optional absolute SQLite file path. Defaults to `instance/members.sqlite3`. Its parent directory must exist and be writable. Keep this file on durable storage and back it up; exclude accounts and keys from source control.

Schema version 4 initializes automatically at startup. Re-running `python -m flask --app app init-membership-db` is safe and preserves members. Future versions must add a sequential migration in `membership.migrate`; newer database versions are rejected.

Start locally using `python app.py` (port 5001), then visit `/members/register`. Membership does not run collectors or refresh research data. Password recovery sends through Resend when RESEND_API_KEY is configured. Email verification and newsletters remain inactive.

## Verification

Run with the project's existing Python environment:

```sh
python -m unittest test_membership test_page_layouts test_trend_filters -v
```

Membership tests cover validation, duplicate emails, hashed passwords, login failures/success, consent defaults and opt-out, preference persistence, schema re-initialization, CSRF rejection and token rotation, logout semantics, public access, and production secret requirements. The existing page-layout and trend-filter tests verify browsing and analysis still behave as before.


## Password recovery and request limits

The login page now links to `/members/forgot-password`. With RESEND_API_KEY configured, existing accounts receive a Resend recovery email and unknown accounts receive the same public response without email. Without a key, the page reports temporary unavailability. Links use the trusted configured public origin and tokens are never displayed on the recovery page. See HOSTING.md for settings.

For local testing, create an account and then run this from the membership checkout using the project Python environment:

```sh
python -m flask --app app membership-reset-link YOUR_ACCOUNT_EMAIL
```

Open the printed localhost:5002 link and choose a new password. Treat that URL as a secret. This operator command is disabled when `TREND_FINDAH_ENV=production`. Reset tokens are random, stored only as SHA-256 hashes, expire after 15 minutes, and can be used once. Issuing a new link replaces previous links. A successful reset invalidates existing login sessions and directs the user to log in again. Existing accounts are preserved by the version 1 → 2 migration.

Login and recovery are each limited to 5 requests per normalized email and 30 requests per peer IP per 15-minute window. Counters reside in SQLite and survive worker/server restarts. The app does not trust forwarded IP headers. On a host behind a proxy, configure the known proxy chain before relying on per-user IP limits; otherwise users behind that proxy share the IP limit. Limits include successful attempts.

## Persistent storage and backups

Local account storage already persists in `instance/members.sqlite3`. On a host, mount durable storage and set `TREND_FINDAH_DATABASE` to a file on that mount. Keep the session secret stable across deployments. The hosted service uses Render and Resend recovery delivery. Configure and verify the key and sender before testing real delivery.

Create a consistent backup to a new file with:

```sh
python -m flask --app app backup-membership-db /absolute/path/to/new-backup.sqlite3
```

The command uses SQLite's backup API, restricts the new file to its owner, and refuses to overwrite existing files. Store backups separately from the host's main disk and arrange a retention schedule during hosting setup. Backups contain private account data; don't commit or upload them to public repositories. To restore, stop the membership app, preserve the existing database, copy the backup to the configured database path, then restart. No scheduled backup job is installed.

Before public release, configure the Resend key, verify the sending domain, apply the host's trusted-proxy settings, and test real delivery. Newsletter email remains disabled.

## Signup totals

In the Render service's Shell, run `python -m flask --app wsgi membership-count`. It reports total members, signups in the last seven days, and newsletter opt-ins without printing member emails. This operator command is not a public endpoint. Running it locally counts only the local database, not hosted accounts.

## Automatic account backups

With hosted automatic updates enabled, the account database is backed up every six hours into `/var/data/account-backups`. The SQLite backup API produces a consistent copy while users are active. Every snapshot is integrity checked and restored into a temporary database; full rows and counts are compared before it becomes a retained backup. The directory is private (0700) and snapshots are private (0600). The newest 112 snapshots are retained, approximately 28 days at the six-hour schedule. In Render Shell, run `python -m flask --app wsgi membership-backup-status` to check the latest verification. These backups share the service disk: they do not protect against loss of the entire disk. Arrange a separate private storage destination before treating disaster recovery as complete. No automatic upload of member data occurs.

For recovery, verify a selected copy in isolation with `membership_backups.verify_restore`, then stop the web service before an operator replaces the account database. Keep the current database separately. Do not restore over a running service, and do not use an entire disk rollback for routine account recovery because it would also roll back stats and sealed predictions.

## My Watchlist

Profiles contain a private team/trend watchlist, up to 100 saved items per member. Save teams on their statistics or matchup pages; save trends on their detail pages. Duplicate saves do not create duplicate items. Membership CSRF protection and authenticated owner checks protect save/remove actions. Saved team links show current statistics; saved trend URLs retain their original filters and recalculate results against available data. Schema version 3 adds the watchlist without altering existing accounts. Verified account backups include watchlist rows and continue supporting older version-2 snapshots.

## Beta feedback

The navigation menu links to a public CSRF-protected feedback form. Reports include category, page path (query strings and password-reset tokens removed), message, optional authenticated member ID, and time. No email is sent. Reports are retained privately in the account database and included in verified backups. Owner review requires an explicit operator grant: in Render Shell run `python -m flask --app wsgi membership-owner YOUR_REGISTERED_EMAIL`. This grants access only to an existing account; registration itself never grants privileges. The account then sees Review Feedback in the menu and profile. Owners can mark reports resolved or reopen them. Review responses are not cached; other accounts and guests receive 403. Feedback submissions have validation and database-backed rate limits. Schema version 4 adds feedback and owner roles without replacing accounts or watchlists.
