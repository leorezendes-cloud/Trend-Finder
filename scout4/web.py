"""Scout 4.0 read-only statistics pages."""
import json
from collections import defaultdict
from pathlib import Path
from flask import Blueprint, abort, render_template, request
from .stats import (read_csv, team_records, player_records, summarize_team,
                    summarize_player, adjusted_defense, mean_metric)

ROOT = Path(__file__).resolve().parents[1]
bp = Blueprint('scout4', __name__)


def sources(season):
    cache = ROOT / 'data' / 'scout4'
    pointer = cache / str(season) / 'latest.json'
    if not pointer.exists():
        return [], [], None
    manifest = json.loads(pointer.read_text())
    paths = {}
    for kind in ('team', 'player'):
        path = (cache / manifest['files'][kind]['path']).resolve()
        if not path.is_relative_to(cache.resolve()):
            raise ValueError('Statistics cache path is outside its directory')
        paths[kind] = path
    return read_csv(paths['team']), read_csv(paths['player']), manifest


def view_data():
    schedule = read_csv(ROOT / 'nfl_games.csv')
    years = sorted({int(r['season']) for r in schedule}, reverse=True)
    cache_years = sorted(int(p.parent.name) for p in (ROOT/'data'/'scout4').glob('*/latest.json'))
    try:
        season = int(request.args.get('season', max(cache_years) if cache_years else max(years)))
        before_week = int(request.args.get('before_week', 19))
    except ValueError:
        abort(400, description='Season and week must be numbers.')
    if season not in years or not 1 <= before_week <= 19:
        abort(400, description='Choose an available season and a week from 1 to 19.')
    venue = request.args.get('venue', 'All')
    if venue not in ('All', 'Home', 'Away', 'Neutral'):
        abort(400, description='Choose All, Home, Away, or Neutral venue.')
    teams, players, manifest = sources(season)
    records = team_records(schedule, teams, season, before_week)
    diagnostics = {}
    all_players = player_records(schedule, players, season, before_week, diagnostics)
    return dict(season=season, before_week=before_week, venue=venue, years=years,
                cache_years=cache_years, records=records, players=all_players, manifest=manifest, diagnostics=diagnostics,
                coverage_week=max((r['week'] for r in records),default=None),
                teams=sorted({r['team'] for r in records}),
                positions=sorted({r['position'] for r in all_players}))


def filtered(rows, venue):
    return [r for r in rows if venue == 'All' or r['venue'] == venue]


@bp.app_template_filter('stat')
def stat(value, digits=1):
    return '—' if value is None else f'{value:,.{digits}f}'


@bp.route('/scout4/teams')
def teams_page():
    v = view_data()
    team = request.args.get('team', '')
    opponent = request.args.get('opponent', '')
    if team and team not in v['teams'] or opponent and opponent not in v['teams']:
        abort(400, description='Choose a team with completed games in this window.')
    defense = adjusted_defense(v['records'])
    cards = []
    selected_teams = [team] if team else v['teams']
    for code in selected_teams:
        baseline = [r for r in v['records'] if r['team'] == code]
        games = filtered(baseline, v['venue'])
        cards.append({'team': code, 'games': games, 'summary': summarize_team(games, baseline),
                      'defense': defense.get(code, {})})
    matchup = []
    if team and opponent and team != opponent:
        for attacker, defender in ((team, opponent), (opponent, team)):
            # Matchups respect the selected venue for offensive/allowed averages.
            attack = filtered([r for r in v['records'] if r['team'] == attacker], v['venue'])
            stop = filtered([r for r in v['records'] if r['team'] == defender], v['venue'])
            matchup.append({'attacker': attacker, 'defender': defender,
                            'attack_games': len(attack), 'defense_games': len(stop),
                            'metrics': [{'label': label, 'offense': mean_metric(attack, metric),
                                         'allowed': mean_metric(stop, metric + '_allowed')}
                                        for label,metric in (('Passing yards / game', 'passing_yards'),
                                                             ('Rushing yards / game', 'rushing_yards'),
                                                             ('Passing EPA / game', 'passing_epa'),
                                                             ('Rushing EPA / game', 'rushing_epa'))]})
    return render_template('scout4_teams.html', view=v, cards=cards, team=team, opponent=opponent, matchup=matchup)


