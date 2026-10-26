"""Compact live game center. Uses existing scoreboard and bounded summary cache.

No full-season PBP, forecasts, background jobs, or database writes on requests.
"""
import json
import re
import time
from collections import OrderedDict
from datetime import datetime
from threading import Lock
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from flask import abort, jsonify, render_template, url_for

_DETAIL_LOCK = Lock()
_DETAIL_CACHE = OrderedDict()
_MAX_DETAILS = 16
_ALLOWED_METRICS = (
    ('firstDowns', 'First downs'),
    ('totalYards', 'Total yards'),
    ('netPassingYards', 'Net passing yards'),
    ('rushingYards', 'Rushing yards'),
    ('turnovers', 'Turnovers'),
    ('possessionTime', 'Possession time'),
)


def _game_context(game_id):
    """Resolve a saved matchup; use the existing scoreboard cache for identity."""
    from fan_views import ROOT, _score_lock, _score_cache, _refresh_score_feed
    from scout4.stats import read_csv, team_code
    from pregame_lines import effective_rows
    from site_week import active_week

    saved_rows = read_csv(ROOT / 'nfl_games.csv')
    game = next((g for g in saved_rows if g.get('game_id') == game_id), None)
    if game is None:
        abort(404)
    expected = (team_code(game['away_team']), team_code(game['home_team']))
    day = game['gameday']
    current = active_week(saved_rows)
    with _score_lock:
        _refresh_score_feed(current)
        feed = [dict(row) for row in _score_cache['games']]
        stale = bool(_score_cache.get('stale', False))
    matching = []
    for item in feed:
        try:
            feed_day = datetime.fromisoformat(item['date'].replace('Z', '+00:00')).astimezone(
                ZoneInfo('America/New_York')).date().isoformat()
        except (ValueError, KeyError, AttributeError):
            continue
        if (item.get('away'), item.get('home')) == expected and feed_day == day:
            matching.append(item)
    # Don't guess event identities when a provider returns ambiguous matches.
    score = matching[0] if len(matching) == 1 else None
    if score is not None:
        score['_stale'] = stale
    return game, score


def _clean(value, limit=200):
    return str(value or '').strip()[:limit]


def parse_summary(data, away, home):
    """Whitelist small, display-ready fields rather than caching provider JSON."""
    plays = []
    for item in (data.get('scoringPlays') or [])[:45]:
        if not isinstance(item, dict):
            continue
        team = _clean((item.get('team') or {}).get('abbreviation'), 8)
        if team not in (away, home):
            continue
        qtr = (item.get('period') or {}).get('number')
        try:
            qtr = int(qtr)
            if not 1 <= qtr <= 6:
                continue
        except (TypeError, ValueError):
            continue
        plays.append({
            'quarter': qtr,
            'time': _clean((item.get('clock') or {}).get('displayValue'), 12),
            'team': team,
            'text': _clean(item.get('text'), 210),
            'away_score': item.get('awayScore'),
            'home_score': item.get('homeScore'),
        })
    rows = {}
    box = data.get('boxscore') or {}
    for item in (box.get('teams') or []):
        if not isinstance(item, dict):
            continue
        team = _clean((item.get('team') or {}).get('abbreviation'), 8)
        if team not in (away, home):
            continue
        rows[team] = {stat.get('name'): _clean(stat.get('displayValue'), 35)
                      for stat in (item.get('statistics') or [])
                      if isinstance(stat, dict) and isinstance(stat.get('name'), str)}
    metrics = [{'label': label,
                'away': rows.get(away, {}).get(key, '—'),
                'home': rows.get(home, {}).get(key, '—')}
               for key, label in _ALLOWED_METRICS
               if key in rows.get(away, {}) or key in rows.get(home, {})]
    leaders = {away: [], home: []}
    for team_group in (box.get('players') or []):
        if not isinstance(team_group, dict):
            continue
        team = _clean((team_group.get('team') or {}).get('abbreviation'), 8)
        if team not in leaders:
            continue
        for category in (team_group.get('statistics') or []):
            if not isinstance(category, dict):
                continue
            role = _clean(category.get('name'), 30).lower()
            if role not in ('passing', 'rushing', 'receiving'):
                continue
            athletes = category.get('athletes') or []
            if not athletes:
                continue
            athlete = athletes[0]
            if not isinstance(athlete, dict):
                continue
            name = _clean((athlete.get('athlete') or {}).get('displayName'), 65)
            statline = ' · '.join(_clean(s, 25) for s in (athlete.get('stats') or [])[:3])
            if name:
                leaders[team].append({'role': role.title(), 'name': name,
                                      'line': statline[:95]})
    return {'plays': plays[-35:], 'metrics': metrics,
            'leaders': leaders}


