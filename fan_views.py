"""Fan-facing comparisons and a read-only, cached scoreboard."""
import json
import math
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
from hot_matchups import (matches_for_score, upcoming_for_trend, hot_trend_id,
                          current_season_evidence, earlier_evidence,
                          is_fireworthy, scorecard_trends,
                          current_season_research_params)

ROOT = Path(__file__).resolve().parent
bp = Blueprint('fans', __name__)
_score_lock = Lock()
_score_cache = {'expires': 0, 'games': [], 'updated': None}


@bp.app_template_global('hot_trend_id')
def hot_trend_anchor(trend):
    return hot_trend_id(trend)


@bp.app_template_global('hot_current_evidence')
def hot_current_evidence(trend):
    return current_season_evidence(trend)


@bp.app_template_global('hot_earlier_evidence')
def hot_earlier_evidence(trend):
    return earlier_evidence(trend)


@bp.app_template_global('hot_research_params')
def hot_research_params(trend):
    return current_season_research_params(trend)


@bp.app_template_global('hot_fireworthy')
def hot_fireworthy(trend):
    return is_fireworthy(trend)


@bp.app_template_global('hot_upcoming_for')
def hot_upcoming_for(trend):
    """Lazy, request-local reuse of the existing saved schedule and week."""
    from flask import g
    from site_week import active_week
    if not hasattr(g, '_hot_upcoming_context'):
        path = ROOT / 'nfl_games.csv'
        try:
            rows = read_csv(path)
            g._hot_upcoming_context = (
                effective_rows(rows, path, include_scores=False), active_week(rows),
                datetime.now(ZoneInfo('America/New_York')))
        except (OSError, ValueError, KeyError, TypeError):
            g._hot_upcoming_context = ([], None, datetime.now(ZoneInfo('America/New_York')))
    rows, week, now = g._hot_upcoming_context
    if not week:
        return []
    return upcoming_for_trend(rows, trend, now=now, active_week=week)


def parse_scores(payload):
    games = []
    for event in payload.get('events', []):
        try:
            datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
            contest = event['competitions'][0]
            sides = {r['homeAway']: r for r in contest['competitors']}
            state = contest['status']['type']
            row = {'provider_id': str(event.get('id') or ''), 'date': event['date'], 'status': state.get('shortDetail', state.get('description', '')),
                   'state': state['state'], 'completed': state.get('completed') is True, 'away': team_code(sides['away']['team']['abbreviation']),
                   'home': team_code(sides['home']['team']['abbreviation']),
                   'away_score': sides['away'].get('score') if state['state'] != 'pre' else None,
                   'home_score': sides['home'].get('score') if state['state'] != 'pre' else None}
            games.append(row)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            continue
    return sorted(games, key=lambda g: (0 if g['state'] == 'in' else 1, g['date']))


_score_response_lock = Lock()
_score_response = {'key': None, 'expires': 0, 'body': None}


@bp.get('/scores.json')
def scores():
    # Cache the complete badge response, not just ESPN's feed. One refresh at a
    # time; waiting visitors must not tie up the health-check thread pool.
    from flask import Response
    from active_trends import qb_source_signature
    paths = (ROOT/'anomaly_events.csv', ROOT/'nfl_games.csv', ROOT/'public_money_snapshots.csv', ROOT/'manual_spread_overrides.csv')
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else (str(p), None, None) for p in paths)
    key = (signature, qb_source_signature(ROOT/'nfl_games.csv'),
           datetime.now(ZoneInfo('America/New_York')).date().isoformat())
    def cached():
        return Response(_score_response['body'], mimetype='application/json',
                        headers={'Cache-Control':'no-store'})
    if (_score_response['key'] == key and time.monotonic() < _score_response['expires']
            and time.monotonic() < _score_cache['expires']):
        return cached()
    if not _score_response_lock.acquire(blocking=False):
        if _score_response['key'] == key and _score_response['body'] is not None:
            return cached()
        return ('Scores are refreshing. Please retry shortly.', 503,
                {'Retry-After':'1', 'Cache-Control':'no-store'})
    try:
        if (_score_response['key'] == key and time.monotonic() < _score_response['expires']
            and time.monotonic() < _score_cache['expires']):
            return cached()
        response = _scores_uncached()
        _score_response.update(key=key, expires=time.monotonic()+5,
                               body=response.get_data())
        return response
    finally:
        _score_response_lock.release()


