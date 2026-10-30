"""Owner-only recovered NFL totals ledger, separate from Scout and The Plug.

Run python recovered_nfl_tracker.py --root /path/to/site-data for offline capture.
Only pregame, timestamp-verified lines and sourced expected-QB reports can seal
live picks. Postgame QB verification never manufactures a pregame QB pick.
"""
import argparse
import csv
import json
import math
import sqlite3
from collections import Counter
from contextlib import contextmanager,closing
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import Blueprint,abort,current_app,g,render_template
from research_qbs import research_rows
from recovered_totals_rules import calculate

ROOT=Path(__file__).resolve().parent
ET=ZoneInfo('America/New_York')
bp=Blueprint('recovered_nfl',__name__)
VERSION='recovered-nfl-qb-v1'


@bp.app_context_processor
def tracker_navigation():
    return dict(recovered_nfl_enabled=True)


def stamp(value):
    try:
        value=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (TypeError,ValueError):return None


def kickoff(game):
    try:return datetime.fromisoformat(game['gameday']+'T'+game['gametime']).replace(tzinfo=ET).astimezone(timezone.utc)
    except (KeyError,ValueError,TypeError):return None


def read_csv(path):
    if not path.exists():return []
    with path.open(newline='',encoding='utf-8-sig') as stream:return list(csv.DictReader(stream))


def final(game,now):
    ko=kickoff(game)
    if not ko or ko>=now:return None
    try:
        a,h=(float(game[k]) for k in ('away_score','home_score'))
        if not all(math.isfinite(v) and v>=0 and v.is_integer() for v in (a,h)):return None
        # Future/scheduled rows sometimes carry 0-0 placeholders.
        if a==h==0:return None
        if game.get('result') not in ('',None) and float(game['result'])!=h-a:return None
        return int(a+h)
    except (KeyError,TypeError,ValueError):return None


def line_for(game,quotes,now):
    ko=kickoff(game);found=[]
    for row in quotes:
        if row.get('game_id')!=game['game_id'] or row.get('market')!='Total':continue
        observed=stamp(row.get('captured_at_utc'))
        if not observed or not observed<=now<ko or now-observed>timedelta(hours=6) or stamp(row.get('kickoff_utc'))!=ko:continue
        if (row.get('away_team'),row.get('home_team'),row.get('side_a'),row.get('side_b'))!=(game['away_team'],game['home_team'],'Over','Under'):continue
        try:
            a,b=float(row['line_a']),float(row['line_b'])
            if not math.isfinite(a) or a<=0 or a!=b:continue
        except (KeyError,ValueError,TypeError):continue
        if not row.get('source_url','').startswith('https://') or not row.get('sportsbook'):continue
        found.append(row)
    return max(found,key=lambda r:stamp(r['captured_at_utc'])) if found else None


def forecast(game,games,quotes,now):
    ko=kickoff(game)
    pending=dict(game_id=game['game_id'],away=game['away_team'],home=game['home_team'],season=game['season'],week=game['week'],kickoff_utc=ko.isoformat() if ko else None,state='pending')
    if not ko or not now<ko or game.get('location')!='Home':return dict(pending,reason='No eligible upcoming home/away matchup.')
    prior=[r for r in games if r['season']==game['season'] and r['game_type']=='REG' and r['gameday']<now.astimezone(ET).date().isoformat() and final(r,now) is not None]
    groups=[[],[],[],[],[]];previous={}
    for r in sorted(prior,key=lambda r:(r['gameday'],r['game_id'])):
        total=Decimal(r['away_score'])+Decimal(r['home_score']);groups[4].append(total)
        for side,i in (('away',0),('home',1)):
            team=game[side+'_team'];old='away' if r['away_team']==team else 'home' if r['home_team']==team else None
            if old:
                groups[i].append(total);previous[side]=dict(name=r.get(old+'_qb_name',''),game_id=r['game_id'])
                if r['location']=='Home' and old==side:groups[i+2].append(total)
    if any(not values for values in groups):return dict(pending,reason='Waiting for prior season and away/home split finals.')
    values=dict(zip(('away_season','home_season','away_split','home_split','league_total'),(str(sum(v)/len(v)) for v in groups)))
    quote=line_for(game,quotes,now)
    if not quote:return dict(pending,reason='Waiting for a verified market total captured within six hours.')
    values['market_total']=quote['line_a']
    return dict(pending,state='ready',version=VERSION,inputs=values,result=calculate(values),previous_qbs=previous,counts=list(map(len,groups)),quote=quote)


