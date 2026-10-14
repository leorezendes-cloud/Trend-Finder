# Trendfindah newsletter

The newsletter is now implemented in the current original project. Its order is prediction highlights, upcoming matchups, notable trends, and optional site updates. It uses the existing membership database, explicit opt-in and weekly/monthly preferences, site-owner permissions, and Resend account. It does not run models or collectors. No newsletter has been sent or scheduled by this implementation.

## Write and review

Sign in with an existing site-owner account. Open **Menu → Manage Newsletter**, or `/newsletter/manage`. Regular members and guests cannot access the editor, issue details, subscriber counts or previews. If your account has not already been granted site-owner access, use the existing private host Shell command `python -m flask --app wsgi membership-owner YOUR_REGISTERED_EMAIL` for the trusted owner account. Local and hosted owner roles are separate because their databases are separate.

Create a weekly or monthly draft, enter published prediction highlights and optional supporting sections, preview the email, and edit as needed. Content is plain text and HTML is escaped. Approve the issue when ready. Approval locks the content, but sends no email. You can cancel an issue to stop remaining delivery; previously accepted messages cannot be recalled.

Weekly issues only target weekly opt-ins; monthly issues only target monthly opt-ins. Preferences remain under My Profile. The delivery command freezes the audience and exact email payload at its first sending run. New subscribers do not receive an old issue when the command is rerun. Opt-out, frequency, email address, and cancellation are checked before each queued send.

## Host environment settings

Use the existing `RESEND_API_KEY` and trusted `TREND_FINDAH_PUBLIC_ORIGIN` configured for password recovery. Set these additional NAME / VALUE pairs in the host environment:

| Name | Value |
| --- | --- |
| TREND_FINDAH_NEWSLETTER_ENABLED | false until ready; true explicitly enables delivery |
| TREND_FINDAH_NEWSLETTER_FROM | Trendfindah <noreply@mail.trendfindah.com> (or your verified sender) |
| TREND_FINDAH_NEWSLETTER_ADDRESS | your business postal mailing address |

Sender name has been set to **Trendfindah**. The postal address still needs to be supplied. Sending refuses to run without it and the Resend key. The sender domain must already be verified in Resend. Newsletter delivery is distinct from password recovery and will stay off unless explicitly enabled. Changing newsletter settings does not enable or disable password recovery.

Restart/redeploy the current site with these source changes to add the menu entry and routes. No remote deploy or environment update has been performed. The two newsletter tables initialize idempotently at startup and are included in existing membership database backups. Existing member accounts, preferences, and watchlists are preserved.

## Delivery commands

From the project folder, use the host's Python environment (or `.venv/bin/python` locally). Replace ISSUE_ID with the number shown in the newsletter page.

Dry run, which never sends email:

```sh
python -m flask --app wsgi newsletter-send ISSUE_ID
```

After reviewing and approving the issue and configuring live delivery, the operator can deliberately send:

```sh
python -m flask --app wsgi newsletter-send ISSUE_ID --send
```

There is no unattended schedule or automatic sending on signup, page views, preference changes, approval, or startup. Publish at the weekly/monthly cadence selected by subscribers; each edition needs its own draft and approval. Sending occurs sequentially and should run from a host shell or a separate worker, not within a web request. Sending configuration and initial inbox verification remain required before launch.

Each recipient has a durable record and random idempotency key. Successful acceptance is never resent by this issue. Temporary/uncertain requests can be retried using the identical frozen payload/key for up to 23 hours after the first attempt, stopping before Resend's 24-hour key expiry. After that, inspect provider records manually before doing anything that could resend. Do not delete delivery records or create a replacement issue merely to retry an uncertain message. Provider acceptance is not proof of delivery; bounce/complaint processing and delivery webhooks are not configured by this milestone.

Unsubscribe URLs are signed, contain no email address, require no login, and support one-click unsubscribe headers. Opening a link displays confirmation and does not change consent; confirming the form does. Mail clients can POST `List-Unsubscribe=One-Click` to opt out directly using the signed URL. Opt-out clears the stored newsletter consent without deleting the member's account/watchlist. Unsubscribe links should not be logged; existing Gunicorn configuration avoids request-path access logging.

## Verification

```sh
python -m unittest test_newsletter test_membership test_membership_backups test_hosting -v
```

Tests use temporary member databases and mocked Resend requests. They cover owner permissions, CSRF, editing/locking, preview escaping and section order, audience/frequency selection, unsubscribe, opt-out on retry, frozen audiences, duplicate prevention, retry payload/key stability, stale-retry refusal, disabled delivery, and the actual CLI path. No member email or real provider request is used.

Provider references: https://resend.com/docs/api-reference/emails/send-email and https://resend.com/docs/dashboard/emails/idempotency-keys
