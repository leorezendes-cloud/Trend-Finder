"""Read-only ATS repricing of a frozen projection; never generates a forecast."""
import csv
import math
from pathlib import Path
from datetime import datetime,timezone
from public_pick_market import matchup_public_market

def instant(value):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:raise ValueError('Timezone required')
    return dt.astimezone(timezone.utc)

def compare_line(scout,root,now=None,rows=None):
    now=now or datetime.now(timezone.utc)
    game=scout['game'];q=scout.get('quotes',{}).get('Spread',{})
    team=scout.get('spread',{}).get('side');away=game['away_team'];home=game['home_team']
    if team not in (away,home) or not q.get('sportsbook') or {q.get('side_a'),q.get('side_b')}!={away,home}:return None
    try:
        original=float(q['line_a'] if q['side_a']==team else q['line_b'])
        observed=instant(q['captured_at_utc']);cutoff=instant(scout['cutoff_utc']);kickoff=instant(game['kickoff_utc'])
        if q.get('game_id')!=game['game_id'] or not observed<=cutoff<kickoff or observed>now:return None
        if rows is None:
            path=Path(root)/'public_money_snapshots.csv'
            if not path.exists():return None
            with path.open(newline='',encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        # Filter before selecting latest, so another book can never replace this book.
        same=[r for r in rows if r.get('sportsbook')==q['sportsbook'] and r.get('market')=='Spread']
        market=matchup_public_market(root,dict(game_id=game['game_id'],away=away,home=home,kickoff_at=game['kickoff_utc']),now,rows=same)
        latest=next((m for m in market['markets'] if m['key']=='Spread' and m['sides']),None)
        if not latest or instant(latest['captured'])<observed:return None
        line=next(s['line'] for s in latest['sides'] if s['name']==team)
        margin=float(scout['scores'][team])-float(scout['scores'][home if team==away else away])
        if not all(math.isfinite(v) for v in (original,line,margin)):return None
    except (ValueError,KeyError,TypeError,StopIteration):return None
    old_edge=margin+original;edge=margin+line;movement=line-original
    return dict(team=team,sportsbook=q['sportsbook'],original_line=original,latest_line=line,
        original_observed=q['captured_at_utc'],latest_observed=latest['captured'],movement=movement,
        original_edge=old_edge,latest_edge=edge,unsupported=edge<=0,
        material=abs(movement)>=1 or ((old_edge>0)!=(edge>0)),stale=latest['stale'],closed=market['closed'])
