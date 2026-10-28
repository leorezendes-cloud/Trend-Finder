"""Immutable, separately graded Plug O/U selections. Never modifies Scout files.

Issued once before kickoff from frozen Scout quote + independent v14. The
original saved Scout forecast and any archived Expert report remain unchanged.
"""
import hashlib
import json
import math
from datetime import datetime,timezone
from pathlib import Path

from forecast_history import pregame_record
from plug_publication import immutable
from plug_totals_policy import select, POLICY_VERSION

MODEL_VERSION='independent-vegas-v14-2026'

def archive(root):
    return Path(root)/'data/scout4/blend/plug_ou'

def _time(value):
    instant=datetime.fromisoformat(value.replace('Z','+00:00'))
    if instant.tzinfo is None:raise ValueError('Timezone required')
    return instant

def _file(root,game_id):
    if not isinstance(game_id,str) or not game_id.replace('_','').isalnum() or '/' in game_id:
        raise ValueError('Invalid game ID')
    return archive(root)/(game_id+'.json')

def read(root,game_id,*,verify_source=True):
    path=_file(root,game_id)
    if not path.exists():return None
    receipt=json.loads(path.read_bytes())
    if receipt.get('game_id')!=game_id or receipt.get('policy_version')!=POLICY_VERSION:
        raise ValueError('Invalid Plug O/U receipt')
    if receipt.get('side') not in ('Over','Under'):
        raise ValueError('Invalid Plug O/U side')
    if not _time(receipt['issued_at_utc'])<_time(receipt['kickoff_utc']):
        raise ValueError('Plug O/U receipt issued after kickoff')
    if not _time(receipt['quote_observed_utc'])<=_time(receipt['issued_at_utc']):
        raise ValueError('Plug O/U quote issued after selection')
    if not 10<float(receipt['market_total'])<90:
        raise ValueError('Invalid Plug O/U receipt total')
    if verify_source:
        path=Path(root)/'data/scout4/blend/predictions'/(game_id+'.json')
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['source_sha256']:
            raise ValueError('Plug O/U original Scout source mismatch')
        source=json.loads(path.read_bytes())
        pregame_record(source)
        if receipt['original_scout_side']!=source['totals']['prediction']['lean']:
            raise ValueError('Original Scout total changed')
        if float(receipt['market_total'])!=float(source['totals']['quote']['line']):
            raise ValueError('Plug O/U quote changed')
        if receipt['kickoff_utc']!=source['kickoff_utc']:
            raise ValueError('Plug O/U kickoff mismatch')
    return receipt

def grade(receipt,away_score=None,home_score=None):
    if not receipt or away_score in ('',None) or home_score in ('',None):
        return 'Pending'
    try:
        away,home=float(away_score),float(home_score)
        if not all(math.isfinite(x) and x>=0 and x.is_integer() for x in (away,home)):
            return 'Pending'
        gap=away+home-float(receipt['market_total'])
        return 'Push' if abs(gap)<1e-9 else (
            'Win' if (gap>0)==(receipt['side']=='Over') else 'Loss')
    except (ValueError,TypeError,KeyError):
        return 'Pending'

def issue_pending(root,*,now=None,projection_fn=None):
    """Compute full slate once; install only verified future-game decisions.

    This does not run from HTTP requests. Existing receipts stay unchanged.
    No data from after the target game week is used to construct v14 features.
    """
    root=Path(root)
    now=now or datetime.now(timezone.utc)
    folder=root/'data/scout4/blend/predictions'
    pending=[]
    for path in sorted(folder.glob('*.json')):
        source_bytes=path.read_bytes()
        record=json.loads(source_bytes)
        if path.stem!=record['game_id'] or int(record.get('season',0))!=2026:
            continue
        if _time(record['kickoff_utc'])<=now:
            continue
        existing=read(root,record['game_id'])
        if existing is not None:
            continue
        pregame_record(record)
        if record.get('status')!='SEALED_PREKICKOFF_RESEARCH':
            continue
        total=record.get('totals')
        if not total or total['prediction'].get('lean') not in ('Over','Under'):
            continue
        if total['quote'].get('market')!='Total':
            continue
        captured=_time(total['quote']['captured_at_utc'])
        if captured>_time(record['decision_cutoff_utc']) or captured>=_time(record['kickoff_utc']):
            continue
        pending.append((record,hashlib.sha256(source_bytes).hexdigest()))
    status={'eligible':len(pending),'issued':0,'preserved':0,'missing_model':0}
    if not pending:return status
    if projection_fn is None:
        from plug_v14_model import projections
        projection_fn=projections
    schedule=root/'nfl_games.csv'
    schedule_bytes=schedule.read_bytes()
    schedule_hash=hashlib.sha256(schedule_bytes).hexdigest()
    estimates=projection_fn(schedule,season=2026,eligible_ids={r['game_id'] for r,_ in pending})
    for record,digest in pending:
        game_id=record['game_id']
        estimate=estimates.get(game_id)
        if estimate is None:
            status['missing_model']+=1
            continue
        quote=record['totals']['quote']
        line=float(quote['line'])
        if not math.isfinite(line) or not 10<line<90:
            raise ValueError('Invalid saved market total')
        decision=select(record['totals']['prediction']['lean'],line,estimate)
        receipt={
            'game_id':game_id,'season':2026,'week':int(record['week']),
            'away_team':record['away_team'],'home_team':record['home_team'],
            'kickoff_utc':record['kickoff_utc'],'issued_at_utc':now.isoformat(),
            'policy_version':POLICY_VERSION,'model_version':MODEL_VERSION,
            'source_sha256':digest,'schedule_snapshot_sha256':schedule_hash,
            'quote_observed_utc':quote['captured_at_utc'],
            'market_total':line,'v14_total':estimate,
            'original_scout_side':record['totals']['prediction']['lean'],
            'side':decision['side'],'decision_source':decision['source'],
            'gap':decision['gap']}
        if now>=_time(record['kickoff_utc']):
            continue
        raw=json.dumps(receipt,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        path=_file(root,game_id)
        immutable(path,raw)
        if path.read_bytes()!=raw:
            raise ValueError('Conflicting issued Plug O/U selection')
        status['issued']+=1
    return status
