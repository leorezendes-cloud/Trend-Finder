"""Read-only standings for The Huddle's public leaderboard and existing owner preview.

Shared My Picks grades are authoritative; league-specific picks retain their own
private standings. This module never syncs results or changes persisted picks.
"""
import os

from flask import Blueprint, abort, current_app, g, render_template, request
from membership import db

bp = Blueprint('huddle_leaderboard', __name__, url_prefix='/community/leaderboard')
MARKETS = {'ats': 'Against the spread', 'su': 'Straight up', 'ou': 'Over / Under'}
DEFAULT_MIN_DECISIONS = 5


def init_huddle_leaderboard(app):
    """Keep the original owner-only preview behind its independent flag."""
    app.config.setdefault('HUDDLE_LEADERBOARD_PREVIEW_ENABLED',
                          os.environ.get('HUDDLE_LEADERBOARD_PREVIEW_ENABLED', '').lower()
                          in ('1', 'true', 'yes'))
    app.register_blueprint(bp)
    app.jinja_env.globals['huddle_leaderboard_available'] = True


def standings(connection, *, season=None, week_id=None,
              minimum=DEFAULT_MIN_DECISIONS, limit=100):
    """Return ranked W/L records for graded, non-void published games only.

    Pushes/ties are displayed but excluded from the win-percentage denominator.
    Never regrade or sync in a public-read request. Tied W/L records share rank.
    """
    if season is not None and (type(season) is not int or not 1999 <= season <= 2100):
        raise ValueError('Invalid season')
    if week_id is not None and (type(week_id) is not int or week_id < 1):
        raise ValueError('Invalid week')
    if type(minimum) is not int or not 1 <= minimum <= 1000:
        raise ValueError('Invalid minimum sample')
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Invalid leaderboard limit')

    has_profiles = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                      "AND name='community_profiles'").fetchone()
    profile_join = ('LEFT JOIN community_profiles profile ON profile.member_id=p.member_id'
                    if has_profiles else '')
    name_expr = 'MAX(profile.display_name)' if has_profiles else 'NULL'
    output = {}
    for market in MARKETS:
        # Field names are restricted to the hardcoded MARKETS keys.
        result_col = 'p.' + market + '_result'
        selection_col = 'p.' + market
        query = f'''SELECT p.member_id, {name_expr} AS nickname,
                      SUM(CASE WHEN {result_col}='Win' THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN {result_col}='Loss' THEN 1 ELSE 0 END) AS losses,
                      SUM(CASE WHEN {result_col}='Push' THEN 1 ELSE 0 END) AS pushes,
                      SUM(CASE WHEN {result_col}='Tie' THEN 1 ELSE 0 END) AS ties
                    FROM member_picks p
                    JOIN pick_games game ON game.id=p.game_id
                    JOIN pick_weeks week ON week.id=game.week_id
                    JOIN members member ON member.id=p.member_id
                    {profile_join}
                    WHERE week.published_at IS NOT NULL
                      AND game.away_final IS NOT NULL AND game.home_final IS NOT NULL
                      AND game.result_at IS NOT NULL AND game.void_reason IS NULL
                      AND {selection_col} IS NOT NULL
                      AND {result_col} IN ('Win','Loss','Push','Tie')'''
        params = []
        if season is not None:
            query += ' AND week.season=?'
            params.append(season)
        if week_id is not None:
            query += ' AND week.id=?'
            params.append(week_id)
        query += ' GROUP BY p.member_id'
        rows = []
        for record in connection.execute(query, params):
            member_id, nickname, wins, losses, pushes, ties = record
            member_id, wins, losses, pushes, ties = map(
                int, (member_id, wins, losses, pushes, ties))
            decisions = wins + losses
            if decisions < minimum:
                continue
            rows.append({'member_id': member_id, 'name': nickname or f'Fan #{member_id}',
                         'wins': wins, 'losses': losses, 'pushes': pushes, 'ties': ties,
                         'decisions': decisions, 'win_pct': 100 * wins / decisions})
        rows.sort(key=lambda row: (-row['win_pct'], -row['wins'],
                                   -row['decisions'], row['member_id']))
        last_record = None
        rank = 0
        for position, row in enumerate(rows, 1):
            record = (row['wins'], row['losses'])
            if record != last_record:
                rank = position
            row['rank'] = rank
            last_record = record
        output[market] = rows[:limit]
    return output


