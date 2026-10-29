"""Read-only Scout presentation/grades, gated by prospective worker issuance.

No projections are calculated on requests. Plug/Expert inputs stay untouched.
"""
from datetime import datetime, timezone
from pathlib import Path
import os

from scout_dynamic_store import (POLICY, canonical, checked_read, closing, folder,
                                 grade, journal, signed, utc)


def activation(root):
    path=Path(root)/'scout_dynamic/activation.json'
    if not path.exists():
        return None
    data=checked_read(path)
    if data['policy'] != POLICY:
        raise ValueError('Unrecognized Scout activation')
    utc(data['activated_at'])
    return data


def enroll(root, gid, row, *, now):
    if os.environ.get('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC') != '1':
        return
    gate=activation(root)
    if gate is None or not utc(gate['activated_at']) <= now < utc(row['kickoff_utc']):
        return
    if gate['configuration_sha256'] != row['configuration_sha256']:
        raise ValueError('Scout activation configuration differs')
    from plug_publication import immutable
    path=folder(root,gid)/'issued.json'
    if not path.exists():
        immutable(path,canonical(signed(dict(policy=POLICY,game_id=gid,
            issued_at=now.isoformat(),kickoff_utc=row['kickoff_utc'],
            configuration_sha256=row['configuration_sha256']))))


def state(root, game, *, now):
    if os.environ.get('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC') != '1':
        return None
    gate=activation(root)
    if gate is None or utc(game['kickoff_utc']) <= utc(gate['activated_at']):
        return None
    gid=game['game_id'];path=folder(root,gid)/'issued.json'
    if not path.exists():
        raise ValueError('Awaiting prospective Scout issuance')
    issued=checked_read(path)
    if (issued['policy'] != POLICY or issued['game_id'] != gid
            or not utc(gate['activated_at']) <= utc(issued['issued_at']) <= now
            or utc(issued['issued_at']) >= utc(game['kickoff_utc'])
            or utc(issued['kickoff_utc']) != utc(game['kickoff_utc'])):
        raise ValueError('Invalid Scout issuance')
    if now >= utc(game['kickoff_utc']):
        row=closing(root,gid)
        if row is None:
            raise ValueError('Awaiting immutable Scout closing snapshot')
        status='locked'
    else:
        rows=journal(root,gid)
        if not rows:
            raise ValueError('Scout revisions unavailable')
        row=rows[-1];status='pregame'
    if (utc(row['kickoff_utc']) != utc(game['kickoff_utc']) or utc(row['evaluated_at']) > now
            or any(row[k] != game[k] for k in ('away_team','home_team'))
            or row['configuration_sha256'] != gate['configuration_sha256']
            or issued['configuration_sha256'] != row['configuration_sha256']):
        raise ValueError('Scout public identity differs from saved prediction')
    return dict(status=status,row=row)


def attach(root, item, *, now):
    """Add a separate display field; never mutate saved_picks, scout or Plug fields."""
    item.pop('scout_dynamic',None)
    try:
        value=state(root,item['scout']['game'],now=now)
        if value is not None:
            if value['status']=='locked':
                final=item.get('final_score')
                if final is None:
                    from plug_dashboard import _completed_games
                    scores=_completed_games(Path(root)).get(value['row']['game_id'])
                    final={'away':scores[0],'home':scores[1]} if scores else None
                value['grades']=grade(value['row'], (final['away'],final['home']) if final else None)
            item['scout_dynamic']=value
    except (ValueError,OSError,KeyError,TypeError) as error:
        if os.environ.get('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC') == '1':
            item['scout_dynamic']=dict(status='review',message='Scout update awaiting verified evidence.')
    return item


def records(root, finals, season, week, *, now=None):
    """Separate dynamic cohort. Never aggregate with first-issued Scout results."""
    if os.environ.get('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC') != '1' or season is None or week is None:
        return {}
    now=now or datetime.now(timezone.utc)
    rows=[];review=False
    for path in sorted((Path(root)/'scout_dynamic').glob('*_*_*_*')):
        if not path.is_dir():
            continue
        year,number,away,home=path.name.split('_')
        if (int(year),int(number)) != (int(season),int(week)):
            continue
        try:
            saved=journal(root,path.name)
            if not saved:
                continue
            game={k:saved[-1][k] for k in ('game_id','away_team','home_team','kickoff_utc')}
            value=state(root,game,now=now)
            if value:
                row=value['row']
                result=grade(row,finals.get(path.name) if value['status']=='locked' else None)
                rows.append(dict(row,grades=result))
        except (ValueError,OSError,KeyError,TypeError):
            review=True
    counts={m:{outcome:sum(r['grades'][m]==outcome for r in rows)
               for outcome in ('Win','Loss','Push','Pending','No Call','Tie')} for m in ('ats','ou','su')}
    return dict(scout_dynamic_records=rows,scout_dynamic_counts=counts,scout_dynamic_review=review)
