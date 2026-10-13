"""Auditable team ratings and experimental scoring estimates.

Ratings only consume completed games before the requested week. The regression
conversion is fitted separately on earlier seasons. No injury or ATS trend
weights are assumed, and no calibrated probabilities are claimed.
"""
import math
from collections import defaultdict
from .stats import team_records, mean_metric, adjusted_defense

VERSION = 'scout4-ratings-1'
PRIOR_GAMES = 4.0
MIN_GAMES = 3
RIDGE = 8.0  # Fixed research specification, not tuned on evaluation outcomes.
FEATURE_LABELS = {
    'off_scoring': 'Own opponent-adjusted scoring offense',
    'opp_def_scoring': 'Opponent adjusted scoring defense',
    'recent_net': 'Own recent scoring margin',
    'opp_recent_net': 'Opponent recent scoring margin',
    'venue_scoring': 'Own venue scoring context',
    'venue_indicator': 'Home / away / neutral context',
    'off_pass': 'Own passing EPA strength',
    'off_rush': 'Own rushing EPA strength',
    'opp_def_pass': 'Opponent passing EPA suppression',
    'opp_def_rush': 'Opponent rushing EPA suppression',
}
SCORING_FEATURES = list(FEATURE_LABELS)[:6]
ALL_FEATURES = list(FEATURE_LABELS)


def shrink(value, n, prior=0.0):
    return (n * value + PRIOR_GAMES * prior) / (n + PRIOR_GAMES)


def build_ratings(schedule, feed, season, before_week):
    rows = team_records(schedule, feed, season, before_week)
    league = mean_metric(rows, 'points_for')['value']
    if league is None:
        return {}, None
    histories = defaultdict(list)
    for r in rows:
        histories[r['team']].append(r)
    defense = adjusted_defense(rows)
    league_epa = {kind: mean_metric(rows, f'{kind}_epa')['value'] for kind in ('passing', 'rushing')}
    result = {}
    for code, history in histories.items():
        adjusted_off, adjusted_def, evidence = [], [], []
        for g in history:
            others = [r for r in histories[g['opponent']] if r['game_id'] != g['game_id']]
            pa = mean_metric(others, 'points_against')
            pf = mean_metric(others, 'points_for')
            defense_bonus = shrink(league - pa['value'], pa['n']) if pa['n'] else 0.0
            offense_bonus = shrink(pf['value'] - league, pf['n']) if pf['n'] else 0.0
            adjusted_off.append(g['points_for'] - league + defense_bonus)
            adjusted_def.append(league - g['points_against'] + offense_bonus)
            evidence.append({'game_id': g['game_id'], 'opponent': g['opponent'],
                             'other_opponent_games': len(others), 'offense_adjustment': defense_bonus,
                             'defense_adjustment': offense_bonus})
        n = len(history)
        recent = history[-3:]
        rating = {'team': code, 'games': n, 'season': season, 'before_week': before_week,
                  'off_scoring': shrink(sum(adjusted_off)/n, n),
                  'def_scoring': shrink(sum(adjusted_def)/n, n),
                  'recent_net': shrink(sum(r['net_points'] for r in recent)/len(recent), len(recent)),
                  'recent_games': len(recent), 'opponent_evidence': evidence,
                  'history_game_ids': [r['game_id'] for r in history], 'coverage': {}, 'venues': {}}
        average_scored = mean_metric(history, 'points_for')['value']
        for venue in ('Home', 'Away', 'Neutral'):
            sample = [r for r in history if r['venue'] == venue]
            avg = mean_metric(sample, 'points_for')
            rating['venues'][venue] = {'games': len(sample),
                'scoring_context': shrink(avg['value']-average_scored, len(sample)) if sample else 0.0}
        for name, kind in (('pass', 'passing'), ('rush', 'rushing')):
            off = mean_metric(history, f'{kind}_epa')
            stop = defense[code][name]
            rating[f'off_{name}'] = (shrink(off['value']-league_epa[kind], off['n'])
                                      if off['n'] and league_epa[kind] is not None else None)
            rating[f'def_{name}'] = shrink(stop['value'], stop['n']) if stop['n'] else None
            rating['coverage'][f'off_{name}'] = off['n']
            rating['coverage'][f'def_{name}'] = stop['n']
        result[code] = rating
    return result, league


