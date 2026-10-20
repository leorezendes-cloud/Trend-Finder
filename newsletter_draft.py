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


def _trends_content(origin, warnings):
    try:
        from active_trends import load_highlights
        trends = load_highlights()[:MAX_TRENDS]
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        warnings.append('Hot Right Now highlights were unavailable; no trends were invented.')
        return [], []
    labels = {'Cover': 'ATS covers', 'Win': 'wins', 'Loss': 'losses',
              'Over': 'overs', 'Under': 'unders'}
    output, identities = [], []
    for trend in trends:
        if trend.get('outcome') not in labels or not trend.get('params'):
            warnings.append('One featured trend was skipped because its evidence link was unavailable.')
            continue
        qualification = (f"{trend['streak']} straight {labels[trend['outcome']]}" if trend['streak'] >= 5
                         else f"{trend['wins']} of the last {trend['sample']} {labels[trend['outcome']]}")
        query = urlencode(trend['params'])
        link = origin + '/trend-finder?' + query + '#matching-games'
        detail = qualification
        sample = number(trend.get('sample'))
        wins = number(trend.get('wins'))
        if sample is not None and wins is not None and sample > 0 and 0 <= wins <= sample:
            detail += f" · {wins:g}/{sample:g} ({100 * wins / sample:.0f}%) in the recorded sample"
        output.append(f"{trend['title']}\n{detail}\n{link}")
        identities.append({'title': trend['title'], 'latest_id': trend.get('latest_id')})
    return output, identities


def _matchups(root, now, origin, sources, warnings, *, days=7, active_only=True):
    def read(path):
        raw = path.read_bytes()
        sources[str(path.relative_to(root))] = hashlib.sha256(raw).hexdigest()
        return raw.decode('utf-8-sig')

    schedule = root / 'nfl_games.csv'
    rows = list(csv.DictReader(read(schedule).splitlines())) if schedule.exists() else []
    if not rows:
        warnings.append('No saved schedule was available for the matchup roundup.')
        return []
    if active_only:
        from site_week import active_week
        current = active_week(rows, now)
    else:
        current = None
    has_week = any(row.get('season') and row.get('week') for row in rows)
    upcoming = []
    for row in rows:
        if row.get('away_score') or row.get('home_score'):
            continue
        try:
            kickoff = (datetime.fromisoformat(row['gameday']+'T'+row['gametime'])
                       .replace(tzinfo=ET).astimezone(timezone.utc))
        except (KeyError, ValueError):
            continue
        if active_only and has_week and (int(row.get('season', 0)), int(row.get('week', 0))) != current:
            continue
        if not all(row.get(key) for key in ('game_id', 'away_team', 'home_team')):
            continue
        if now < kickoff <= now + timedelta(days=days):
            upcoming.append((kickoff, row))
    lines = []
    for kickoff, row in sorted(upcoming, key=lambda entry: entry[0])[:8]:
        label = _event_label(row, kickoff)
        url = origin + '/matchup/' + row['game_id']
        lines.append(label + '\n' + url)
    return lines


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
    trends, trend_ids = _trends_content(origin, warnings)

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
        picks, expert, versions = _plug_content(now, origin, warnings,
                                                max_picks=None if premium else MAX_PICKS)
        matchups = _matchups(root, now, origin, sources, warnings)
        if not picks:
            warnings.append('No eligible published upcoming picks; review before approving the issue.')
        if premium and len(picks) < 13:
            warnings.append(f'Premium preview contains {len(picks)} published games, not a full 13-game slate.')
        sections = {'predictions': '\n\n'.join(picks) or 'No published picks available for the upcoming week.',
                    'trends': '\n\n'.join(trends) or 'No current featured trends available.',
                    'expert': '\n\n'.join(expert),
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
