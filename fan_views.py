"""Fan-facing comparisons and a read-only, cached scoreboard."""
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from threading import Lock
from urllib.request import Request, urlopen
from flask import Blueprint, abort, jsonify, render_template, url_for
from scout4.web import sources, view_data
from scout4.stats import read_csv, team_records, player_records, summarize_team, summarize_player, team_code, betting_result
from pathlib import Path
from pregame_lines import effective_rows

ROOT = Path(__file__).resolve().parent
bp = Blueprint('fans', __name__)
_score_lock = Lock()
_score_cache = {'expires': 0, 'games': [], 'updated': None}


def parse_scores(payload):
    games = []
    for event in payload.get('events', []):
        try:
            datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
            contest = event['competitions'][0]
            sides = {r['homeAway']: r for r in contest['competitors']}
            state = contest['status']['type']
            row = {'date': event['date'], 'status': state.get('shortDetail', state.get('description', '')),
                   'state': state['state'], 'away': team_code(sides['away']['team']['abbreviation']),
                   'home': team_code(sides['home']['team']['abbreviation']),
                   'away_score': sides['away'].get('score') if state['state'] != 'pre' else None,
                   'home_score': sides['home'].get('score') if state['state'] != 'pre' else None}
            games.append(row)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            continue
    return sorted(games, key=lambda g: (0 if g['state'] == 'in' else 1, g['date']))