def summary(event_id, away, home, state):
    """At most one source request per game/TTL and four tiny parsed entries."""
    if not re.fullmatch(r'\d{6,12}', str(event_id or '')):
        return None
    key = (str(event_id), away, home)
    now = time.monotonic()
    if not _DETAIL_LOCK.acquire(blocking=False):
        return (_DETAIL_CACHE.get(key) or {}).get('data')
    try:
        item = _DETAIL_CACHE.get(key)
        if item and now < item['expires']:
            _DETAIL_CACHE.move_to_end(key)
            return item['data']
        try:
            from hosted_memory import analytics_network_wait
            req = Request(
                'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=' + str(event_id),
                headers={'User-Agent': 'TrendFindah/1.0'})
            with analytics_network_wait():
                with urlopen(req, timeout=2) as response:
                    payload = response.read(1_500_001)
            if len(payload) > 1_500_000:
                raise ValueError('Oversized game summary')
            parsed = parse_summary(json.loads(payload), away, home)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            parsed = item['data'] if item else None
        # Failures are retried after 30 seconds, not on every visitor.
        ttl = (30 if state == 'in' else 300) if parsed is not None else 30
        _DETAIL_CACHE[key] = {'data': parsed, 'expires': now + ttl}
        _DETAIL_CACHE.move_to_end(key)
        while len(_DETAIL_CACHE) > _MAX_DETAILS:
            _DETAIL_CACHE.popitem(last=False)
        return parsed
    finally:
        _DETAIL_LOCK.release()


def game_data(game_id):
    game, score = _game_context(game_id)
    away, home = game['away_team'], game['home_team']
    state = score.get('state', 'pre') if score else 'pre'
    if score:
        away, home = score['away'], score['home']
    details = summary(score.get('provider_id'), away, home, state) if score else None
    body = {
        'away': away, 'home': home, 'state': state,
        'status': score.get('status', 'Scheduled') if score else 'Score feed unavailable',
        'away_score': score.get('away_score') if score else None,
        'home_score': score.get('home_score') if score else None,
        'details': details, 'refresh_seconds': 30 if state == 'in' else 60,
        'stale': bool(score.get('_stale')) if score else True,
    }
    response = jsonify(body)
    response.headers['Cache-Control'] = 'no-store'
    return response


def board_page():
    from flask import redirect, url_for
    return redirect(url_for('home', _anchor='home-scores'), code=302)


def game_page(game_id):
    game, _ = _game_context(game_id)
    recent = _recent_team_context(game)
    my_picks = _member_pick_preview(game_id)
    from flask import g, make_response
    response = make_response(render_template('game_center.html', game=game,
                                             recent=recent, my_picks=my_picks))
    if g.get('member'):
        response.headers['Cache-Control'] = 'private, no-store'
    return response


# Cache only the compact current slate, not historical frames or ESPN payloads.
from functools import lru_cache

