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


def _week_six_shadow_totals(root):
    """Load the sealed Week 6 replay from the frozen Market + statistics candidate."""
    import hashlib
    import json
    config=json.loads((Path(root)/'automatic_model.json').read_text())
    candidate=config.get('totals_candidate',{})
    model=candidate.get('model',{})
    if (config.get('totals_model_file_sha256') is None
            or model.get('version') != 'scout4-totals-1'
            or candidate.get('name') != 'Market + statistics'
            or config.get('target_season') != 2026
            or config.get('first_eligible_week') != 6):
        raise ValueError('Week 6 totals candidate is not the approved frozen model')
    from scout4.shadow import view
    records=[r for r in view(Path(root))['records']
             if r.get('season') == 2026 and r.get('week') == 6 and r.get('market') == 'Total']
    expected_hash=config['totals_model_file_sha256']
    if len(records) != 14 or any(r.get('model_sha256') != expected_hash
                                 or r.get('model_name') != 'Market + statistics'
                                 for r in records):
        raise ValueError('Week 6 shadow totals do not match the approved 14-game model cohort')
    output=[]
    seen=set()
    for record in records:
        gid=record['game_id']
        if gid in seen or record.get('selected_side') not in ('Over','Under'):
            raise ValueError('Invalid or duplicate Week 6 shadow total')
        seen.add(gid)
        result={'Correct':'Win','Wrong':'Loss','Push':'Push','Pending':'Pending',
                'No Call':'No Call','Review needed':'Pending'}.get(record.get('result'))
        if result is None:
            raise ValueError('Unrecognized Week 6 shadow grade')
        output.append(dict(
            game_id=gid,season=2026,week=6,away_team=record['away_team'],
            home_team=record['home_team'],kickoff_utc=record['kickoff_utc'],
            ou_side=record['selected_side'],total_quote=record['quote'],
            grades={'ou':result,'ats':'No Call','su':'No Call'},
            source='sealed historical simulation',model_version=model['version']))
    return output


def records(root, finals, season, week, *, now=None):
    """One Scout O/U cohort: Week 6 sealed replay plus later live-issued totals."""
    if season is None:
        return {}
    now=now or datetime.now(timezone.utc)
    rows=[];review=False
    live_enabled = os.environ.get('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC') == '1'
    if not live_enabled and int(season) != 2026:
        return {}
    for path in (sorted((Path(root)/'scout_dynamic').glob('*_*_*_*')) if live_enabled else []):
        if not path.is_dir():
            continue
        year,number,away,home=path.name.split('_')
        if int(year) != int(season) or (week is not None and int(number) != int(week)):
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
                rows.append(dict(row,grades=result,source='live-issued Dynamic Scout'))
        except (ValueError,OSError,KeyError,TypeError):
            review=True
    if int(season) == 2026 and (week is None or int(week) == 6):
        try:
            replay=_week_six_shadow_totals(root)
            live_ids={r['game_id'] for r in rows}
            rows.extend(r for r in replay if r['game_id'] not in live_ids)
        except (ValueError,OSError,KeyError,TypeError):
            review=True
    # Weeks 7+ use the already-published positive Scout totals lean.
    # This is intentionally not the ATS fade: totals are graded from the
    # saved pregame forecast and its frozen O/U quote.
    if int(season) == 2026 and (week is None or int(week) >= 7):
        try:
            import csv
            from forecast_history import official_sources, total_result
            schedule_path=Path(root)/'nfl_games.csv'
            with schedule_path.open(newline='') as handle:
                games={g['game_id']:g for g in csv.DictReader(handle)}
            saved=official_sources(Path(root))
            existing={r['game_id'] for r in rows}
            for record in saved.values():
                if (int(record.get('season',0)) != 2026
                        or int(record.get('week',0)) < 7
                        or (week is not None and int(record.get('week',0)) != int(week))
                        or record.get('game_id') in existing):
                    continue
                total=record.get('totals') or {}
                prediction=total.get('prediction') or {}
                lean=prediction.get('lean')
                if not total or lean not in ('Over','Under','No Call',None):
                    continue
                game=games.get(record.get('game_id'))
                outcome=total_result(record,game)
                result={'Correct':'Win','Wrong':'Loss','Win':'Win','Loss':'Loss',
                        'Push':'Push','Pending':'Pending','No Call':'No Call'}.get(outcome)
                if result is None:
                    raise ValueError('Unrecognized saved Scout totals grade')
                rows.append(dict(
                    game_id=record['game_id'],season=2026,week=int(record['week']),
                    away_team=record['away_team'],home_team=record['home_team'],
                    kickoff_utc=record['kickoff_utc'],ou_side=lean,
                    total_quote=total.get('quote',{}).get('line'),
                    grades={'ou':result,'ats':'No Call','su':'No Call'},
                    source='saved positive Scout totals'))
                existing.add(record['game_id'])
        except (ValueError,OSError,KeyError,TypeError):
            review=True
    rows.sort(key=lambda r:(int(r.get('week',0)),r.get('kickoff_utc',''),r.get('game_id','')))
    counts={m:{outcome:sum(r['grades'][m]==outcome for r in rows)
               for outcome in ('Win','Loss','Push','Pending','No Call','Tie')} for m in ('ats','ou','su')}
    # Make cohort coverage visible: an empty/missing receipt set is not a 0-0-0 record.
    import csv
    schedule_path=Path(root)/'nfl_games.csv'
    expected_ids=set()
    if schedule_path.exists():
        with schedule_path.open(newline='') as handle:
            for game in csv.DictReader(handle):
                try:
                    if (int(game.get('season',0))==int(season)
                            and game.get('game_type')=='REG'
                            and int(game.get('week',0)) >= 6
                            and (week is None or int(game.get('week',0))==int(week))):
                        expected_ids.add(game['game_id'])
                except (TypeError,ValueError,KeyError):
                    continue
    available_ids={r['game_id'] for r in rows if r.get('ou_side') in ('Over','Under')}
    coverage=dict(expected=len(expected_ids),available=len(expected_ids & available_ids),
                  missing=max(0,len(expected_ids)-len(expected_ids & available_ids)))
    return dict(scout_dynamic_records=rows,scout_dynamic_counts=counts,
                scout_dynamic_review=review,scout_dynamic_coverage=coverage)
