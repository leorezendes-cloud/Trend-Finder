#!/usr/bin/env python3
"""Collect public DraftKings spread handle snapshots; retain raw evidence."""
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from ats_money_analysis import snapshot_from_row, REQUIRED

ROOT = Path(__file__).resolve().parent
SOURCE = 'https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/?tb_eg=88808&itm_content=NFL&tb_edate=n7days'

class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def text(self):
        return ' '.join(c.text() if isinstance(c, Node) else c for c in self.children).strip()
    def find(self, cls):
        found = [self] if cls in self.attrs.get('class', '').split() else []
        for child in self.children:
            if isinstance(child, Node): found.extend(child.find(cls))
        return found

class Tree(HTMLParser):
    def __init__(self):
        super().__init__(); self.root=Node(); self.stack=[self.root]
    def handle_starttag(self, tag, attrs):
        node=Node(tag, attrs); self.stack[-1].children.append(node)
        if tag not in {'img','input','br','hr','meta','link','source','wbr','area','base','embed','param','col'}:
            self.stack.append(node)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag: self.stack=self.stack[:i]; break
    def handle_data(self, data): self.stack[-1].children.append(data)


def team_code(code, label):
    if code == 'LA':
        if 'Chargers' in label: return 'LAC'
        if 'Rams' in label: return 'LA'
        raise ValueError('Ambiguous Los Angeles team')
    if code == 'LAR': return 'LA'
    if code == 'NY':
        if 'Jets' in label: return 'NYJ'
        if 'Giants' in label: return 'NYG'
        raise ValueError('Ambiguous New York team')
    return {'WSH': 'WAS'}.get(code, code)


def parse_page(html):
    tree=Tree(); tree.feed(html)
    events=[]
    for event in tree.root.find('tb-se'):
        titles=event.find('tb-se-title-new')
        if len(titles)!=1: raise ValueError('Unexpected matchup title layout')
        title=' '.join(titles[0].text().split())
        match=re.fullmatch(r'([A-Z]{2,3}) .+ @ ([A-Z]{2,3}) .+',title)
        if not match: raise ValueError(f'Unrecognized matchup: {title}')
        sides={}
        market=''
        # Heads and selection rows occur in source order within each event.
        def walk(node):
            nonlocal market
            classes=node.attrs.get('class','').split()
            if 'tb-se-head' in classes:
                cells=[c for c in node.children if isinstance(c,Node)]
                labels=[' '.join(c.text().split()) for c in cells]
                if len(labels)!=4 or labels[2:]!=['% Handle','% Bets']:
                    raise ValueError('Unexpected betting-split columns')
                market=labels[0]
            if 'tb-sodd' in classes and market=='Spread':
                cells=[c for c in node.children if isinstance(c,Node)]
                if len(cells)!=4: raise ValueError('Unexpected spread row')
                label=' '.join(cells[0].text().split()).replace('−','-')
                m=re.fullmatch(r'([A-Z]{2,3}) .+ ([+-]\d+(?:\.\d+)?|[Pp][Kk])',label)
                pct=re.fullmatch(r'(\d+(?:\.\d+)?)%',cells[2].text().strip())
                if not m or not pct: raise ValueError('Missing spread or handle percentage')
                team=team_code(m[1],label)
                if team in sides: raise ValueError('Duplicate spread side')
                sides[team]=(0.0 if m[2].lower()=='pk' else float(m[2]),float(pct[1]))
            for child in node.children:
                if isinstance(child,Node): walk(child)
        walk(event)
        away_label,home_label=title.split(' @ ')
        away,home=team_code(match[1],away_label),team_code(match[2],home_label)
        if len(sides)!=2 or set(sides)!={away,home}: raise ValueError('Missing spread market')
        if abs(sides[away][0]+sides[home][0])>1e-8: raise ValueError('Non-opposing spreads')
        date_match=re.search(r'(\d{1,2}/\d{1,2}),\s*(\d{1,2}:\d{2}[AP]M)',event.find('tb-se-title')[0].text())
        if not date_match: raise ValueError('Missing event date/time')
        event_time=datetime.strptime('2000/'+date_match[1]+' '+date_match[2],'%Y/%m/%d %I:%M%p')
        events.append((away,home,sides,event_time))
    if not events: raise ValueError('No NFL events found; nothing collected')
    return events


