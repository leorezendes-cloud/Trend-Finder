"""Free member picks with automatically frozen common weekly lines."""
import csv
import math
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import secrets
from urllib.parse import urlsplit
from flask import Blueprint,abort,current_app,g,redirect,render_template,request,session,url_for,flash,jsonify
from membership import db

bp=Blueprint('member_picks',__name__,url_prefix='/picks')


def now_utc():return datetime.now(timezone.utc)
def number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None

def kickoff(row):
    return datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)

def schedule():
    path=Path(current_app.config['PICKS_SOURCE_ROOT'])/'nfl_games.csv'
    if not path.exists():return {}
    with path.open(newline='',encoding='utf-8-sig') as stream:
        rows=list(csv.DictReader(stream))
    ids=[row.get('game_id') for row in rows]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate game identities in saved schedule')
    return {row['game_id']:row for row in rows}


def init_picks(app):
    app.config.setdefault('PICKS_SOURCE_ROOT',app.root_path)
    app.register_blueprint(bp)
    app.jinja_env.filters['pick_time'] = lambda value: datetime.fromisoformat(value).astimezone(ZoneInfo('America/New_York')).strftime('%a %b %d, %I:%M %p ET')
    with app.app_context():
        with db():
            db().execute('''CREATE TABLE IF NOT EXISTS pick_weeks (
                id INTEGER PRIMARY KEY,season INTEGER NOT NULL,week INTEGER NOT NULL,
                stage TEXT NOT NULL DEFAULT 'REG',published_at TEXT,owner_id INTEGER NOT NULL,
                UNIQUE(season,week,stage))''')
            db().execute('''CREATE TABLE IF NOT EXISTS pick_games (
                id INTEGER PRIMARY KEY,week_id INTEGER NOT NULL,game_id TEXT NOT NULL UNIQUE,
                away TEXT NOT NULL,home TEXT NOT NULL,kickoff_at TEXT NOT NULL,lock_at TEXT NOT NULL,
                away_spread REAL,total REAL,line_source TEXT NOT NULL,
                locked INTEGER NOT NULL DEFAULT 0,void_reason TEXT,
                away_final INTEGER,home_final INTEGER,result_at TEXT)''')
            db().execute('''CREATE TABLE IF NOT EXISTS member_picks (
                member_id INTEGER NOT NULL,game_id INTEGER NOT NULL,
                su TEXT,ats TEXT,ou TEXT,su_result TEXT NOT NULL DEFAULT 'Pending',
                ats_result TEXT NOT NULL DEFAULT 'Pending',ou_result TEXT NOT NULL DEFAULT 'Pending',
                updated_at TEXT NOT NULL,PRIMARY KEY(member_id,game_id))''')

    @app.before_request
    def protect_pick_forms():
        if request.blueprint=='member_picks' and request.method=='POST':
            token=request.form.get('csrf_token','');expected=session.get('_csrf','')
            if not expected or not secrets.compare_digest(expected,token):abort(400)

    @app.before_request
    def open_automatic_week():
        if request.blueprint=='member_picks':
            from weekly_pick_lines import publish_saved_snapshot
            publish_saved_snapshot(db(),Path(current_app.config['PICKS_SOURCE_ROOT']),now_utc())

    @app.after_request
    def protect_private_picks(response):
        if request.blueprint=='member_picks' or g.get('member') and request.endpoint in ('fans.matchup','scout4.teams_page'):response.headers['Cache-Control']='no-store'
        return response


def owner():
    if not g.get('is_owner'):abort(403)

def grade(game,su,ats,ou):
    if game['void_reason']:return tuple('Void' if value else 'Pending' for value in (su,ats,ou))
    away,home=game['away_final'],game['home_final']
    if away is None or home is None:return ('Pending',)*3
    margin=away-home
    straight='Tie' if margin==0 else 'Win' if su==(game['away'] if margin>0 else game['home']) else 'Loss'
    cover=margin+game['away_spread']
    spread='Push' if abs(cover)<1e-8 else 'Win' if ats==(game['away'] if cover>0 else game['home']) else 'Loss'
    total=away+home-game['total']
    over='Push' if abs(total)<1e-8 else 'Win' if ou==('Over' if total>0 else 'Under') else 'Loss'
    return tuple(result if value else 'Pending' for result,value in zip((straight,spread,over),(su,ats,ou)))


