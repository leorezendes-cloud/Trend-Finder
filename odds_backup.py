"""Verified pregame prices from ESPN; never invents betting-split percentages.

The unchanged forecast engine reads the existing market CSV. Raw responses and
their hashes preserve the independent source and actual observation time.
"""
import csv
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

BASE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite market value')
    return result


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Missing source timezone')
    return result.astimezone(timezone.utc)


def team(value):
    return {'LAR': 'LA', 'WSH': 'WAS'}.get(value, value)


def parse(payload, schedule, captured, source_url):
    """Require exact teams AND kickoff; use explicit current two-sided prices."""
    from scout4.shadow import kickoff
    candidates = {(g['away_team'], g['home_team'], kickoff(g)): g for g in schedule
                  if g.get('game_type') == 'REG' and g.get('gametime')
                  and not g.get('away_score') and not g.get('home_score')
                  and captured < kickoff(g) <= captured + timedelta(days=8)}
    rows, seen = [], set()
    for event in payload.get('events', []):
        for competition in event.get('competitions', []):
            try:
                if competition['status']['type']['state'] != 'pre':
                    continue
                sides = competition['competitors']
                if len(sides) != 2 or {s['homeAway'] for s in sides} != {'home', 'away'}:
                    continue
                teams = {s['homeAway']: team(s['team']['abbreviation']) for s in sides}
                ko = instant(competition['date'])
                if instant(event['date']) != ko:
                    continue
                game = candidates.get((teams['away'], teams['home'], ko))
                if not game:
                    continue
                # Use the identified sportsbook, never a provider-free consensus.
                offers = [o for o in competition.get('odds', [])
                          if o.get('provider', {}).get('name') == 'DraftKings']
                if len(offers) != 1:
                    continue
                offer = offers[0]
                identity = dict(game_id=game['game_id'], kickoff_utc=ko.isoformat(),
                                captured_at_utc=captured.isoformat(),
                                away_team=teams['away'], home_team=teams['home'],
                                sportsbook='DraftKings', source_url=source_url)
                for market, field, first, second, side_a, side_b in (
                    ('Spread', 'pointSpread', 'away', 'home', teams['away'], teams['home']),
                    ('Total', 'total', 'over', 'under', 'Over', 'Under')):
                    try:
                        a, b = offer[field][first]['close'], offer[field][second]['close']
                        la, lb = str(a['line']), str(b['line'])
                        if market == 'Total':
                            if not la.startswith('o') or not lb.startswith('u'):
                                raise ValueError('Unidentified total sides')
                            la, lb = la[1:], lb[1:]
                        la, lb, oa, ob = map(number, (la, lb, a['odds'], b['odds']))
                        if (abs(oa) < 100 or abs(ob) < 100
                                or la * 2 != int(la * 2) or lb * 2 != int(lb * 2)):
                            raise ValueError('Invalid line or American price')
                        if market == 'Spread':
                            if abs(la + lb) > 1e-8 or abs(la) > 60:
                                raise ValueError('Non-opposing spread')
                        elif la != lb or not 1 <= la <= 150:
                            raise ValueError('Inconsistent total')
                        key = (game['game_id'], market)
                        if key in seen:
                            raise RuntimeError('Duplicate backup market identity')
                        seen.add(key)
                        rows.append(dict(identity, market=market, side_a=side_a, side_b=side_b,
                                         line_a=f'{la:g}', line_b=f'{lb:g}',
                                         odds_a=f'{oa:g}', odds_b=f'{ob:g}',
                                         handle_a='', handle_b='', bets_a='', bets_b=''))
                    except (KeyError, ValueError, TypeError):
                        continue
            except (KeyError, ValueError, TypeError):
                continue
    return rows


def collect(root, *, clock=None, fetch=None, required=None):
    """Caller holds ats_capture.lock, also used by the primary collector."""
    from public_money import append_market_snapshots
    from scout4.shadow import kickoff
    root = Path(root)
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    with (root/'nfl_games.csv').open(newline='', encoding='utf-8-sig') as stream:
        schedule = list(csv.DictReader(stream))
    games = [g for g in schedule if g.get('game_type') == 'REG' and g.get('gametime')
             and not g.get('away_score') and not g.get('home_score')
             and now < kickoff(g) <= now + timedelta(days=8)]
    evidence = root/'logs/odds_backup'
    evidence.mkdir(parents=True, exist_ok=True)
    rows, captures = [], []
    for season, week in sorted({(g['season'], g['week']) for g in games}):
        url = f'{BASE}?dates={int(season)}&seasontype=2&week={int(week)}&limit=100'
        if fetch is None:
            with urlopen(Request(url, headers={'User-Agent': 'TrendFindah-Research/1.0'}), timeout=25) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        else:
            raw = fetch(url)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('Oversized backup response')
        captured = clock()  # Observation is after receipt, never a backdated cutoff.
        filename = captured.strftime('%Y%m%dT%H%M%S%fZ') + f'-{season}-{week}.json'
        from archive_storage import save_capture
        save_capture(evidence/filename,raw)
        captures.append(dict(url=url, file=filename, captured_at_utc=captured.isoformat(),
                             sha256=hashlib.sha256(raw).hexdigest()))
        rows.extend(parse(json.loads(raw), [g for g in games if (g['season'], g['week']) == (season, week)], captured, url))
    before_write = clock()
    rows = [r for r in rows if instant(r['kickoff_utc']) > before_write
            and (required is None or (r['game_id'], r['market']) in required)]
    manifest = dict(captures=captures, rows=rows, splits_available=False)
    (evidence/(before_write.strftime('%Y%m%dT%H%M%S%fZ')+'-manifest.json')).write_text(json.dumps(manifest, indent=2)+'\n')
    if not rows:
        raise ValueError('Backup returned no verified upcoming spread or total prices')
    append_market_snapshots(root, rows)
    return rows
