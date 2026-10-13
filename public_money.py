"""Public-money fades by market; saved pregame quotes, one-unit stake accounting."""
import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from collect_ats_handle import Tree, Node, team_code

MARKETS={'Spread':'Spread (ATS)','Moneyline':'Moneyline (SU)','Total':'Total (O/U)'}
FIELDS=['game_id','kickoff_utc','captured_at_utc','away_team','home_team','sportsbook','source_url','market','side_a','side_b','line_a','line_b','odds_a','odds_b','handle_a','handle_b','bets_a','bets_b']

def parse_markets(html):
    tree=Tree();tree.feed(html);events={}
    for event in tree.root.find('tb-se'):
        title=' '.join(event.find('tb-se-title-new')[0].text().split())
        a,b=title.split(' @ ');away=team_code(a.split()[0],a);home=team_code(b.split()[0],b)
        markets={};market=None
        def walk(node):
            nonlocal market
            classes=node.attrs.get('class','').split()
            cells=[c for c in node.children if isinstance(c,Node)]
            if 'tb-se-head' in classes:
                labels=[' '.join(c.text().split()) for c in cells]
                if labels[1:]!=['Odds','% Handle','% Bets']:raise ValueError('Unknown market columns')
                market=labels[0]
            if 'tb-sodd' in classes and market in MARKETS:
                if len(cells)!=4:raise ValueError('Unknown selection layout')
                label=' '.join(cells[0].text().split()).replace('−','-')
                if market=='Moneyline': side=team_code(label.split()[0],label);line=''
                elif market=='Spread':
                    m=re.fullmatch(r'([A-Z]{2,3}) .+ ([+-]\d+(?:\.\d+)?|[Pp][Kk])',label)
                    if not m:raise ValueError('Missing spread')
                    side=team_code(m[1],label);line='0' if m[2].lower()=='pk' else m[2]
                else:
                    m=re.fullmatch(r'(Over|Under) (\d+(?:\.\d+)?)',label)
                    if not m:raise ValueError('Missing total')
                    side,line=m.groups()
                odd=cells[1].text().strip().replace('−','-')
                if odd.upper() in {'EVEN','EV','EVS'}:odd='+100'
                if not re.fullmatch(r'[+-]?\d+',odd) or abs(int(odd))<100:raise ValueError('Invalid American odds')
                vals=[]
                for cell in cells[2:]:
                    text=cell.text().strip();m=re.fullmatch(r'(\d+(?:\.\d+)?)%',text)
                    if not m:raise ValueError('Missing percentage')
                    vals.append(float(m[1]))
                dest=markets.setdefault(market,{})
                if side in dest:raise ValueError('Duplicate market side')
                dest[side]=dict(line=line,odds=odd,handle=vals[0],bets=vals[1])
            for child in node.children:
                if isinstance(child,Node):walk(child)
        walk(event)
        result=[]
        for market,sides in markets.items():
            sa,sb=('Over','Under') if market=='Total' else (away,home)
            if set(sides)!={sa,sb}:raise ValueError('Incomplete market')
            row=dict(market=market,side_a=sa,side_b=sb)
            for suffix,side in [('a',sa),('b',sb)]:
                for key,value in sides[side].items():row[f'{key}_{suffix}']=value
            validate_market(row)
            result.append(row)
        events[(away,home)]=result
    return events

def validate_market(row):
    if row['market'] not in MARKETS:raise ValueError('Unknown market')
    for kind in ['handle','bets']:
        a,b=float(row[f'{kind}_a']),float(row[f'{kind}_b'])
        if not (0<=a<=100 and 0<=b<=100) or abs(a+b-100)>1.1:raise ValueError('Invalid percentages')
    for suffix in ['a','b']:
        if abs(float(row[f'odds_{suffix}']))<100 or not math.isfinite(float(row[f'odds_{suffix}'])):raise ValueError('Invalid odds')
    if row['market']!='Moneyline':
        a,b=float(row['line_a']),float(row['line_b'])
        if not all(math.isfinite(n) for n in [a,b]):raise ValueError('Invalid lines')
        if (row['market']=='Spread' and abs(a+b)>1e-8) or (row['market']=='Total' and (a!=b or a<=0)):raise ValueError('Inconsistent lines')

def append_market_snapshots(root,rows):
    path=root/'public_money_snapshots.csv';existing=[]
    if path.exists():
        with path.open(newline='') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames!=FIELDS:raise ValueError('Unexpected market snapshot header')
            existing=list(reader)
    # Readers see either the old complete CSV or the new complete CSV.
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(existing);writer.writerows(rows)
    temporary.replace(path)

