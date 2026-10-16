# Member picks

Members can use **Menu → My Picks** or `/picks/` to submit free straight-up, against-the-spread, and over/under picks. Their profile links to this page. Their own record is shown separately for each category; other members' choices and records are not exposed. There are no wagers, payments, prizes, competitions or leaderboards.

## Automatic common weekly lines

Wednesday at 8 a.m. Eastern, the hosted worker captures the market and freezes shared spreads and totals for all unstarted games in the new NFL week. No manual line entry or publish button is required. Everyone uses the same immutable sheet. See [WEEKLY_POLICY.md](WEEKLY_POLICY.md) for observed timestamps, missing-quote behavior and the one-time 2026 Week 6 exception.

`/picks/admin` lists the sheets and lets the owner void a canceled/unplayed game with an explanation. Published lines cannot be edited, including after market movement. Existing published sheets are preserved.

## Members and locking

Members may choose any/all categories, change or clear their choices until the server's locking deadline, and save. Submission uses the signed-in member ID, not a form-supplied ID. All pick writes and owner mutations require CSRF tokens. Kickoff checks run inside the database transaction, so a submission at or after the deadline is rejected.

The deadline is the earlier of the published kickoff and any earlier kickoff subsequently found in the saved schedule. Locking is permanent: postponing a game does not reopen picks. Missing schedule rows or changed team identities do not produce guessed results. A verified saved final also locks the game immediately.

## Grading and records

The module reads the existing verified-final-score pipeline's canonical `nfl_games.csv`. It never runs collectors, predictions, data updates, or external requests. It requires finite nonnegative integer away/home scores and a matching saved result field (home minus away). Pending/incomplete data leaves results pending.

- Straight-up: chosen team wins/loses; equal final scores are a **Tie**.
- ATS: away scoring margin plus the fixed away spread determines the covering side; exactly zero is a **Push**.
- Total: combined final score compared with the fixed total; equality is a **Push**.
- Missing choices are not counted in a category's record.
- An owner may mark an ungraded, canceled/unplayed game **Void**, with a visible reason of 10–300 characters. It remains locked, and its picks do not add wins/losses. Games with recorded final scores cannot be voided through this feature.

Grading synchronizes on My Picks visits and submissions using the already-saved result data. Repeating grading does not duplicate games or inflate records. This is not a separate background score-fetching service: hosted score refresh must continue to provide verified finals through the existing pipeline. Admins should verify cancellation before voiding; missing scores do not automatically imply cancellation.

The three new tables (`pick_weeks`, `pick_games`, `member_picks`) initialize idempotently in the existing durable membership database and are included in its existing backups. No member account or research files are replaced. Published game identity, lines, deadline, submitted choices and final scores are stored in that database.

## Deployment and verification

Deploy the updated main commit in Render. Existing member accounts and site-owner roles work without new configuration. No week is created/published automatically; the owner must review and publish the first week's lines. Email settings and newsletter sending remain unchanged.

```sh
python -m unittest test_member_picks test_membership test_newsletter test_hosting -v
```

Tests use temporary schedules and member databases. They cover private drafts, common immutable lines, per-member choices, invalid selections, CSRF/access control, kickoff boundaries, idempotent final grading, pushes/ties, pending scores, postponements, voids and rebuilding draft weeks without modifying source data.

## Site week and shortcuts

See [WEEKLY_POLICY.md](WEEKLY_POLICY.md). The default sheet and submission window switch Wednesday at 8 a.m. Eastern. Automatic publication opens only the active week. Members can reach picks from the homepage, Upcoming Matchups, market and team comparison pages; game-specific links narrow the current sheet.

## Compact checklist and partial saves

My Picks displays a three-column card grid with one Save picks button. Check one choice per category; clicking a checked option again clears it. Blank categories can be saved and completed later. Saved choices reappear on subsequent visits. Each game keeps its kickoff deadline; if a game locks during editing, its existing picks stay unchanged while other open games save. Invalid choices reject the entire submission.

Matchup details and selected team-versus-opponent comparisons include the same controls inline. Saving keeps the member on that page, and changes use the same private records as My Picks. Clicking a My Picks matchup opens its comparison page. All save requests require CSRF protection and use the signed-in member ID. Signed-in comparison pages are marked no-store because they include private selections.

On mobile, successful saves collapse the checklist into one expandable menu and scroll that menu into view. Saved selections remain available when reopened. Desktop keeps the full cards visible. The client retries one network interruption or transient gateway error with the same submission; the existing database upsert makes retries safe. Failed saves remain expanded with an explanation. The original “Load failed” cause has not been established from production logs.

## Comparison-page market card

Inline pick controls on team and matchup comparisons are paired with a separate Game Market card. It reads the same latest saved pregame quotes as the market view, shows the spread for both teams and the total with available capture/source details, and stacks below the pick card on mobile. For a started game it falls back to the effective saved pregame lines. Missing markets are labeled unavailable. These display values never change the shared frozen member-pick lines or grading.
