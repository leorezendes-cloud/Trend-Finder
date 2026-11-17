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
    """Attach current-policy Scout picks; never expose archived Blend picks as live."""
    item.pop('scout_dynamic',None)
    item.pop('scout_current_ats',None)
    try:
        game=item['scout']['game']
        value=state(root,game,now=now)
        if value is not None:
            if value['status']=='locked':
                final=item.get('final_score')
                if final is None:
                    from plug_dashboard import _completed_games
                    scores=_completed_games(Path(root)).get(value['row']['game_id'])
                    final={'away':scores[0],'home':scores[1]} if scores else None
                value['grades']=grade(value['row'], (final['away'],final['home']) if final else None)
            item['scout_dynamic']=value
        from forecast_history import official_sources
        source=official_sources(Path(root)).get(game['game_id'])
        if source:
            from scout_fade import pick_for_record, grade_pick
            side=pick_for_record(source,root)
            if side:
                line=float(source['quote']['line'])
                signed_line=line if side==game['away_team'] else -line
                final=item.get('final_score')
                score_game=dict(game)
                if final:
                    score_game.update(away_score=final.get('away'),home_score=final.get('home'))
                else:
                    from plug_dashboard import _completed_games
                    scores=_completed_games(Path(root)).get(game['game_id'])
                    if scores:score_game.update(away_score=scores[0],home_score=scores[1])
                item['scout_current_ats']=dict(side=side,pick=f'{side} {signed_line:+g}',
                    result=grade_pick(source,score_game,side))
    except (ValueError,OSError,KeyError,TypeError):
        if os.environ.get('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC') == '1':
            item['scout_dynamic']=dict(status='review',message='Scout update awaiting verified evidence.')
    # Keep the previous signed ATS journal available, but never expose its
    # retired O/U projection in the public Scout card.
    value=item.get('scout_dynamic')
    if isinstance(value,dict) and isinstance(value.get('row'),dict) and value['row'].get('totals',{}).get('model')!='scout5-ou-v1':
        item.pop('scout_dynamic',None)
    # Existing archived Scout O/U fields are obsolete. The new compact replay
    # replaces the public O/U side and grade without touching any ATS fields.
    try:
        from scout5_totals import load_bundle
        game=item['scout']['game']
        bundle=load_bundle(Path(__file__).resolve().parent/'scout5_ou_bundle.json')
        replay=next((r for r in bundle.get('replay_history',[])
                     if r['game_id']==game['game_id']),None)
        if replay is not None:
            item.setdefault('saved_picks',{}).setdefault('total',{})['side']=replay['ou_side']
            item.setdefault('locked_quotes',{})['Total']={'line_a':replay['total_quote']['line']}
            item.setdefault('completed_grades',{})['scout_total']=replay['grades']['ou']
        else:
            value=item.get('scout_dynamic')
            row=value.get('row') if isinstance(value,dict) else None
            if row is not None and row.get('totals',{}).get('model')=='scout5-ou-v1':
                item.setdefault('saved_picks',{}).setdefault('total',{})['side']=row['ou_side']
                item.setdefault('locked_quotes',{})['Total']={'line_a':row['total_quote']['line']}
            else:
                # Do not display legacy O/U from historical combined ATS seals.
                item.setdefault('saved_picks',{}).setdefault('total',{})['side']=None
                item.setdefault('locked_quotes',{}).pop('Total',None)
                item.setdefault('completed_grades',{}).pop('scout_total',None)
    except (OSError,ValueError,KeyError,TypeError):
        item.setdefault('saved_picks',{}).setdefault('total',{})['side']=None
        item.setdefault('locked_quotes',{}).pop('Total',None)
        item.setdefault('completed_grades',{}).pop('scout_total',None)
    return item


def records(root, finals, season, week, *, now=None):
    """Scout 5.0 O/U ONLY: compact historical replay + new live-issued rows.

    Never consults archived Scout 4 totals or duplicates its history on disk.
    ATS remains independently owned by existing readers.
    """
    import csv
    from scout5_totals import load_bundle
    if season is None:
        return {}
    now=now or datetime.now(timezone.utc)
    root=Path(root)
    rows=[];review=False
    try:
        bundle=load_bundle(Path(__file__).resolve().parent/'scout5_ou_bundle.json')
        if int(season)==int(bundle['season']):
            for old in bundle.get('replay_history',[]):
                if week is not None and int(old['week'])!=int(week):
                    continue
                row=dict(old)
                row['source']='Scout 5.0 reconstructed historical replay'
                rows.append(row)
    except (ValueError,OSError,KeyError,TypeError):
        review=True
    existing={r['game_id'] for r in rows}
    live_enabled=os.environ.get('TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC')=='1'
    if live_enabled:
        for path in sorted((root/'scout_dynamic').glob('*_*_*_*')):
            if not path.is_dir() or path.name in existing:
                continue
            try:
                parts=path.name.split('_')
                if int(parts[0])!=int(season) or (week is not None and int(parts[1])!=int(week)):
                    continue
                saved=journal(root,path.name)
                if not saved:
                    continue
                game={k:saved[-1][k] for k in ('game_id','away_team','home_team','kickoff_utc')}
                value=state(root,game,now=now)
                if value is None:
                    continue
                row=value['row']
                if row.get('totals',{}).get('model')!='scout5-ou-v1':
                    continue  # Reject old Scout totals; never publish old O/U
                outcome=grade(row,finals.get(path.name) if value['status']=='locked' else None)
                rows.append(dict(row,grades=outcome,source='issued Scout 5.0'))
                existing.add(path.name)
            except (ValueError,OSError,KeyError,TypeError):
                review=True
    rows.sort(key=lambda r:(int(r.get('week',0)),r.get('kickoff_utc',''),r.get('game_id','')))
    counts={m:{outcome:sum(r['grades'][m]==outcome for r in rows)
               for outcome in ('Win','Loss','Push','Pending','No Call','Tie')}
            for m in ('ats','ou','su')}
    expected_ids=set()
    schedule_path=root/'nfl_games.csv'
    if schedule_path.exists():
        with schedule_path.open(newline='') as handle:
            for game in csv.DictReader(handle):
                try:
                    if (int(game.get('season',0))==int(season)
                            and game.get('game_type')=='REG'
                            and int(game.get('week',0))>=6
                            and (week is None or int(game.get('week',0))==int(week))):
                        expected_ids.add(game['game_id'])
                except (TypeError,ValueError,KeyError):
                    continue
    available_ids={r['game_id'] for r in rows if r.get('ou_side') in ('Over','Under')}
    coverage=dict(expected=len(expected_ids),available=len(expected_ids & available_ids),
                  missing=max(0,len(expected_ids)-len(expected_ids & available_ids)))
    return dict(scout_dynamic_records=rows,scout_dynamic_counts=counts,
                scout_dynamic_review=review,scout_dynamic_coverage=coverage)