def grade(row,game):
    qualifies=max(float(row['handle_a']),float(row['handle_b']))>=65
    fade='b' if float(row['handle_a'])>=65 else 'a'
    pick=row[f'side_{fade}'] if qualifies else None
    odds=float(row[f'odds_{fade}']) if qualifies else None
    line=row[f'line_{fade}'] if qualifies else None
    result='Pending' if qualifies else 'Below threshold';profit=None
    if qualifies and game.get('away_score') and game.get('home_score'):
        away,home=float(game['away_score']),float(game['home_score'])
        if row['market']=='Total': margin=(away+home-float(line))*(1 if pick=='Over' else -1)
        else:
            margin=(away-home)*(1 if pick==row['away_team'] else -1)
            if row['market']=='Spread':margin+=float(line)
        result='Win' if margin>1e-8 else 'Loss' if margin<-1e-8 else 'Push'
        profit=(odds/100 if odds>0 else 100/abs(odds)) if result=='Win' else -1.0 if result=='Loss' else 0.0
    selection=pick or 'No fade'
    if qualifies and row['market']!='Moneyline':selection+=f' {float(line):+g}' if row['market']=='Spread' else f' {float(line):g}'
    if qualifies:selection+=f' ({odds:+g})'
    return dict(row,qualifies=qualifies,pick=selection,result=result,profit=profit,handle_a=float(row['handle_a']),handle_b=float(row['handle_b']),bets_a=float(row['bets_a']),bets_b=float(row['bets_b']),market_label=MARKETS[row['market']])

def tally(rows):
    rows=[r for r in rows if r['qualifies']]
    wins=sum(r['result']=='Win' for r in rows);losses=sum(r['result']=='Loss' for r in rows);pushes=sum(r['result']=='Push' for r in rows);settled=wins+losses+pushes
    profit=sum(r['profit'] for r in rows if r['profit'] is not None)
    return dict(qualifying=len(rows),wins=wins,losses=losses,pushes=pushes,pending=len(rows)-settled,rate=round(100*wins/(wins+losses),1) if wins+losses else None,profit=round(profit,2) if settled else None,roi=round(100*profit/settled,1) if settled else None)

def build_market_view(root,games,start,end,season,archive_week=None,archive_stage='REG'):
    path=root/'public_money_snapshots.csv';latest={};rejected=0
    if path.exists():
        with path.open(newline='') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames!=FIELDS:raise ValueError('Invalid market CSV header')
            for row in reader:
                try:
                    validate_market(row);game=games[row['game_id']]
                    capture=datetime.fromisoformat(row['captured_at_utc']);kickoff=datetime.fromisoformat(row['kickoff_utc'])
                    if capture.tzinfo is None or kickoff.tzinfo is None or capture>=kickoff:raise ValueError('Not pregame')
                    if (game['away_team'],game['home_team'])!=(row['away_team'],row['home_team']):raise ValueError('Mismatch')
                    expected=('Over','Under') if row['market']=='Total' else (row['away_team'],row['home_team'])
                    if (row['side_a'],row['side_b'])!=expected:raise ValueError('Side mismatch')
                    if urlparse(row['source_url']).scheme not in {'https','http'}:raise ValueError('Invalid source')
                    if row['sportsbook']!='DraftKings':continue
                    key=(row['game_id'],row['market'])
                    if key not in latest or capture>datetime.fromisoformat(latest[key]['captured_at_utc']):latest[key]=row
                except (ValueError,KeyError,TypeError):rejected+=1
    rows=[grade(row,games[row['game_id']]) for row in latest.values()]
    def selected(row):
        game=games[row['game_id']]
        if archive_week=='all':return game['season']==season
        if archive_week is not None:return game['season']==season and game['week']==str(archive_week) and game['game_type']==archive_stage
        return start.isoformat()<=game['gameday']<end.isoformat()
    visible=[r for r in rows if selected(r)];cards={}
    for r in visible:
        game=games[r['game_id']]
        card=cards.setdefault(r['game_id'],dict(matchup=f"{game['away_team']} @ {game['home_team']}",gameday=game['gameday'],week=game['week'],markets=[],source_url=r['source_url']))
        card['markets'].append(r)
    order={m:i for i,m in enumerate(MARKETS)}
    for card in cards.values():card['markets'].sort(key=lambda r:order[r['market']])
    running=[r for r in rows if games[r['game_id']]['season']==season and (games[r['game_id']]['game_type']!='REG' or int(games[r['game_id']]['week'])>=6)]
    history_groups={}
    for r in rows:
        game=games[r['game_id']]
        if game['season']==season and game['gameday']<start.isoformat():
            history_groups.setdefault((game['game_type'],game['week']),[]).append(r)
    history=[dict(stage=stage,week=week,label=f'Week {week}' if stage=='REG' else stage,tallies=[dict(label=label,**tally([r for r in group if r['market']==market])) for market,label in MARKETS.items()]) for (stage,week),group in sorted(history_groups.items(),key=lambda item:int(item[0][1]),reverse=True)]
    return dict(history=history,cards=sorted(cards.values(),key=lambda c:(c['gameday'],c['matchup'])),tallies=[dict(label=label,**tally([r for r in visible if r['market']==market])) for market,label in MARKETS.items()],running=[dict(label=label,**tally([r for r in running if r['market']==market])) for market,label in MARKETS.items()],total=tally(visible),rejected=rejected)
