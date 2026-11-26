"""Bounded, standalone research database. No production imports or side effects."""
import csv
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = 'player-scheme-v1'
LIMIT = 64 * 1024 * 1024  # DB + worst-case rollback journal stay below 150 MB
ALIASES = {'LA':'LAR','STL':'LAR','SD':'LAC','OAK':'LV'}
POSITIONS = {'QB','RB','WR','TE'}
PLAYER = ('attempts','completions','passing_yards','passing_epa','carries','rushing_yards',
          'rushing_epa','targets','receptions','receiving_yards')
TEAM = ('attempts','carries','passing_yards','rushing_yards','passing_epa','rushing_epa','sacks_suffered')

def team(value):
    return ALIASES.get(value, value)

def timestamp(value):
    d = datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if d.tzinfo is None:
        raise ValueError('Timezone required')
    return d.astimezone(timezone.utc).isoformat()

def number(value):
    if value in (None, '', 'NA', 'NaN'):
        return None
    n = float(value)
    if not math.isfinite(n):
        raise ValueError('Non-finite statistic')
    return n

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(65536), b''): h.update(b)
    return h.hexdigest()

def connect(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA auto_vacuum=INCREMENTAL')
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA temp_store=FILE')
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA max_page_count=%d' % (LIMIT//4096))
    db.executescript('''
    CREATE TABLE IF NOT EXISTS sources(kind TEXT,season INTEGER,sha TEXT,url TEXT,
      captured TEXT, rows INTEGER, PRIMARY KEY(kind,season));
    CREATE TABLE IF NOT EXISTS games(gid TEXT PRIMARY KEY,season INTEGER,week INTEGER,
      kickoff TEXT,end_at TEXT,available TEXT,away TEXT,home TEXT,away_score REAL,home_score REAL);
    CREATE INDEX IF NOT EXISTS games_time ON games(kickoff);
    CREATE TABLE IF NOT EXISTS observations(kind TEXT,gid TEXT,team TEXT,opponent TEXT,
      pid TEXT,position TEXT,name TEXT,available TEXT,payload TEXT,
      PRIMARY KEY(kind,gid,team,pid),FOREIGN KEY(gid) REFERENCES games(gid));
    CREATE INDEX IF NOT EXISTS obs_game ON observations(gid,kind);
    ''')
    return db

def ingest(db, path, kind, *, season, captured_at, url):
    """One season per input; atomic validated refresh, unchanged sources do no work.

    Captured-at is caller supplied provenance, NOT evidence of original publication.
    Retrospective evaluation must explicitly opt into an assumed 48-hour delay.
    """
    if kind not in ('schedule','team','player'): raise ValueError('Unsupported source kind')
    captured=timestamp(captured_at);checksum=sha(path)
    prior=db.execute('SELECT sha FROM sources WHERE kind=? AND season=?',(kind,season)).fetchone()
    if prior and prior[0]==checksum:return {'unchanged':True,'sha256':checksum}
    count=0;seen=set();previous={}
    if kind!='schedule':
        previous={(r[0],r[1],r[2]):(r[3],r[4],r[5],r[6],r[7]) for r in db.execute(
            'SELECT gid,team,pid,opponent,position,name,available,payload FROM observations WHERE kind=? AND gid IN (SELECT gid FROM games WHERE season=?)',(kind,season))}
    with db:
        if kind!='schedule':
            db.execute('DELETE FROM observations WHERE kind=? AND gid IN (SELECT gid FROM games WHERE season=?)',(kind,season))
        with Path(path).open(newline='') as f:
            reader=csv.DictReader(f)
            required={'game_id','season','week'} | ({'gameday','gametime','away_team','home_team','away_score','home_score','game_type'} if kind=='schedule' else {'team','opponent_team','season_type'} | ({'player_id','position'} if kind=='player' else set())) | (set(PLAYER) if kind=='player' else set(TEAM) if kind=='team' else set())
            if not required<=set(reader.fieldnames or []):raise ValueError('Missing required columns: '+str(required-set(reader.fieldnames or [])))
            for row in reader:
                if int(row['season'])!=season:continue
                if row.get('game_type',row.get('season_type'))!='REG':continue
                gid=row['game_id'];week=int(row['week'])
                if not 1<=week<=18 or not gid.startswith(str(season)+'_'):raise ValueError('Invalid game identity/week')
                if kind=='schedule':
                    # No unknown-time guesses. Finals only; future schedules are separate prediction inputs.
                    if not row['gametime'] or row['away_score']=='' or row['home_score']=='':continue
                    from zoneinfo import ZoneInfo
                    start=datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
                    a,h=number(row['away_score']),number(row['home_score'])
                    if min(a,h)<0 or int(a)!=a or int(h)!=h:raise ValueError('Invalid final score')
                    away,home=team(row['away_team']),team(row['home_team'])
                    if gid!=f'{season}_{week:02}_{row["away_team"]}_{row["home_team"]}':raise ValueError('Schedule identity mismatch')
                    if gid in seen:raise ValueError('Duplicate game')
                    seen.add(gid)
                    # Conservative event-end proxy; never used as actual publication timestamp.
                    db.execute('INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(gid) DO UPDATE SET kickoff=excluded.kickoff,end_at=excluded.end_at,available=CASE WHEN games.kickoff=excluded.kickoff AND games.away_score=excluded.away_score AND games.home_score=excluded.home_score THEN games.available ELSE excluded.available END,away_score=excluded.away_score,home_score=excluded.home_score',
                        (gid,season,week,start.isoformat(),(start+timedelta(hours=6)).isoformat(),captured,away,home,a,h))
                else:
                    g=db.execute('SELECT season,week,away,home FROM games WHERE gid=?',(gid,)).fetchone()
                    if g is None:continue  # incomplete/unknown-time schedule, counted below by source inventory
                    t,o=team(row['team']),team(row['opponent_team'])
                    if g[:2]!=(season,week) or {t,o}!={g[2],g[3]}:raise ValueError('Team/opponent schedule mismatch')
                    pid=row.get('player_id','');pos=row.get('position','')
                    if kind=='player' and pos not in POSITIONS:continue
                    if kind=='player' and (not pid or not pid.startswith('00-')):raise ValueError('GSIS player ID required; names never joined')
                    key=(gid,t,pid)
                    if key in seen:raise ValueError('Duplicate observation identity')
                    seen.add(key)
                    if len(seen)>20000:raise ValueError('Season observation limit exceeded')
                    values={k:number(row.get(k)) for k in (PLAYER if kind=='player' else TEAM)}
                    for k in ('attempts','completions','carries','targets','receptions','sacks_suffered'):
                        v=values.get(k)
                        if v is not None and (v<0 or int(v)!=v):raise ValueError('Invalid count '+k)
                    if kind=='player':
                        for a,b in [('completions','attempts'),('receptions','targets')]:
                            if values[a] is not None and values[b] is not None and values[a]>values[b]:raise ValueError('Impossible count relationship')
                    payload=json.dumps(values,separators=(',',':'));name=row.get('player_display_name','')
                    old=previous.get(key);available=old[3] if old and (old[0],old[1],old[2],old[4])==(o,pos,name,payload) else captured
                    db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)',(kind,gid,t,o,pid,pos,name,available,payload))
                count+=1
        if not count:raise ValueError('Empty eligible source')
        db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)',(kind,season,checksum,url,captured,count))
    return {'unchanged':False,'rows':count,'sha256':checksum}

