"""Read-only Weekly/Monthly Plug drafts and owner-only premium preview.

No forecasting, provider requests, newsletter sending, or writes occur here.
The page owner's approval and manual newsletter-send safeguards remain separate.
"""
import csv
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
MAX_PICKS = 8
MAX_TRENDS = 8


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    return value.astimezone(timezone.utc)


def period_key(frequency, now):
    local = now.astimezone(ET)
    if frequency == 'monthly':
        return local.strftime('%Y-%m')
    from site_week import week_window
    start, _ = week_window(now)
    year, week, _ = start.isocalendar()
    return f'{year}-W{week:02d}'


def _origin():
    from flask import current_app
    return current_app.config['PUBLIC_ORIGIN'].rstrip('/')


def _event_label(game, kickoff):
    return (f"{game['away_team']} @ {game['home_team']} · "
            f"{kickoff.astimezone(ET).strftime('%a %b %d, %I:%M %p ET')}")


def _side_label(side, quote, market):
    if not side:
        return 'No pick'
    if not quote:
        return side
    if market == 'Spread':
        line = number(quote.get('line_a') if side == quote.get('side_a') else
                      quote.get('line_b') if side == quote.get('side_b') else None)
        return f'{side} {line:+g}' if line is not None else side
    line = number(quote.get('line_a'))
    return f'{side} {line:g}' if line is not None else side


def _plug_content(now, origin, warnings, max_picks=MAX_PICKS):
    """Read the same published card objects used by /the-plug.

    Archive records must be published pregame records. Development and historical
    reconstructions are deliberately excluded from subscriber content.
    Gemini is included ONLY for publicly featured, approved reports: subscriber
    emails must never depend on a premium viewer's access to a private report.
    """
    try:
        from expert_beta import store, public_record, validate_expert
        from plug_dashboard import combined_cards
        archive = store()
        records = archive.records()
        cards, _ = combined_cards(records, public_record, now)
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        warnings.append('The published Plug archive could not be read. No predictions were invented.')
        return [], [], []

    by_version = {r['version']: r for r in records}
    picks, expert = [], []
    seen = set()
    featured_by_week = {}
    for item in cards:
        if not item.get('upcoming'):
            continue
        record = by_version.get(item.get('version'))
        # Only released pregame snapshots, never test/lab forecasts.
        if record is None or record.get('kind') not in ('production_import', 'prospective'):
            continue
        game = record['scout']['game']
        kickoff = timestamp(game['kickoff_utc'])
        if not now < kickoff <= now + timedelta(days=7):
            continue
        game_id = game['game_id']
        if game_id in seen:
            continue
        seen.add(game_id)
        selections = item.get('saved_picks') or {}
        ats = (selections.get('spread') or {}).get('side')
        total = (selections.get('total') or {}).get('side')
        if ats not in (None, game['away_team'], game['home_team']) or total not in (None, 'Over', 'Under'):
            warnings.append('One Plug card was skipped because its published selections were invalid.')
            continue
        quotes = item.get('locked_quotes') or record['scout'].get('quotes') or {}
        url = (f"{origin}/the-plug/{int(game['season'])}/"
               f"{int(game['week'])}/{game['away_team']}-{game['home_team']}")
        label = _event_label(game, kickoff)
        if ats or total:
            pick_text = (f"{label}\nATS: {_side_label(ats, quotes.get('Spread'), 'Spread')}"
                         f" · Total: {_side_label(total, quotes.get('Total'), 'Total')}\n{url}")
            picks.append((kickoff, pick_text, record['version']))

        report = record.get('expert') or {}
        if not report or report.get('review_status') != 'approved':
            continue
        key = (int(game['season']), int(game['week']))
        if key not in featured_by_week:
            try:
                featured_by_week[key] = set(archive.featured(*key))
            except (ValueError, OSError, TypeError):
                warnings.append('Featured Expert configuration needs review; no Expert text was included.')
                featured_by_week[key] = set()
        identifier = f"{key[0]}/{key[1]}/{game['away_team']}-{game['home_team']}"
        if identifier not in featured_by_week[key]:
            continue
        try:
            validate_expert(report, record['scout'])
        except (ValueError, KeyError, TypeError, AttributeError):
            warnings.append('An Expert report failed published-review validation and was skipped.')
            continue
        summary = (report.get('summary') or '').strip()
        if not summary:
            summary = next((s['text'].strip() for s in report.get('sections', [])
                            if s.get('heading') == 'The Expert’s Final Verdict' and s.get('text')), '')
        # Keep drafts concise; owner can expand after reviewing.
        summary = ' '.join(summary.split())
        summary = summary[:350].rsplit(' ', 1)[0].rstrip(' ,;:') + '…' if len(summary) > 350 else summary
        if not summary:
            continue
        expert_picks = (f"ATS: {report.get('ats_side') or 'No pick'}"
                        f" · Total: {report.get('total_side') or 'No pick'}")
        expert.append((kickoff, f"{label}\n{expert_picks}\n{summary}\n{url}"))

    picks.sort(key=lambda pair: pair[0])
    expert.sort(key=lambda pair: pair[0])
    selected = picks if max_picks is None else picks[:max_picks]
    # Keep the audit list aligned with the selections actually shown.
    return [text for _, text, _ in selected], [text for _, text in expert], [version for _, _, version in selected]




