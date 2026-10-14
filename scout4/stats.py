"""Pure statistics and schedule joins. No network calls or prediction side effects."""
import csv
import math
from collections import defaultdict
from pathlib import Path

ALIASES = {'LAR': 'LA', 'STL': 'LA', 'OAK': 'LV', 'SD': 'LAC', 'WSH': 'WAS', 'JAC': 'JAX'}
TEAM_METRICS = ('passing_yards', 'rushing_yards', 'passing_epa', 'rushing_epa',
                'attempts', 'carries', 'sacks_suffered')
PLAYER_METRICS = ('completions', 'attempts', 'passing_yards', 'passing_tds',
                  'passing_interceptions', 'passing_epa', 'carries', 'rushing_yards',
                  'rushing_tds', 'rushing_epa', 'targets', 'receptions', 'receiving_yards',
                  'receiving_tds', 'def_tackles_solo', 'def_sacks', 'def_interceptions',
                  'fg_made', 'fg_att')


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def team_code(value):
    return ALIASES.get(value, value)


def read_csv(path):
    if not Path(path).exists():
        return []
    with Path(path).open(newline='', encoding='utf-8-sig') as file:
        return list(csv.DictReader(file))


def schedule_index(rows):
    result = {}
    for row in rows:
        key = row['game_id']
        if key in result:
            raise ValueError(f'Duplicate schedule game: {key}')
        result[key] = row
    return result


def eligible(game, season, before_week, stage='REG'):
    return (str(game.get('season')) == str(season)
            and game.get('game_type') == stage
            and int(game['week']) < before_week
            and number(game.get('away_score')) is not None
            and number(game.get('home_score')) is not None)


def context(game, team):
    away, home = team_code(game['away_team']), team_code(game['home_team'])
    if team not in (away, home):
        raise ValueError('Stat team does not belong to the schedule game')
    is_home = team == home
    neutral = str(game.get('location', '')).lower() == 'neutral'
    return {'game_id': game['game_id'], 'week': int(game['week']),
            'date': game.get('gameday', ''), 'team': team,
            'opponent': away if is_home else home,
            'venue': 'Neutral' if neutral else 'Home' if is_home else 'Away',
            'designated_side': 'Home' if is_home else 'Away'}


def team_records(schedule, feed, season, before_week):
    """Scored schedule rows are authoritative; missing feed data stays missing."""
    by_game = {}
    for row in feed:
        if row.get('season_type') != 'REG' or str(row.get('season')) != str(season):
            continue
        key = (row['game_id'], team_code(row['team']))
        if key in by_game:
            raise ValueError(f'Duplicate team-stat row: {key}')
        by_game[key] = row
    output = []
    for game in schedule:
        if not eligible(game, season, before_week):
            continue
        for side, other in (('away', 'home'), ('home', 'away')):
            team = team_code(game[f'{side}_team'])
            row = context(game, team)
            row.update(points_for=number(game[f'{side}_score']),
                       points_against=number(game[f'{other}_score']))
            own = by_game.get((game['game_id'], team), {})
            opp = by_game.get((game['game_id'], row['opponent']), {})
            for metric in TEAM_METRICS:
                row[metric] = number(own.get(metric))
            for metric in ('passing_yards', 'rushing_yards', 'passing_epa', 'rushing_epa'):
                row[metric + '_allowed'] = number(opp.get(metric))
            row['net_points'] = row['points_for'] - row['points_against']
            output.append(row)
    return sorted(output, key=lambda r: (r['date'], r['week'], r['game_id'], r['team']))


def player_records(schedule, feed, season, before_week, diagnostics=None):
    games = schedule_index(schedule)
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update(unmatched_games=0, unidentified_players=0)
    result, seen = [], set()
    for source in feed:
        if source.get('season_type') != 'REG' or str(source.get('season')) != str(season):
            continue
        game = games.get(source.get('game_id'))
        if int(source['week']) >= before_week:
            continue
        if game is None:
            diagnostics['unmatched_games'] += 1
            continue
        if not eligible(game, season, before_week):
            continue
        team = team_code(source.get('team'))
        player_id = source.get('player_id')
        if not player_id:
            diagnostics['unidentified_players'] += 1
            continue  # Unattributed stat lines are not invented player identities.
        key = (game['game_id'], team, player_id)
        if key in seen:
            raise ValueError(f'Duplicate player-stat row: {key}')
        seen.add(key)
        row = context(game, team)
        row.update(player_id=player_id, name=source.get('player_display_name') or source.get('player_name') or player_id,
                   position=source.get('position') or 'Unknown')
        row.update({m: number(source.get(m)) for m in PLAYER_METRICS})
        result.append(row)
    return sorted(result, key=lambda r: (r['date'], r['week'], r['name']))


