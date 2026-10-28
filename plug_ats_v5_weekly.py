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

def _utc(value):
    value=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Timezone required')
    return value.astimezone(timezone.utc)

def _json(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _receipt_path(year,week):
    if not 2019<=int(year)<=2100 or not 1<=int(week)<=22:raise ValueError('Bad ATS week')
    return storage_root()/f'{int(year)}_{int(week):02}_{POLICY}.json'

def read_week(year,week):
    path=_receipt_path(year,week)
    if not path.is_file():return None
    receipt=json.loads(path.read_bytes())
    stamp=receipt.pop('receipt_sha256',None)
    if not stamp or stamp!=hashlib.sha256(_json(receipt)).hexdigest():
        raise ValueError('ATS v5 receipt integrity error')
    if (receipt.get('policy')!=POLICY or receipt.get('status')!='PUBLISHED_BEFORE_FIRST_KICKOFF'
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
            _utc(r['sealed_at_utc'])>=_utc(r['kickoff_utc'])):
            raise ValueError('Late or unsealed ATS selection')
        expected=classify(r['model_away_spread'],r['away_line'],
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

def issue_pending(root,*,now=None):
    """Once-only pregame weekly publication, worker only, never an HTTP request."""
    root=Path(root);now=now or datetime.now(timezone.utc)
    report={'published':0,'preserved':0,'pending':0,'started':0,'selected':0}
    for (year,week),slate in sorted(_scheduled(root,now).items()):
        previous=read_week(year,week)
        if previous is not None:
            report['preserved']+=1
            continue
        if not slate or any(kick is None or kick<=now for _,kick in slate):
            report['started']+=1
            continue
        # Use only complete, verified, sealed production forecasts with the
        # original observed sportsbook spread. Never substitute closing lines.
        candidates=[]
        for g,kick in sorted(slate,key=lambda t:t[0]['game_id']):
            path=root/'data/scout4/blend/predictions'/(g['game_id']+'.json')
            if not path.is_file():break
            record=json.loads(path.read_bytes())
            pregame_record(record)
            q=record['quote']
            if (record.get('version')!='plug-points-only-4' or
                int(record['season'])!=year or int(record['week'])!=week or
                record['game_id']!=g['game_id'] or record['away_team']!=g['away_team'] or
                record['home_team']!=g['home_team'] or
                _utc(record['kickoff_utc'])!=kick or
                _utc(q['captured_at_utc'])>now or
                _utc(record['sealed_at_utc'])>now or
                q.get('market')!='Spread'):
                break
            line=float(q['line'])
            if not math.isfinite(line):break
            candidates.append(dict(game_id=g['game_id'],season=year,week=week,
                away_team=g['away_team'],home_team=g['home_team'],
                kickoff_utc=kick.isoformat(),away_line=line,
                quote_observed_utc=q['captured_at_utc'],
                sealed_at_utc=record['sealed_at_utc'],
                source_sha256=_digest(path)))
        if len(candidates)!=len(slate):
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
            model=float(pred[r['game_id']])
            r['model_away_spread']=model
            r['gap']=round(model-r['away_line'],6)
            r['side']=classify(model,r['away_line'],r['away_team'],r['home_team'])
            r['selected']=r['side'] is not None
        # Final cutoff check after expensive fitting, before first-write.
        if any(kick<=datetime.now(timezone.utc) for _,kick in slate):
            report['started']+=1
            continue
        receipt=dict(policy=POLICY,status='PUBLISHED_BEFORE_FIRST_KICKOFF',
                     season=year,week=week,issued_at_utc=datetime.now(timezone.utc).isoformat(),
                     total_games=len(candidates),selected_ids=sorted(r['game_id']
                        for r in candidates if r['selected']),games=candidates,
                     derivation='Follow independent v5 when 0<|v5 away spread - frozen Vegas away spread|<1 and |Vegas away spread|>7. No quota. Exact agreement is Stay Away.',
                     v5_code_sha256=_digest(Path(__file__).with_name('plug_ats_v5_model.py')))
        receipt['receipt_sha256']=hashlib.sha256(_json(receipt)).hexdigest()
        path=_receipt_path(year,week)
        try:
            immutable(path,_json(receipt))
        except ValueError:
            if read_week(year,week) is None:raise
        verify=read_week(year,week)
        report['published']+=1
        report['selected']+=len(verify['selected_ids'])
    return report

def _older_week(year,week):
    old=storage_root()/f'{int(year)}_{int(week):02}_{LEGACY_POLICY}.json'
    return read_legacy(old) if old.is_file() else None

def effective_week(year,week):
    updated=read_week(year,week)
    return updated if updated is not None else _older_week(year,week)

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

def published_history(final_scores):
    """Separately sourced v1+v2 receipts, newer policy wins only on overlap."""
    receipts={}
    for path in storage_root().glob('*.json'):
        if not path.name.endswith((POLICY+'.json', LEGACY_POLICY+'.json')):continue
        try:
            parts=path.stem.split('_')
            year,week=int(parts[0]),int(parts[1])
            receipt=effective_week(year,week)
            if receipt:receipts[(year,week)]=receipt
        except (ValueError,OSError,TypeError,KeyError):
            raise
    rows=[];seasons=defaultdict(Counter)
    for receipt in receipts.values():
        for r in receipt['games']:
            if not r['selected']:continue
            result=grade(r,final_scores.get(r['game_id']))
            row={**r,'policy':receipt['policy'],'issued_at_utc':receipt['issued_at_utc'],
                 'result':result or 'Pending'}
            rows.append(row);seasons[int(r['season'])][row['result']]+=1
    rows.sort(key=lambda r:(r['kickoff_utc'],r['game_id']),reverse=True)
    return rows,{y:dict(c) for y,c in sorted(seasons.items(),reverse=True)}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--root',default=str(Path('/var/data/site-data') if Path('/var/data/site-data').exists() else Path(__file__).resolve().parent))
    args=parser.parse_args()
    print(json.dumps(issue_pending(args.root),sort_keys=True))
