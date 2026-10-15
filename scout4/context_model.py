"""Prospective injury/weather research; never writes official predictions."""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from .personnel import ROOT, timestamp

FEATURES = ('wind', 'gusts', 'cold', 'rain', 'away_out', 'home_out')


def features(prediction, weather, personnel):
    cutoff = timestamp(prediction['decision_cutoff_utc'])
    kickoff = timestamp(prediction['kickoff_utc'])
    for evidence in (weather, personnel):
        observed = timestamp(evidence['observed_at'])
        if evidence['game_id'] != prediction['game_id'] or timestamp(evidence['kickoff_utc']) != kickoff:
            raise ValueError('Evidence belongs to another game')
        if not observed <= cutoff < kickoff or (cutoff-observed).total_seconds() > 86400:
            raise ValueError('Evidence is late or stale')
    # Outside forecasts cannot establish conditions under a closed/unknown roof.
    if weather['roof_context'] != 'Open-air metadata':
        raise ValueError('Field weather exposure unverified')
    hours = weather['hours']
    if len(hours) != 4:
        raise ValueError('Incomplete weather window')
    def mean(field):
        values = [float(h[field]) for h in hours]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid weather values')
        return sum(values)/4
    values = [mean('wind_speed_10m'), mean('wind_gusts_10m'),
              max(0, 50-mean('temperature_2m')), mean('precipitation')]
    for side in ('away', 'home'):
        team = prediction[side+'_team']
        report = personnel['personnel'][team]
        if report['injury_coverage'] == 'unknown' or timestamp(report['observed_at']) > cutoff:
            raise ValueError('Injury coverage unknown or late')
        # Reported absences are observations, not assumed point penalties.
        values.append(sum(str(r.get('report_status', '')).lower() == 'out'
                          for r in report['injury_rows']))
    return values


def capture(root=ROOT):
    root = Path(root); folder = root/'data/scout4/context'; folder.mkdir(parents=True, exist_ok=True)
    weather = {}; personnel = {}
    for path in sorted((root/'data/scout4/weather').glob('*/evidence.json')):
        for row in json.loads(path.read_text()).get('records', []):
            weather.setdefault(row['game_id'], []).append(row)
    for path in sorted((root/'data/scout4/personnel').glob('*/*/pregame_evidence.json')):
        for row in json.loads(path.read_text()).get('games', []):
            personnel.setdefault(row['game_id'], []).append(row)
    records = folder/'records'; records.mkdir(exist_ok=True); excluded = {}
    training = []
    for saved in records.glob('*.json'):
        old = json.loads(saved.read_text())
        label_path = folder/'labels'/(old['game_id']+'.json')
        if label_path.exists():
            label = json.loads(label_path.read_text())
            training.append((old, label))
    for path in sorted((root/'data/scout4/blend/predictions').glob('*.json')):
        prediction = json.loads(path.read_text()); game_id = prediction['game_id']
        target = records/(game_id+'.json')
        if target.exists(): continue
        if not prediction.get('totals', {}).get('prediction'):
            excluded[game_id] = 'Baseline total unavailable'
            continue
        valid = []
        for w in weather.get(game_id, []):
            for p in personnel.get(game_id, []):
                try: vector = features(prediction, w, p)
                except (ValueError, KeyError, TypeError): continue
                valid.append((min(timestamp(w['observed_at']), timestamp(p['observed_at'])), vector, w, p))
        if not valid:
            excluded[game_id] = 'No complete verified pre-cutoff injury and open-air weather pair'
            continue
        _, vector, w, p = max(valid, key=lambda item:item[0])
        record = {'version':'context-ridge-1', 'feature_names':FEATURES, 'ridge_penalty':10, 'game_id': game_id, 'cutoff': prediction['decision_cutoff_utc'],
                  'kickoff': prediction['kickoff_utc'], 'features': vector,
                  'baseline': prediction, 'weather': w, 'personnel': p,
                  'baseline_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        prior = [(old, label) for old, label in training
                 if timestamp(label['observed_at']) < timestamp(record['cutoff'])]
        record['candidate'] = None
        record['training_games'] = len(prior)
        record['training_game_ids'] = sorted(old['game_id'] for old,label in prior)
        if len(prior) >= 100:
            candidate = {}
            for kind in ('margin', 'total'):
                def baseline(r):
                    return float(r['baseline']['components']['Blend']['away_margin'] if kind == 'margin'
                                 else r['baseline']['totals']['prediction']['total'])
                rows = [(old['features'], label[kind]-baseline(old)) for old,label in prior]
                correction = fit(rows)(vector)
                candidate[kind] = baseline(record)+correction
            record['candidate'] = candidate
        with target.open('x') as output: json.dump(record, output, indent=2)
    status = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'research only; published picks unchanged',
              'eligible_records': len(list(records.glob('*.json'))), 'excluded': excluded}
    status['evaluation'] = evaluate(root)
    (folder/'status.json').write_text(json.dumps(status, indent=2))
    return status


