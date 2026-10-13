"""Read-only public schedule/quote views; never modifies canonical or frozen data."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from scout4.stats import read_csv,number
from scout4.shadow import kickoff,aware

ROOT=Path(__file__).resolve().parent


def upcoming_rows(root=ROOT,now=None):
    now=now or datetime.now(timezone.utc)
    snapshots=read_csv(root/'public_money_snapshots.csv');frozen={}
    for path in (root/'data/scout4/blend/predictions').glob('*.json'):
        r=json.loads(path.read_text());frozen[r['game_id']]=r
    output=[]
    for source in read_csv(root/'nfl_games.csv'):
        if source.get('away_score') or source.get('home_score') or not source.get('gametime') or not source.get('gameday'):continue
        try:ko=kickoff(source)
        except ValueError:continue
        if not now<ko<=now+timedelta(days=7):continue
        game=dict(source);record=frozen.get(game['game_id']);line=None;stamp=None;label=None
        if record and all(record.get(k)==game.get(k) for k in ('away_team','home_team')) and aware(record['kickoff_utc'])==ko and aware(record['quote']['captured_at_utc'])<=now:
            line=number(record['quote']['line']);stamp=record['quote']['captured_at_utc'];label='Frozen public-pick line'
        if line is None:
            quotes=[]
            for q in snapshots:
                if q.get('game_id')!=game['game_id'] or q.get('market')!='Spread' or any(q.get(k)!=game.get(k) for k in ('away_team','home_team')):continue
                try:t=aware(q['captured_at_utc']);qko=aware(q['kickoff_utc'])
                except (ValueError,KeyError):continue
                a,b=number(q.get('line_a')),number(q.get('line_b'))
                if not t<=now<ko or qko!=ko or a is None or b is None or abs(a+b)>1e-9:continue
                if {q.get('side_a'),q.get('side_b')}!={game['away_team'],game['home_team']}:continue
                quotes.append((t,a if q['side_a']==game['away_team'] else b,q['captured_at_utc']))
            if quotes:
                _,line,stamp=max(quotes,key=lambda q:q[0]);label='Saved market snapshot'
        if line is None:
            line=number(game.get('spread_line'));label='Schedule line' if line is not None else 'Spread unavailable'
        game['spread_line']='' if line is None else str(line)
        game['public_line_source']=label;game['public_line_time']=stamp
        game['public_line_stale']=bool(stamp and now-aware(stamp)>timedelta(hours=24))
        output.append(game)
    return sorted(output,key=lambda g:(g['gameday'],g['gametime'],g['game_id']))


def public_matchups(comparisons,root=ROOT,now=None):
    from trend_finder_2 import match_upcoming_game
    rows=upcoming_rows(root,now);result=[];pending=[]
    for g in rows:
        line=number(g['spread_line'])
        if line is None or line==0:
            pending.append({'game_id':g['game_id'],'away_team':g['away_team'],'home_team':g['home_team'],'reason':'Spread unavailable' if line is None else 'Pick’em: no underdog trend'});continue
        dog=g['away_team'] if line>0 else g['home_team'];side='Away' if line>0 else 'Home';prime=g['gametime']>='19:00'
        game={'game_id':g['game_id'],'gameday':g['gameday'],'gametime_et':g['gametime'],'away_team':g['away_team'],'home_team':g['home_team'],
              'dog_team':dog,'dog_spread':abs(line),'dog_location':side,'is_primetime':prime,
              'line_source':g['public_line_source'],'line_time':g['public_line_time'],'line_stale':g['public_line_stale'],
              'neutral':g.get('location')=='Neutral','matches':match_upcoming_game(comparisons,side,prime,abs(line))}
        result.append(game)
    return result,pending
