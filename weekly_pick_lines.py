"""Immutable shared lines from the Wednesday market snapshot; no model work."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from market_views import market_games, read, stamp
from site_week import active_week, week_window

SOURCE=Path(__file__).resolve().parent


def snapshot_path(root, season, week):
    return Path(root)/'data/member_lines'/f'{season}_{week:02d}.json'


def freeze_snapshot(root, now=None, *, exception=False):
    now=now or datetime.now(timezone.utc)
    current=active_week(read(Path(root)/'nfl_games.csv'),now)
    if current is None:return {'state':'pending','reason':'No active regular-season NFL week'}
    path=snapshot_path(root,*current)
    if path.exists():return json.loads(path.read_text())
    cutoff=week_window(now)[0].astimezone(timezone.utc)
    # A capture started at 8 a.m. needs a little time to return. After that window,
    # catch-up may only use evidence observed on or before the scheduled cutoff.
    live_window=cutoff<=now<cutoff+timedelta(minutes=10)
    as_of=now if exception or live_window else cutoff
    games=market_games(root,now,quote_cutoff=as_of)
    missing=[game['game_id'] for game in games if any(
        game[key] is None or game[key+'_quote'] is None or
        not 0<= (as_of-stamp(game[key+'_time'])).total_seconds() <=24*3600
        or (live_window and not exception and stamp(game[key+'_time'])<cutoff)
        for key in ('spread','total'))]
    if not games or missing:
        return {'state':'pending','reason':'Fresh verified spreads and totals are required for every unstarted game','missing':missing}
    report={'state':'ready','season':current[0],'week':current[1],'scheduled_cutoff':cutoff.isoformat(),
            'frozen_at':now.isoformat(),'exception':exception,'games':games}
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(path)
    return report


def available_snapshot(root,now):
    current=active_week(read(Path(root)/'nfl_games.csv'),now)
    if current is None:return None
    path=snapshot_path(root,*current)
    if path.exists():return json.loads(path.read_text())
    exception=SOURCE/'member_lines_exception.json'
    if exception.exists():
        report=json.loads(exception.read_text())
        if (report.get('season'),report.get('week'))==current and stamp(report['frozen_at'])<=now:
            return report
    return None


def publish_saved_snapshot(connection,root,now):
    report=available_snapshot(root,now)
    if not report or report.get('state')!='ready':return False
    season,week=report['season'],report['week']
    current=connection.execute('SELECT * FROM pick_weeks WHERE season=? AND week=? AND stage="REG"',(season,week)).fetchone()
    if current and current['published_at']:return True
    schedule={r['game_id']:r for r in read(Path(root)/'nfl_games.csv')}
    candidates=[]
    for game in report['games']:
        row=schedule.get(game['game_id'])
        if not row or any(row.get(key)!=game.get(key) for key in ('away_team','home_team','season','week')):return False
        from member_picks import kickoff,number
        ko=kickoff(row)
        if ko<=now or row.get('away_score') or row.get('home_score'):continue
        if ko!=stamp(game['kickoff_utc']):return False
        spread,total=number(game.get('spread')),number(game.get('total'))
        if spread is None or total is None or abs(spread)>60 or not 1<=total<=150 or spread*2!=int(spread*2) or total*2!=int(total*2):return False
        label=('This week’s exception' if report['exception'] else 'Wednesday 8 a.m. ET snapshot')
        def friendly(value):return stamp(value).astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %I:%M %p ET')
        source=f"{label}; frozen {friendly(report['frozen_at'])}; spread observed {friendly(game['spread_time'])}; total observed {friendly(game['total_time'])}"
        candidates.append((game,ko,spread,total,source))
    if not candidates:return False
    connection.execute('BEGIN IMMEDIATE')
    try:
        current=connection.execute('SELECT * FROM pick_weeks WHERE season=? AND week=? AND stage="REG"',(season,week)).fetchone()
        if current and current['published_at']:
            connection.rollback();return True
        owner=connection.execute('SELECT member_id FROM site_owners ORDER BY member_id LIMIT 1').fetchone()
        connection.execute('INSERT OR IGNORE INTO pick_weeks(season,week,owner_id) VALUES(?,?,?)',(season,week,owner[0] if owner else 0))
        sheet=connection.execute('SELECT id FROM pick_weeks WHERE season=? AND week=? AND stage="REG"',(season,week)).fetchone()[0]
        # Replace only an unpublished legacy draft, never a published member sheet.
        connection.execute('DELETE FROM pick_games WHERE week_id=?',(sheet,))
        for game,ko,spread,total,source in candidates:
            connection.execute('INSERT INTO pick_games(week_id,game_id,away,home,kickoff_at,lock_at,away_spread,total,line_source) VALUES(?,?,?,?,?,?,?,?,?)',
                (sheet,game['game_id'],game['away_team'],game['home_team'],ko.isoformat(),ko.isoformat(),spread,total,source))
        connection.execute('UPDATE pick_weeks SET published_at=? WHERE id=?',(now.isoformat(),sheet))
        connection.commit()
    except Exception:
        connection.rollback();raise
    return True


def scheduled_capture(root):
    """Invoked by the hosted scheduler only, never by a page visit."""
    import fcntl
    root=Path(root);logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/'auto_update.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 75
        now=datetime.now(timezone.utc)
        report=available_snapshot(root,now)
        if report:
            path=snapshot_path(root,report['season'],report['week'])
            if not path.exists():
                path.parent.mkdir(parents=True,exist_ok=True)
                temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(path)
        else:
            start=week_window(now)[0].astimezone(timezone.utc)
            if start<=now<start+timedelta(minutes=10):
                from scheduled_ats_capture import run
                if run(root)!=0:raise RuntimeError('Wednesday market capture failed')
            report=freeze_snapshot(root,datetime.now(timezone.utc))
        # Report "ready" only after publication was confirmed. An interrupted
        # publication must not leave a success marker that suppresses retries.
        if report['state']=='ready':
            from app import app
            from membership import db
            with app.app_context():
                if not publish_saved_snapshot(db(),root,datetime.now(timezone.utc)):
                    raise RuntimeError('Verified weekly snapshot could not be published')
        from scheduler_runtime import atomic_json
        status = (report if report['state']=='pending' else
                  {**{k:report[k] for k in ('state','season','week','scheduled_cutoff','frozen_at')},
                   'published':True})
        atomic_json(logs/'weekly_lines_status.json', status)


if __name__=='__main__':
    if os.environ.get('TREND_FINDAH_AUTO_UPDATE')!='1' or os.environ.get('TREND_FINDAH_ENV')!='production':
        raise SystemExit('Weekly capture is enabled only in hosted production')
    raise SystemExit(scheduled_capture(Path('/var/data/site-data')) or 0)
