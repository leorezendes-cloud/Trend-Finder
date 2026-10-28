"""Immutable pre-kickoff weekly selection overlay for already-issued Plug O/U v1.

V1 per-game directions stay archived exactly as originally issued. V3 adds a
distinct weekly *selection* decision: all independently
signalled totals (>= 48) are official prospective Plug shortlist picks.
A missing/partial slate never publishes a reconstructed shortlist.
"""
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from plug_ou_receipts import archive, read as read_v1, _time
from plug_ou_all_qualifiers import POLICY_VERSION, shortlist
from plug_publication import immutable
from zoneinfo import ZoneInfo

def kickoff(game):
    """Lightweight schedule timestamp; identical timezone rule to Scout."""
    if not game.get('gameday') or not game.get('gametime'):
        raise ValueError('Missing scheduled kickoff')
    return datetime.fromisoformat(game['gameday']+'T'+game['gametime']).replace(
        tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)

def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def _weekly_file(root,season,week):
    if not 2000<=int(season)<=2100 or not 1<=int(week)<=22:
        raise ValueError('Invalid Plug O/U season/week')
    return archive(root)/'weekly_v3'/f'{int(season)}_{int(week):02}.json'

def read_week(root,season,week):
    """Read and verify the complete published policy, without modifying it."""
    path=_weekly_file(root,season,week)
    if not path.exists():return None
    receipt=json.loads(path.read_bytes())
    checksum=receipt.pop('receipt_sha256',None)
    if not isinstance(checksum,str) or hashlib.sha256(_canonical(receipt)).hexdigest()!=checksum:
        raise ValueError('Plug O/U weekly receipt checksum mismatch')
    if (receipt.get('policy_version')!=POLICY_VERSION or
        (receipt.get('season'),receipt.get('week'))!=(int(season),int(week)) or
        receipt.get('state')!='PUBLISHED_PREKICKOFF'):
        raise ValueError('Unknown Plug O/U weekly policy')
    games=receipt.get('games')
    if not isinstance(games,list) or not games:
        raise ValueError('Incomplete Plug O/U weekly receipt')
    identities=[g['game_id'] for g in games]
    if len(set(identities))!=len(identities) or identities!=sorted(identities):
        raise ValueError('Invalid Plug O/U weekly game identities')
    selected={g['game_id'] for g in games if type(g.get('selected')) is bool and g['selected']}
    if (any(type(g.get('selected')) is not bool for g in games) or
        selected!=set(receipt.get('selected_ids',[]))):
        raise ValueError('Plug O/U weekly selection mismatch')
    issued=_time(receipt['issued_at_utc'])
    for game in games:
        if issued>=_time(game['kickoff_utc']):
            raise ValueError('Plug O/U weekly policy issued after kickoff')
        # Require original v1 fingerprints; a historical source never changes.
        original=read_v1(root,game['game_id'])
        if original is None or hashlib.sha256(_canonical(original)).hexdigest()!=game['v1_sha256']:
            raise ValueError('Plug O/U weekly source receipt changed')
        if (original['kickoff_utc']!=game['kickoff_utc'] or
            original['side']!=game['side'] or
            float(original['market_total'])!=float(game['market_total'])):
            raise ValueError('Plug O/U weekly source identity mismatch')
    receipt['receipt_sha256']=checksum
    return receipt

def read_effective(root,game_id):
    """Read the selected side from v2, or a transparently marked legacy v1.

    No v1 per-game receipt is ever rewritten or hidden. A published v2 week
    overrides only the *official shortlist membership*, never its direction.
    """
    original=read_v1(root,game_id)
    if original is None:return None
    weekly=read_week(root,original['season'],original['week'])
    result=dict(original)
    if weekly is None:
        result.update(selected=False,selection_status='awaiting_weekly_selection',
                      shortlist_policy='pending-v3',
                      note='Original all-game v1 receipt archived; new v3 shortlist not yet issued')
        return result
    matches=[game for game in weekly['games'] if game['game_id']==game_id]
    if len(matches)!=1:
        raise ValueError('Published Plug O/U slate missing game')
    game=matches[0]
    result.update(selected=game['selected'],selection_status='selected' if game['selected'] else 'stay_away',
                  shortlist_policy=POLICY_VERSION,shortlist_issued_at_utc=weekly['issued_at_utc'])
    return result

