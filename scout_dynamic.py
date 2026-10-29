"""Worker-only dynamic Scout adapter. Calls frozen production functions; never fits.

Public points and private Scout scoring retain their existing identities. Scout
4.1 is not deployed in main and is never substituted for either component.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil

from scout_dynamic_store import (POLICY, append, closing, digest, finalize,
                                 folder, journal, utc)

SOURCE = Path(__file__).resolve().parent


def enabled():
    return any(os.environ.get(k) == '1' for k in (
        'TREND_FINDAH_SCOUT_DYNAMIC_RESEARCH', 'TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC'))


def configuration(source=SOURCE):
    raw = (Path(source) / 'automatic_model.json').read_bytes()
    config = json.loads(raw)
    if config['version'] != 'plug-points-only-4' or config['weights'] != {'scout_scoring':0.0, 'plug_points_only':1.0}:
        raise ValueError('Unapproved Scout configuration')
    for name, signature in config['code_sha256'].items():
        if hashlib.sha256((Path(source) / name).read_bytes()).hexdigest() != signature:
            raise ValueError('Frozen Scout code changed: ' + name)
    return config, hashlib.sha256(raw).hexdigest()


def markets(root, game, now):
    from public_pick_market import matchup_public_market
    raw = matchup_public_market(root, dict(game_id=game['game_id'], away=game['away_team'],
        home=game['home_team'], kickoff_at=game['kickoff_utc']), now=now)
    output = {}
    for kind in ('Spread', 'Total'):
        found = [m for m in raw['markets'] if m['key'] == kind]
        if len(found) != 1 or not found[0].get('sides') or found[0].get('stale'):
            raise ValueError('Missing fresh Scout ' + kind)
        item = found[0];sides = item['sides']
        expected = [game['away_team'], game['home_team']] if kind == 'Spread' else ['Over', 'Under']
        if [s['name'] for s in sides] != expected or len(sides) != 2:
            raise ValueError('Scout market teams differ')
        a,b = [s['line'] for s in sides]
        import math
        if any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in (a,b)):
            raise ValueError('Invalid Scout market numbers')
        if (kind == 'Spread' and abs(a+b)>1e-9) or (kind == 'Total' and (a != b or a <= 0)):
            raise ValueError('Scout market sides disagree')
        stamp = utc(item['captured'])
        if not stamp <= now < utc(game['kickoff_utc']) or (now-stamp).total_seconds() > 21600:
            raise ValueError('Scout market quote expired')
        output[kind] = dict(line=a, captured_at_utc=stamp.isoformat(),
                            kickoff_utc=game['kickoff_utc'], source=item.get('source'), url=item.get('url'))
    return output


def evaluate(root, game, config, config_hash, now, *, cache):
    from forecast_history import pregame_record
    from scout4.shadow import load_stats, statistics_gate
    from scout4.stats import eligible
    from scout4.blend import plug_prediction, combine, plug_ats_pick, plug_total_pick
    from scout4.ratings import build_ratings, matchup
    from scout4.totals import profiles, features, predict
    gid = game['game_id'];year,week = int(game['season']),int(game['week'])
    # Existing official seals admit the game but are never rewritten or replaced
    # as model sources for The Plug or the Expert.
    seed = json.loads((Path(root)/'data/scout4/blend/predictions'/(gid+'.json')).read_bytes())
    pregame_record(seed)
    if (seed['configuration_sha256'] != config_hash or seed['version'] != config['version']
            or seed['kickoff_utc'] != game['kickoff_utc']
            or any(seed[k] != game[k] for k in ('game_id','away_team','home_team'))
            or utc(seed['sealed_at_utc']) > now):
        raise ValueError('Scout seed does not match approved game')
    if year not in cache:
        cache[year] = load_stats(Path(root), year)
    feed, manifest = cache[year]
    schedule = cache['schedule']
    problem = statistics_gate(schedule, feed, manifest, year, week, now)
    if problem:
        raise ValueError(problem)
    q = markets(root, game, now)
    prior = [g for g in schedule if eligible(g, year, week)]
    ids = {g['game_id'] for g in prior}
    prior_feed = sorted([r for r in feed if r.get('game_id') in ids], key=lambda r:(r['game_id'],r['team']))
    inputs = digest(dict(schedule=prior, stats=prior_feed, configuration=config_hash,
                         target={k:game.get(k) for k in ('game_id','away_team','home_team','location')}))
    previous = journal(root, gid)
    last = previous[-1] if previous else None
    total_model = config['totals_candidate']['model']
    # Market+statistics totals are genuinely market-anchored in the unchanged
    # frozen model. A line change never shifts the independent score projection.
    if last and last['inputs_sha256'] == inputs:
        projection = last['projection']; scoring = last['scout_scoring']
        values = dict(last['total_features']); model_as_of = last['model_as_of']
    else:
        projection = plug_prediction(schedule, game)
        key = (year,week)
        if key not in cache:
            ratings,_ = build_ratings(schedule, feed, year, week)
            teams,league = profiles(schedule, feed, year, week)
            cache[key] = ratings,teams,league
        ratings,teams,league = cache[key]
        scout = matchup(config['score_model'], ratings, game['away_team'], game['home_team'],
                        'Neutral' if game.get('location') == 'Neutral' else 'Away')
        if not projection or not scout or not scout['first_estimate']['plausible'] or not scout['second_estimate']['plausible']:
            raise ValueError('Missing plausible Scout projections')
        scoring = dict(model_family='Scout 4.0', version=config['score_model']['version'],
                       away_margin=scout['margin_first'], total=scout['total'])
        values = features(teams, league, game['away_team'], game['home_team'],
                          game.get('location') == 'Neutral', q['Total']['line'])
        if values is None:
            raise ValueError('Scout total features unavailable')
        model_as_of = now.isoformat()
    values['market_total'] = q['Total']['line']
    total = predict(total_model, values, q['Total']['line'])
    if total is None or not total['plausible']:
        raise ValueError('Scout totals unavailable')
    total = plug_total_pick(total, config.get('always_pick',False))
    side = plug_ats_pick(combine(projection['away_margin'],projection['away_margin'],q['Spread']['line'],config['weights']),
                         game, q['Spread']['line'], config.get('always_pick',False))
    row = dict(policy=POLICY, model_family='Scout 4.0', model_version=config['version'],
               configuration_sha256=config_hash, inputs_sha256=inputs, model_as_of=model_as_of,
               seed_sha256=hashlib.sha256((Path(root)/'data/scout4/blend/predictions'/(gid+'.json')).read_bytes()).hexdigest(),
               game_id=gid, away_team=game['away_team'], home_team=game['home_team'],
               kickoff_utc=game['kickoff_utc'], evaluated_at=now.isoformat(),
               projection={k:projection[k] for k in ('away_points','home_points','away_margin')},
               scout_scoring=scoring, total_features=values,
               totals=dict(total=total['total'], market_anchored='market_total' in total_model['columns']),
               ats_side=side, ou_side=total['lean'] if total['lean'] in ('Over','Under') else None,
               spread=q['Spread'], total_quote=q['Total'])
    # Observation timestamps/provenance refresh without duplicating identical
    # model inputs, projected values, selections and lines.
    row['decision_id'] = digest({k:v for k,v in row.items() if k not in (
        'model_as_of','evaluated_at','spread','total_quote')} | {
        'spread_line':q['Spread']['line'], 'total_line':q['Total']['line']})
    return row


def cycle(root, *, now=None, source=SOURCE, clock=None):
    """One bounded existing-worker cycle. Closing never depends on new markets."""
    if not enabled():
        return {'state':'disabled'}
    from scout4.stats import read_csv
    from scout4.shadow import kickoff
    from scout_dynamic_public import enroll
    from scheduler_runtime import atomic_json
    root=Path(root); now=now or datetime.now(timezone.utc)
    report=dict(state='ok', refreshed=0, closed=0, pending={}, errors={})
    base=root/'scout_dynamic'
    # Finalize first, even if the model config, stats or market provider is down.
    for path in sorted(base.glob('*')):
        if not path.is_dir() or not (path/'revisions.json').exists():
            continue
        try:
            if closing(root,path.name) is None and finalize(root,path.name,now=now):
                report['closed']+=1
        except (ValueError,OSError,KeyError,TypeError) as error:
            report['errors'][path.name]=str(error)
    try:
        if shutil.disk_usage(root).free < 128*1024*1024:
            raise ValueError('Scout revisions paused: less than 128 MiB free')
        config,signature=configuration(source)
        schedule=read_csv(root/'nfl_games.csv')
        cache={'schedule':schedule}
        candidates=[]
        for game in schedule:
            if game.get('game_type') != 'REG' or game.get('away_score') or game.get('home_score'):
                continue
            if not game.get('gameday') or not game.get('gametime'):
                continue
            at=kickoff(game)
            if 0 < (at-now).total_seconds() <= 8*86400:
                candidates.append((game,at))
        if len(candidates)>32 or len({g['game_id'] for g,_ in candidates}) != len(candidates):
            raise ValueError('Invalid or oversized upcoming Scout slate')
        for game,at in candidates:
            g=dict(game,kickoff_utc=at.isoformat())
            gid=g['game_id']
            try:
                row=evaluate(root,g,config,signature,now,cache=cache)
                saved=append(root,gid,row,clock=clock)
                enroll(root,gid,saved,now=clock() if clock else datetime.now(timezone.utc))
                report['refreshed']+=1
            except (ValueError,OSError,KeyError,TypeError) as error:
                report['pending'][gid]=str(error)
    except (ValueError,OSError,KeyError,TypeError) as error:
        report['errors']['inputs']=str(error)
    report['state']='review' if report['errors'] else 'partial' if report['pending'] else 'ok'
    atomic_json(base/'status.json', dict(report, checked_at=datetime.now(timezone.utc).isoformat()))
    return report
