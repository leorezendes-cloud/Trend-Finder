"""Current, auditable NFL hot trends. No picks, odds forecasts, or data writes.

A hot trend is 5+ consecutive favorable results, or 5 of the latest 7 games.
Pushes, ties, and missing outcomes occupy a game slot and interrupt streaks.
"""
import csv
from collections import defaultdict
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from general_research import research_games
from pregame_lines import effective_rows
from research_qbs import research_rows

MAX_FEATURED = 8
MAX_AGE_DAYS = 21


def _current(games, season, as_of):
    """Anchor every cross-season trend to a recently completed current-season game."""
    if not games or int(games[0]['season']) != season:
        return False
    days = (as_of - date.fromisoformat(games[0]['gameday'])).days
    return 0 <= days <= MAX_AGE_DAYS


def _outcomes(games, kind, result, side=None):
    values = []
    for game in games:
        if kind == 'total':
            values.append(game['total_result'])
        else:
            chosen = side(game) if callable(side) else side
            if chosen not in ('home', 'away'):
                values.append('Unavailable')
            elif kind == 'ats':
                values.append(game[chosen + '_ats'])
            else:
                scored = game['away_score'] - game['home_score']
                margin = scored if chosen == 'away' else -scored
                values.append('Win' if margin > 0 else 'Loss' if margin < 0 else 'Tie')
    return values


def _trend(games, *, kind, direction, title, category, subject, season, as_of, scope,
           params, side=None, family=None):
    if not _current(games, season, as_of):
        return None
    values = _outcomes(games, kind, direction, side)
    streak = 0
    for value in values:
        if value != direction:
            break
        streak += 1
    recent = values[:7]
    hits = recent.count(direction)
    if streak < 5 and not (len(recent) == 7 and hits >= 5):
        return None
    losses = sum(value not in (direction, 'Push', 'Tie', 'Unavailable') for value in recent)
    pushes = sum(value in ('Push', 'Tie') for value in recent)
    missing = recent.count('Unavailable')
    span = len({g['season'] for g in games[:max(7, streak)]}) > 1
    mode = 'streak' if streak >= 5 else 'recent'
    return dict(
        title=title, kind=kind, category=category, family=family or category,
        subject=subject, outcome=direction, season=season, scope=scope,
        spans_seasons=span, streak=streak, wins=hits, losses=losses, pushes=pushes,
        missing=missing, sample=len(recent), latest=games[0]['gameday'],
        latest_id=games[0]['game_id'], mode=mode, params=params,
        # Keep actual game IDs and outcome labels for independent verification.
        evidence=[dict(game_id=g['game_id'], date=g['gameday'],
                       matchup=g['away_team']+' @ '+g['home_team'], result=v)
                  for g, v in zip(games[:max(7, streak)], values[:max(7, streak)])],
    )


def _params(**kwargs):
    return dict(research_view='general', run='analyze', game_type='REG',
                show_games='1', **kwargs)


def _rank(trend):
    """Prefer active straight streaks and recent strength, not arbitrary team names."""
    return (trend['streak'] >= 5, trend['streak'], trend['wins'],
            trend['latest'], -trend['pushes'], trend['title'])


def _feature(all_trends, limit=MAX_FEATURED):
    """Limit repetition: two per category, at most one card per team/QB."""
    featured = []
    category_counts = defaultdict(int)
    subjects = set()
    for trend in sorted(all_trends, key=_rank, reverse=True):
        if trend['subject'] in subjects or category_counts[trend['category']] >= 2:
            continue
        featured.append(trend)
        subjects.add(trend['subject'])
        category_counts[trend['category']] += 1
        if len(featured) == limit:
            break
    # Backfill if fewer than eight unique subjects/category-balanced results exist.
    if len(featured) < limit:
        for trend in sorted(all_trends, key=_rank, reverse=True):
            if trend in featured or trend['subject'] in subjects:
                continue
            featured.append(trend)
            subjects.add(trend['subject'])
            if len(featured) == limit:
                break
    return featured


