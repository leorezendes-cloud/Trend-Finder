# Launch readiness — October 13, 2026

## Completed in this pass

- Trend Finder rejects invalid seasons, incomplete/reversed ranges, nonnumeric spreads, NaN/infinity, out-of-range spreads, unsupported modes, and invalid location/primetime values without running analysis or crashing.
- Older QB/evidence tests now use `/trend-finder`; legacy home POST redirects are also checked.
- A restore copy of the changed pre-existing files is saved at `backups/2026-10-13-before-launch-fixes/changed-files.zip`. Earlier full-workspace backups remain available.
- Predictive-model scripts and saved model outputs were not changed.

## Before public deployment

1. Follow HOSTING.md and deploy the reviewed release using `wsgi:app`, not the development server. No service was created or deployed in this pass.
2. Configure the production environment, stable session secret, persistent membership database, HTTPS, and the verified proxy-hop count. Verify login, registration, logout, and `/healthz` on the real host.
3. Configure and test transactional password-recovery email with a verified sender and trusted public origin. Resend delivery is implemented; actual inbox delivery still needs verification after configuring the key.
4. Verify hosted write restrictions reject research edits/captures while allowing the read-only analysis form and protected membership actions.
5. Arrange database backups and verify restoration. Keep local credentials, account databases, and research backups out of the published release.
6. Publish a reviewed, current NFL/market data snapshot and decide who updates it. Hosted browsing does not automatically refresh the research data.
7. Verify all primary pages on mobile and desktop, then check response times with multiple visitors in staging. Automated local tests do not establish live-host performance.
8. Keep model forecasts labeled experimental until their independently evaluated performance supports stronger claims. This pass did not retrain or revalidate the predictive models.

Start with a controlled beta after these deployment checks, before a broad public launch.
