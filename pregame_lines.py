"""Read-only spread overlay: manual correction, pregame snapshot, original CSV."""
import csv,math
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

def effective_rows(rows,path):
    rows=[dict(row) for row in rows];root=Path(path).resolve().parent
    manual_path=root/'manual_spread_overrides.csv';manual={}
    if manual_path.exists():
        with manual_path.open(newline='') as f:manual={r['game_id']:r for r in csv.DictReader(f)}
    snapshots=root/'public_money_snapshots.csv';latest={};games={g['game_id']:g for g in rows};now=datetime.now(timezone.utc)
    if snapshots.exists():
        with snapshots.open(newline='') as f:
            for s in csv.DictReader(f):
                g=games.get(s.get('game_id'))
                if not g or s.get('sportsbook')!='DraftKings' or s.get('market')!='Spread':continue
                if (s.get('side_a'),s.get('side_b'))!=(g['away_team'],g['home_team']):continue
                try:
                    capture=datetime.fromisoformat(s['captured_at_utc']);kickoff=datetime.fromisoformat(g['gameday']+'T'+g['gametime']).replace(tzinfo=ZoneInfo('America/New_York'))
                    claimed=datetime.fromisoformat(s['kickoff_utc']);a=float(s['line_a']);b=float(s['line_b'])
                    if capture.tzinfo is None or claimed.tzinfo is None or claimed!=kickoff or capture>=kickoff or capture>now or not all(math.isfinite(v) for v in (a,b)) or abs(a+b)>1e-8:continue
                except (KeyError,ValueError,TypeError):continue
                if g['game_id'] not in latest or capture>latest[g['game_id']][0]:latest[g['game_id']]=(capture,kickoff,a,s['source_url'])
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
        if g.get('dog_team') is not None and g.get('spread_line'):
            spread=float(g['spread_line']);g['dog_team']=g['away_team'] if spread>0 else g['home_team'] if spread<0 else '';g['dog_spread']=str(abs(spread))
    return rows