def features(own, opponent, venue):
    if venue not in ('Home', 'Away', 'Neutral'):
        raise ValueError('Matchup venue must be Home, Away or Neutral')
    return {'off_scoring': own['off_scoring'], 'opp_def_scoring': opponent['def_scoring'],
            'recent_net': own['recent_net'], 'opp_recent_net': opponent['recent_net'],
            'venue_scoring': own['venues'][venue]['scoring_context'],
            'venue_indicator': {'Home': 1.0, 'Away': -1.0, 'Neutral': 0.0}[venue],
            'off_pass': own['off_pass'], 'off_rush': own['off_rush'],
            'opp_def_pass': opponent['def_pass'], 'opp_def_rush': opponent['def_rush']}


def solve(matrix, vector):
    """Small ridge normal equation system, partial-pivot Gaussian elimination."""
    a = [list(row)+[value] for row,value in zip(matrix,vector)]
    n = len(vector)
    for col in range(n):
        pivot = max(range(col,n), key=lambda r:abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        if abs(scale) < 1e-12:
            raise ValueError('Regression matrix is singular')
        a[col] = [x/scale for x in a[col]]
        for row in range(n):
            if row == col:
                continue
            weight = a[row][col]
            a[row] = [x-weight*y for x,y in zip(a[row], a[col])]
    return [row[-1] for row in a]


def fit(samples, columns):
    usable = [(x,y) for x,y in samples if all(x.get(c) is not None and math.isfinite(x[c]) for c in columns)]
    if len(usable) < 150:
        raise ValueError('Need at least 150 historical team-scoring observations')
    means = [sum(x[c] for x,_ in usable)/len(usable) for c in columns]
    scales = [max(1e-6, math.sqrt(sum((x[c]-m)**2 for x,_ in usable)/len(usable))) for c,m in zip(columns,means)]
    matrix = [[0.0]*(len(columns)+1) for _ in range(len(columns)+1)]
    target = [0.0]*(len(columns)+1)
    for x,y in usable:
        vector = [1.0]+[(x[c]-m)/s for c,m,s in zip(columns,means,scales)]
        for i,vi in enumerate(vector):
            target[i] += vi*y
            for j,vj in enumerate(vector):
                matrix[i][j] += vi*vj
    for i in range(1,len(matrix)):
        matrix[i][i] += RIDGE
    return {'version': VERSION, 'columns': columns, 'means': means, 'scales': scales,
            'coefficients': solve(matrix,target), 'ridge': RIDGE, 'training_team_rows': len(usable)}


def estimate(model, values):
    if any(values.get(c) is None for c in model['columns']):
        return None
    contributions = [{'label': 'Fitted scoring baseline', 'feature': 'intercept',
                      'value': 1.0, 'points': model['coefficients'][0]}]
    for c,m,s,b in zip(model['columns'],model['means'],model['scales'],model['coefficients'][1:]):
        contributions.append({'label': FEATURE_LABELS[c], 'feature': c,
                              'value': values[c], 'points': b*(values[c]-m)/s})
    # Preserve the additive, unrounded estimate. Implausible negatives are flagged,
    # not clipped silently or converted to apparent scoring probabilities.
    score = sum(row['points'] for row in contributions)
    return {'score': score, 'contributions': contributions,
            'plausible': score >= 0, 'status': 'EXPERIMENTAL — not calibrated probabilities'}


def matchup(model, ratings, first, second, first_venue):
    if first == second or first not in ratings or second not in ratings:
        return None
    a,h = ratings[first],ratings[second]
    if min(a['games'],h['games']) < MIN_GAMES:
        return None
    second_venue = {'Home': 'Away', 'Away': 'Home', 'Neutral': 'Neutral'}[first_venue]
    a_values,h_values = features(a,h,first_venue),features(h,a,second_venue)
    a_score,h_score = estimate(model,a_values),estimate(model,h_values)
    if a_score is None or h_score is None:
        return None
    return {'first': first, 'second': second, 'first_venue': first_venue, 'second_venue': second_venue,
            'first_estimate': a_score, 'second_estimate': h_score,
            'margin_first': a_score['score']-h_score['score'], 'total': a_score['score']+h_score['score'],
            'features_first': a_values, 'features_second': h_values}