def collect(root=ROOT):
    from public_money import parse_markets, append_market_snapshots
    with (root/'nfl_games.csv').open(newline='',encoding='utf-8-sig') as f:
        games=list(csv.DictReader(f))
    evidence=root/'logs'/'ats_handle'; evidence.mkdir(parents=True,exist_ok=True)
    rows=[]; skipped=[]; captures=[]; market_rows=[]
    # Follow only the observed NFL table's numbered pagination links.
    for page in range(1,21):
        url=SOURCE+f'&tb_page={page}'
        with urlopen(Request(url,headers={'User-Agent':'TrendFindah-Research/1.0'}),timeout=30) as response:
            raw=response.read()
        captured=datetime.now(timezone.utc)
        stamp=captured.strftime('%Y%m%dT%H%M%S%fZ')
        from archive_storage import save_capture
        archive=evidence/f'{stamp}-page{page}.html'; save_capture(archive,raw)
        html=raw.decode('utf-8')
        markets_by_game=parse_markets(html)
        captures.append(dict(url=url,captured_at_utc=captured.isoformat(),file=archive.name,sha256=hashlib.sha256(raw).hexdigest()))
        for away,home,sides,event_time in parse_page(html):
            candidates=[]
            for game in games:
                if (game['away_team'],game['home_team'])!=(away,home) or not game.get('gametime'): continue
                scheduled=datetime.fromisoformat(game['gameday']+'T'+game['gametime'])
                if (scheduled.month,scheduled.day,scheduled.hour,scheduled.minute)!=(event_time.month,event_time.day,event_time.hour,event_time.minute): continue
                kickoff=scheduled.replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
                if captured<kickoff and (kickoff-captured).total_seconds()<8*86400:
                    candidates.append((game,kickoff))
            if len(candidates)!=1:
                skipped.append(f'{away}@{home}: no unique upcoming scheduled game'); continue
            game,kickoff=candidates[0]
            row=dict(game_id=game['game_id'],kickoff_utc=kickoff.isoformat(),captured_at_utc=captured.isoformat(),away_team=away,home_team=home,away_spread=str(sides[away][0]),away_handle_pct=str(sides[away][1]),home_handle_pct=str(sides[home][1]),sportsbook='DraftKings',source_url=url)
            snapshot_from_row(row)
            if any(r['game_id']==row['game_id'] for r in rows): raise ValueError('Duplicate event across pages')
            rows.append(row)
            for market in markets_by_game[(away,home)]:
                metadata={key:row[key] for key in ['game_id','kickoff_utc','captured_at_utc','away_team','home_team','sportsbook','source_url']}
                market_rows.append(dict(metadata,**market))
        # Decode &amp; before recognizing the next page.
        from html import unescape
        if not re.search(r'tb_page='+str(page+1)+r'(?:[&"\'])',unescape(html)): break
    else: raise ValueError('Pagination exceeded limit; refusing partial collection')
    target=root/'ats_handle_snapshots.csv'
    with target.open(newline='',encoding='utf-8-sig') as f:
        header=next(csv.reader(f))
    if set(header)!=REQUIRED: raise ValueError('Unexpected snapshot CSV header')
    # Recheck kickoff immediately before writing; page requests may take time.
    now=datetime.now(timezone.utc)
    rows=[r for r in rows if datetime.fromisoformat(r['kickoff_utc'])>now]
    market_rows=[r for r in market_rows if datetime.fromisoformat(r['kickoff_utc'])>now]
    manifest=evidence/f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}-manifest.json'
    manifest.write_text(json.dumps(dict(captures=captures,rows=rows,market_rows=market_rows,skipped=skipped),indent=2))
    if market_rows: append_market_snapshots(root,market_rows)
    print(f'Saved {len(market_rows)} spread, moneyline, and total market observations.')
    with target.open('a',newline='',encoding='utf-8') as f:
        csv.DictWriter(f,fieldnames=header).writerows(rows)
    print(f'Saved {len(rows)} DraftKings spread-handle snapshots. Evidence: {manifest}')
    for row in rows:
        print(f"{row['away_team']} @ {row['home_team']}: {row['away_spread']} | Handle {row['away_handle_pct']}% / {row['home_handle_pct']}%")
    for reason in skipped: print('Skipped:',reason)
    return rows

if __name__=='__main__':
    collect()