def qb_decision(payload,game,reports,id_names,now):
    result=payload['result'];pick=result['selection']['pick'];category=result['selection']['rule']
    if not pick:return None,'Undecided category',{}
    if category not in ('A','B','D','H'):return pick,'No QB flip in this category',{}
    ko=kickoff(game);observations={};same=0
    for side in ('away','home'):
        prev=payload['previous_qbs'].get(side,{}).get('name','')
        r=reports.get((game['game_id'],game[side+'_team']))
        if not r or not prev:continue
        at=stamp(r.get('observed_at'));published=stamp(r.get('published_at'))
        if (not at or not published or not published<=at<=now<ko or now-at>timedelta(hours=24)
                or stamp(r.get('kickoff_utc'))!=ko or not r.get('source_url','').startswith('https://')):continue
        names=id_names.get(r.get('expected_qb_id'),set())
        if len(names)!=1:continue
        name=next(iter(names));observations[side]=dict(name=name,source=r['source_url'],observed_at=r['observed_at'],status='Sourced expected starter; not independently confirmed')
        if name.casefold()!=prev.casefold():
            return ('Under' if pick=='Over' else 'Over'),'QB-change flip from sourced expected-starter report',observations
        same+=1
    if same==2:return pick,'Both expected starters match previous games',observations
    return None,'Waiting for sourced pregame starter reports',observations


@contextmanager
def connect(root):
    folder=Path(root)/'data/recovered_totals';folder.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(folder/'tracker.sqlite3',timeout=15)
    db.execute('CREATE TABLE IF NOT EXISTS forecasts (game_id TEXT PRIMARY KEY,saved_at TEXT NOT NULL,payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS qb_picks (game_id TEXT PRIMARY KEY,saved_at TEXT NOT NULL,pick TEXT NOT NULL,evidence TEXT NOT NULL)')
    try:
        with db:yield db
    finally:db.close()


def sources(root,now=None):
    now=now or datetime.now(timezone.utc);names={};raw=[]
    # This tracker started in 2026. Stream older seasons solely for the small
    # GSIS/name lookup; never materialize the full historical schedule or quotes.
    with (root/'nfl_games.csv').open(newline='',encoding='utf-8-sig') as stream:
        for r in csv.DictReader(stream):
            for side in ('away','home'):
                if r.get(side+'_qb_id') and r.get(side+'_qb_name'):names.setdefault(r[side+'_qb_id'],set()).add(r[side+'_qb_name'].strip())
            if r.get('season','')>='2026':raw.append(r)
    games=research_rows(raw,root/'nfl_games.csv')
    upcoming={r['game_id'] for r in games if (ko:=kickoff(r)) and now<ko<=now+timedelta(days=8)}
    quotes=[];path=root/'public_money_snapshots.csv'
    if path.exists():
        with path.open(newline='',encoding='utf-8-sig') as stream:
            for r in csv.DictReader(stream):
                if r.get('game_id') in upcoming and r.get('market')=='Total':
                    at=stamp(r.get('captured_at_utc'))
                    if at and now-timedelta(hours=6)<=at<=now:quotes.append(r)
    reports={}
    for path in (root/'data/scout4/starter_reports').glob('*.json'):
        try:
            r=json.loads(path.read_text());key=(r['game_id'],r['team']);at=stamp(r['observed_at'])
            if at and (key not in reports or at>stamp(reports[key]['observed_at'])):reports[key]=r
        except (ValueError,KeyError,TypeError):continue
    return games,quotes,reports,names