@bp.get('/scores.json')
def scores():
    # Separate from homepage rendering: a slow feed never delays the main menu.
    with _score_lock:
        if time.monotonic() >= _score_cache['expires']:
            try:
                req = Request('https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
                              headers={'User-Agent': 'TrendFindah/1.0'})
                with urlopen(req, timeout=5) as response:
                    payload = json.loads(response.read(2_000_000))
                if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
                    raise ValueError('Invalid scoreboard')
                _score_cache.update(games=parse_scores(payload),
                                    updated=datetime.now(timezone.utc).isoformat(), stale=False)
            except (OSError, ValueError, TypeError, AttributeError):
                _score_cache['stale'] = True
            interval = 15 if any(game['state']=='in' for game in _score_cache['games']) else 60
            _score_cache['expires'] = time.monotonic() + interval
        schedule = effective_rows(read_csv(ROOT / 'nfl_games.csv'), ROOT / 'nfl_games.csv')
        games = []
        for game in _score_cache['games']:
            row = dict(game)
            matches = [g for g in schedule if team_code(g['away_team']) == row['away']
                       and team_code(g['home_team']) == row['home'] and g['gameday'] == datetime.fromisoformat(row['date'].replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()]
            row['url'] = url_for('fans.matchup', game_id=matches[0]['game_id']) if len(matches) == 1 else None
            row['market'] = None
            if len(matches) == 1:
                saved = dict(matches[0])
                # Live scores are graded only once the provider marks the game final.
                saved.update(home_score=row['home_score'] if row['state']=='post' else '',
                             away_score=row['away_score'] if row['state']=='post' else '')
                row['market'] = betting_result(saved)
            games.append(row)
        result = jsonify(games=games, updated=_score_cache['updated'],
                         stale=_score_cache.get('stale', False), source='ESPN',
                         refresh_seconds=15 if any(game['state']=='in' for game in games) else 60)
        result.headers['Cache-Control'] = 'no-store'
        return result


def fan_context(game):
    season, week = int(game['season']), int(game['week'])
    schedule = effective_rows(read_csv(ROOT / 'nfl_games.csv'), ROOT / 'nfl_games.csv')
    teams, players, manifest = sources(season)
    records = team_records(schedule, teams, season, week)
    people = player_records(schedule, players, season, week)
    return season, week, records, people, manifest


def leaders(rows, code):
    grouped = defaultdict(list)
    for row in rows:
        if row['team'] == code:
            grouped[row['player_id']].append(row)
    cards = [{'id': pid, 'name': games[-1]['name'], 'team': code,
              'summary': summarize_player(games, games)} for pid, games in grouped.items()]
    output = []
    for role, metric, fields in (
        ('Top passer', 'passing_yards', ('passing_yards', 'passing_tds', 'passing_interceptions', 'completions', 'attempts')),
        ('Top rusher', 'rushing_yards', ('rushing_yards', 'carries', 'rushing_tds')),
        ('Top receiver', 'receiving_yards', ('receiving_yards', 'receptions', 'targets', 'receiving_tds'))):
        eligible = [c for c in cards if (c['summary']['metrics'][metric]['total'] or 0) > 0]
        if eligible:
            winner = max(eligible, key=lambda c: c['summary']['metrics'][metric]['total'])
            output.append(dict(winner, role=role, fields=fields))
    return output


@bp.get('/matchup/<game_id>')
def matchup(game_id):
    game = next((g for g in read_csv(ROOT / 'nfl_games.csv') if g['game_id'] == game_id), None)
    if game is None:
        abort(404)
    season, week, records, players, manifest = fan_context(game)
    teams = []
    for side in ('away', 'home'):
        code = team_code(game[side + '_team'])
        rows = [r for r in records if r['team'] == code]
        teams.append({'code': code, 'summary': summarize_team(rows, rows), 'leaders': leaders(players, code)})
    forecast = None
    path = ROOT / 'data/scout4/blend/predictions' / (game_id + '.json')
    if path.exists():
        candidate = json.loads(path.read_text())
        if candidate.get('game_id') == game_id:
            forecast = candidate
    return render_template('matchup.html', game=game, teams=teams, season=season, week=week,
                           manifest=manifest, forecast=forecast)


@bp.get('/fantasy')
def fantasy():
    v = view_data()
    from flask import request
    position = request.args.get('position', '')
    week_value = request.args.get('week', '')
    try:
        week = int(week_value) if week_value else None
    except ValueError:
        abort(400, description='Choose a week from 1 to 18.')
    if week is not None and not 1 <= week <= 18:
        abort(400, description='Choose a week from 1 to 18.')
    if position not in ('', 'QB', 'RB', 'WR', 'TE', 'FB'):
        abort(400)
    grouped = defaultdict(list)
    for row in v['players']:
        if row['position'] in ('QB', 'RB', 'WR', 'TE', 'FB') and (not position or row['position'] == position) and (week is None or row.get('week') == week):
            grouped[(row['player_id'], row['team'])].append(row)
    weights = {'passing_yards': .04, 'passing_tds': 4, 'passing_interceptions': -2,
               'rushing_yards': .1, 'rushing_tds': 6, 'receiving_yards': .1,
               'receiving_tds': 6, 'receptions': 1}
    cards = []
    for (pid, code), games in grouped.items():
        complete = [g for g in games if all(g.get(k) is not None for k in weights)]
        if not complete:
            continue
        points = sum(sum(g[k] * weight for k, weight in weights.items()) for g in complete)
        cards.append({'id': pid, 'team': code, 'name': games[-1]['name'], 'position': games[-1]['position'],
                      'points': points, 'games': len(complete), 'per_game': points / len(complete)})
    cards.sort(key=lambda c: (-c['points'], c['name'], c['id']))
    return render_template('fantasy.html', view=v, cards=cards[:100], position=position, selected_week=week)


def data_freshness():
    pointers = list((ROOT / 'data/scout4').glob('*/latest.json'))
    pointers = [p for p in pointers if p.parent.name.isdigit()]
    latest = max(pointers, key=lambda p: int(p.parent.name), default=None)
    manifest = json.loads(latest.read_text()) if latest else {}
    stamps = []
    for path in (ROOT / 'data/scout4/blend/predictions').glob('*.json'):
        record = json.loads(path.read_text())
        if record.get('sealed_at_utc'):
            stamps.append(record['sealed_at_utc'])
    status_path = ROOT/'logs/auto_update_status.json'
    try:
        automatic = json.loads(status_path.read_text()) if status_path.exists() else None
    except (OSError, ValueError):
        automatic = None
    return {'stats': manifest.get('retrieved_at'), 'predictions': max(stamps, default=None), 'automatic':automatic}


def prediction_performance(records, schedule):
    """Evaluate only verifiably saved pre-kickoff picks, separated by model version."""
    from scout4.blend import grade_components
    from scout4.blend_results import total_result
    groups = {}
    games = {g['game_id']:g for g in schedule}
    excluded = 0
    recent = []
    for record in records:
        try:
            kickoff = datetime.fromisoformat(record['kickoff_utc'])
            stamps = [datetime.fromisoformat(record[k]) for k in ('sealed_at_utc','decision_cutoff_utc')]
            stamps.append(datetime.fromisoformat(record['quote']['captured_at_utc']))
            if kickoff.tzinfo is None or any(stamp.tzinfo is None or stamp >= kickoff for stamp in stamps):
                raise ValueError('Not a verified pregame pick')
            game = games.get(record['game_id'])
            ats = grade_components(record, game)['Blend']
            total = total_result(record, game)
        except (KeyError, TypeError, ValueError):
            excluded += 1
            continue
        key = (record.get('version','Unknown version'), record.get('configuration_sha256','Unknown configuration'))
        group = groups.setdefault(key, {'version':key[0], 'configuration':key[1], 'ats':{}, 'totals':{}})
        for name, result in (('ats',ats), ('totals',total)):
            group[name][result] = group[name].get(result,0) + 1
        recent.append({'id':record['game_id'], 'away':record['away_team'], 'home':record['home_team'],
                       'date':record['kickoff_utc'], 'saved':record['sealed_at_utc'],
                       'pick':record['components']['Blend']['pick'], 'ats':ats,'total':total})
    for group in groups.values():
        for name in ('ats','totals'):
            counts = group[name]
            decisions = counts.get('Win',0) + counts.get('Loss',0)
            counts['decisions'] = decisions
            counts['rate'] = 100 * counts.get('Win',0) / decisions if decisions else None
    graded = [r for r in recent if r['ats'] != 'Pending' or r['total'] not in ('Pending','Unavailable')]
    return list(groups.values()), sorted(graded,key=lambda r:r['date'],reverse=True)[:10], excluded


@bp.get('/predictions/results')
def prediction_results():
    records = [json.loads(p.read_text()) for p in (ROOT / 'data/scout4/blend/predictions').glob('*.json')]
    groups, recent, excluded = prediction_performance(records, read_csv(ROOT / 'nfl_games.csv'))
    return render_template('prediction_results.html', groups=groups, recent=recent,
                           excluded=excluded, freshness=data_freshness())
