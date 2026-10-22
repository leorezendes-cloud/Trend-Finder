"""Free private leagues over shared My Picks; existing grades are read-only."""
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from membership import db, allow_attempt

bp = Blueprint('huddle_leagues', __name__, url_prefix='/huddle/leagues')
CATEGORIES = {'su': 'Straight Up', 'ats': 'Against the Spread', 'ou': 'Over/Under'}
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
OUTCOMES = ('Win', 'Loss', 'Push', 'Tie', 'Void', 'Pending')


def now_utc():
    return datetime.now(timezone.utc)


def init_leagues(app):
    # Additive and repeatable; leave membership user_version and pick tables alone.
    with app.app_context():
        with db():
            db().execute('''CREATE TABLE IF NOT EXISTS huddle_leagues (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(name) BETWEEN 3 AND 64),
                commissioner_id INTEGER NOT NULL REFERENCES members(id), created_at TEXT NOT NULL,
                invite_token TEXT NOT NULL UNIQUE CHECK(length(invite_token)=43),
                su_enabled INTEGER NOT NULL CHECK(su_enabled IN (0,1)),
                ats_enabled INTEGER NOT NULL CHECK(ats_enabled IN (0,1)),
                ou_enabled INTEGER NOT NULL CHECK(ou_enabled IN (0,1)),
                pick_source TEXT NOT NULL DEFAULT 'my_picks' CHECK(pick_source='my_picks'),
                CHECK(su_enabled+ats_enabled+ou_enabled>=1))''')
            db().execute('''CREATE TABLE IF NOT EXISTS huddle_league_members (
                league_id INTEGER NOT NULL REFERENCES huddle_leagues(id),
                member_id INTEGER NOT NULL REFERENCES members(id), joined_at TEXT NOT NULL,
                PRIMARY KEY(league_id,member_id))''')
            db().execute('''CREATE INDEX IF NOT EXISTS huddle_league_member_lookup
                            ON huddle_league_members(member_id,league_id)''')
    app.register_blueprint(bp)

    @app.before_request
    def league_guard():
        if request.blueprint != 'huddle_leagues':
            return
        if request.method == 'POST':
            token = request.form.get('csrf_token', '')
            if not session.get('_csrf') or not secrets.compare_digest(session['_csrf'], token):
                abort(400, description='Your form expired. Reload and try again.')
        if not g.get('member') and request.endpoint != 'huddle_leagues.join':
            return redirect(url_for('membership.login'))

    @app.after_request
    def league_privacy(response):
        if request.blueprint == 'huddle_leagues':
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response


def member_league(league_id):
    row = db().execute('''SELECT l.* FROM huddle_leagues l JOIN huddle_league_members m
        ON m.league_id=l.id WHERE l.id=? AND m.member_id=?''',
        (league_id, g.member['id'])).fetchone()
    if row is None:
        abort(404)
    return row


def selections(connection, league, season, week_id=None):
    """Phase 1 source adapter; optional Phase 2 overrides can be resolved here."""
    if league['pick_source'] != 'my_picks':
        raise ValueError('Unsupported league selection source')
    query = '''SELECT p.*,game.lock_at,game.kickoff_at,game.void_reason,
        game.away_final,game.home_final,game.result_at
        FROM huddle_league_members entry
        JOIN member_picks p ON p.member_id=entry.member_id
        JOIN pick_games game ON game.id=p.game_id
        JOIN pick_weeks week ON week.id=game.week_id
        WHERE entry.league_id=? AND week.season=? AND week.published_at IS NOT NULL
        AND julianday(game.lock_at)>julianday(entry.joined_at)
        AND julianday(game.lock_at)>julianday(?)
        AND julianday(game.kickoff_at)>julianday(entry.joined_at)
        AND julianday(game.kickoff_at)>julianday(?)
        AND (game.result_at IS NULL OR
             (julianday(game.result_at)>julianday(entry.joined_at)
              AND julianday(game.result_at)>julianday(?)))'''
    params = [league['id'],season,league['created_at'],league['created_at'],league['created_at']]
    if week_id is not None:
        query += ' AND week.id=?'
        params.append(week_id)
    return connection.execute(query, params)