def sync_results():
    rows=schedule();now=now_utc()
    with db():
        games=db().execute('SELECT g.* FROM pick_games g JOIN pick_weeks w ON w.id=g.week_id WHERE w.published_at IS NOT NULL').fetchall()
        for game in games:
            row=rows.get(game['game_id']);lock_at=datetime.fromisoformat(game['lock_at'])
            valid=row and row.get('away_team')==game['away'] and row.get('home_team')==game['home']
            if valid:
                try:lock_at=min(lock_at,kickoff(row))
                except (KeyError,ValueError):pass
            a,h,r=(number(row.get(key)) for key in ('away_score','home_score','result')) if valid else (None,None,None)
            final=a is not None and h is not None and r is not None and a>=0 and h>=0 and a.is_integer() and h.is_integer() and abs(r-(h-a))<1e-8
            locked=game['locked'] or now>=lock_at or bool(game['void_reason']) or final
            if lock_at.isoformat()!=game['lock_at'] or int(locked)!=game['locked']:
                db().execute('UPDATE pick_games SET lock_at=?,locked=? WHERE id=?',(lock_at.isoformat(),int(locked),game['id']))
            final_changed=False
            if valid and locked and not game['void_reason']:
                a,h,r=number(row.get('away_score')),number(row.get('home_score')),number(row.get('result'))
                if final and (game['away_final']!=int(a) or game['home_final']!=int(h)):
                    final_changed=True
                    db().execute('UPDATE pick_games SET away_final=?,home_final=?,result_at=? WHERE id=?',(int(a),int(h),now.isoformat(),game['id']))
            current=db().execute('SELECT * FROM pick_games WHERE id=?',(game['id'],)).fetchone()
            if current['away_final'] is None and not current['void_reason']:continue
            selection='SELECT * FROM member_picks WHERE game_id=?'
            if not final_changed:selection+=" AND ((su IS NOT NULL AND su_result='Pending') OR (ats IS NOT NULL AND ats_result='Pending') OR (ou IS NOT NULL AND ou_result='Pending'))"
            for pick in db().execute(selection,(game['id'],)).fetchall():
                outcomes=grade(current,pick['su'],pick['ats'],pick['ou'])
                db().execute('UPDATE member_picks SET su_result=?,ats_result=?,ou_result=? WHERE member_id=? AND game_id=?',(*outcomes,pick['member_id'],game['id']))


def comparison_picks(game_id=None,team=None,opponent=None):
    """Read or open a saved shared sheet; never captures market data."""
    if g.get('member') is None:return []
    from weekly_pick_lines import publish_saved_snapshot
    from site_week import active_week
    publish_saved_snapshot(db(),Path(current_app.config['PICKS_SOURCE_ROOT']),now_utc())
    sync_results()
    current=active_week(list(schedule().values()),now_utc())
    if current is None:return []
    games=db().execute('''SELECT g.*,p.su,p.ats,p.ou,p.su_result,p.ats_result,p.ou_result
        FROM pick_games g JOIN pick_weeks w ON w.id=g.week_id
        LEFT JOIN member_picks p ON p.game_id=g.id AND p.member_id=?
        WHERE w.published_at IS NOT NULL AND w.season=? AND w.week=? ORDER BY g.kickoff_at''',
        (g.member['id'],*current)).fetchall()
    if game_id:return [game for game in games if game['game_id']==game_id]
    return [game for game in games if team in (game['away'],game['home']) and opponent in (game['away'],game['home'])]


def write_choices(connection,game,choices):
    connection.execute('''INSERT INTO member_picks(member_id,game_id,su,ats,ou,updated_at) VALUES(?,?,?,?,?,?)
        ON CONFLICT(member_id,game_id) DO UPDATE SET su=excluded.su,ats=excluded.ats,ou=excluded.ou,updated_at=excluded.updated_at''',
        (g.member['id'],game['id'],*(value or None for value in choices),now_utc().isoformat()))


@bp.post('/save')
def save_all_picks():
    if g.member is None:
        if request.accept_mimetypes.best=='application/json':return jsonify(error='Sign in again to save your picks.'),401
        return redirect(url_for('membership.login'))
    ids=request.form.getlist('game_ids')
    if not ids or len(ids)>32 or len(ids)!=len(set(ids)) or any(not value.isdecimal() for value in ids):abort(400)
    target=request.form.get('return_to','')
    parts=urlsplit(target)
    if parts.scheme or parts.netloc or parts.fragment or parts.path not in ('/picks/','/scout4/teams') and not parts.path.startswith('/matchup/'):
        target=url_for('member_picks.my_picks')
    sync_results();connection=db();connection.execute('BEGIN IMMEDIATE');saved=locked=0
    try:
        from site_week import active_week
        current=active_week(list(schedule().values()),now_utc())
        for ident in ids:
            game=connection.execute('SELECT g.*,w.published_at,w.season,w.week FROM pick_games g JOIN pick_weeks w ON w.id=g.week_id WHERE g.id=?',(int(ident),)).fetchone()
            if game is None or not game['published_at']:abort(404)
            if current!=(game['season'],game['week']):abort(409,description='This NFL week is closed for picks.')
            choices=[]
            for key,allowed in [('su',(game['away'],game['home'])),('ats',(game['away'],game['home'])),('ou',('Over','Under'))]:
                values=request.form.getlist(f'{key}_{ident}')
                if len(values)>1 or values and values[0] not in allowed:abort(400,description='Choose one option per category.')
                choices.append(values[0] if values else '')
            if game['locked'] or game['void_reason'] or now_utc()>=datetime.fromisoformat(game['lock_at']):
                locked+=1;continue
            write_choices(connection,game,choices);saved+=1
        connection.commit()
    except Exception:
        connection.rollback();raise
    message='Picks saved. You can finish any blank selections before kickoff.' if saved else 'These games are locked; your saved picks are unchanged.'
    if saved and locked:message+=' Picks for games that have locked were kept unchanged.'
    if request.accept_mimetypes.best=='application/json':return jsonify(message=message,saved=saved,locked=locked)
    flash(message,'picks');return redirect(target)


