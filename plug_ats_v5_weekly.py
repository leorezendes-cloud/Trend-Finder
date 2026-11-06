"""Prospective independent ATS market-model v5 selection.

Does not mutate historic Plug v1 receipts, Scout forecasts, or O/U.
A complete week of approved pre-kickoff quotes is required. Historical
performance replays NEVER become published picks.
"""
import csv
import hashlib
import json
import math
import os
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from plug_ats_v5_model import projections
from plug_ats_select import storage_root, _read as read_legacy, POLICY as LEGACY_POLICY
from plug_publication import immutable
from forecast_history import pregame_record

POLICY='plug-ats-independent-v5-favorite-near-market-v2'
SCOUT_POLICY='plug-ats-scout-stats-follow-fade-v1'

def _utc(value):
    value=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Timezone required')
    return value.astimezone(timezone.utc)

def _json(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _receipt_path(year,week,policy=POLICY):
    if not 2019<=int(year)<=2100 or not 1<=int(week)<=22:raise ValueError('Bad ATS week')
    return storage_root()/f'{int(year)}_{int(week):02}_{policy}.json'

def read_week(year,week,policy=POLICY):
    path=_receipt_path(year,week,policy)
    if path.is_file():
        return _read_receipt(path, year, week, policy, 'PUBLISHED_BEFORE_FIRST_KICKOFF')
    if policy != SCOUT_POLICY:
        return None
    rows = []
    for game_path in sorted(_scout_game_dir(year, week).glob('*.json')):
        receipt = _read_receipt(game_path, year, week, policy, 'PUBLISHED_BEFORE_GAME_KICKOFF')
        if len(receipt['games']) != 1 or receipt['games'][0]['game_id'] != game_path.stem:
            raise ValueError('Scout ATS receipt game mismatch')
        rows.append({**receipt['games'][0], 'issued_at_utc': receipt['issued_at_utc']})
    if not rows:
        return None
    return dict(policy=policy, season=year, week=week, games=rows,
                issued_at_utc=max(row['issued_at_utc'] for row in rows),
                selected_ids=sorted(row['game_id'] for row in rows if row['selected']))


def _scout_game_dir(year, week):
    return storage_root() / SCOUT_POLICY / f'{int(year)}_{int(week):02}'


def _read_receipt(path, year, week, policy, status):
    receipt=json.loads(path.read_bytes())
    stamp=receipt.pop('receipt_sha256',None)
    if not stamp or stamp!=hashlib.sha256(_json(receipt)).hexdigest():
        raise ValueError('ATS v5 receipt integrity error')
    if (receipt.get('policy')!=policy or receipt.get('status')!=status
        or int(receipt['season'])!=int(year) or int(receipt['week'])!=int(week)):
        raise ValueError('Unrecognized ATS selection receipt')
    rows=receipt['games']
    if not rows or len({r['game_id'] for r in rows})!=len(rows):
        raise ValueError('Incomplete ATS week')
    ids=sorted(r['game_id'] for r in rows if r['selected'])
    if ids!=receipt['selected_ids']:raise ValueError('Incorrect ATS shortlist identifiers')
    issued=_utc(receipt['issued_at_utc'])
    for r in rows:
        if (issued>=_utc(r['kickoff_utc']) or
            _utc(r['quote_observed_utc'])>issued or
            _utc(r['sealed_at_utc'])>issued):
            raise ValueError('Late or unsealed ATS selection')
        selector = classify_scout if policy == SCOUT_POLICY else classify
        expected=selector(r['model_away_spread'],r['away_line'],
                          r['away_team'],r['home_team'])
        if r['selected']!=bool(expected) or r['side']!=expected:
            raise ValueError('ATS v5 rule disagreeing with receipt')
    receipt['receipt_sha256']=stamp
    return receipt

def classify(model_away_spread, market_away_spread, away_team, home_team):
    """Independent v5 near the market: both strict thresholds; no forced pick."""
    model=float(model_away_spread);line=float(market_away_spread)
    if not math.isfinite(model) or not math.isfinite(line):
        raise ValueError('Nonfinite model or Vegas spread')
    gap=model-line
    if abs(line)<=7 or not 1e-9<abs(gap)<1:
        return None
    return away_team if gap<0 else home_team

def classify_scout(model_away_spread, market_away_spread, away_team, home_team):
    """Follow Scout above seven; fade moderate gaps on smaller spreads."""
    model, line = float(model_away_spread), float(market_away_spread)
    if not math.isfinite(model) or not math.isfinite(line):
        raise ValueError('Nonfinite Scout projection or Vegas spread')
    gap = model - line
    if abs(gap) <= 1e-9:
        return None
    if abs(line) > 7:
        return away_team if gap < 0 else home_team
    if 1 <= abs(gap) < 3:
        return home_team if gap < 0 else away_team
    return None


def _scheduled(root,now):
    with (Path(root)/'nfl_games.csv').open(newline='',encoding='utf-8-sig') as f:
        games=list(csv.DictReader(f))
    possible=defaultdict(list)
    for g in games:
        if g.get('game_type')!='REG':continue
        try:year,week=int(g['season']),int(g['week'])
        except (ValueError,TypeError,KeyError):continue
        if year<2026:continue
        kick=None
        if g.get('gameday') and g.get('gametime'):
            try:
                kick=datetime.fromisoformat(g['gameday']+'T'+g['gametime']).replace(
                    tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
            except (ValueError,TypeError):pass
        # Include the ENTIRE scheduled week, including games already started
        # or missing kickoff, so partial slates cannot be issued after kickoff.
        possible[(year,week)].append((g,kick))
    return {key:slate for key,slate in possible.items()
            if any(kick is not None and now<kick<=now+timedelta(days=10)
                   for _,kick in slate)}

def _candidate(root, game, kickoff, year, week, now, *, scout=False):
    game_id = game['game_id']
    path = root / 'data/scout4/blend/predictions' / (game_id + '.json')
    try:
        raw = path.read_bytes()
        record = json.loads(raw)
        pregame_record(record)
        quote = record['quote']
        if (record.get('version') != 'plug-points-only-4'
                or int(record['season']) != year or int(record['week']) != week
                or any(record[key] != game[key] for key in ('game_id', 'away_team', 'home_team'))
                or _utc(record['kickoff_utc']) != kickoff
                or _utc(quote['captured_at_utc']) > now
                or _utc(record['sealed_at_utc']) > now or quote.get('market') != 'Spread'):
            return None
        line = float(quote['line'])
        if not math.isfinite(line):
            return None
        row = dict(game_id=game_id, season=year, week=week, away_team=game['away_team'],
                   home_team=game['home_team'], kickoff_utc=kickoff.isoformat(),
                   away_line=line, quote_observed_utc=quote['captured_at_utc'],
                   sealed_at_utc=record['sealed_at_utc'], source_sha256=hashlib.sha256(raw).hexdigest())
        if scout:
            model = -float(record['scout_scoring']['margin_first'])
            side = classify_scout(model, line, row['away_team'], row['home_team'])
            row.update(model_away_spread=model, gap=round(model-line, 6), side=side,
                       selected=side is not None)
        return row
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _issue_scout_games(root, now):
    report = dict(published=0, preserved=0, pending=0, started=0, selected=0)
    for (year, week), slate in sorted(_scheduled(root, now).items()):
        existing = read_week(year, week, SCOUT_POLICY)
        saved = {row['game_id'] for row in existing['games']} if existing else set()
        for game, kickoff in slate:
            game_id = game['game_id']
            if game_id in saved:
                report['preserved'] += 1
                continue
            if kickoff is None or kickoff <= now:
                report['started'] += 1
                continue
            if kickoff > now + timedelta(days=10):
                continue
            row = _candidate(root, game, kickoff, year, week, now, scout=True)
            if row is None:
                report['pending'] += 1
                continue
            path = _scout_game_dir(year, week) / (game_id + '.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            issued = datetime.now(timezone.utc)
            if kickoff <= issued:
                report['started'] += 1
                continue
            status = 'PUBLISHED_BEFORE_GAME_KICKOFF'
            receipt = dict(policy=SCOUT_POLICY, status=status, season=year, week=week,
                           issued_at_utc=issued.isoformat(), total_games=1,
                           selected_ids=[game_id] if row['selected'] else [], games=[row])
            receipt['receipt_sha256'] = hashlib.sha256(_json(receipt)).hexdigest()
            try:
                immutable(path, _json(receipt))
            except ValueError:
                _read_receipt(path, year, week, SCOUT_POLICY, status)
                report['preserved'] += 1
                continue
            report['published'] += 1
            report['selected'] += int(row['selected'])
    return report


def issue_pending(root,*,now=None,policy=POLICY,require_scout_receipt=False):
    """Once-only pregame weekly publication, worker only, never an HTTP request."""
    root=Path(root);now=now or datetime.now(timezone.utc)
    if policy == SCOUT_POLICY:
        return _issue_scout_games(root, now)
    report={'published':0,'preserved':0,'pending':0,'started':0,'selected':0}
    for (year,week),slate in sorted(_scheduled(root,now).items()):
        previous=read_week(year,week,policy)
        if require_scout_receipt and previous is None and read_week(year,week,SCOUT_POLICY) is None:
            continue
        if previous is not None:
            report['preserved']+=1
            continue
        if not slate or any(kick is None or kick<=now for _,kick in slate):
            report['started']+=1
            continue
        candidates = []
        for g, kick in sorted(slate, key=lambda item: item[0]['game_id']):
            candidate = _candidate(root, g, kick, year, week, now)
            if candidate is None:
                break
            candidates.append(candidate)
        if len(candidates)!=len(slate):
            report['pending']+=1
            continue
        if policy == POLICY:
            # An unfinished previous week means QB history and team-form
            # features are incomplete. Do not silently fit from a partial season.
            with (root/'nfl_games.csv').open(newline='',encoding='utf-8-sig') as stream:
                prior=[g for g in csv.DictReader(stream)
                       if g.get('game_type')=='REG' and str(g.get('season'))==str(year)
                       and g.get('week') and int(g['week'])<week]
            if any((g.get('away_score') in ('',None) or
                    g.get('home_score') in ('',None)) for g in prior):
                report['pending']+=1
                continue
            try:
                pred=projections(root/'nfl_games.csv',year,week)
            except (OSError,ValueError,KeyError,TypeError):
                report['pending']+=1
                continue
            if set(pred)!={r['game_id'] for r in candidates}:
                report['pending']+=1
                continue
        for r in candidates:
            model = float(pred[r['game_id']])
            r['model_away_spread']=model
            r['gap']=round(model-r['away_line'],6)
            r['side']=classify(model,r['away_line'],r['away_team'],r['home_team'])
            r['selected']=r['side'] is not None
        # Final cutoff check after expensive fitting, before first-write.
        if any(kick<=datetime.now(timezone.utc) for _,kick in slate):
            report['started']+=1
            continue
        receipt=dict(policy=policy,status='PUBLISHED_BEFORE_FIRST_KICKOFF',
                     season=year,week=week,issued_at_utc=datetime.now(timezone.utc).isoformat(),
                     total_games=len(candidates),selected_ids=sorted(r['game_id']
                        for r in candidates if r['selected']),games=candidates,
                     derivation='Follow independent v5 when 0<|v5 away spread - frozen Vegas away spread|<1 and |Vegas away spread|>7. No quota. Exact agreement is Stay Away.',
                     )
        receipt['v5_code_sha256'] = _digest(Path(__file__).with_name('plug_ats_v5_model.py'))
        receipt['receipt_sha256']=hashlib.sha256(_json(receipt)).hexdigest()
        path=_receipt_path(year,week,policy)
        try:
            immutable(path,_json(receipt))
        except ValueError:
            if read_week(year,week,policy) is None:raise
        verify=read_week(year,week,policy)
        report['published']+=1
        report['selected']+=len(verify['selected_ids'])
    return report

def _older_week(year,week):
    old=storage_root()/f'{int(year)}_{int(week):02}_{LEGACY_POLICY}.json'
    return read_legacy(old) if old.is_file() else None

def effective_week(year,week):
    updated=read_week(year,week,SCOUT_POLICY) or read_week(year,week)
    if updated is not None:return updated
    legacy=_older_week(year,week)
    if legacy is None:return None
    # Historical v1 receipts remain readable, but do not advertise the old
    # top-quarter policy as this week's current v5 recommendations.
    if all(_utc(r['kickoff_utc'])>datetime.now(timezone.utc)
           for r in legacy['games']):
        return None
    return legacy

def for_game(game_id):
    try:
        year,week,*_=game_id.split('_')
        receipt=effective_week(int(year),int(week))
        return next((r for r in receipt['games'] if r['game_id']==game_id),None) if receipt else None
    except (TypeError,ValueError,KeyError,OSError):return None

def decorate_dashboard(sections,now):
    """Read-only. Never create a legacy v1 shortlist on page views."""
    groups=defaultdict(list)
    for key in ('games','underway_games','completed_games','awaiting_games'):
        for item in sections.get(key,[]):
            game=item['scout']['game']
            groups[(int(game['season']),int(game['week']))].append(item)
    for (year,week),items in groups.items():
        try:receipt=effective_week(year,week)
        except (OSError,ValueError,KeyError,TypeError):receipt=None
        rows={r['game_id']:r for r in receipt['games']} if receipt else {}
        for item in items:
            gid=item['scout']['game']['game_id']
            row=rows.get(gid)
            item['plug_ats_policy']=receipt['policy'] if row else None
            item['plug_ats_status']=('selected' if row['selected'] else 'stay_away') if row else 'pending'
            item['plug_ats_decision']=row
            final=item.get('final_score')
            item['plug_ats_result']=grade(row, (final['away'],final['home'])) if row and final else None
    return sections

def grade(row,scores):
    if not row or not row['selected'] or scores is None:return None
    away,home=map(float,scores)
    edge=away-home+float(row['away_line'])
    if abs(edge)<1e-9:return 'Push'
    return 'Win' if (edge>0)==(row['side']==row['away_team']) else 'Loss'

def published_history(final_scores, *, scout_only=False):
    """Separately sourced v1+v2 receipts, newer policy wins only on overlap."""
    receipts={}
    for path in storage_root().glob('*.json'):
        if not path.name.endswith((POLICY+'.json', LEGACY_POLICY+'.json', SCOUT_POLICY+'.json')):continue
        try:
            parts=path.stem.split('_')
            year,week=int(parts[0]),int(parts[1])
            if scout_only and not path.name.endswith(SCOUT_POLICY+'.json'):
                continue
            receipt=read_week(year,week,SCOUT_POLICY) if scout_only else effective_week(year,week)
            if receipt:receipts[(year,week)]=receipt
        except (ValueError,OSError,TypeError,KeyError):
            raise
    for folder in (storage_root() / SCOUT_POLICY).glob('[0-9][0-9][0-9][0-9]_[0-9][0-9]'):
        year, week = map(int, folder.name.split('_'))
        if (year, week) not in receipts:
            receipt = read_week(year, week, SCOUT_POLICY)
            if receipt:
                receipts[(year, week)] = receipt
    rows=[];seasons=defaultdict(Counter)
    for receipt in receipts.values():
        for r in receipt['games']:
            if not r['selected']:continue
            result=grade(r,final_scores.get(r['game_id']))
            row={**r,'policy':receipt['policy'],'issued_at_utc':r.get('issued_at_utc',receipt['issued_at_utc']),
                 'result':result or 'Pending'}
            rows.append(row);seasons[int(r['season'])][row['result']]+=1
    rows.sort(key=lambda r:(r['kickoff_utc'],r['game_id']),reverse=True)
    return rows,{y:dict(c) for y,c in sorted(seasons.items(),reverse=True)}

def scout_ats_replay(season, week=None):
    """Read the frozen 2026 replay. A live weekly receipt takes precedence."""
    if season != 2026:
        return []
    path = Path(__file__).with_name('plug_scout_ats_replay_2026.json')
    replay = json.loads(path.read_text())
    weeks = [w for w in replay['weeks'] if week is None or w == week]
    replay_weeks = {w for w in weeks if read_week(season, w, SCOUT_POLICY) is None}
    rows = []
    for game in replay['games']:
        if game['week'] not in replay_weeks:
            continue
        side = classify_scout(game['model_away_spread'], game['away_line'],
                              game['away_team'], game['home_team'])
        if side is None:
            raise ValueError('Frozen Scout ATS replay contains a nonqualifying game')
        row = {**game, 'side': side, 'selected': True, 'replay': True}
        row['result'] = grade(row, (game['away_score'], game['home_score']))
        rows.append(row)
    return rows


def scout_ats_record(final_scores, season, week=None):
    """Show current-policy live picks and the labeled historical replay."""
    outcomes = ('Win', 'Loss', 'Push', 'Pending')
    tally = {name: dict.fromkeys(outcomes, 0) for name in ('Follow', 'Fade')}
    rows = []
    review = False
    try:
        issued, _ = published_history(final_scores, scout_only=True)
        issued += scout_ats_replay(season, week)
    except (OSError, ValueError, TypeError, KeyError):
        issued, review = [], True
    for row in issued:
        if int(row['season']) != season or (week is not None and int(row['week']) != week):
            continue
        rule = 'Follow' if abs(row['away_line']) > 7 else 'Fade'
        line = row['away_line'] if row['side'] == row['away_team'] else -row['away_line']
        tally[rule][row['result']] += 1
        rows.append({**row, 'rule': rule, 'pick': f"{row['side']} {line:+g}"})
    rows.sort(key=lambda row: (row['week'], row['game_id']), reverse=True)
    combined = {outcome: sum(tally[name][outcome] for name in tally) for outcome in outcomes}
    # Preserve existing display fields, while exposing separate source-of-truth
    # totals so retrospective rule discovery cannot be mistaken for live picks.
    cohorts = {}
    by_week = {}
    for name, selected_rows in (
        ('issued', [row for row in rows if not row.get('replay')]),
        ('replay', [row for row in rows if row.get('replay')]),
    ):
        counts = {outcome: sum(row['result'] == outcome for row in selected_rows)
                  for outcome in outcomes}
        cohorts[name] = {**counts, 'selections': len(selected_rows)}
        for row in selected_rows:
            week_counts = by_week.setdefault(int(row['week']), {}).setdefault(
                name, dict.fromkeys((*outcomes, 'selections'), 0))
            week_counts[row['result']] += 1
            week_counts['selections'] += 1
    return dict(rows=rows, rules=tally, combined=combined, cohorts=cohorts,
                by_week=by_week, review=review)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--root',default=str(Path('/var/data/site-data') if Path('/var/data/site-data').exists() else Path(__file__).resolve().parent))
    args=parser.parse_args()
    report = {'scout_ats': issue_pending(args.root, policy=SCOUT_POLICY)}
    if os.environ.get('TREND_FINDAH_DYNAMIC_OFFICIAL') == '1' or os.environ.get('TREND_FINDAH_DYNAMIC_RESEARCH') == '1':
        # Dynamic totals still verify their original v5 source. Its ATS side
        # does not supersede the new Scout-stats selection.
        report['dynamic_source'] = issue_pending(args.root, require_scout_receipt=True)
    print(json.dumps(report, sort_keys=True))