# Newsletter copy is deliberately separate from the site Hot Trends data model.
# Source outcome/streak/evidence remain untouched; this only narrates them.
_NEWSLETTER_TEAMS = {
    line.split(':', 1)[0]: line.split(':', 1)[1]
    for line in """
ARI:Arizona Cardinals
ATL:Atlanta Falcons
BAL:Baltimore Ravens
BUF:Buffalo Bills
CAR:Carolina Panthers
CHI:Chicago Bears
CIN:Cincinnati Bengals
CLE:Cleveland Browns
DAL:Dallas Cowboys
DEN:Denver Broncos
DET:Detroit Lions
GB:Green Bay Packers
HOU:Houston Texans
IND:Indianapolis Colts
JAX:Jacksonville Jaguars
KC:Kansas City Chiefs
LA:Los Angeles Rams
LAR:Los Angeles Rams
LAC:Los Angeles Chargers
LV:Las Vegas Raiders
MIA:Miami Dolphins
MIN:Minnesota Vikings
NE:New England Patriots
NO:New Orleans Saints
NYG:New York Giants
NYJ:New York Jets
PHI:Philadelphia Eagles
PIT:Pittsburgh Steelers
SEA:Seattle Seahawks
SF:San Francisco 49ers
TB:Tampa Bay Buccaneers
TEN:Tennessee Titans
WAS:Washington Commanders""".splitlines() if ':' in line
}


