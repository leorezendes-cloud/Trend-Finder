"""Pregame comparison forecasts; never alter the published direction."""
import math
import statistics
from datetime import datetime
from collections import defaultdict
from .stats import eligible, number, team_code


def recent_epa(schedule, feed, game):
    """Fixed prior net-EPA recipe; target-game performance is excluded."""
    season, week = int(game['season']), int(game['week'])
    prior = {g['game_id']:g for g in schedule if eligible(g, season, week)}
    values = {}
    for row in feed:
        if row.get('game_id') not in prior or row.get('season_type') != 'REG':
            continue
        passing, rushing = number(row.get('passing_epa')), number(row.get('rushing_epa'))
        if passing is None or rushing is None:
            continue
        values[(row['game_id'], team_code(row['team']))] = passing+rushing
    history = defaultdict(list)
    for game_id, past in prior.items():
        away, home = team_code(past['away_team']), team_code(past['home_team'])
        if (game_id, away) not in values or (game_id, home) not in values:
            continue
        net = values[(game_id, away)]-values[(game_id, home)]
        history[away].append((int(past['week']), game_id, net))
        history[home].append((int(past['week']), game_id, -net))
    ratings, used = {}, {}
    for side in ('away', 'home'):
        team = team_code(game[side+'_team']); rows = sorted(history[team])
        if len(rows) < 3:
            return None
        ratings[side] = .75*statistics.mean(r[2] for r in rows)+.25*statistics.mean(r[2] for r in rows[-2:])
        used[side] = [r[1] for r in rows]
    margin = ratings['away']-ratings['home']
    if not math.isfinite(margin):
        return None
    return {'away_margin':margin, 'version':'net-epa-recent-form-1', 'history':used,
            'status':'Research comparison only; not calibrated score margin or probability',
            'weights':{'season_net_epa':.75,'last_two_net_epa':.25}}


def grade_benchmarks(record, game):
    """Grade only saved directions against their original shared quote."""
    if not game or any(record.get(k) != game.get(k) for k in ('game_id','away_team','home_team')):
        raise ValueError('Benchmark outcome identity mismatch')
    kickoff = datetime.fromisoformat(record['kickoff_utc'])
    stamps = [datetime.fromisoformat(record[key]) for key in ('decision_cutoff_utc','sealed_at_utc')]
    stamps.append(datetime.fromisoformat(record['quote']['captured_at_utc']))
    if kickoff.tzinfo is None or any(t.tzinfo is None or t>=kickoff for t in stamps):
        raise ValueError('Benchmark was not verifiably saved before kickoff')
    away, home = number(game.get('away_score')), number(game.get('home_score'))
    actual = None if away is None or home is None else away-home+record['quote']['line']
    results = {}
    for name, item in record.get('research_benchmarks', {}).items():
        if item.get('pick') not in (None,record['away_team'],record['home_team']):
            raise ValueError('Unknown benchmark team')
        if not item.get('pick'):
            results[name] = 'Unavailable'
        elif actual is None:
            results[name] = 'Pending'
        elif abs(actual) < 1e-9:
            results[name] = 'Push'
        else:
            results[name] = 'Win' if item['pick'] == (record['away_team'] if actual > 0 else record['home_team']) else 'Loss'
    return results
