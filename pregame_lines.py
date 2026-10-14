"""Read-only market overlay and exact name corrections; original records stay intact."""
from name_aliases import corrected_row
import csv,math
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

def effective_rows(rows,path):
    rows=[corrected_row(row) for row in rows];root=Path(path).resolve().parent
    manual_path=root/'manual_spread_overrides.csv';manual={}
    if manual_path.exists():
        with manual_path.open(newline='') as f:manual={r['game_id']:r for r in csv.DictReader(f)}
    snapshots=root/'public_money_snapshots.csv';latest={};latest_totals={};games={g['game_id']:g for g in rows};now=datetime.now(timezone.utc)
    if snapshots.exists():
        with snapshots.open(newline='') as f:
            for s in csv.DictReader(f):
                g=games.get(s.get('game_id'))
                if not g or s.get('sportsbook')!='DraftKings' or s.get('market') not in ('Spread','Total'):continue
                if s['market']=='Spread' and (s.get('side_a'),s.get('side_b'))!=(g['away_team'],g['home_team']):continue
                if s['market']=='Total' and (s.get('side_a'),s.get('side_b'))!=('Over','Under'):continue
                try:
                    capture=datetime.fromisoformat(s['captured_at_utc']);kickoff=datetime.fromisoformat(g['gameday']+'T'+g['gametime']).replace(tzinfo=ZoneInfo('America/New_York'))
                    claimed=datetime.fromisoformat(s['kickoff_utc']);a=float(s['line_a']);b=float(s['line_b'])
                    if capture.tzinfo is None or claimed.tzinfo is None or claimed!=kickoff or capture>=kickoff or capture>now or not all(math.isfinite(v) for v in (a,b)) or (s['market']=='Spread' and abs(a+b)>1e-8) or (s['market']=='Total' and (a<=0 or abs(a-b)>1e-8)):continue
                except (KeyError,ValueError,TypeError):continue
                selected = latest if s['market']=='Spread' else latest_totals
                if g['game_id'] not in selected or capture>selected[g['game_id']][0]:selected[g['game_id']]=(capture,kickoff,a,s['source_url'])
    for g in rows:
        g['line_source']='Original CSV';g['line_capture']='';g['line_minutes']='';g['line_url']=''
        m=manual.get(g['game_id']);s=latest.get(g['game_id'])
        if m:
            try:value=float(m['spread_line'])
            except (ValueError,KeyError):value=None
            if value is not None and math.isfinite(value):g.update(spread_line=f'{value:g}',line_source='Manual correction',line_url=m.get('source_url',''))
        elif s:
            capture,kickoff,away,url=s
            g.update(spread_line=f'{away:g}',line_source='DraftKings pregame capture',line_capture=capture.astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %I:%M %p ET'),line_minutes=round((kickoff-capture).total_seconds()/60,1),line_url=url)
        g['total_source']='Original CSV';g['total_capture']=''
        if g['game_id'] in latest_totals:
            capture,_,total,_ = latest_totals[g['game_id']]
            g.update(total_line=f'{total:g}',total_source='DraftKings pregame capture',total_capture=capture.astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %I:%M %p ET'))
        if g.get('dog_team') is not None and g.get('spread_line'):
            spread=float(g['spread_line']);g['dog_team']=g['away_team'] if spread>0 else g['home_team'] if spread<0 else '';g['dog_spread']=str(abs(spread))
    return rows