def active_highlights(rows, as_of=None, *, featured=False):
    """Full qualifying list by default; use featured=True for the homepage (max 8)."""
    as_of = as_of or datetime.now(ZoneInfo('America/New_York')).date()
    completed = [r for r in rows if r.get('gameday') and r['gameday'] <= as_of.isoformat()
                 and r.get('game_type') == 'REG']
    if not completed:
        return []
    # Never confuse a future-season schedule with actual completed games.
    season = max(int(r['season']) for r in completed if r.get('away_score') not in ('', None)
                 and r.get('home_score') not in ('', None)) if any(
                     r.get('away_score') not in ('', None) and r.get('home_score') not in ('', None)
                     for r in completed) else None
    if season is None:
        return []
    output = []

    # All teams: straight-up, ATS, and totals. Allow streaks to span seasons,
    # but insist the latest completed game is from the current season.
    team_games = defaultdict(list)
    qb_games = defaultdict(list)
    for row in completed:
        for key in ('away_team', 'home_team'):
            if row.get(key):
                team_games[row[key]].append(row)
        for qb in {row.get('away_qb_name'), row.get('home_qb_name')} - {None, ''}:
            qb_games[qb].append(row)
    for team, group in team_games.items():
        report = research_games(group, team=team, filters={'game_type': 'REG'})
        games = report['matches']
        if not _current(games, season, as_of):
            continue
        params = _params(research_team=team)
        side = lambda g: 'away' if g['away_team'] == team else 'home'
        for kind, directions in (('su', ('Win', 'Loss')),
                                 ('ats', ('Cover', 'Loss')),
                                 ('total', ('Over', 'Under'))):
            for direction in directions:
                item = _trend(games, kind=kind, direction=direction,
                              title=f'{team} — {"SU" if kind == "su" else "ATS" if kind == "ats" else "Game totals"}',
                              category='team', subject='team:'+team, season=season,
                              as_of=as_of, scope='team', side=side,
                              params=params)
                if item:
                    output.append(item)

    # QB records measure the quarterback's side, not the game's home team.
    # QB totals concern BOTH teams' combined points in games with that QB.
    for qb, group in qb_games.items():
        report = research_games(group, filters={'game_type': 'REG', 'qb_name': qb})
        games = [g for g in report['matches'] if g.get('selected_side') in ('home', 'away')]
        if not _current(games, season, as_of):
            continue
        params = _params(qb_name=qb)
        for kind, directions in (('su', ('Win', 'Loss')),
                                 ('ats', ('Cover', 'Loss')),
                                 ('total', ('Over', 'Under'))):
            for direction in directions:
                item = _trend(games, kind=kind, direction=direction,
                              title=f'{qb} — {"SU" if kind == "su" else "ATS" if kind == "ats" else "Game totals"}',
                              category='qb', subject='qb:'+qb, season=season,
                              as_of=as_of, scope='qb', side=lambda g: g['selected_side'],
                              params=params)
                if item:
                    output.append(item)

    # Situations remain current-season only (unlike player and team streaks).
    for role in ('favorite', 'underdog'):
        for prime in ('yes', 'no'):
            for location in ('', 'home', 'away'):
                report = research_games(completed, season=season,
                                        filters={'game_type': 'REG'},
                                        role=role, primetime=prime, location=location)
                games = report['matches']
                if not _current(games, season, as_of):
                    continue
                label = ('Primetime' if prime == 'yes' else 'Non-primetime')
                label += (' ' + location) if location else ''
                label += (' favorites' if role == 'favorite' else ' underdogs')
                params = _params(season=season, research_role=role,
                                 primetime=prime, research_location=location)
                for direction in ('Cover', 'Loss'):
                    item = _trend(games, kind='ats', direction=direction,
                                  title=label+' — ATS', category='situational',
                                  subject='situation:'+role+':'+prime+':'+location,
                                  season=season, as_of=as_of, scope='situational',
                                  side=lambda g, role=role: g['dog_side'] if role == 'underdog'
                                  else ('home' if g['dog_side'] == 'away' else 'away'),
                                  params=params)
                    if item:
                        output.append(item)

    # Full league primetime/non-primetime game totals are also eligible.
    for prime in ('yes', 'no'):
        report = research_games(completed, season=season,
                                filters={'game_type': 'REG'}, primetime=prime)
        games = report['matches']
        for direction in ('Over', 'Under'):
            item = _trend(games, kind='total', direction=direction,
                          title=('Primetime' if prime == 'yes' else 'Non-primetime')+' game totals',
                          category='situational', subject='total:'+prime,
                          season=season, as_of=as_of, scope='situational',
                          params=_params(season=season, primetime=prime))
            if item:
                output.append(item)

    output.sort(key=_rank, reverse=True)
    return _feature(output) if featured else output


@lru_cache(maxsize=8)
def _cached_highlights(path, signature, today):
    with open(path, newline='') as source:
        rows = research_rows(list(effective_rows(csv.DictReader(source), path)), path)
    return active_highlights(rows, date.fromisoformat(today))


def qb_source_signature(path):
    root = Path(path).resolve().parent
    paths = (root/'research_qb_corrections.csv', root/'data/research_qbs/verified.json')
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) if p.exists()
                 else (str(p), None, None) for p in paths)


def load_highlights(*, all_trends=False):
    from trend_finder_2 import game_file, _trend_data_signature
    today = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    all_results = _cached_highlights(str(game_file),
                                     (_trend_data_signature(), qb_source_signature(game_file)),
                                     today)
    return all_results if all_trends else _feature(all_results)