def _slate(root,season,week):
    schedule=Path(root)/'nfl_games.csv'
    with schedule.open(newline='',encoding='utf-8-sig') as stream:
        rows=[r for r in csv.DictReader(stream)
              if r.get('game_type')=='REG'
              and r.get('season')==str(season)
              and r.get('week')==str(week)]
    if not rows:return []
    found={}
    for row in rows:
        game_id=row['game_id']
        if game_id in found:raise ValueError('Duplicate scheduled game')
        found[game_id]=kickoff(row)
    return sorted(found.items())

def issue_weekly(root,*,now=None):
    """Issue one complete weekly shortlist before its first kickoff.

    Expects v1 receipts to already exist for every scheduled game. A complete
    and fully sealed slate is essential: partial slates produce zero picks.
    No HTTP path or historical backfill calls this function.
    """
    root=Path(root)
    now=now or datetime.now(timezone.utc)
    # Only current 2026 regular-season weeks that have original v1 receipts
    # can be issued by this release, and never after the earliest kickoff.
    possible=defaultdict(list)
    for path in sorted(archive(root).glob('*.json')):
        if not path.stem.startswith('2026_'):continue
        original=read_v1(root,path.stem)
        possible[(int(original['season']),int(original['week']))].append(original)
    report={'published':0,'preserved':0,'pending_slate':0,'started':0,'selected':0}
    for (season,week),originals in sorted(possible.items()):
        existing=read_week(root,season,week)
        if existing is not None:
            report['preserved']+=1
            continue
        slate=_slate(root,season,week)
        if not slate:
            report['pending_slate']+=1
            continue
        if any(ko<=now for _,ko in slate):
            report['started']+=1
            continue
        original_by_id={r['game_id']:r for r in originals}
        if set(original_by_id)!={game_id for game_id,_ in slate}:
            report['pending_slate']+=1
            continue
        candidates=[]
        for game_id,kick in slate:
            source=original_by_id[game_id]
            if (_time(source['kickoff_utc'])!=kick or
                _time(source['issued_at_utc'])>=kick or
                _time(source['quote_observed_utc'])>_time(source['issued_at_utc'])):
                raise ValueError('Plug O/U v1 source not sealed before kickoff')
            gap=source.get('gap')
            # A saved <48 direction was inherited from Scout, not an independent
            # v14 selection. The exact model-market tie is also not a signal.
            line=float(source['market_total'])
            independent=(line>=48 and gap is not None and abs(float(gap))>1e-9)
            candidates.append(dict(game_id=game_id,season=season,week=week,
                side=source['side'],market_total=line,kickoff_utc=source['kickoff_utc'],
                v1_sha256=hashlib.sha256(_canonical(source)).hexdigest(),
                gap=float(gap) if independent else 0.0,eligible=bool(independent)))
        selected=shortlist(candidates)
        payload={'policy_version':POLICY_VERSION,'state':'PUBLISHED_PREKICKOFF',
                 'season':season,'week':week,'issued_at_utc':now.isoformat(),
                 'candidate_count':sum(c['eligible'] for c in candidates),
                 'total_games':len(candidates),'selected_ids':sorted(selected),
                 'games':[{**c,'selected':c['game_id'] in selected} for c in candidates],
                 'derivation':'All full-week nonzero independent v14 gaps at totals >=48; no quota. Eligibility is not a proven edge.'}
        payload['receipt_sha256']=hashlib.sha256(_canonical(payload)).hexdigest()
        path=_weekly_file(root,season,week)
        if any(now>=ko for _,ko in slate):
            report['started']+=1
            continue
        immutable(path,_canonical(payload))
        reread=read_week(root,season,week)
        report['published']+=1
        report['selected']+=len(reread['selected_ids'])
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Issue prospective immutable Plug O/U v3 shortlist, if complete')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--root',default=str(Path('/var/data/site-data') if Path('/var/data/site-data').exists() else Path(__file__).resolve().parent))
    args=parser.parse_args()
    print(json.dumps(issue_weekly(Path(args.root)),sort_keys=True))