def _refresh_score_feed(current):
    """Update the shared ESPN feed cache; caller must hold _score_lock.

    Keep the existing 15/60-second TTL, week boundary, 2-second timeout,
    and stale-on-network-failure semantics used by the public scoreboard.
    """
    if _score_cache.get('week')!=current:
        _score_cache.update(expires=0,games=[],updated=None,week=current)
    if time.monotonic() >= _score_cache['expires']:
        try:
            query=f'?dates={current[0]}&seasontype=2&week={current[1]}' if current else ''
            req = Request('https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'+query,
                          headers={'User-Agent': 'TrendFindah/1.0'})
            from hosted_memory import analytics_network_wait
            with analytics_network_wait():
                with urlopen(req, timeout=2) as response:
                    raw_payload = response.read(2_000_000)
            payload = json.loads(raw_payload)
            del raw_payload
            if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
                raise ValueError('Invalid scoreboard')
            _score_cache.update(games=parse_scores(payload),
                                updated=datetime.now(timezone.utc).isoformat(), stale=False)
        except (OSError, ValueError, TypeError, AttributeError):
            _score_cache['stale'] = True
        interval = 15 if any(game['state']=='in' for game in _score_cache['games']) else 60
        _score_cache['expires'] = time.monotonic() + interval


def confirmed_final_feed():
    """Read provider-confirmed finals without building scorecard trend badges.

    A busy scoreboard refresh must not block member-pick pages. Fall back
    to same-week cached finals only; never reuse another week's results.
    """
    from site_week import active_week
    current=active_week(read_csv(ROOT/'nfl_games.csv'))
    if _score_lock.acquire(blocking=False):
        try:
            _refresh_score_feed(current)
            games=list(_score_cache['games'])
        finally:
            _score_lock.release()
    else:
        games=list(_score_cache.get('games',[])) if _score_cache.get('week')==current else []
    return [dict(game) for game in games
            if game.get('completed') is True and game.get('state')=='post']