def capture(root=ROOT,now=None):
    root=Path(root);injected=now;now=now or datetime.now(timezone.utc)
    games,quotes,reports,names=sources(root,now);inserted=0
    with connect(root) as db:
        db.execute('BEGIN IMMEDIATE')
        # Recheck real time after acquiring the writer lock; injected clocks are
        # reserved for deterministic offline tests.
        current=injected or datetime.now(timezone.utc)
        for game in games:
            current=injected or datetime.now(timezone.utc)
            ko=kickoff(game)
            if game.get('game_type')!='REG' or not ko or not current<ko<=current+timedelta(days=8):continue
            saved=db.execute('SELECT payload FROM forecasts WHERE game_id=?',(game['game_id'],)).fetchone()
            payload=json.loads(saved[0]) if saved else forecast(game,games,quotes,current)
            if payload['state']!='ready':continue
            if payload['kickoff_utc']!=ko.isoformat():continue
            current=injected or datetime.now(timezone.utc)
            if current>=ko:continue
            if not saved:
                db.execute('INSERT OR IGNORE INTO forecasts VALUES(?,?,?)',(game['game_id'],current.isoformat(),json.dumps(payload)));inserted+=1
            pick,reason,evidence=qb_decision(payload,game,reports,names,current)
            if pick:db.execute('INSERT OR IGNORE INTO qb_picks VALUES(?,?,?,?)',(game['game_id'],current.isoformat(),pick,json.dumps(dict(reason=reason,reports=evidence))))
    return inserted


def grade(pick,line,actual):
    if not pick:return 'Awaiting QB' if actual is None else 'No pregame QB pick'
    if actual is None:return 'Pending'
    gap=Decimal(str(actual))-Decimal(str(line))
    if not gap:return 'Push'
    return 'Win' if (gap>0)==(pick=='Over') else 'Loss'


def view(root=ROOT,now=None):
    root=Path(root);now=now or datetime.now(timezone.utc)
    games,quotes,reports,names=sources(root,now);index={r['game_id']:r for r in games};rows=[]
    path=root/'data/recovered_totals/tracker.sqlite3';saved={};qb={}
    if path.exists():
        with closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as db:
            saved={r[0]:(r[1],json.loads(r[2])) for r in db.execute('SELECT * FROM forecasts')}
            qb={r[0]:dict(saved_at=r[1],pick=r[2],evidence=json.loads(r[3])) for r in db.execute('SELECT * FROM qb_picks')}
    for game in games:
        ko=kickoff(game);stored=saved.get(game['game_id'])
        if not stored and (game.get('game_type')!='REG' or not ko or not now<ko<=now+timedelta(days=8)):continue
        if stored:payload=stored[1]
        else:payload=forecast(game,games,quotes,now)
        row=dict(payload,saved_at=stored[0] if stored else None,locked=bool(stored),qb_record=qb.get(game['game_id']))
        actual=final(game,now)
        if stored and (not ko or payload['kickoff_utc']!=ko.isoformat()
                       or payload['away']!=game['away_team'] or payload['home']!=game['home_team']):
            actual=None;row['review']='Schedule identity changed; grading paused'
        row['actual_total']=actual
        row['original_grade']=grade(payload.get('result',{}).get('selection',{}).get('pick'),payload.get('result',{}).get('market_total',0),actual) if stored else 'Preview'
        row['qb_grade']=grade(row['qb_record']['pick'] if row['qb_record'] else None,payload.get('result',{}).get('market_total',0),actual) if stored else 'Preview'
        if stored and not payload['result']['selection']['pick']:row['original_grade']=row['qb_grade']='Undecided'
        row['qb_sensitive']=payload.get('result',{}).get('selection',{}).get('rule') in ('A','B','D','H')
        rows.append(row)
    rows.sort(key=lambda r:(r.get('kickoff_utc') or '',r['game_id']),reverse=False)
    summary={key:Counter(r[field] for r in rows if r['locked']) for key,field in [('original','original_grade'),('qb','qb_grade')]}
    categories={letter:{key:Counter(r[field] for r in rows if r['locked'] and r.get('result',{}).get('selection',{}).get('rule')==letter) for key,field in [('original','original_grade'),('qb','qb_grade')]} for letter in 'ABCDEFGHIJKL'}
    return dict(rows=rows,summary=summary,categories=categories,now=now.isoformat())


@bp.get('/research/recovered-totals')
def dashboard():
    if not getattr(g,'is_owner',False):abort(403)
    root=Path(current_app.config.get('PICKS_SOURCE_ROOT',ROOT))
    response=current_app.make_response(render_template('recovered_nfl_tracker.html',view=view(root)))
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Robots-Tag']='noindex, nofollow'
    return response


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args()
    print('Recovered NFL forecasts captured:',capture(args.root))