OFFENSE_POSITIONS = {'QB', 'RB', 'FB', 'WR', 'TE'}
DEFENSE_POSITIONS = {'CB', 'DB', 'DE', 'DL', 'DT', 'FS', 'ILB', 'LB', 'MLB', 'NT', 'OLB', 'S', 'SAF', 'SS', 'EDGE'}
OFFENSE_RANKS = {'yards': 'Passing + rushing + receiving yards', 'passing_yards': 'Passing yards',
                 'rushing_yards': 'Rushing yards', 'receiving_yards': 'Receiving yards'}
DEFENSE_RANKS = {'def_sacks': 'Sacks', 'def_tackles_solo': 'Solo tackles', 'def_interceptions': 'Interceptions'}


def leaderboard(cards, positions, metric):
    leaders = []
    fields = ('passing_yards', 'rushing_yards', 'receiving_yards') if metric == 'yards' else (metric,)
    for card in cards:
        if card['position'] not in positions:
            continue
        totals = [card['summary']['metrics'][field]['total'] for field in fields]
        # Do not treat missing components as known zeros for a combined total.
        if any(value is None for value in totals):
            continue
        total = sum(totals)
        if total > 0:
            leaders.append({**card, 'rank_total': total})
    leaders.sort(key=lambda c: (-c['rank_total'], c['name'], c['team'], c['id']))
    return [{**card, 'rank': index} for index, card in enumerate(leaders[:10], 1)]