def _scores_uncached():
    # Separate from homepage rendering: a slow feed never delays the main menu.
    from site_week import active_week
    current=active_week(read_csv(ROOT/'nfl_games.csv'))
    with _score_lock:
        _refresh_score_feed(current)
        # Break scores -> highlights -> confirmed finals -> scores recursion.
        # Only provider-confirmed finals enter the read-only display overlay.
        from flask import g
        g.public_confirmed_finals = [game for game in _score_cache['games']
                                    if game.get('completed') is True and game.get('state') == 'post']
        schedule = effective_rows(read_csv(ROOT / 'nfl_games.csv'), ROOT / 'nfl_games.csv',include_scores=False)
        # Keep normal badges limited to the homepage's featured Top 8.
        # Explicitly include an exceptional 10+ game primetime dog COVER streak
        # even if the Top 8 category-balancing rule omits it. Both calls reuse
        # active_trends' cache; never build a new trend from live scores.
        from active_trends import load_highlights
        try:
            hot_trends = scorecard_trends(
                load_highlights(), load_highlights(all_trends=True)
            ) if _score_cache['games'] else []
        except (OSError, ValueError, KeyError, TypeError):
            hot_trends = []  # Never take the live scores endpoint down for badges.
        games = []
        now = datetime.now(ZoneInfo('America/New_York'))
        for game in _score_cache['games']:
            row = dict(game)
            matches = [g for g in schedule if team_code(g['away_team']) == row['away']
                       and team_code(g['home_team']) == row['home'] and g['gameday'] == datetime.fromisoformat(row['date'].replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()]
            row['url'] = url_for('fans.game_center', game_id=matches[0]['game_id']) if len(matches) == 1 else None
            row['anomalies'] = []
            if len(matches) == 1 and row['state'] == 'post' and row.get('completed') is True:
                from anomaly_badges import saved_anomaly_links
                row['anomalies'] = saved_anomaly_links(matches[0]['game_id'], ROOT)
            row['market'] = None
            if len(matches) == 1:
                saved = dict(matches[0])
                # Live scores are graded only once the provider marks the game final.
                saved.update(home_score=row['home_score'] if row['state']=='post' else '',
                             away_score=row['away_score'] if row['state']=='post' else '')
                row['market'] = betting_result(saved)
                # A game only gets a flame for an exact recent evidence ID or
                # for fully checked pregame conditions. Build links server-side.
                qualifying = matches_for_score(matches[0], hot_trends,
                                               state=row['state'], now=now,
                                               active_week=current)
                row['hot_matches'] = [
                    {'label': f"{trend['title']} · {trend['outcome']}",
                     'url': url_for('hot_trends_page') + '#' + hot_trend_id(trend),
                     'confirmed': True}
                    for trend in qualifying]
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
    return season, week, records, people, manifest, teams, players


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


def _saved_final(game):
    """Only a saved result makes a game final; the live scoreboard is separate."""
    try:
        return all(str(game[k]).strip() != '' and math.isfinite(float(game[k]))
                   for k in ('away_score', 'home_score'))
    except (KeyError, TypeError, ValueError):
        return False


def _recorded_number(value):
    """Preserve missing values instead of converting them to a misleading zero."""
    try:
        if value is None or str(value).strip() == '':
            return None
        result = float(value)
        if not math.isfinite(result):
            return None
        return int(result) if result.is_integer() else round(result, 1)
    except (TypeError, ValueError):
        return None


def _game_stat_rows(rows, game_id):
    """An exact saved game ID is required: never borrow stats from another week."""
    return [row for row in (rows or [])
            if isinstance(row, dict) and str(row.get('game_id') or row.get('gameid') or '') == game_id]


def _final_box_score(game, team_data, player_data):
    """Build actual-game, side-by-side statistics from cached nflverse rows.

    Game rows are not pregame evidence. Scout comparisons continue to use
    team_records/player_records strictly before the displayed matchup week.
    """
    game_id = game['game_id']
    codes = (team_code(game['away_team']), team_code(game['home_team']))
    team_rows = _game_stat_rows(team_data, game_id)
    player_rows = _game_stat_rows(player_data, game_id)
    by_team = {team_code(row['team']): row for row in team_rows
               if row.get('team') and team_code(row['team']) in codes}

    def team_metric(code, field):
        return _recorded_number(by_team.get(code, {}).get(field))

    metrics = []
    for field, label in (
        ('passing_yards', 'Passing yards'),
        ('rushing_yards', 'Rushing yards'),
        ('total_yards', 'Total yards'),
        ('attempts', 'Pass attempts'),
        ('carries', 'Rush attempts'),
        ('sacks_suffered', 'Sacks allowed'),
    ):
        values = []
        for code in codes:
            if field == 'total_yards':
                passing, rushing = (team_metric(code, key) for key in ('passing_yards', 'rushing_yards'))
                value = passing + rushing if passing is not None and rushing is not None else None
            else:
                value = team_metric(code, field)
            values.append(value)
        if any(value is not None for value in values):
            metrics.append({'label': label, 'values': values})

    performers = []
    leader_specs = (
        ('Passing', 'passing_yards', 'passing_tds', 'attempts', 'Attempts'),
        ('Rushing', 'rushing_yards', 'rushing_tds', 'carries', 'Carries'),
        ('Receiving', 'receiving_yards', 'receiving_tds', 'receptions', 'Catches'),
    )
    for code in codes:
        own_players = [row for row in player_rows
                       if row.get('team') and team_code(row['team']) == code]
        top_players = []
        for role, yard_field, td_field, count_field, count_label in leader_specs:
            candidates = []
            for row in own_players:
                name = str(row.get('player_display_name') or row.get('player_name') or '').strip()
                yards = _recorded_number(row.get(yard_field))
                if name and yards is not None and yards > 0:
                    candidates.append((yards, name, row))
            if not candidates:
                continue
            yards, name, winner = max(candidates, key=lambda item: (item[0], item[1]))
            stats = [f'{yards:g} yards']
            count = _recorded_number(winner.get(count_field))
            if count is not None:
                stats.append(f'{count:g} {count_label.lower()}')
            tds = _recorded_number(winner.get(td_field))
            if tds is not None:
                stats.append(f'{tds:g} TD')
            top_players.append({'role': role, 'name': name, 'stat_line': ' · '.join(stats)})
        performers.append({'team': code, 'leaders': top_players})

    return {'codes': codes, 'metrics': metrics, 'performers': performers,
            'has_details': bool(metrics or any(p['leaders'] for p in performers))}


@bp.get('/games')
def all_games_board():
    from game_center import board_page
    return board_page()


@bp.get('/game/<game_id>')
def game_center(game_id):
    from game_center import game_page
    return game_page(game_id)


@bp.get('/game/<game_id>/data')
def game_center_data(game_id):
    from game_center import game_data
    return game_data(game_id)


@bp.get('/matchup/<game_id>')
def matchup(game_id):
    game = next((g for g in effective_rows(read_csv(ROOT / 'nfl_games.csv'),ROOT/'nfl_games.csv') if g['game_id'] == game_id), None)
    if game is None:
        abort(404)
    season, week, records, players, manifest, team_data, player_data = fan_context(game)
    is_final = _saved_final(game)
    box_score = _final_box_score(game, team_data, player_data) if is_final else None
    teams = []
    for side in ('away', 'home'):
        code = team_code(game[side + '_team'])
        rows = [r for r in records if r['team'] == code]
        teams.append({'code': code, 'summary': summarize_team(rows, rows), 'leaders': leaders(players, code)})
    from forecast_history import official_sources
    forecast = official_sources(ROOT).get(game_id)
    path = ROOT / 'data/scout4/blend/predictions' / (game_id + '.json')
    from expert_beta import matchup_prediction, private_cache
    from flask import request
    from forecast_history import pregame_record
    history_digest = request.args.get('forecast')
    archive_version = request.args.get('archive')
    if history_digest is not None and archive_version is not None:
        abort(400, description='Choose one saved forecast version.')
    use_results_forecast = False
    if history_digest is not None and path.exists():
        raw = path.read_bytes()
        import hashlib
        if hashlib.sha256(raw).hexdigest() == history_digest:
            forecast = json.loads(raw)
            forecast['_history_digest'] = history_digest
    if forecast and archive_version is None and (forecast is not None or history_digest is not None):
        try:
            pregame_record(forecast)
        except (KeyError, TypeError, ValueError):
            abort(409, description='Saved results forecast requires provenance review.')
        import hashlib
        digest = forecast['_history_digest']
        if history_digest is not None and history_digest != digest:
            abort(409, description='This link does not match the saved forecast version.')
        use_results_forecast = True
    elif history_digest is not None:
        abort(404, description='Saved results forecast not found.')
    prediction_item = matchup_prediction(game_id,version=archive_version) if archive_version is not None else matchup_prediction(game_id)
    from member_picks import comparison_picks
    inline_picks=comparison_picks(game_id=game_id)
    from flask import make_response
    return private_cache(make_response(render_template('matchup.html', inline_picks=inline_picks, game=game, teams=teams, season=season, week=week,
                           manifest=manifest, forecast=forecast, prediction_item=prediction_item, is_final=is_final, box_score=box_score,
                           use_results_forecast=use_results_forecast, archive_version=archive_version)))


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
    from forecast_history import grade_components, total_result, pregame_record, record_digest
    groups = {}
    games = {g['game_id']:g for g in schedule}
    excluded = 0
    recent = []
    ids = [record.get('game_id') for record in records]
    for record in records:
        try:
            if ids.count(record.get('game_id')) != 1:
                raise ValueError('Conflicting forecast versions require cohort review')
            pregame_record(record)
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
                       'pick':record['components']['Blend']['pick'], 'ats':ats,'total':total,
                       'line':record['quote']['line'] if record['components']['Blend']['pick']==record['away_team'] else -record['quote']['line'],
                       'model_version':record.get('version','Unknown version'),
                       'forecast_digest':record.get('_history_digest') or record_digest(record)})
    for group in groups.values():
        for name in ('ats','totals'):
            counts = group[name]
            decisions = counts.get('Win',0) + counts.get('Loss',0)
            counts['decisions'] = decisions
            counts['rate'] = 100 * counts.get('Win',0) / decisions if decisions else None
    graded = [r for r in recent if r['ats'] != 'Pending' or r['total'] not in ('Pending','Unavailable')]
    return list(groups.values()), sorted(graded,key=lambda r:r['date'],reverse=True)[:10], excluded


