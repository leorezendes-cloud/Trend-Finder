"""Seal first eligible pre-kickoff ATS/totals research forecasts and grade separately.

Run .venv/bin/python -m scout4.shadow. Reads existing quote/statistics caches;
never fetches on page load, substitutes later lines, or alters frozen records.
"""
import argparse
import csv
import hashlib
import json
import math
import re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .web import ROOT
from .stats import read_csv,number
from .ratings import build_ratings
from .margin_lab import difference
from .ats_lab import predict as ats_predict
from .totals import profiles,features as total_features,predict as totals_predict

ATS_RELATIVE='data/scout4/multiseason_runs/20261013T041621206406Z/frozen_research_candidate_2026.json'
CORE=('scout4/shadow.py','scout4/ats_lab.py','scout4/ratings.py','scout4/margin_lab.py','scout4/stats.py','scout4/totals.py')
MAX_QUOTE_AGE=timedelta(hours=6)
MAX_STATS_AGE=timedelta(hours=24)


def aware(value):
    try:dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (ValueError,TypeError):raise ValueError('Invalid timestamp')
    if dt.tzinfo is None:raise ValueError('Timestamp requires timezone')
    return dt.astimezone(timezone.utc)


def kickoff(game):
    if not game.get('gameday') or not game.get('gametime'):raise ValueError('Missing scheduled kickoff')
    return datetime.fromisoformat(game['gameday']+'T'+game['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)


def american(value):
    odds=number(value)
    return odds if odds is not None and abs(odds)>=100 else None


def quote(rows,game,market,now):
    valid=[];ko=kickoff(game)
    for r in rows:
        if r.get('game_id')!=game['game_id'] or r.get('market')!=market:continue
        try:captured=aware(r['captured_at_utc']);qko=aware(r['kickoff_utc'])
        except (KeyError,ValueError):continue
        if not captured<=now<ko or now-captured>MAX_QUOTE_AGE or qko!=ko:continue
        if r.get('away_team')!=game['away_team'] or r.get('home_team')!=game['home_team']:continue
        if not r.get('sportsbook') or not r.get('source_url'):continue
        a,b=number(r.get('line_a')),number(r.get('line_b'))
        oa,ob=american(r.get('odds_a')),american(r.get('odds_b'))
        if a is None or b is None or oa is None or ob is None:continue
        if market=='Spread':
            if {r.get('side_a'),r.get('side_b')}!={game['away_team'],game['home_team']} or abs(a+b)>1e-9:continue
            line=a if r['side_a']==game['away_team'] else b
            odds={'away':oa if r['side_a']==game['away_team'] else ob,'home':ob if r['side_b']==game['home_team'] else oa}
        elif market=='Total':
            if {r.get('side_a'),r.get('side_b')}!={'Over','Under'} or abs(a-b)>1e-9 or a<=0:continue
            line=a;odds={'Over':oa if r['side_a']=='Over' else ob,'Under':ob if r['side_b']=='Under' else oa}
        else:continue
        valid.append({'line':line,'odds':odds,'sportsbook':r['sportsbook'],'source_url':r['source_url'],
                      'captured_at_utc':captured.isoformat(),'source_update_time':'Unavailable',
                      'kickoff_utc':ko.isoformat(),'market':market})
    return max(valid,key=lambda r:r['captured_at_utc']) if valid else None


def statistics_gate(schedule,feed,manifest,year,week,now):
    try:retrieved=aware(manifest['retrieved_at'])
    except (KeyError,ValueError):return 'Statistics retrieval time is unverified'
    if retrieved>now:return 'Statistics were retrieved after the decision cutoff'
    if now-retrieved>MAX_STATS_AGE:return 'Statistics cache is older than 24 hours'
    expected=[g for g in schedule if g['season']==str(year) and g['game_type']=='REG' and int(g['week'])<week]
    if any(number(g.get('away_score')) is None or number(g.get('home_score')) is None for g in expected):
        return 'An earlier week still has incomplete results'
    lookup={}
    for r in feed:
        if r.get('season_type')=='REG' and str(r.get('season'))==str(year) and int(r['week'])<week:
            key=(r['game_id'],r['team'])
            if key in lookup:return 'Duplicate earlier team-stat observation'
            lookup[key]=r
    required=('passing_epa','rushing_epa','attempts','carries','sacks_suffered')
    for g in expected:
        for side,other in [('away','home'),('home','away')]:
            r=lookup.get((g['game_id'],g[side+'_team']))
            if r is None:return 'Earlier team statistics are incomplete'
            if int(r['week'])!=int(g['week']) or r.get('opponent_team')!=g[other+'_team']:
                return 'Earlier statistics do not match schedule identity'
            if any(number(r.get(c)) is None for c in required):return 'Earlier EPA/play-volume inputs are incomplete'
            if any(number(r[c])<0 or not number(r[c]).is_integer() for c in ('attempts','carries','sacks_suffered')):
                return 'Earlier play-volume counts are invalid'
    return None


def load_stats(root,year):
    base=root/'data/scout4';manifest=json.loads((base/str(year)/'latest.json').read_text())
    info=manifest['files']['team'];path=(base/info['path']).resolve()
    if not path.is_relative_to(base.resolve()):raise ValueError('Invalid statistics cache path')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('Statistics cache fingerprint mismatch')
    return read_csv(path),manifest


def seal(path,record,clock=None):
    """First eligible snapshot wins; later runs cannot rewrite it."""
    if path.exists():return False
    clock=clock or (lambda:datetime.now(timezone.utc))
    stamp=clock()
    if stamp.tzinfo is None or stamp>=aware(record['kickoff_utc']):raise ValueError('Kickoff reached before forecast sealing')
    if stamp<aware(record['decision_cutoff_utc']):raise ValueError('Seal clock precedes decision cutoff')
    record={**record,'sealed_at_utc':stamp.astimezone(timezone.utc).isoformat(),'status':'SEALED_PREKICKOFF_RESEARCH'}
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with path.open('x') as f:json.dump(record,f,indent=2)
    except FileExistsError:return False
    return True


def grade(record,game):
    if game.get('game_id')!=record['game_id'] or game.get('away_team')!=record['away_team'] or game.get('home_team')!=record['home_team']:
        raise ValueError('Outcome identity mismatch')
    a,h=number(game.get('away_score')),number(game.get('home_score'))
    if a is None or h is None:return 'Pending'
    # Always use the frozen line, never today's line or closing replacement.
    if record['market']=='Spread':
        margin=a-h+record['quote']['line']
        winner=game['away_team'] if margin>0 else game['home_team']
    else:
        margin=a+h-record['quote']['line'];winner='Over' if margin>0 else 'Under'
    if abs(margin)<1e-9:return 'Push'
    if record['selected_side'] is None:return 'No Call'
    return 'Correct' if record['selected_side']==winner else 'Wrong'


def view(root=ROOT):
    base=root/'data/scout4/shadow';games={g['game_id']:g for g in read_csv(root/'nfl_games.csv')}
    records=[]
    for path in sorted((base/'predictions').glob('*.json')):
        r=json.loads(path.read_text())
        try:r['result']=grade(r,games[r['game_id']]) if r['game_id'] in games else 'Pending'
        except ValueError:r['result']='Review needed'
        r['file_path']=str(path);records.append(r)
    status=json.loads((base/'status.json').read_text()) if (base/'status.json').exists() else {'pending':[]}
    return {'records':records,'status':status}


def run(root=ROOT,now=None,seal_clock=None):
    root=Path(root);now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Decision cutoff requires timezone')
    now=now.astimezone(timezone.utc);base=root/'data/scout4/shadow';base.mkdir(parents=True,exist_ok=True)
    ats_path=root/ATS_RELATIVE
    totals_paths=sorted((root/'data/scout4/totals_runs').glob('*/frozen_totals_candidate_2026.json'))
    if not totals_paths:raise ValueError('No frozen totals research candidate')
    config_path=base/'config.json'
    if config_path.exists():
        config=json.loads(config_path.read_text());ats_path=root/config['ats_path'];totals_path=root/config['totals_path']
    else:
        totals_path=totals_paths[-1]
        config={'created_at':now.isoformat(),'policy':'First eligible valid snapshot per game/market/model; no overwrite',
                'ats_path':str(ats_path.relative_to(root)),'totals_path':str(totals_path.relative_to(root)),
                'ats_sha256':hashlib.sha256(ats_path.read_bytes()).hexdigest(),'totals_sha256':hashlib.sha256(totals_path.read_bytes()).hexdigest(),
                'pipeline_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in CORE}}
        with config_path.open('x') as f:json.dump(config,f,indent=2)
    for p,h in config['pipeline_sha256'].items():
        if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h:raise ValueError('Frozen shadow pipeline changed; create a separately validated version')
    for path,key in [(ats_path,'ats_sha256'),(totals_path,'totals_sha256')]:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=config[key]:raise ValueError('Frozen research model changed')
    ats=json.loads(ats_path.read_text());totals=json.loads(totals_path.read_text())
    # Check the forecast-generating algorithms against their frozen candidate versions.
    for candidate in (ats,totals):
        for p,h in candidate['code_sha256'].items():
            if p in CORE and hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h:
                raise ValueError('Candidate feature/model algorithm changed since freezing')
    stamp=now.strftime('%Y%m%dT%H%M%S%fZ');input_dir=base/'inputs'/stamp;input_dir.mkdir(parents=True,exist_ok=False)
    for name in ('nfl_games.csv','public_money_snapshots.csv'):
        (input_dir/name).write_bytes((root/name).read_bytes())
    schedule=read_csv(input_dir/'nfl_games.csv');quotes=read_csv(input_dir/'public_money_snapshots.csv')
    upcoming=[]
    for g in schedule:
        if g['game_type']!='REG' or g['season']!='2026' or int(g['week'])<6 or g['away_score'] or g['home_score']:continue
        if not re.fullmatch(r'2026_[0-9]{2}_[A-Z]{2,3}_[A-Z]{2,3}',g['game_id']) or g['game_id']!=f"2026_{int(g['week']):02}_{g['away_team']}_{g['home_team']}":
            continue
        try:ko=kickoff(g)
        except ValueError:continue
        if now<ko<=now+timedelta(days=7):upcoming.append(g)
    status={'checked_at_utc':now.isoformat(),'saved':0,'preserved':0,'pending':[],'upcoming_games':len(upcoming)}
    feeds={};ratings={};total_profiles={}
    for g in upcoming:
        year,week=int(g['season']),int(g['week'])
        try:
            if year not in feeds:feeds[year]=load_stats(root,year)
            feed,manifest=feeds[year]
            block=statistics_gate(schedule,feed,manifest,year,week,now)
        except (OSError,ValueError,KeyError) as exc:block=f'Statistics unavailable: {exc}'
        if block:
            status['pending'].append({'game_id':g['game_id'],'market':'Both','reason':block});continue
        if week not in ratings:ratings[week]=build_ratings(schedule,feed,year,week)[0]
        if week not in total_profiles:total_profiles[week]=profiles(schedule,feed,year,week)
        for market,candidate,hashkey in [('Spread',ats,'ats_sha256'),('Total',totals,'totals_sha256')]:
            if int(candidate['target_season'])!=year or week<int(candidate['first_eligible_week']):continue
            model_hash=config[hashkey];path=base/'predictions'/f"{g['game_id']}__{market}__{model_hash[:12]}.json"
            if path.exists():status['preserved']+=1;continue
            q=quote(quotes,g,market,now)
            if q is None:
                status['pending'].append({'game_id':g['game_id'],'market':market,'reason':'No fresh, verified pre-kickoff line and odds'});continue
            if market=='Spread':
                a,h=ratings[week].get(g['away_team']),ratings[week].get(g['home_team'])
                if not a or not h or min(a['games'],h['games'])<3:prediction=None
                else:
                    values={**difference(a,h,'Neutral' if g.get('location')=='Neutral' else 'Away'),'away_handicap':q['line']}
                    prediction=ats_predict(candidate['model'],values)
                if prediction is not None:
                    prob=prediction['probability'];side=None if abs(prob-.5)<1e-12 else g['away_team'] if prob>.5 else g['home_team']
                    details={'away_cover_probability':prob,'contributions':prediction['contributions']}
            else:
                teams,league=total_profiles[week]
                values=total_features(teams,league,g['away_team'],g['home_team'],g.get('location')=='Neutral',q['line'])
                prediction=totals_predict(candidate['model'],values,q['line']) if values is not None else None
                if prediction is not None:
                    side=None if prediction['lean']=='No Call' else prediction['lean'];details=prediction
            if prediction is None:
                status['pending'].append({'game_id':g['game_id'],'market':market,'reason':'Model inputs are incomplete'});continue
            record={'game_id':g['game_id'],'season':year,'week':week,'away_team':g['away_team'],'home_team':g['home_team'],
                    'kickoff_utc':kickoff(g).isoformat(),'decision_cutoff_utc':now.isoformat(),'market':market,
                    'quote':q,'selected_side':side,'features':values,'prediction':details,
                    'history_away':ratings[week][g['away_team']]['history_game_ids'],
                    'history_home':ratings[week][g['home_team']]['history_game_ids'],
                    'model_sha256':model_hash,'model_name':candidate.get('candidate_name',candidate.get('name','Simplified ATS')),
                    'stats_source_manifest':manifest,'schedule_snapshot_sha256':hashlib.sha256((input_dir/'nfl_games.csv').read_bytes()).hexdigest(),
                    'quote_snapshot_sha256':hashlib.sha256((input_dir/'public_money_snapshots.csv').read_bytes()).hexdigest(),
                    'input_snapshot_dir':str(input_dir.relative_to(root)),'pipeline_sha256':config['pipeline_sha256'],
                    'limitations':['Research forecast, not validated confidence or a betting recommendation.',
                                   'No injury/replacement or forecast weather effects.',
                                   'Source update timestamps may be unavailable; inputs were observed/retrieved before cutoff.']}
            if seal(path,record,clock=seal_clock):status['saved']+=1
            else:status['preserved']+=1
    temp=base/'status.tmp';temp.write_text(json.dumps(status,indent=2));temp.replace(base/'status.json')
    print(json.dumps(status,indent=2));return status


def refresh_and_run():
    from .collect import collect
    from scheduled_ats_capture import run as capture_market
    collect(2026,ROOT/'data/scout4')
    if capture_market(ROOT)!=0:
        raise ValueError('Market collection failed; no new forecasts sealed')
    return run()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true',help='Refresh statistics and market quotes before capture')
    args=parser.parse_args()
    refresh_and_run() if args.refresh else run()