def history(db, cutoff, *, mode='observed', days=180, kinds=None):
    """No same-game or future facts. Two explicit availability policies."""
    if mode not in ('observed','retrospective'):raise ValueError('Unknown cutoff mode')
    at=datetime.fromisoformat(timestamp(cutoff));low=(at-timedelta(days=days)).isoformat()
    sql='''SELECT o.kind,o.gid,o.team,o.opponent,o.pid,o.position,o.name,o.payload,g.kickoff,
         g.end_at,g.available,o.available,g.away,g.home,g.away_score,g.home_score
         FROM observations o JOIN games g ON g.gid=o.gid
         WHERE g.kickoff>=? AND g.kickoff<?'''
    parameters=[low,at.isoformat()]
    if kinds:
        sql+=' AND o.kind IN ('+','.join('?' for _ in kinds)+')';parameters.extend(kinds)
    sql+=' ORDER BY g.kickoff,o.gid,o.team,o.pid'
    for r in db.execute(sql,parameters):
        # Assumed 48h publication delay after conservative six-hour game end.
        event_ready=datetime.fromisoformat(r[9])+timedelta(hours=48)
        observed=max(datetime.fromisoformat(r[10]),datetime.fromisoformat(r[11]))
        if max(event_ready,observed if mode=='observed' else event_ready)>=at:continue
        yield dict(kind=r[0],gid=r[1],team=r[2],opponent=r[3],pid=r[4],position=r[5],name=r[6],
                   values=json.loads(r[7]),kickoff=r[8],points=r[14] if r[2]==r[12] else r[15],
                   allowed=r[15] if r[2]==r[12] else r[14])

def maintain(db, *, keep_seasons=8):
    """Explicit research-store retention only; never touches repository/production archives."""
    if keep_seasons<3:raise ValueError('Keep at least three seasons')
    seasons=[r[0] for r in db.execute('SELECT DISTINCT season FROM games ORDER BY season DESC')]
    stale=seasons[keep_seasons:]
    with db:
        for y in stale:
            db.execute('DELETE FROM observations WHERE gid IN (SELECT gid FROM games WHERE season=?)',(y,))
            db.execute('DELETE FROM games WHERE season=?',(y,));db.execute('DELETE FROM sources WHERE season=?',(y,))
    db.execute('PRAGMA incremental_vacuum')
    return {'removed_research_seasons':stale}