def published_weeks(connection):
    """Return only published weeks containing an actual game, newest first."""
    return connection.execute('''SELECT week.id, week.season, week.week, week.stage
        FROM pick_weeks week WHERE week.published_at IS NOT NULL
        AND EXISTS(SELECT 1 FROM pick_games game WHERE game.week_id=week.id)
        ORDER BY week.season DESC, week.week DESC, week.id DESC''').fetchall()


@bp.get('')
@bp.get('/')
def index():
    """Public overall leaderboard; private league membership stays private."""
    connection = db()
    weeks = published_weeks(connection)
    seasons = list(dict.fromkeys(int(row['season']) for row in weeks))
    view = request.args.get('view', 'weekly')
    market = request.args.get('market', 'ats')
    if view not in ('weekly', 'season', 'alltime') or market not in MARKETS:
        abort(400)
    raw_season = request.args.get('season')
    if raw_season is None:
        season = seasons[0] if seasons else None
    elif raw_season.isdecimal() and int(raw_season) in seasons:
        season = int(raw_season)
    else:
        abort(400)
    season_weeks = [row for row in weeks if row['season'] == season]
    raw_week = request.args.get('week_id')
    if raw_week is not None and (not raw_week.isdecimal() or
                                 int(raw_week) not in {row['id'] for row in weeks}):
        abort(400)
    # Changing the season with the form may carry the previously selected week.
    # In that case select the newest week of the new season, not an invalid 400.
    season_ids = {row['id'] for row in season_weeks}
    selected_week = (int(raw_week) if raw_week is not None and int(raw_week) in season_ids
                     else season_weeks[0]['id'] if season_weeks else None)
    minimum = 1 if view == 'weekly' else DEFAULT_MIN_DECISIONS
    # An empty slate should show the empty state, not all-time results.
    if view == 'weekly' and selected_week is None:
        rows = []
    else:
        tables = standings(connection,
                           season=None if view == 'alltime' else season,
                           week_id=selected_week if view == 'weekly' else None,
                           minimum=minimum)
        rows = tables[market]
    # Only link to leagues where the signed-in member is an active participant.
    leagues = []
    if g.get('member') is not None:
        leagues = connection.execute('''SELECT league.id, league.name
            FROM huddle_leagues league
            JOIN huddle_league_members entry ON entry.league_id=league.id
            WHERE entry.member_id=?
            ORDER BY league.created_at DESC, league.id DESC LIMIT 12''',
            (g.member['id'],)).fetchall()
    response = current_app.make_response(render_template(
        'huddle_leaderboard.html', rows=rows, markets=MARKETS,
        market=market, view=view, minimum=minimum, seasons=seasons,
        season=season, weeks=season_weeks, selected_week=selected_week,
        leagues=leagues))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex, follow'
    return response


@bp.get('/preview')
def preview():
    # Existing private preview is still hidden unless explicitly opted in.
    if not current_app.config.get('HUDDLE_LEADERBOARD_PREVIEW_ENABLED') or not g.get('is_owner', False):
        abort(404)
    season_text = request.args.get('season', 'all')
    if season_text == 'all':
        season = None
    elif season_text.isdecimal() and 1999 <= int(season_text) <= 2100:
        season = int(season_text)
    else:
        abort(400)
    tables = standings(db(), season=season)
    response = current_app.make_response(render_template(
        'huddle_leaderboard_preview.html', tables=tables, markets=MARKETS,
        season=season, minimum=DEFAULT_MIN_DECISIONS))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response
