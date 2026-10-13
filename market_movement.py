"""Three-market movement observations, explicitly measured from recorded quotes."""
import csv
from collections import defaultdict
from datetime import datetime
from public_money import MARKETS, validate_market, grade, tally

def implied(odds):
    odds=float(odds)
    return 100*(-odds/(-odds+100) if odds<0 else 100/(odds+100))

def build_market_movement(root,games,start,end,season,archive_week=None,archive_stage='REG'):
    groups=defaultdict(dict);path=root/'public_money_snapshots.csv';rejected=0
    if path.exists():
        with path.open(newline='') as f:
            for row in csv.DictReader(f):
                try:
                    validate_market(row);game=games[row['game_id']]
                    captured=datetime.fromisoformat(row['captured_at_utc']);kickoff=datetime.fromisoformat(row['kickoff_utc'])
                    if captured.tzinfo is None or kickoff.tzinfo is None or captured>=kickoff:raise ValueError('Not pregame')
                    if (game['away_team'],game['home_team'])!=(row['away_team'],row['home_team']):raise ValueError('Mismatch')
                    if row['sportsbook']!='DraftKings':continue
                    groups[(row['game_id'],row['market'])][captured]=row
                except (ValueError,KeyError,TypeError):rejected+=1
    rows=[];cards={}
    for (game_id,market),quotes in groups.items():
        game=games[game_id]
        if archive_week=='all':selected=game['season']==season
        elif archive_week is not None:selected=game['season']==season and game['week']==str(archive_week) and game['game_type']==archive_stage
        else:selected=start.isoformat()<=game['gameday']<end.isoformat()
        if not selected:continue
        quotes=[quotes[t] for t in sorted(quotes)];first,last=quotes[0],quotes[-1]
        backed='a' if float(last['handle_a'])>=65 else 'b' if float(last['handle_b'])>=65 else None
        side=backed or 'a'
        if market=='Moneyline':
            before,after=float(first[f'odds_{side}']),float(last[f'odds_{side}'])
            change=implied(after)-implied(before);against=-change;unit='probability points'
            first_quote=f"{last[f'side_{side}']} {before:+g}";latest_quote=f"{last[f'side_{side}']} {after:+g}"
        elif market=='Spread':
            before,after=float(first[f'line_{side}']),float(last[f'line_{side}']);change=after-before;against=change;unit='spread points'
            first_quote=f"{last[f'side_{side}']} {before:+g}";latest_quote=f"{last[f'side_{side}']} {after:+g}"
        else:
            before,after=float(first['line_a']),float(last['line_a']);change=after-before;against=-change if side=='a' else change;unit='total points'
            first_quote=f'{before:g}';latest_quote=f'{after:g}'
        qualified=bool(backed and len(quotes)>=2 and against>1e-8)
        status='Reverse movement' if qualified else 'Need another observation' if len(quotes)<2 else 'Below 65% money' if not backed else 'Quote unchanged' if abs(change)<1e-8 else 'Moves with public money'
        result=grade(last,game)
        if not qualified:result.update(qualifies=False,pick='No reverse-line fade',result=status,profit=None)
        result.update(status=status,first_quote=first_quote,latest_quote=latest_quote,change=round(change,2),unit=unit,snapshot_count=len(quotes),backed=last[f'side_{backed}'] if backed else None,history=quotes)
        rows.append(result)
        card=cards.setdefault(game_id,dict(matchup=f"{game['away_team']} @ {game['home_team']}",week=game['week'],gameday=game['gameday'],markets=[],source_url=last['source_url']))
        card['markets'].append(result)
    order={market:i for i,market in enumerate(MARKETS)}
    for card in cards.values():card['markets'].sort(key=lambda row:order[row['market']])
    return dict(cards=sorted(cards.values(),key=lambda card:card['gameday']),tallies=[dict(label=label,**tally([row for row in rows if row['market']==market])) for market,label in MARKETS.items()],total=tally(rows),rejected=rejected)