def _trend_copy(trend):
    """Plain-language headline and description grounded in stored outcomes."""
    title = str(trend['title'])
    subject = title.rsplit(' — ', 1)[0]
    kind = trend['kind']
    outcome = trend['outcome']
    streak = int(trend.get('streak') or 0)
    hits = int(trend.get('wins') or 0)
    sample = int(trend.get('sample') or 0)
    label = 'SU' if kind == 'su' else 'ATS' if kind == 'ats' else 'O/U'
    scope = trend.get('scope')
    name = _NEWSLETTER_TEAMS.get(subject, subject)
    long_streak = streak >= 5
    count = streak if long_streak else hits
    if kind == 'su':
        noun = 'Wins' if outcome == 'Win' else 'Losses'
    elif kind == 'ats':
        noun = 'Covers' if outcome == 'Cover' else 'Non-Covers'
    else:
        noun = 'Overs' if outcome == 'Over' else 'Unders'
    result = (f'{count} Straight {noun}' if long_streak
              else f'{hits} of Last {sample} {noun}')
    heading = f'{subject} — {label}: {result}'

    if kind == 'su':
        action = 'won' if outcome == 'Win' else 'lost'
        verb_phrase = f'has {action} {count} consecutive games outright' if long_streak else f'has {action} {hits} of its last {sample} games outright'
    elif kind == 'ats':
        action = 'covered the spread' if outcome == 'Cover' else 'failed to cover the spread'
        verb_phrase = f'has {action} in {count} consecutive games' if long_streak else f'has {action} in {hits} of its last {sample} games'
    else:
        action = 'gone over' if outcome == 'Over' else 'gone under'
        verb_phrase = f'has {action} the total in {count} consecutive games' if long_streak else f'has {action} the total in {hits} of its last {sample} games'

    if scope == 'team':
        if kind == 'total':
            subject_text = f'Games involving the {name} '
            detail = subject_text + verb_phrase.replace('has ', 'have ', 1) + '.'
        else:
            detail = f'The {name} {verb_phrase.replace("has ", "have ", 1)}.'
    elif scope == 'qb':
        detail = (f'In games featuring {name}, the quarterback’s team {verb_phrase}.' if kind != 'total'
                  else f'Games featuring {name} {verb_phrase.replace("has ", "have ", 1)}.')
    else:
        # Situational subjects can include location and favorite/underdog filters.
        label_text = subject.lower()
        location = 'home ' if 'home ' in label_text else 'away ' if 'away ' in label_text else ''
        timing = 'primetime' if label_text.startswith('primetime') else ('non-primetime' if label_text.startswith('non-primetime') else '')
        if 'underdog' in label_text or 'favorite' in label_text:
            role = 'underdogs' if 'underdog' in label_text else 'favorites'
            qualifier = ' '.join(x for x in (location.strip(), timing) if x)
            subset = f'{qualifier} {role}'.strip().capitalize()
            # Better grammar for plural situations.
            if outcome == 'Cover':
                action = 'have covered the spread'
            else:
                action = 'have failed to cover the spread'
            detail = (f'{subset} {action} in {count} straight games.' if long_streak
                      else f'{subset} {action} in {hits} of their last {sample} games.')
        else:
            games_name = (timing.capitalize() + ' games') if timing else 'These games'
            action = 'have gone over' if outcome == 'Over' else 'have gone under'
            detail = (f'{games_name} {action} the total in {count} straight games.' if long_streak
                      else f'{games_name} {action} the total in {hits} of the last {sample} games.')
    if trend.get('spans_seasons') and scope in ('team', 'qb'):
        detail += ' The streak spans multiple seasons.' if long_streak else ''
    return heading, detail


def _weekly_featured_pick(picks, experts, versions, warnings):
    """Pick one approved/public featured Expert matchup, with its matching Scout snapshot.

    No claim of highest confidence is made: the existing public featured list has
    no audited common ranking score. Deterministic ordering is kickoff order;
    the owner can edit the draft before approval.
    """
    indexed = {}
    for i, block in enumerate(picks):
        lines = [part.strip() for part in block.splitlines() if part.strip()]
        if len(lines) >= 3 and lines[-1].startswith(('https://', 'http://')):
            indexed[lines[-1]] = (lines, versions[i] if i < len(versions) else None)
    for block in experts:
        lines = [part.strip() for part in block.splitlines() if part.strip()]
        if len(lines) < 4 or lines[-1] not in indexed:
            continue
        scout, version = indexed[lines[-1]]
        # Label the two decision sources separately (they may disagree).
        featured = '\n'.join([
            scout[0],
            'Scout: ' + scout[1],
            'Expert: ' + lines[1],
            "Expert's take: " + ' '.join(lines[2:-1]),
            lines[-1],
        ])
        return featured, [version] if version else []
    warnings.append('No approved publicly featured Expert pick matched an eligible saved Scout pick; feature remains pending.')
    return 'The featured Expert pick is being prepared. Check The Plug for published picks.', []


def _trends_content(origin, warnings, limit=MAX_TRENDS):
    try:
        from active_trends import load_highlights
        trends = load_highlights()[:limit]
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        warnings.append('Hot Right Now highlights were unavailable; no trends were invented.')
        return [], []
    output, identities = [], []
    for trend in trends:
        if trend.get('outcome') not in ('Cover', 'Win', 'Loss', 'Over', 'Under') or not trend.get('params'):
            warnings.append('One featured trend was skipped because its evidence link was unavailable.')
            continue
        heading, detail = _trend_copy(trend)
        query = urlencode(trend['params'])
        link = origin + '/trend-finder?' + query + '#matching-games'
        output.append(f'{heading}\n{detail}\n{link}')
        identities.append({'title': trend['title'], 'latest_id': trend.get('latest_id')})
    return output, identities