def mean_metric(rows, metric):
    values = [r[metric] for r in rows if r.get(metric) is not None]
    return {'value': sum(values)/len(values) if values else None, 'n': len(values)}


def smooth(observed, baseline, prior_games=4):
    """Descriptive shrinkage, not learned confidence or predictive calibration."""
    if observed['value'] is None or baseline['value'] is None:
        return None
    n = observed['n']
    return (n * observed['value'] + prior_games * baseline['value']) / (n + prior_games)


def summarize_team(selected, all_venues):
    metrics = ('points_for', 'points_against', 'net_points', 'passing_yards', 'rushing_yards',
               'passing_yards_allowed', 'rushing_yards_allowed', 'passing_epa', 'rushing_epa',
               'passing_epa_allowed', 'rushing_epa_allowed')
    summary = {m: mean_metric(selected, m) for m in metrics}
    for metric in metrics:
        summary[metric]['smoothed'] = smooth(summary[metric], mean_metric(all_venues, metric))
    return {'games': len(selected), 'wins': sum(r['net_points'] > 0 for r in selected),
            'losses': sum(r['net_points'] < 0 for r in selected),
            'ties': sum(r['net_points'] == 0 for r in selected), 'metrics': summary,
            'baseline_games': len(all_venues)}


def adjusted_defense(rows):
    """Opponent suppression against other games available at the chosen cutoff.

    Positive values mean less EPA allowed than that offense's other-game average.
    The played matchup is excluded from its baseline. This is a cutoff-level
    descriptive rating, not a historical per-game pre-kickoff feature.
    """
    by_team = defaultdict(list)
    for row in rows:
        by_team[row['team']].append(row)
    output = {}
    for team, history in by_team.items():
        values = {'pass': [], 'rush': []}
        for game in history:
            others = [r for r in by_team[game['opponent']] if r['game_id'] != game['game_id']]
            for name, metric in (('pass', 'passing_epa'), ('rush', 'rushing_epa')):
                baseline = mean_metric(others, metric)['value']
                allowed = game[metric + '_allowed']
                if baseline is not None and allowed is not None:
                    values[name].append({'value': baseline - allowed, 'game_id': game['game_id']})
        output[team] = {name: {'value': sum(r['value'] for r in group)/len(group) if group else None,
                               'n': len(group), 'evidence': group} for name, group in values.items()}
    return output


def summarize_player(rows, baseline):
    metrics = {}
    for metric in PLAYER_METRICS:
        values = [r[metric] for r in rows if r.get(metric) is not None]
        observed = mean_metric(rows, metric)
        metrics[metric] = {'total': sum(values) if values else None,
                           'value': observed['value'], 'n': len(values),
                           'smoothed': smooth(observed, mean_metric(baseline, metric))}
    def rate(numerator, denominator, multiplier=1):
        pairs = [(r[numerator], r[denominator]) for r in rows
                 if r.get(numerator) is not None and r.get(denominator) is not None]
        n = sum(d for _, d in pairs)
        return {'value': multiplier*sum(v for v, _ in pairs)/n if n else None, 'opportunities': n}
    return {'games': len({r['game_id'] for r in rows}), 'baseline_games': len({r['game_id'] for r in baseline}),
            'metrics': metrics, 'completion': rate('completions', 'attempts', 100),
            'yards_per_attempt': rate('passing_yards', 'attempts'),
            'yards_per_carry': rate('rushing_yards', 'carries'),
            'catch_rate': rate('receptions', 'targets', 100)}


def recent_form(rows):
    ordered = sorted(rows, key=lambda r: (r['date'], r['week'], r['game_id']))
    recent = ordered[-5:][::-1]
    outcomes = ['W' if r['net_points'] > 0 else 'L' if r['net_points'] < 0 else 'T' for r in ordered]
    count = 0
    for result in reversed(outcomes):
        if result != outcomes[-1]:
            break
        count += 1
    return {'games': recent, 'sequence': ' · '.join(outcomes[-5:]),
            'streak': f'{count} straight ' + ({'W':'win','L':'loss','T':'tie'}[outcomes[-1]] if count == 1 else {'W':'wins','L':'losses','T':'ties'}[outcomes[-1]]) if outcomes else 'No completed games',
            'recent_points': mean_metric(ordered[-3:], 'points_for')['value'],
            'season_points': mean_metric(ordered, 'points_for')['value']}
