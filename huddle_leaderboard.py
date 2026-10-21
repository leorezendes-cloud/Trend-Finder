"""Hidden, read-only member pick standings for The Huddle.

No new database tables, no model runs, no weekly snapshots, no public routes.
The public Huddle 'Coming soon' card is intentionally unchanged.
"""
import os

from flask import Blueprint, abort, current_app, g, render_template, request
from membership import db

bp = Blueprint('huddle_leaderboard', __name__, url_prefix='/community/leaderboard')
MARKETS = {'ats': 'Against the spread', 'su': 'Straight-up', 'ou': 'Over / Under'}
DEFAULT_MIN_DECISIONS = 5


def init_huddle_leaderboard(app):
    """Preview requires BOTH an opt-in config flag and existing site-owner access."""
    app.config.setdefault('HUDDLE_LEADERBOARD_PREVIEW_ENABLED',
                          os.environ.get('HUDDLE_LEADERBOARD_PREVIEW_ENABLED', '').lower() in ('1', 'true', 'yes'))
    app.register_blueprint(bp)


def standings(connection, *, season=None, minimum=DEFAULT_MIN_DECISIONS, limit=100):
    """Rank only already-graded, non-void, published final games.

    The member-picks grader is authoritative: don't compute outcomes or run
    sync_results() here. Pushes and ties do not enter win percentage.
    """
    if season is not None and (type(season) is not int or not 1999 <= season <= 2100):
        raise ValueError('Invalid season')
    if type(minimum) is not int or not 1 <= minimum <= 1000:
        raise ValueError('Invalid minimum sample')
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Invalid leaderboard limit')
    output = {}
    for market in MARKETS:
        # Column names come solely from the hardcoded MARKETS dictionary.
        result_col = 'p.' + market + '_result'
        selection_col = 'p.' + market
        query = f'''SELECT p.member_id AS member_id,
                     SUM(CASE WHEN {result_col}='Win' THEN 1 ELSE 0 END) AS wins,
                     SUM(CASE WHEN {result_col}='Loss' THEN 1 ELSE 0 END) AS losses,
                     SUM(CASE WHEN {result_col}='Push' THEN 1 ELSE 0 END) AS pushes,
                     SUM(CASE WHEN {result_col}='Tie' THEN 1 ELSE 0 END) AS ties
                   FROM member_picks p
                   JOIN pick_games game ON game.id = p.game_id
                   JOIN pick_weeks week ON week.id = game.week_id
                   JOIN members member ON member.id = p.member_id
                   WHERE week.published_at IS NOT NULL
                     AND game.away_final IS NOT NULL AND game.home_final IS NOT NULL
                     AND game.result_at IS NOT NULL AND game.void_reason IS NULL
                     AND {selection_col} IS NOT NULL
                     AND {result_col} IN ('Win','Loss','Push','Tie')'''
        params = []
        if season is not None:
            query += ' AND week.season=?'
            params.append(season)
        query += ' GROUP BY p.member_id'
        rows = []
        for item in connection.execute(query, params):
            member_id, wins, losses, pushes, ties = map(int, item)
            decisions = wins + losses
            if decisions < minimum:
                continue
            rows.append({'member_id': member_id, 'name': f'Fan #{member_id}',
                         'wins': wins, 'losses': losses, 'pushes': pushes, 'ties': ties,
                         'decisions': decisions, 'win_pct': 100.0 * wins / decisions})
        rows.sort(key=lambda r: (-r['win_pct'], -r['wins'], -r['decisions'], r['member_id']))
        # Competition ranking (1,1,3), stable and reproducible for equal records.
        last_key = None
        last_rank = 0
        for index, row in enumerate(rows, start=1):
            key = (row['wins'], row['losses'])
            if key != last_key:
                last_rank = index
                last_key = key
            row['rank'] = last_rank
        output[market] = rows[:limit]
    return output


@bp.get('/preview')
def preview():
    # Return the same 404 for everybody unless preview was explicitly enabled
    # AND the logged-in user is a verified site owner.
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
    response = current_app.make_response(render_template('huddle_leaderboard_preview.html',
        tables=tables, markets=MARKETS, season=season,
        minimum=DEFAULT_MIN_DECISIONS))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response