def _matchups(root, now, origin, sources, warnings, *, days=7, active_only=True,
              max_games=8, editorial=False):
    """Select a compact, diverse viewing guide without inventing viewing figures.

    Relevance is an editorial heuristic from the saved current-season standings,
    divisional matchups, and the scheduled broadcast window. It is NOT based on
    measured TV ratings or conjectured player availability.
    """
    def read(path):
        raw = path.read_bytes()
        sources[str(path.relative_to(root))] = hashlib.sha256(raw).hexdigest()
        return raw.decode('utf-8-sig')

    schedule = root / 'nfl_games.csv'
    rows = list(csv.DictReader(read(schedule).splitlines())) if schedule.exists() else []
    if not rows:
        warnings.append('No saved schedule was available for the matchup roundup.')
        return []

    current = None
    if active_only:
        from site_week import active_week
        current = active_week(rows, now)
    has_week = any(row.get('season') and row.get('week') for row in rows)
    upcoming = []
    for row in rows:
        if row.get('away_score') not in (None, '') or row.get('home_score') not in (None, ''):
            continue
        try:
            kickoff = (datetime.fromisoformat(row['gameday'] + 'T' + row['gametime'])
                       .replace(tzinfo=ET).astimezone(timezone.utc))
            if active_only and has_week and (int(row.get('season') or 0), int(row.get('week') or 0)) != current:
                continue
            if not all(row.get(key) for key in ('game_id', 'away_team', 'home_team')):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        if now < kickoff <= now + timedelta(days=days):
            upcoming.append((kickoff, row))
    upcoming.sort(key=lambda item: (item[0], item[1]['game_id']))

    if not editorial:
        return [_event_label(row, kickoff) + '\n' + origin + '/matchup/' + row['game_id']
                for kickoff, row in upcoming[:max_games]]

    # Known NFL divisions; used only to recognize actual divisional pairings.
    divisions = {
        'BUF':'AFC East','MIA':'AFC East','NE':'AFC East','NYJ':'AFC East',
        'BAL':'AFC North','CIN':'AFC North','CLE':'AFC North','PIT':'AFC North',
        'HOU':'AFC South','IND':'AFC South','JAX':'AFC South','TEN':'AFC South',
        'DEN':'AFC West','KC':'AFC West','LAC':'AFC West','LV':'AFC West',
        'DAL':'NFC East','NYG':'NFC East','PHI':'NFC East','WAS':'NFC East',
        'CHI':'NFC North','DET':'NFC North','GB':'NFC North','MIN':'NFC North',
        'ATL':'NFC South','CAR':'NFC South','NO':'NFC South','TB':'NFC South',
        'ARI':'NFC West','LA':'NFC West','LAR':'NFC West','SF':'NFC West','SEA':'NFC West',
    }

    def time_window(kickoff):
        local = kickoff.astimezone(ET)
        weekday, hour = local.weekday(), local.hour
        if weekday == 3:
            return 'Thursday night' if hour >= 17 else 'Thursday'
        if weekday == 0:
            return 'Monday night' if hour >= 17 else 'Monday'
        if weekday == 6:
            if hour < 12:
                return 'Sunday morning'
            if hour < 16:
                return 'Sunday early'
            if hour < 19:
                return 'Sunday late'
            return 'Sunday night'
        if weekday == 5:
            return 'Saturday'
        return local.strftime('%A')

    # Use only finished games from the same scheduled season that were completed
    # before this draft was generated; no future data or in-progress scores.
    seasons = {str(row.get('season')) for _, row in upcoming if row.get('season')}
    results, seen = {}, set()
    for row in rows:
        if seasons and str(row.get('season')) not in seasons:
            continue
        game_id = row.get('game_id')
        if not game_id or game_id in seen:
            continue
        try:
            away, home = row['away_team'], row['home_team']
            a, h = number(row.get('away_score')), number(row.get('home_score'))
            played = (datetime.fromisoformat(row['gameday'] + 'T' + row['gametime'])
                      .replace(tzinfo=ET).astimezone(timezone.utc))
        except (KeyError, ValueError, TypeError):
            continue
        if None in (a, h) or min(a, h) < 0 or played + timedelta(hours=6) > now:
            continue
        seen.add(game_id)
        for team, points, against in ((away, a, h), (home, h, a)):
            stats = results.setdefault(team, {'W':0,'L':0,'T':0})
            key = 'W' if points > against else 'L' if points < against else 'T'
            stats[key] += 1

    def record(team):
        rec = results.get(team)
        if not rec:
            return None
        n = sum(rec.values())
        return (rec['W'], rec['L'], rec['T'], (rec['W'] + rec['T']/2) / n) if n else None

    def relevance(item):
        _kickoff, row = item
        away, home = row['away_team'], row['home_team']
        a, h = record(away), record(home)
        rivalry = divisions.get(away) is not None and divisions.get(away) == divisions.get(home)
        score = 32 if rivalry else 0
        if a and h:
            score += 2 * (a[0] + h[0])
            score += 12 if a[3] > .5 and h[3] > .5 else 0
            score += max(0, 8 - 16 * abs(a[3] - h[3]))
        elif a or h:
            score += 2 * (a or h)[0]
        # Do not invent TV ratings. Ties break by earlier kickoff and game ID.
        return score

    best_by_window = {}
    for item in upcoming:
        window = time_window(item[0])
        earlier = best_by_window.get(window)
        if earlier is None or relevance(item) > relevance(earlier):
            best_by_window[window] = item

    # Guarantee diverse kickoff windows first. If >5 windows remain, prioritize
    # national primetime and the major Sunday windows, then the strong matchups.
    priority = {'Thursday night':7, 'Sunday night':7, 'Monday night':7,
                'Sunday late':6, 'Sunday early':6, 'Sunday morning':5,
                'Saturday':4, 'Thursday':3, 'Monday':3}
    selected = sorted(best_by_window.values(), key=lambda item:
                      (-priority.get(time_window(item[0]), 2),
                       -relevance(item), item[0], item[1]['game_id']))[:max_games]
    selected.sort(key=lambda item: (item[0], item[1]['game_id']))

    output = []
    for kickoff, row in selected:
        away, home = row['away_team'], row['home_team']
        window = time_window(kickoff)
        local = kickoff.astimezone(ET)
        ar, hr = record(away), record(home)
        def short_record(rec):
            if rec is None:
                return ''
            return f' ({rec[0]}–{rec[1]}' + (f'–{rec[2]}' if rec[2] else '') + ')'
        away_name = _NEWSLETTER_TEAMS.get(away, away)
        home_name = _NEWSLETTER_TEAMS.get(home, home)
        rivalry = divisions.get(away) is not None and divisions.get(away) == divisions.get(home)
        # Broadcast-led, fact-grounded newsletter descriptions.
        cities = {
            'ARI':'Glendale', 'ATL':'Atlanta', 'BAL':'Baltimore',
            'BUF':'Buffalo', 'CAR':'Charlotte', 'CHI':'Chicago',
            'CIN':'Cincinnati', 'CLE':'Cleveland', 'DAL':'Dallas',
            'DEN':'Denver', 'DET':'Detroit', 'GB':'Green Bay',
            'HOU':'Houston', 'IND':'Indianapolis', 'JAX':'Jacksonville',
            'KC':'Kansas City', 'LA':'Los Angeles', 'LAR':'Los Angeles',
            'LAC':'Los Angeles', 'LV':'Las Vegas', 'MIA':'Miami',
            'MIN':'Minneapolis', 'NE':'Foxborough', 'NO':'New Orleans',
            'NYG':'New York', 'NYJ':'New York', 'PHI':'Philadelphia',
            'PIT':'Pittsburgh', 'SEA':'Seattle', 'SF':'San Francisco',
            'TB':'Tampa', 'TEN':'Nashville', 'WAS':'Washington'
        }
        neutral = any(
            str(row.get(key) or '').strip().lower() in
            ('yes', 'true', '1', 'neutral')
            for key in ('neutral_site', 'is_neutral', 'neutral', 'location')
        )
        city = None if neutral else cities.get(home)

        away_display = away_name + short_record(ar)
        home_display = home_name + short_record(hr)
        away_conf = (divisions.get(away) or '').split(' ')[0]
        home_conf = (divisions.get(home) or '').split(' ')[0]

        if rivalry:
            angle = f'an {divisions[away]} divisional showdown'
        elif away_conf and home_conf and away_conf != home_conf:
            angle = 'an interconference showdown'
        elif away_conf and away_conf == home_conf:
            angle = f'an {away_conf} matchup'
        else:
            angle = 'a featured NFL matchup'

        broadcast = {
            'Thursday night': ('THURSDAY NIGHT FOOTBALL',
                               'Thursday Night Football heads to'),
            'Sunday night': ('SUNDAY NIGHT FOOTBALL',
                             'Sunday Night Football takes center stage in'),
            'Monday night': ('MONDAY NIGHT FOOTBALL',
                             'Monday Night Football closes the week in')
        }
        if window in broadcast:
            label, opening = broadcast[window]
            if city:
                description = (
                    f'{opening} {city} as the {away_display} '
                    f'visit the {home_display} for {angle}.'
                )
            else:
                description = (
                    f'{label.title()} features the {away_display} '
                    f'against the {home_display} for {angle}.'
                )
        elif rivalry:
            location = f'in {city}' if city else 'on the schedule'
            description = (
                f'{divisions[away]} rivals meet {location} as the '
                f'{away_display} visit the {home_display}.'
            )
        elif ar and hr and ar[3] > .5 and hr[3] > .5:
            location = f'in {city}' if city else 'this week'
            description = (
                f'Two teams with winning records meet {location} as the '
                f'{away_display} face the {home_display}.'
            )
        else:
            description = (
                f'The {away_display} visit the {home_display} '
                f'for {angle}.'
            )

        heading_label = broadcast[window][0] if window in broadcast else window.upper()
        heading = f'{heading_label} · {away} at {home}'
        when = (f"{local.strftime('%a, %b')} {local.day} · "
                f"{(local.hour % 12) or 12}:{local.minute:02d} "
                f"{'AM' if local.hour < 12 else 'PM'} ET")
        output.append(heading + '\n' + when + '\n' + description +
                      '\n' + origin + '/matchup/' + row['game_id'])
    return output


