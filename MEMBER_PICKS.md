# Member picks

Members can use **Menu → My Picks** or `/picks/` to submit free straight-up, against-the-spread, and over/under picks. Their profile links to this page. Their own record is shown separately for each category; other members' choices and records are not exposed. There are no wagers, payments, prizes, competitions or leaderboards.

## Publish common weekly lines

A site owner uses **Menu → Manage Weekly Picks** (`/picks/admin`) to prepare a regular-season year/week from the saved NFL schedule. Only games with known future kickoff times and no saved scores are included. This does not fetch odds or refresh game data. Initial spread/total values come from the saved schedule and may be blank; the owner must review/fill every value before publishing.

On the review page, enter the away-team spread (positive means the away team is an underdog; negative means favored) and the total, both in half-point increments. A spread of zero is allowed. Save the draft or publish. Published spreads and totals are permanent for that week and identical for all members. Missing/invalid lines prevent publication; games that have started or schedules that changed prevent publication. Drafts are not accessible to members.

If the schedule changes before publication, **Rebuild this unpublished week** explicitly discards the draft lines and recreates only the still-unstarted games from current saved data. Published weeks cannot be rebuilt. Postseason weeks are not included in this first milestone.

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