def standings(connection, league, season, week_id=None, now=None):
    """Derive points from verified stored grades; never sync or regrade picks."""
    now = now or now_utc()
    has_profiles = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='community_profiles'").fetchone()
    profiles = 'LEFT JOIN community_profiles profile ON profile.member_id=entry.member_id' if has_profiles else ''
    name = 'profile.display_name' if has_profiles else 'NULL'
    members = connection.execute(f'''SELECT entry.member_id,{name} display_name
        FROM huddle_league_members entry {profiles} WHERE entry.league_id=?
        ORDER BY entry.member_id''', (league['id'],)).fetchall()
    rows = {m['member_id']: dict(member_id=m['member_id'],name=m['display_name'] or f"Fan #{m['member_id']}",
            points=0, **{outcome:0 for outcome in OUTCOMES}) for m in members}
    for pick in selections(connection, league, season, week_id):
        try:
            verified = (pick['away_final'] is not None and pick['home_final'] is not None
                and pick['result_at'] is not None
                and datetime.fromisoformat(pick['result_at']) <= now
                and datetime.fromisoformat(pick['lock_at']) <= now)
        except (ValueError, TypeError):
            verified = False
        row = rows[pick['member_id']]
        for category in CATEGORIES:
            if not league[category+'_enabled'] or not pick[category]:
                continue
            outcome = 'Void' if pick['void_reason'] else pick[category+'_result'] if verified else 'Pending'
            if outcome not in OUTCOMES:
                outcome = 'Pending'
            row[outcome] += 1
            row['points'] += int(outcome == 'Win')
    result = sorted(rows.values(), key=lambda row:(-row['points'],row['member_id']))
    previous = None
    for position,row in enumerate(result,1):
        if row['points'] != previous:
            rank = position
        row['rank'] = rank
        previous = row['points']
    return result


@bp.get('/')
def mine():
    leagues = db().execute('''SELECT l.* FROM huddle_leagues l JOIN huddle_league_members m
        ON m.league_id=l.id WHERE m.member_id=? ORDER BY l.created_at DESC,l.id DESC''',
        (g.member['id'],)).fetchall()
    return render_template('huddle_leagues.html', mode='mine',leagues=leagues,categories=CATEGORIES)


@bp.route('/create', methods=['GET','POST'])
def create():
    error = None
    chosen = request.form.getlist('categories') if request.method == 'POST' else ['ats']
    name = ' '.join(request.form.get('name','').split())
    if request.method == 'POST':
        if not 3 <= len(name) <= 64:
            error = 'Use a league name between 3 and 64 characters.'
        elif not chosen or not set(chosen) <= set(CATEGORIES) or len(chosen) != len(set(chosen)):
            error = 'Choose at least one valid scoring category.'
        elif not allow_attempt('league-create',str(g.member['id'])):
            abort(429,description='Too many league creations. Try again in 15 minutes.')
        else:
            connection = db()
            connection.execute('BEGIN IMMEDIATE')
            try:
                created = now_utc().isoformat()
                cursor = connection.execute('''INSERT INTO huddle_leagues
                    (name,commissioner_id,created_at,invite_token,su_enabled,ats_enabled,ou_enabled)
                    VALUES(?,?,?,?,?,?,?)''', (name,g.member['id'],created,secrets.token_urlsafe(32),
                                               *(int(c in chosen) for c in CATEGORIES)))
                league_id = cursor.lastrowid
                connection.execute('INSERT INTO huddle_league_members VALUES(?,?,?)',
                                   (league_id,g.member['id'],created))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return redirect(url_for('huddle_leagues.view',league_id=league_id),303)
    return render_template('huddle_leagues.html',mode='create',categories=CATEGORIES,
                           chosen=chosen,name=name,error=error),400 if error else 200


def invite_token(raw):
    raw = raw.strip()
    if TOKEN.fullmatch(raw):
        return raw
    try:
        parsed = urlsplit(raw)
    except ValueError:
        abort(400,description='Paste a valid league invitation link or code.')
    prefix = '/huddle/leagues/join/'
    if (parsed.scheme in ('https','http') and parsed.netloc and not parsed.query and not parsed.fragment
            and parsed.path.startswith(prefix) and TOKEN.fullmatch(parsed.path[len(prefix):])):
        return parsed.path[len(prefix):]
    abort(400,description='Paste a valid league invitation link or code.')