@lru_cache(maxsize=3)
def _cached_home_slate(path, modified, size, week_start):
    import csv
    from datetime import timedelta
    from site_week import active_slate
    end_day = (week_start + timedelta(days=7)).date().isoformat()
    begin_day = week_start.date().isoformat()
    with open(path, newline='', encoding='utf-8-sig') as stream:
        candidates = [row for row in csv.DictReader(stream)
                      if begin_day <= row.get('gameday','') <= end_day]
    key, games = active_slate(candidates, now=week_start)
    ordered = sorted(games, key=lambda row: (
        row.get('gameday',''), row.get('gametime',''), row.get('game_id','')))[:24]
    groups = {'in': [], 'pre': [], 'post': []}
    for row in ordered:
        try:
            home, away = int(row['home_score']), int(row['away_score'])
            finished = float(row['result']) == home-away
        except (KeyError, TypeError, ValueError, OverflowError):
            finished = False
        groups['post' if finished else 'pre'].append(row)
    label = (str(key[0]), str(key[1]), key[2]) if key else ('','','')
    return {'slate': label, 'games': ordered, 'groups': groups}


def home_board_context():
    from fan_views import ROOT
    from site_week import week_window
    path = ROOT / 'nfl_games.csv'
    start, _ = week_window()
    st = path.stat()
    return _cached_home_slate(str(path), st.st_mtime_ns, st.st_size, start)


def _recent_team_context(game):
    """2026 saved final-score form before kickoff, with no forecast or network work."""
    from fan_views import ROOT
    import csv
    teams = [game['away_team'], game['home_team']]
    rows = {team: [] for team in teams}
    cutoff = (game.get('gameday') or '', game.get('gametime') or '')
    with (ROOT / 'nfl_games.csv').open(newline='', encoding='utf-8-sig') as stream:
        history = [row for row in csv.DictReader(stream)
                   if row.get('season') == game.get('season') and
                   row.get('gameday','') <= game.get('gameday','')]
    for row in history:
        if row.get('season') != game.get('season') or row.get('game_id') == game['game_id']:
            continue
        if (row.get('gameday') or '',row.get('gametime') or '') >= cutoff:
            continue
        try:
            home, away = float(row['home_score']), float(row['away_score'])
            if (not home.is_integer() or not away.is_integer() or
                    float(row['result']) != home-away or home<0 or away<0):
                continue
            home, away = int(home), int(away)
        except (TypeError, KeyError, ValueError, OverflowError):
            continue
        for team in teams:
            if row.get('home_team') == team:
                own, allowed = home, away
                opponent, venue = row.get('away_team', ''), 'vs'
            elif row.get('away_team') == team:
                own, allowed = away, home
                opponent, venue = row.get('home_team', ''), '@'
            else:
                continue
            rows[team].append({
                'date': row.get('gameday', ''), 'time': row.get('gametime', ''),
                'opponent': opponent, 'venue': venue,
                'points_for': own, 'points_against': allowed,
                'outcome': 'W' if own > allowed else 'L' if own < allowed else 'T',
            })
    result = {}
    for team, games in rows.items():
        recent = sorted(games, key=lambda item: (item['date'], item['time']), reverse=True)[:5]
        result[team] = {'games':len(recent),
                        'wins':sum(item['outcome'] == 'W' for item in recent),
                        'losses':sum(item['outcome'] == 'L' for item in recent),
                        'ties':sum(item['outcome'] == 'T' for item in recent),
                        'points_for':round(sum(item['points_for'] for item in recent)/len(recent),1) if recent else None,
                        'points_against':round(sum(item['points_against'] for item in recent)/len(recent),1) if recent else None,
                        'history': recent}
    return result


def _member_pick_preview(game_id):
    """Read-only saved shared picks. No market capture or auto-publishing on GET."""
    from flask import g
    if not g.get('member'):
        return None
    from membership import db
    try:
        record = db().execute("""SELECT p.su, p.ats, p.ou,
            p.su_result, p.ats_result, p.ou_result,
            pg.away_spread, pg.total, pg.locked, pg.away, pg.home
            FROM pick_games pg
            LEFT JOIN member_picks p ON p.game_id=pg.id AND p.member_id=?
            WHERE pg.game_id=?""", (g.member['id'],game_id)).fetchone()
    except (KeyError, ValueError):
        return None
    return dict(record) if record else {}