def completed_month_games(root, now, sources=None):
    """Saved, completed month-to-date scores as of an aware UTC timestamp.

    Reused by the email digest and its linked public archive so the count,
    deduplication, and six-hour completion cutoff always agree.
    """
    root = Path(root)
    schedule = root / 'nfl_games.csv'
    if not schedule.exists():
        return []
    raw = schedule.read_bytes()
    if sources is not None:
        sources[str(schedule.relative_to(root))] = hashlib.sha256(raw).hexdigest()
    rows = csv.DictReader(raw.decode('utf-8-sig').splitlines())
    local = now.astimezone(ET)
    first = local.date().replace(day=1)
    completed, ids = [], set()
    for row in rows:
        try:
            gameday = datetime.strptime(row['gameday'], '%Y-%m-%d').date()
            if not first <= gameday <= local.date():
                continue
            home = number(row.get('home_score'))
            away = number(row.get('away_score'))
            if None in (home, away) or home < 0 or away < 0:
                continue
            game_id = row['game_id']
            if game_id in ids or not all(row.get(k) for k in ('away_team', 'home_team', 'gametime')):
                continue
            kickoff = (datetime.fromisoformat(row['gameday'] + 'T' + row['gametime'])
                       .replace(tzinfo=ET).astimezone(timezone.utc))
            # An in-progress game may have scores; never label it completed.
            if kickoff + timedelta(hours=6) > now:
                continue
            ids.add(game_id)
            completed.append((gameday, row, away, home))
        except (KeyError, ValueError, TypeError):
            continue
    completed.sort(key=lambda item: (item[0], item[1]['game_id']), reverse=True)
    return completed


