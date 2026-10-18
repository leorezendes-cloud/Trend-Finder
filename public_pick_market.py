"""Validated saved public splits for an inline matchup card; no collection or writes."""
import csv
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from public_money import validate_market

MARKETS=(('Moneyline','SU winner'),('Spread','ATS winner'),('Total','Over / Under'))

def matchup_public_market(root,pick,now=None,rows=None):
    now=now or datetime.now(timezone.utc)
    kickoff=datetime.fromisoformat(pick['kickoff_at'])
    if kickoff.tzinfo is None:raise ValueError('Kickoff timezone missing')
    latest={};path=Path(root)/'public_money_snapshots.csv'
    def consume(records):
        for row in records:
            if row.get('game_id')!=pick['game_id'] or (row.get('away_team'),row.get('home_team'))!=(pick['away'],pick['home']):continue
            try:
                validate_market(row)
                captured=datetime.fromisoformat(row['captured_at_utc']);claimed=datetime.fromisoformat(row['kickoff_utc'])
                if captured.tzinfo is None or claimed.tzinfo is None or claimed!=kickoff or captured>=kickoff or captured>now:continue
                expected=('Over','Under') if row['market']=='Total' else (pick['away'],pick['home'])
                if (row['side_a'],row['side_b'])!=expected:continue
                if urlsplit(row['source_url']).scheme!='https':continue
            except (ValueError,TypeError,KeyError):continue
            if row['market'] not in latest or captured>latest[row['market']][0]:latest[row['market']]=(captured,row)
    if rows is not None:
        consume(rows)
    elif path.exists():
        with path.open(newline='',encoding='utf-8-sig') as source:
            consume(csv.DictReader(source))
    output=[]
    for key,label in MARKETS:
        match=latest.get(key);item={'key':key,'label':label,'sides':[]}
        if match:
            captured,row=match
            item.update(captured=row['captured_at_utc'],source=row['sportsbook'],url=row['source_url'],stale=(now-captured).total_seconds()>86400)
            for side in ('a','b'):
                item['sides'].append({'name':row['side_'+side],'line':float(row['line_'+side]) if key!='Moneyline' else None,'odds':float(row['odds_'+side]),'bets':float(row['bets_'+side]),'money':float(row['handle_'+side])})
        output.append(item)
    return {'markets':output,'closed':now>=kickoff}
