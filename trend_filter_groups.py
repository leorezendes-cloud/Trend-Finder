"""Readable grouped choices layered over existing exact historical filters."""
import math

GROUP_OPTIONS = {
    'gametime': ('1 p.m. ET window', '4 p.m. ET window'),
    'game_type': ('Playoffs (all rounds)',),
    'temp': ('Freezing (below 32°F)', 'Cool (32 to below 60°F)', 'Mild (60 to below 80°F)', 'Hot (80°F+)'),
    'wind': ('Light wind (under 10 mph)', 'Breezy (10 to below 20 mph)', 'Windy (20+ mph)'),
}


def matches_group(game, field, expected):
    """Return None for an exact-value choice; missing observations never match a band."""
    if expected not in GROUP_OPTIONS.get(field, ()):
        return None
    if field == 'game_type':
        return game.get(field) in ('WC', 'DIV', 'CON', 'SB', 'POST')
    if field == 'gametime':
        try:
            hour, minute = map(int, game.get(field, '').split(':'))
        except (ValueError, TypeError, AttributeError):
            return False
        return 0 <= minute < 60 and hour == (13 if expected == GROUP_OPTIONS[field][0] else 16)
    try:
        value = float(game.get(field, ''))
    except (ValueError, TypeError):
        return False
    if not math.isfinite(value):
        return False
    index = GROUP_OPTIONS[field].index(expected)
    if field == 'temp':
        return (value < 32, 32 <= value < 60, 60 <= value < 80, value >= 80)[index]
    return (0 <= value < 10, 10 <= value < 20, value >= 20)[index]