@bp.route('/scout4/players')
def players_page():
    v = view_data()
    team = request.args.get('team', '')
    position = request.args.get('position', '')
    player = request.args.get('player', '')
    display = request.args.get('display', 'top')
    offense_metric = request.args.get('offense_metric', 'yards')
    defense_metric = request.args.get('defense_metric', 'def_sacks')
    if display not in ('top', 'all') or offense_metric not in OFFENSE_RANKS or defense_metric not in DEFENSE_RANKS:
        abort(400, description='Choose an available display and ranking metric.')
    if team and team not in v['teams'] or position and position not in v['positions']:
        abort(400, description='Choose a team or position available in this window.')
    choices = sorted({(r['player_id'], r['name']) for r in v['players']
                      if (not team or r['team'] == team) and (not position or r['position'] == position)}, key=lambda x:x[1])
    if player and player not in {p[0] for p in choices}:
        abort(400, description='Choose a player matching your team and position filters.')
    groups = defaultdict(list)
    for row in v['players']:
        if (not team or row['team'] == team) and (not position or row['position'] == position) and (not player or row['player_id'] == player):
            # Group transferred players by identity and team, avoiding mixed team splits.
            groups[(row['player_id'], row['team'])].append(row)
    cards = []
    for (pid, code), baseline in groups.items():
        games = filtered(baseline, v['venue'])
        if games:
            cards.append({'id': pid, 'team': code, 'name': baseline[-1]['name'],
                          'position': baseline[-1]['position'], 'games': games,
                          'summary': summarize_player(games, baseline)})
    cards.sort(key=lambda c:(c['name'], c['team']))
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        abort(400)
    sections = []
    if display == 'top' and not player:
        sections = [
            {'title': 'Top 10 offense', 'label': OFFENSE_RANKS[offense_metric],
             'cards': leaderboard(cards, OFFENSE_POSITIONS, offense_metric)},
            {'title': 'Top 10 defense', 'label': DEFENSE_RANKS[defense_metric],
             'cards': leaderboard(cards, DEFENSE_POSITIONS, defense_metric)}]
        pages = 1
    else:
        pages = max(1, (len(cards)+39)//40)
    if not 1 <= page <= pages:
        abort(400, description='Choose an available page.')
    total = len(cards)
    links = {}
    for label, number in (('previous', page-1), ('next', page+1)):
        if 1 <= number <= pages:
            args = request.args.to_dict(); args['page'] = number
            from flask import url_for
            links[label] = url_for('scout4.players_page', **args)
    return render_template('scout4_players.html', view=v, cards=cards[(page-1)*40:page*40],
                           team=team, position=position, player=player, choices=choices,
                           page=page, pages=pages, total=total, links=links, sections=sections,
                           display=display, offense_metric=offense_metric, defense_metric=defense_metric,
                           offense_ranks=OFFENSE_RANKS, defense_ranks=DEFENSE_RANKS)


@bp.route('/scout4/ratings')
def ratings_page():
    import hashlib
    from .ratings import build_ratings, matchup
    v = view_data()
    team = request.args.get('team', '')
    opponent = request.args.get('opponent', '')
    site = request.args.get('matchup_site', 'Away')
    label = request.args.get('model', 'Scoring + matchup EPA')
    if site not in ('Home', 'Away', 'Neutral'):
        abort(400, description='Choose a matchup venue.')
    feed,_,_ = sources(v['season'])
    ratings,league = build_ratings(read_csv(ROOT/'nfl_games.csv'),feed,v['season'],v['before_week'])
    if (team and team not in ratings) or (opponent and opponent not in ratings):
        abort(400, description='Choose teams with completed games in this window.')
    pointer = ROOT/'data'/'scout4'/'ratings_latest.json'
    models,report,estimate = {},None,None
    unavailable = None
    if pointer.exists():
        manifest = json.loads(pointer.read_text())
        model_path = (ROOT/manifest['models_path']).resolve()
        summary_path = (ROOT/manifest['summary_path']).resolve()
        if not model_path.is_relative_to((ROOT/'data'/'scout4').resolve()) or not summary_path.is_relative_to((ROOT/'data'/'scout4').resolve()):
            abort(500, description='Invalid ratings artifact path')
        if hashlib.sha256(model_path.read_bytes()).hexdigest()!=manifest['model_sha256']:
            abort(500, description='Ratings model fingerprint mismatch')
        models=json.loads(model_path.read_text());report=json.loads(summary_path.read_text())
        if label not in models:
            abort(400,description='Choose an available model.')
        if team and opponent:
            if team==opponent:
                unavailable='Choose two different teams.'
            elif v['season']<=models[label]['training_season']:
                unavailable='This conversion was fitted on 2024. Estimates require a later season to avoid training-period contamination.'
            else:
                estimate=matchup(models[label],ratings,team,opponent,site)
                if estimate is None:
                    unavailable='Need at least three earlier games for each team and complete coverage of the selected model inputs.'
    else:
        unavailable='The scoring conversion has not been built yet.'
    ranked = sorted(ratings.values(),key=lambda r:-(r['off_scoring']+r['def_scoring']))
    return render_template('scout4_ratings.html',view=v,team=team,opponent=opponent,
                           ratings=ranked,league=league,matchup_site=site,models=models,
                           model_label=label,report=report,estimate=estimate,unavailable=unavailable)


@bp.app_template_filter('eastern_time')
def eastern_time(value):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %I:%M %p ET')


@bp.route('/scout4/shadow')
def shadow_page():
    from .shadow import view
    tracker=view();grouped={}
    for r in tracker['records']:
        game=grouped.setdefault(r['game_id'],{'game_id':r['game_id'],'away':r['away_team'],'home':r['home_team'],
                                            'kickoff':r['kickoff_utc'],'Spread':None,'Total':None})
        game[r['market']]=r
    from .personnel import tracker_records
    personnel=tracker_records()
    from .starters import latest_reports
    starter_reports=latest_reports()
    from .weather import view as weather_view
    weather=weather_view()
    pace_paths=sorted((ROOT/'data/scout4/pace/2026').glob('*/profiles_before_week6.json'))
    pace=json.loads(pace_paths[-1].read_text()) if pace_paths else {}
    for game in grouped.values():
        game['personnel_evidence']=personnel.get(game['game_id'])
        game['weather']=weather['records'].get(game['game_id'])
        game['weather_pending']=next((r['reason'] for r in weather['pending'] if r['game_id']==game['game_id']),None)
        game['pace']=pace if game['game_id'].startswith('2026_06_') else {}
        game['starter_reports']={team:starter_reports.get((game['game_id'],team)) for team in (game['away'],game['home'])}
    games=sorted(grouped.values(),key=lambda g:(g['kickoff'],g['game_id']))
    totals_paths=sorted((ROOT/'data/scout4/totals_runs').glob('*/summary.json'))
    totals_report=json.loads(totals_paths[-1].read_text()) if totals_paths else None
    status=tracker['status'];market=request.args.get('market','All')
    if market not in ('All','Spread','Total'):abort(400)
    return render_template('scout4_shadow.html',games=games,tracker=tracker,market=market,
                           totals_report=totals_report,error=request.args.get('error'))



@bp.record_once
def shadow_navigation_support(state):
    state.app.config['SCOUT4_SHADOW_ENABLED']=True





@bp.record_once
def blend_navigation_support(state):
    state.app.config['SCOUT4_BLEND_ENABLED']=True
