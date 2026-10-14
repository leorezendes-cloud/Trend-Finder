"""Read latest valid saved market quotes; never calls a collector."""
import csv,math
from pathlib import Path
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from site_week import active_week


def read(path):
    if not path.exists():return []
    with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def num(value):
    try:
        x=float(value);return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None

def stamp(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('Unverified timestamp')
    return t.astimezone(timezone.utc)

def market_games(root,now=None):
    root=Path(root);now=now or datetime.now(timezone.utc);schedule=read(root/'nfl_games.csv');week=active_week(schedule,now);quotes=read(root/'public_money_snapshots.csv');output=[]
    for row in schedule:
        try:
            ko=datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
            identity=(int(row['season']),int(row['week']))
        except (KeyError,ValueError):continue
        if row.get('away_score') or row.get('home_score') or ko<=now or identity!=week:continue
        latest={}
        for q in quotes:
            if q.get('game_id')!=row['game_id'] or any(q.get(k)!=row.get(k) for k in ('away_team','home_team')):continue
            try:t=stamp(q['captured_at_utc']);qko=stamp(q['kickoff_utc'])
            except (ValueError,KeyError,TypeError,AttributeError):continue
            if not t<=now<ko or qko!=ko:continue
            market=q.get('market');a,b=num(q.get('line_a')),num(q.get('line_b'))
            if a is None or b is None:continue
            if market=='Spread' and {q.get('side_a'),q.get('side_b')}=={row['away_team'],row['home_team']} and abs(a+b)<1e-8:value=a if q['side_a']==row['away_team'] else b
            elif market=='Total' and {q.get('side_a'),q.get('side_b')}=={'Over','Under'} and a>0 and abs(a-b)<1e-8:value=a
            else:continue
            if market not in latest or t>latest[market][0]:latest[market]=(t,value,q)
        game=dict(row,kickoff_utc=ko.isoformat())
        for market,key,field in [('Spread','spread','spread_line'),('Total','total','total_line')]:
            quote=latest.get(market)
            game[key]=quote[1] if quote else num(row.get(field))
            game[key+'_source']='Saved market quote' if quote else 'Saved schedule' if game[key] is not None else 'Unavailable'
            game[key+'_time']=quote[0].isoformat() if quote else None
            game[key+'_stale']=bool(quote and now-quote[0]>timedelta(hours=24))
        output.append(game)
    return sorted(output,key=lambda g:g['kickoff_utc'])
