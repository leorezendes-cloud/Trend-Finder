"""Read-only links between active Hot Trends and upcoming/completed NFL games.

Never creates a new trend, adjusts historical results, infers a QB starter from an
old game, or uses an outcome to qualify a future matchup.
"""
import math
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo('America/New_York')


def _numeric(value):
    try:
        if value is None or str(value).strip() == '':
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _kickoff(game):
    """Match the historical research's Eastern game-time convention."""
    day = game.get('gameday') or ''
    hour = game.get('gametime') or ''
    if not day or not hour:
        return None
    try:
        time = datetime.fromisoformat(f'{day}T{hour}')
        if time.tzinfo is not None:
            return None  # Local game CSV convention expected, not an arbitrary zone.
        return time.replace(tzinfo=EASTERN)
    except (TypeError, ValueError):
        return None


def _confirmed_qb(game, name):
    """Only explicit, sourced participation confirmation; not historic QB labels."""
    from trend_finder_2 import canonical_name
    for side in ('away', 'home'):
        if (str(game.get(f'{side}_qb_status', '')).strip().lower() == 'confirmed'
                and str(game.get(f'{side}_qb_source') or '').strip()
                and canonical_name(game.get(f'{side}_qb_name')) == canonical_name(name)):
            return True
    return False


def hot_trend_id(trend):
    """Stable anchor to the exact recent-streak card, not all-time research."""
    fields = (trend.get('season'), trend.get('category'), trend.get('subject'),
              trend.get('kind'), trend.get('outcome'))
    text = '|'.join(str(value or '') for value in fields)
    return 'hot-' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def current_season_evidence(trend):
    """Historical evidence kept intact, but expose THIS season separately."""
    prefix = str(trend.get('season', '')) + '_'
    return [item for item in trend.get('evidence', [])
            if str(item.get('game_id', '')).startswith(prefix)]


def earlier_evidence(trend):
    prefix = str(trend.get('season', '')) + '_'
    return [item for item in trend.get('evidence', [])
            if not str(item.get('game_id', '')).startswith(prefix)]


def is_standout_primetime_dog(trend):
    """A genuinely long league-wide primetime-underdog ATS COVER streak.

    Unlike generic league totals/ATS situations, ten straight covers are a
    selective, current-season-verifiable signal worth flagging. The separate
    current-season gate in is_fireworthy still applies.
    """
    params = trend.get('params') or {}
    return (trend.get('category') == 'situational'
            and trend.get('kind') == 'ats'
            and trend.get('outcome') == 'Cover'
            and params.get('primetime') == 'yes'
            and params.get('research_role') == 'underdog'
            and not params.get('research_location')
            and int(trend.get('streak') or 0) >= 10)


def is_fireworthy(trend):
    """Require a strong CURRENT-season signal, not a generic historical angle.

    Historical trend discovery remains unchanged. These stricter criteria apply
    only to the visible flame and prospective-game links.
    """
    category = trend.get('category')
    params = trend.get('params') or {}
    if category not in ('team', 'qb', 'situational'):
        return False
    if category == 'situational':
        # Non-primetime totals and league-wide favorite/underdog categories
        # match too many games to justify a game-level fire badge.
        if (params.get('research_location') not in ('home', 'away')
                or params.get('research_role') not in ('favorite', 'underdog')):
            if not is_standout_primetime_dog(trend):
                return False
    current = current_season_evidence(trend)[:7]
    # At least five of the latest evidence games MUST be this season, with four
    # favorable outcomes this season. A 20-year pooled ATS record isn't a fire.
    return (len(current) >= 5 and
            sum(item.get('result') == trend.get('outcome') for item in current) >= 4 and
            (int(trend.get('streak') or 0) >= 5 or
             int(trend.get('wins') or 0) >= 5))


def scorecard_trends(featured, all_active):
    """Keep featured badges selective; add only exceptional 10+ game dog streaks.

    The All Hot Trends destination contains every trend, even when category
    balancing omitted an outstanding long streak from the homepage Top 8.
    """
    selected = list(featured)
    seen = {hot_trend_id(t) for t in selected}
    for candidate in all_active:
        if (is_standout_primetime_dog(candidate)
                and is_fireworthy(candidate)
                and hot_trend_id(candidate) not in seen):
            selected.append(candidate)
            seen.add(hot_trend_id(candidate))
    return selected


def current_season_research_params(trend):
    """Route explicit analysis clicks to current-season evidence by default."""
    params = dict(trend.get('params') or {})
    params['season'] = trend['season']
    return params


def qualifies_upcoming(game, trend, *, now=None, active_week=None):
    """True only when every applicable pregame trend filter is satisfied."""
    now = now or datetime.now(EASTERN)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    kickoff = _kickoff(game)
    if kickoff is None or kickoff <= now.astimezone(EASTERN):
        return False
    if game.get('game_type') != 'REG':
        return False
    try:
        season, week = int(game['season']), int(game['week'])
    except (KeyError, ValueError, TypeError):
        return False
    if season != int(trend.get('season', -1)):
        return False
    if active_week is not None and (season, week) != tuple(map(int, active_week)):
        return False

    # A market result trend must have a saved corresponding pregame line.
    if trend.get('kind') == 'ats' and _numeric(game.get('spread_line')) is None:
        return False
    if trend.get('kind') == 'total' and _numeric(game.get('total_line')) is None:
        return False
    if trend.get('kind') not in ('ats', 'total', 'su'):
        return False

    category = trend.get('category')
    params = trend.get('params') or {}
    if category == 'team':
        name = params.get('research_team')
        return bool(name and name in (game.get('home_team'), game.get('away_team')))

    if category == 'qb':
        name = params.get('qb_name')
        return bool(name and _confirmed_qb(game, name))

    if category != 'situational':
        return False
    # The historic research labels all games >= 19:00 ET as primetime.
    prime = params.get('primetime')
    if prime not in ('yes', 'no') or (kickoff.hour >= 19) != (prime == 'yes'):
        return False

    role = params.get('research_role')
    location = params.get('research_location') or ''
    if role in ('favorite', 'underdog'):
        spread = _numeric(game.get('spread_line'))
        if spread is None or spread == 0:
            return False
        # Historical general_research defines positive spread_line as AWAY dog.
        dog = 'away' if spread > 0 else 'home'
        focus = dog if role == 'underdog' else ('home' if dog == 'away' else 'away')
        if location and focus != location:
            return False
        if location and str(game.get('location', '')).lower() == 'neutral':
            return False
    elif role not in (None, '') or location:
        return False
    return True


def upcoming_for_trend(schedule, trend, *, now=None, active_week=None):
    """Current-slate future games only, never added to historical evidence."""
    if not is_fireworthy(trend):
        return []
    result = [g for g in schedule if qualifies_upcoming(g, trend, now=now,
                                                       active_week=active_week)]
    return sorted(result, key=lambda g: (g['gameday'], g['gametime'], g['game_id']))


def matches_for_score(game, trends, *, state, now=None, active_week=None):
    """Past: require exact evidence ID. Future: verify all pregame filters."""
    if not game or not game.get('game_id'):
        return []
    output = []
    for trend in trends:
        if not is_fireworthy(trend):
            continue
        if state == 'post':
            is_match = any(item.get('game_id') == game['game_id']
                           for item in trend.get('evidence', ()))
        elif state == 'pre':
            is_match = qualifies_upcoming(game, trend, now=now,
                                          active_week=active_week)
        else:
            is_match = False  # No new classification from mid-game results.
        if is_match:
            output.append(trend)
    return output