def _monthly_recap(root, now, origin, sources, warnings):
    """Month-to-date recorded NFL scores, never fabricated Scout grading."""
    root = Path(root)
    if not (root / 'nfl_games.csv').exists():
        warnings.append('No saved NFL schedule for the monthly recap.')
        return 'No verified results available for this month.'

    local = now.astimezone(ET)
    completed = completed_month_games(root, now, sources)
    if not completed:
        warnings.append('No verified completed games yet this month.')
        return f"{local.strftime('%B %Y')} — no completed games in the saved results yet."

    # Match the full-results link to the exact generated-at time, not a live
    # month view that would later contradict the number printed in this email.
    archive = (f"{origin}/newsletter/results/{local.year}/{local.month}"
               f"?at={int(now.timestamp())}")
    lines = [f"{local.strftime('%B %Y')} · {len(completed)} completed NFL games recorded through {local.strftime('%b %d')}.\n{archive}"]
    for gameday, row, away, home in completed[:8]:
        lines.append(f"{gameday.strftime('%b %d')}: {row['away_team']} {away:g} – {row['home_team']} {home:g}\n{origin}/matchup/{row['game_id']}")
    return '\n\n'.join(lines)


def build_draft(root, now, frequency='weekly', *, premium=False):
    """Compose reviewable public issues; premium=True is preview-only.

    Sending code calls only the default (free) edition. There are no premium
    recipient entitlements or premium delivery registrations here.
    """
    root = Path(root)
    if now.tzinfo is None:
        raise ValueError('Newsletter draft generation requires an aware timestamp')
    if frequency not in ('weekly', 'monthly') or (premium and frequency != 'weekly'):
        raise ValueError('Unsupported newsletter edition')
    now = now.astimezone(timezone.utc)
    sources, warnings = {}, []
    origin = _origin()
    # Keep the monthly digest's eight-trend archive coverage; weekly is shorter.
    trends, trend_ids = _trends_content(origin, warnings, limit=5 if frequency == 'weekly' else MAX_TRENDS)

    if frequency == 'monthly':
        recap = _monthly_recap(root, now, origin, sources, warnings)
        matchups = _matchups(root, now, origin, sources, warnings,
                            days=30, active_only=False)
        sections = {'predictions': recap,
                    'trends': '\n\n'.join(trends) or 'No featured trends are available.',
                    'expert': '',
                    'matchups': '\n\n'.join(matchups) or 'No games scheduled in the next 30 days.',
                    'updates': ''}
        versions = []
    else:
        # Read all eligible pregame records, but select only one published Expert
        # report AND its matching Scout snapshot for the free weekly newsletter.
        picks, expert, all_versions = _plug_content(now, origin, warnings, max_picks=None)
        matchups = _matchups(root, now, origin, sources, warnings,
                            max_games=5 if not premium else 8, editorial=not premium)
        if premium:
            if len(picks) < 13:
                warnings.append(f'Premium preview contains {len(picks)} published games, not a full 13-game slate.')
            # Existing premium preview stays a separate, unsent owner-only report.
            featured_content = '\n\n'.join(picks) or 'No published picks available.'
            expert_content = '\n\n'.join(expert)
            versions = all_versions
        else:
            featured_content, versions = _weekly_featured_pick(picks, expert, all_versions, warnings)
            expert_content = ''  # Expert analysis is embedded with its Scout selection.
        sections = {'predictions': featured_content,
                    'trends': '\n\n'.join(trends) or 'No current featured trends available.',
                    'expert': expert_content,
                    'matchups': '\n\n'.join(matchups) or 'No upcoming games in the saved schedule.',
                    'updates': ''}
    if not trends:
        warnings.append('No current featured trends met the criteria.')
    metadata = {'generated_at': now.isoformat(), 'sources': sources,
                'warnings': sorted(set(warnings)), 'published_forecast_versions': versions,
                'featured_trends': trend_ids}
    if premium:
        metadata['preview_only'] = True
    return sections, metadata


def build_premium_preview(root, now):
    """All eligible released-game picks for owner review; NEVER an email issue."""
    return build_draft(root, now, frequency='weekly', premium=True)