@bp.get('/')
def my_picks():
    if g.member is None:return redirect(url_for('membership.login'))
    sync_results()
    weeks=db().execute('SELECT * FROM pick_weeks WHERE published_at IS NOT NULL ORDER BY season DESC,week DESC').fetchall()
    from site_week import active_week
    current=active_week(list(schedule().values()),now_utc())
    default=next((week['id'] for week in weeks if (week['season'],week['week'])==current),None)
    selected=request.args.get('week_id',type=int) or default
    games=db().execute('''SELECT g.*,p.su,p.ats,p.ou,p.su_result,p.ats_result,p.ou_result
        FROM pick_games g JOIN pick_weeks w ON w.id=g.week_id
        LEFT JOIN member_picks p ON p.game_id=g.id AND p.member_id=?
        WHERE g.week_id=? AND w.published_at IS NOT NULL ORDER BY g.kickoff_at,g.id''',(g.member['id'],selected)).fetchall()
    records={}
    for market in ('su','ats','ou'):
        results=db().execute(f'SELECT {market}_result result,COUNT(*) n FROM member_picks WHERE member_id=? AND {market} IS NOT NULL GROUP BY {market}_result',(g.member['id'],)).fetchall()
        records[market]={row['result']:row['n'] for row in results}
    team=request.args.get('team','');opponent=request.args.get('opponent','');target=request.args.get('game_id','')
    if target:games=[game for game in games if game['game_id']==target]
    elif team:games=[game for game in games if team in (game['away'],game['home']) and (not opponent or opponent in (game['away'],game['home']))]
    active_selected=next((week for week in weeks if week['id']==selected),None)
    week_open=bool(active_selected and (active_selected['season'],active_selected['week'])==current)
    return render_template('member_picks.html',weeks=weeks,selected=selected,games=games,records=records,current=current,week_open=week_open)


@bp.post('/games/<int:game_id>')
def save_pick(game_id):
    if g.member is None:return redirect(url_for('membership.login'))
    sync_results();connection=db();connection.execute('BEGIN IMMEDIATE')
    try:
        game=connection.execute('SELECT g.*,w.published_at,w.season,w.week FROM pick_games g JOIN pick_weeks w ON w.id=g.week_id WHERE g.id=?',(game_id,)).fetchone()
        if game is None or not game['published_at']:abort(404)
        from site_week import active_week
        if active_week(list(schedule().values()),now_utc())!=(game['season'],game['week']):abort(409,description='This week is not open for picks. Weeks change Wednesday at 8 a.m. Eastern.')
        if game['locked'] or game['void_reason'] or now_utc()>=datetime.fromisoformat(game['lock_at']):abort(409,description='Picks are locked for this game.')
        su=request.form.get('su','');ats=request.form.get('ats','');ou=request.form.get('ou','')
        if su not in ('',game['away'],game['home']) or ats not in ('',game['away'],game['home']) or ou not in ('','Over','Under'):abort(400)
        write_choices(connection,game,(su,ats,ou))
        connection.commit()
    except Exception:
        connection.rollback();raise
    return redirect(url_for('member_picks.my_picks',week_id=game['week_id']))


@bp.get('/admin')
def admin():
    owner()
    sheets=db().execute('SELECT * FROM pick_weeks ORDER BY season DESC,week DESC').fetchall()
    return render_template('pick_week_admin.html',sheets=sheets)


@bp.get('/admin/weeks/<int:week_id>')
def review_week(week_id):
    owner();sheet=db().execute('SELECT * FROM pick_weeks WHERE id=?',(week_id,)).fetchone()
    if sheet is None:abort(404)
    games=db().execute('SELECT * FROM pick_games WHERE week_id=? ORDER BY kickoff_at',(week_id,)).fetchall()
    return render_template('pick_week_review.html',sheet=sheet,games=games)


@bp.post('/admin/games/<int:game_id>/void')
def void_game(game_id):
    owner();reason=request.form.get('reason','').strip()
    if not 10<=len(reason)<=300:abort(400)
    with db():
        game=db().execute('SELECT * FROM pick_games WHERE id=?',(game_id,)).fetchone()
        if game is None:abort(404)
        if game['away_final'] is not None:abort(409)
        db().execute('UPDATE pick_games SET void_reason=?,locked=1 WHERE id=?',(reason,game_id))
    sync_results()
    return redirect(url_for('member_picks.review_week',week_id=game['week_id']))