def combine_prediction_groups(groups):
    """A weekly scoreboard is one card; preserve configuration cohorts for audit."""
    result = {}
    for market in ('ats', 'totals'):
        counts = {status: sum(group[market].get(status, 0) for group in groups)
                  for status in ('Win', 'Loss', 'Push', 'Pending', 'No Call',
                                 'Unavailable', 'Review needed')}
        counts['decisions'] = counts['Win'] + counts['Loss']
        counts['rate'] = 100 * counts['Win'] / counts['decisions'] if counts['decisions'] else None
        result[market] = counts
    return result


def plug_week_record(rows, season, week):
    """An independent weekly slice of previously issued Plug ATS receipts."""
    from collections import Counter
    matches = [r for r in rows if str(r['season']) == str(season)
               and str(r['week']) == str(week)]
    counts = Counter(r['result'] for r in matches)
    return matches, {name: counts.get(name, 0) for name in ('Win','Loss','Push','Pending')}


@bp.get('/predictions/results')
def prediction_results():
    from flask import request
    from site_week import active_week
    import hashlib
    from forecast_history import official_sources
    records = list(official_sources(ROOT).values())
    path = ROOT / 'nfl_games.csv'
    original_schedule = read_csv(path)
    schedule = effective_rows(original_schedule, path)
    saved_weeks = set()
    for record in records:
        try:
            season, week = int(record['season']), int(record['week'])
            if 1 <= week <= 18:
                saved_weeks.add((season, week))
        except (KeyError, TypeError, ValueError):
            continue
    current = active_week(original_schedule)
    if saved_weeks:
        season = current[0] if current and any(year == current[0] for year, _ in saved_weeks) else max(year for year, _ in saved_weeks)
        weeks = sorted(week for year, week in saved_weeks if year == season)
        default_week = current[1] if current and current[0] == season and current[1] in weeks else weeks[-1]
    else:
        season, weeks, default_week = (current[0] if current else None), [], None
    selection = request.args.get('week')
    if selection is not None:
        try:
            selected_week = int(selection)
        except (TypeError, ValueError):
            abort(400, description='Invalid week.')
        if selected_week not in weeks:
            abort(400, description='No saved predictions for that week.')
    else:
        selected_week = default_week
    selected_records = [r for r in records if str(r.get('season')) == str(season)
                        and str(r.get('week')) == str(selected_week)] if selected_week is not None else []
    groups, recent, excluded = prediction_performance(selected_records, schedule)
    # Only actually issued Plug receipts count; never reconstruct issued picks
    # from retrospective edge rankings or current market lines.
    from plug_ats_select import published_history
    from plug_dashboard import _completed_games
    try:
        plug_picks, plug_seasons = published_history(_completed_games(ROOT))
        plug_receipts_review = False
    except (OSError, TypeError, ValueError, KeyError):
        plug_picks, plug_seasons = [], {}
        plug_receipts_review = True
    plug_week_picks, plug_week_totals = plug_week_record(plug_picks, season, selected_week)
    return render_template('prediction_results.html', groups=groups,
                           summary=combine_prediction_groups(groups), recent=recent,
                           season=season, weeks=weeks, selected_week=selected_week,
                           excluded=excluded, freshness=data_freshness(),
                           plug_week_picks=plug_week_picks, plug_week_totals=plug_week_totals,
                           plug_season_totals=plug_seasons.get(season, {}),
                           plug_receipts_review=plug_receipts_review)