@bp.route('/join',methods=['GET','POST'])
def join_form():
    if request.method == 'POST':
        return redirect(url_for('huddle_leagues.join',token=invite_token(request.form.get('invite',''))),303)
    return render_template('huddle_leagues.html',mode='join_form',categories=CATEGORIES)


@bp.route('/join/<token>',methods=['GET','POST'])
def join(token):
    if not TOKEN.fullmatch(token):
        abort(404)
    connection = db()
    league = connection.execute('SELECT * FROM huddle_leagues WHERE invite_token=?',(token,)).fetchone()
    if league is None:
        abort(404)
    if not g.get('member'):
        session['_league_invite'] = token
        return render_template('huddle_leagues.html',mode='invite',league=league,categories=CATEGORIES)
    if request.method == 'POST':
        connection.execute('BEGIN IMMEDIATE')
        try:
            league = connection.execute('SELECT * FROM huddle_leagues WHERE invite_token=?',(token,)).fetchone()
            if league is None:
                abort(404)
            connection.execute('''INSERT INTO huddle_league_members VALUES(?,?,?)
                ON CONFLICT(league_id,member_id) DO NOTHING''',
                (league['id'],g.member['id'],now_utc().isoformat()))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        session.pop('_league_invite',None)
        return redirect(url_for('huddle_leagues.view',league_id=league['id']),303)
    return render_template('huddle_leagues.html',mode='invite',league=league,categories=CATEGORIES)


@bp.post('/<int:league_id>/invitation')
def rotate_invitation(league_id):
    league = member_league(league_id)
    if league['commissioner_id'] != g.member['id']:
        abort(403)
    with db():
        db().execute('UPDATE huddle_leagues SET invite_token=? WHERE id=?',
                     (secrets.token_urlsafe(32),league_id))
    return redirect(url_for('huddle_leagues.view',league_id=league_id),303)


@bp.get('/<int:league_id>')
def view(league_id):
    league = member_league(league_id)
    connection = db()
    connection.execute('BEGIN')  # Both standings tables see one consistent read snapshot.
    try:
        seasons = [r[0] for r in connection.execute('''SELECT DISTINCT w.season FROM pick_weeks w
            JOIN pick_games game ON game.week_id=w.id WHERE w.published_at IS NOT NULL
            AND julianday(game.lock_at)>julianday(?) ORDER BY w.season DESC''',(league['created_at'],))]
        default = seasons[0] if seasons else now_utc().year-int(now_utc().month<7)
        text = request.args.get('season',str(default))
        if not text.isdecimal() or not 2000 <= int(text) <= 2100:
            abort(400)
        season = int(text)
        if seasons and season not in seasons:
            abort(400)
        weeks = connection.execute('''SELECT w.* FROM pick_weeks w WHERE w.season=?
            AND w.published_at IS NOT NULL AND EXISTS(SELECT 1 FROM pick_games game
            WHERE game.week_id=w.id AND julianday(game.lock_at)>julianday(?))
            ORDER BY w.week DESC,w.id DESC''',(season,league['created_at'])).fetchall()
        text = request.args.get('week_id')
        if text is not None and not text.isdecimal():
            abort(400)
        selected = int(text) if text is not None else weeks[0]['id'] if weeks else None
        if selected is not None and selected not in {w['id'] for w in weeks}:
            abort(400)
        weekly = standings(connection,league,season,selected) if selected is not None else []
        season_rows = standings(connection,league,season)
    finally:
        connection.rollback()
    invite = current_app.config['PUBLIC_ORIGIN']+url_for('huddle_leagues.join',token=league['invite_token'])
    return render_template('huddle_leagues.html',mode='standings',league=league,categories=CATEGORIES,
        seasons=seasons or [season],season=season,weeks=weeks,selected=selected,weekly=weekly,
        season_rows=season_rows,invitation=invite)
