"""Recovered worksheet formula, using combined points scored plus allowed."""
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, localcontext


FIELDS = ('away_season', 'home_season', 'away_split', 'home_split', 'league_total', 'market_total')


def grade(result, actual):
    if not result['selection']['pick']:
        return 'Undecided'
    if actual is None:
        return 'Pending'
    gap = Decimal(str(actual)) - Decimal(result['market_total'])
    if gap == 0:
        return 'Push'
    return 'Win' if (gap > 0) == (result['selection']['pick'] == 'Over') else 'Loss'


def tally(records):
    totals = {key: dict(category=key, Win=0, Loss=0, Push=0, Pending=0, Undecided=0)
              for key in list('ABCDEFGHIJKL') + ['Unclassified', '+10 override', 'All games']}
    for record in records:
        result = record['result']
        outcome = grade(result, record['actual_total'])
        record['outcome'] = outcome
        keys = [result['selection']['rule'] or 'Unclassified', 'All games']
        if result['difference'] >= 10:
            keys.append('+10 override')
        for key in keys:
            totals[key][outcome] += 1
    for row in totals.values():
        decisions = row['Win'] + row['Loss']
        row['win_pct'] = f"{100 * row['Win'] / decisions:.1f}%" if decisions else '—'
    return list(totals.values())


def selection(season, split, market, difference):
    """Apply the user's A–L worksheet rules. Market gaps retain decimals."""
    season, split, market = map(lambda x: Decimal(str(x)), (season, split, market))
    a, b = season-market, split-market
    result = dict(rule=None, pick=None, exception=None,
                  season_market_gap=str(a), split_market_gap=str(b),
                  watch_season_minus_four=difference <= -4 and a == -4)
    if a == 0 or b == 0:
        result['exception'] = 'Projection equals market; no direction established.'
    else:
        position = 0 if min(a, b) > 0 else 2 if max(a, b) < 0 else 1
        group = 'ABC' if difference >= 4 else 'DEF' if difference >= 0 else 'GHI' if difference <= -4 else 'JKL'
        rule = group[position]
        pick = dict(A='Under', B='Over', C='Over', D='Under', E='Under', F='Under',
                    G='Under', H='Over', I='Under', J=None, K='Over', L='Under')[rule]
        exception = None
        if rule == 'A' and a >= 10:
            pick, exception = 'Over', 'Season projection is at least 10 above market.'
        elif rule == 'D' and b >= 10:
            pick, exception = 'Over', 'Split projection is at least 10 above market.'
        elif rule == 'F' and b == -2:
            pick, exception = 'Over', 'Split projection is exactly 2 below market.'
        elif rule == 'J':
            pick = 'Over' if difference == -1 else 'Under' if difference == -2 else None
            if pick is None:
                exception = 'J at a change of -3 is undecided.'
        elif rule == 'L' and min(a, b) <= -10:
            pick, exception = 'Over', 'At least one projection is 10 or more below market.'
        result.update(rule=rule, pick=pick, exception=exception)
    if difference >= 10:
        result.update(pick='Under', exception='Change of +10 or greater: Under override.')
    return result


def calculate(values):
    """Preserve supplied averages; truncate projections before whole rounding."""
    try:
        numbers = {key: Decimal(str(values[key])) for key in FIELDS
                   if key != 'market_total' or values.get(key) not in (None, '')}
    except (KeyError, InvalidOperation, ValueError):
        raise ValueError('Enter valid positive averages and market O/U.') from None
    if any(not value.is_finite() or value <= 0 or value > 10000
           for value in numbers.values()):
        raise ValueError('Enter averages greater than zero and no more than 10,000.')
    with localcontext() as context:
        context.prec = 50
        raw_season = numbers['away_season'] * numbers['home_season'] / numbers['league_total']
        raw_split = numbers['away_split'] * numbers['home_split'] / numbers['league_total']
        season = raw_season.quantize(Decimal('.01'), rounding=ROUND_DOWN)
        split = raw_split.quantize(Decimal('.01'), rounding=ROUND_DOWN)
        season_whole = int(season.to_integral_value(rounding=ROUND_HALF_UP))
        split_whole = int(split.to_integral_value(rounding=ROUND_HALF_UP))
    result = dict(season_total=format(season, '.2f'), split_total=format(split, '.2f'),
                season_rounded=season_whole, split_rounded=split_whole,
                difference=split_whole-season_whole)
    if 'market_total' in numbers:
        market = numbers['market_total']
        # If two-decimal truncation equals market, inspect further decimals.
        result['selection'] = selection(raw_season if season == market else season,
                                        raw_split if split == market else split,
                                        market, result['difference'])
        result['market_total'] = str(market)
    return result