def refresh_sources(season, root=ROOT):
    """At most one successful refresh daily, before new baseline predictions."""
    from .personnel import refresh_tracker
    from .weather import refresh
    now = datetime.now(timezone.utc)
    folder = Path(root)/'data/scout4/context'; folder.mkdir(parents=True, exist_ok=True)
    marker = folder/'collection.json'
    if marker.exists() and (now-timestamp(json.loads(marker.read_text())['completed_at'])).total_seconds() < 20*3600:
        return
    refresh_tracker(season, Path(root))
    refresh(Path(root))
    marker.write_text(json.dumps({'completed_at':datetime.now(timezone.utc).isoformat()}))


def fit(rows, penalty=10):
    """Fixed ridge residual model. Standardization uses training rows only."""
    width = len(FEATURES)
    means = [sum(r[0][j] for r in rows)/len(rows) for j in range(width)]
    scales = [max(1e-6, math.sqrt(sum((r[0][j]-means[j])**2 for r in rows)/len(rows))) for j in range(width)]
    xs = [[1]+[(x[j]-means[j])/scales[j] for j in range(width)] for x, y in rows]
    size = width+1
    matrix = [[sum(x[i]*x[j] for x in xs)+(penalty if i==j and i else 0)
               for j in range(size)]+[sum(x[i]*row[1] for x,row in zip(xs, rows))] for i in range(size)]
    for i in range(size):
        pivot = max(range(i,size), key=lambda k:abs(matrix[k][i]))
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        divisor = matrix[i][i]
        if abs(divisor)<1e-12: raise ValueError('Singular model')
        matrix[i] = [v/divisor for v in matrix[i]]
        for k in range(size):
            if k != i:
                factor = matrix[k][i]
                matrix[k] = [a-factor*b for a,b in zip(matrix[k],matrix[i])]
    weights = [r[-1] for r in matrix]
    return lambda x: weights[0]+sum(weights[j+1]*(x[j]-means[j])/scales[j] for j in range(width))


def evaluate(root=ROOT):
    """Save first observed finals; grade only prospectively issued candidates."""
    from .stats import read_csv
    folder = Path(root)/'data/scout4/context'
    labels = folder/'labels'; labels.mkdir(parents=True, exist_ok=True)
    games = {g['game_id']:g for g in read_csv(Path(root)/'nfl_games.csv')}
    errors = {'margin': [], 'total': []}
    for path in (folder/'records').glob('*.json'):
        record = json.loads(path.read_text()); game = games.get(record['game_id'], {})
        target = labels/path.name
        try: away, home = float(game['away_score']), float(game['home_score'])
        except (ValueError, KeyError, TypeError): continue
        if not all(math.isfinite(x) and x >= 0 for x in (away, home)): continue
        if timestamp(record['kickoff']) >= datetime.now(timezone.utc): continue
        if not target.exists():
            with target.open('x') as output:
                json.dump({'margin':away-home, 'total':away+home,
                           'observed_at':datetime.now(timezone.utc).isoformat()}, output)
        label = json.loads(target.read_text())
        if record['candidate']:
            for kind in errors:
                base = (record['baseline']['components']['Blend']['away_margin'] if kind=='margin'
                        else record['baseline']['totals']['prediction']['total'])
                errors[kind].append((abs(label[kind]-base), abs(label[kind]-record['candidate'][kind])))
    report = {'status':'Collecting prospective evidence; no automatic model promotion',
              'minimum_training_games':100, 'minimum_evaluation_games':30, 'results':{}}
    for kind, rows in errors.items():
        report['results'][kind] = {'games':len(rows),
            'baseline_mae':sum(r[0] for r in rows)/len(rows) if rows else None,
            'candidate_mae':sum(r[1] for r in rows)/len(rows) if rows else None,
            'enough_for_review':len(rows)>=30}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(capture(args.root), indent=2))
