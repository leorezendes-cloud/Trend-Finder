"""Read-only combined forecast cards; original models and archived lines stay intact."""
import csv
from pathlib import Path
from flask import url_for
from expert_beta import instant
from public_pick_market import matchup_public_market
from plug_line_movement import compare_line

ROOT = Path(__file__).resolve().parent


def legacy_records():
    from scout4.blend import view
    return view()


def combined_cards(records, render_record, now):
    items = {}
    originals = {}
    for record in records:
        item = render_record(record)
        originals[record['scout']['game']['game_id']] = record['scout']
        item['locked_quotes'] = record['scout'].get('quotes', {})
        item['show_scores'] = True
        items[record['scout']['game']['game_id']] = item
    for record in legacy_records():
        if record['game_id'] in items:
            item = items[record['game_id']]
            total = record.get('totals')
            original = dict(ats=record['components']['Blend']['pick'],
                line=record['quote']['line'] if record['components']['Blend']['pick']==record['away_team'] else -record['quote']['line'],
                total_side=total['prediction']['lean'] if total else None,total_line=total['quote']['line'] if total else None)
            saved=item['locked_quotes'].get('Spread',{})
            side=item['saved_picks']['spread']['side']
            line=saved.get('line_a') if side==saved.get('side_a') else saved.get('line_b')
            if original['ats']!=side or original['line']!=line or original['total_side']!=item['saved_picks']['total']['side'] or original['total_line']!=item['locked_quotes'].get('Total',{}).get('line_a'):
                item['earlier_forecast']=original
            continue
        game = {key:record[key] for key in ('game_id','away_team','home_team','season','week','kickoff_utc')}
        total = record.get('totals')
        pick = record['components']['Blend']
        quotes = {'Spread':{'side_a':game['away_team'],'side_b':game['home_team'],
                            'line_a':record['quote']['line'],'line_b':-record['quote']['line']}}
        if total:quotes['Total']={'line_a':total['quote']['line']}
        selections = {'spread':{'side':pick['pick'],'label':'Pick'},
                      'total':{'side':total['prediction']['lean'] if total else None,'label':'Pick'}}
        items[game['game_id']] = dict(scout={'game':game,'sources':[]},saved_picks=selections,
            locked_quotes=quotes,show_scores=False,prediction_margin=pick['away_margin'],
            expert_picks=None,expert_available=False,expert_access=False,assessment=None,
            url=url_for('fans.matchup',game_id=game['game_id']),
            legacy=True,ats_result=record.get('results',{}).get('Blend'))
    upcoming, earlier = [], []
    wanted={game_id for game_id,item in items.items() if instant(item['scout']['game']['kickoff_utc'])>now}
    market_rows=[]
    path=ROOT/'public_money_snapshots.csv'
    if wanted and path.exists():
        with path.open(newline='',encoding='utf-8-sig') as source:
            market_rows=[r for r in csv.DictReader(source) if r.get('game_id') in wanted and r.get('market') in ('Moneyline','Spread','Total')]

    for item in items.values():
        game = item['scout']['game']
        future = instant(game['kickoff_utc']) > now
        item['upcoming'] = future
        item['market'] = None
        item['line_movement'] = compare_line(originals[game['game_id']], ROOT, now, rows=market_rows) if future and game['game_id'] in originals else None
        if future:
            market = matchup_public_market(ROOT,dict(game_id=game['game_id'],away=game['away_team'],
                home=game['home_team'],kickoff_at=game['kickoff_utc']),now,rows=market_rows)
            item['market'] = [m for m in market['markets'] if m['key'] in ('Moneyline','Spread','Total') and m['sides']]
        (upcoming if future else earlier).append(item)
    upcoming.sort(key=lambda item:item['scout']['game']['kickoff_utc'])
    earlier.sort(key=lambda item:item['scout']['game']['kickoff_utc'],reverse=True)
    return upcoming, earlier
