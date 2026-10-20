"""Postgame, source-verified starting QBs for Trend Findah historical research.

Never feed this module into predictive features. Nothing is inferred from passing
volume, depth charts or projected lineups. Unverified games stay pending.

The existing hosted_updates.py calls refresh_qbs(root, season) every cycle.
Run the standalone CLI for a focused, Scout-free test or retry.
"""
import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from name_aliases import canonical_name

EASTERN = ZoneInfo('America/New_York')
TEAM_ALIASES = {
    'WSH': 'WAS', 'LAR': 'LA', 'JAC': 'JAX', 'SFO': 'SF',
    'GNB': 'GB', 'NWE': 'NE', 'NOR': 'NO', 'TAM': 'TB',
    'KAN': 'KC', 'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE',
    'CLT': 'IND', 'LVR': 'LV', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA',
}
IDENTITY_KEYS = ('game_id', 'gameday', 'gametime', 'away_team', 'home_team', 'away_score', 'home_score')
ESPN_SITE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl'
ESPN_CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl'


def team_code(value):
    code = str(value or '').strip().upper()
    return TEAM_ALIASES.get(code, code)


def get_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'TrendFindah/1.0'}), timeout=8) as response:
        return json.load(response)


def fetch_summary(event):
    if not str(event).isdigit():
        raise ValueError('Missing ESPN game ID')
    return get_json(f'{ESPN_SITE}/summary?event={event}')


def fetch_scoreboard(gameday):
    day = str(gameday).replace('-', '')
    if not re.fullmatch(r'\d{8}', day):
        raise ValueError('Invalid game date')
    return get_json(f'{ESPN_SITE}/scoreboard?dates={day}')


def fetch_game_roster(event, competitor):
    """ESPN *game* roster; not a team's current depth chart or projection."""
    if not str(event).isdigit() or not str(competitor).isdigit():
        raise ValueError('Missing numeric ESPN event/competitor ID')
    return get_json(f'{ESPN_CORE}/events/{event}/competitions/{event}/competitors/{competitor}/roster')


def event_matches_game(event, game):
    try:
        contests = event['competitions']
        if len(contests) != 1:
            return False
        contest = contests[0]
        if contest.get('status', {}).get('type', {}).get('completed') is not True:
            return False
        teams = {c['homeAway']: c for c in contest['competitors']}
        if set(teams) != {'home', 'away'}:
            return False
        if any(team_code(teams[s]['team']['abbreviation']) != team_code(game[s + '_team'])
               or float(teams[s]['score']) != float(game[s + '_score']) for s in ('home', 'away')):
            return False
        kickoff = datetime.fromisoformat(contest['date'].replace('Z', '+00:00'))
        return kickoff.astimezone(EASTERN).date().isoformat() == game['gameday']
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def find_espn_id(game, scoreboard):
    matches = [str(event.get('id', '')) for event in scoreboard.get('events', [])
               if event_matches_game(event, game)]
    if len(matches) != 1 or not matches[0].isdigit():
        raise ValueError('ESPN scoreboard has no unique matching final game')
    return matches[0]


def verified_contest(payload, game):
    contests = payload.get('header', {}).get('competitions', [])
    if len(contests) != 1:
        raise ValueError('Missing unique ESPN contest')
    contest = contests[0]
    if contest.get('status', {}).get('type', {}).get('completed') is not True:
        raise ValueError('ESPN has not confirmed final')
    kickoff = datetime.fromisoformat(contest['date'].replace('Z', '+00:00'))
    if kickoff.astimezone(EASTERN).date().isoformat() != game['gameday']:
        raise ValueError('Kickoff date mismatch')
    teams = {c['homeAway']: c for c in contest['competitors']}
    if set(teams) != {'away', 'home'}:
        raise ValueError('Incomplete competitors')
    for side in ('away', 'home'):
        if team_code(teams[side]['team']['abbreviation']) != team_code(game[side + '_team']):
            raise ValueError('Team mismatch')
        if float(teams[side]['score']) != float(game[side + '_score']):
            raise ValueError('Final score mismatch')
    return teams


def _passers(payload, side, game):
    """Find passer identities only; passing statistics do NOT establish a start."""
    candidates = []
    for team in payload.get('boxscore', {}).get('players', []):
        if team_code(team.get('team', {}).get('abbreviation')) != team_code(game[side + '_team']):
            continue
        for category in team.get('statistics', []):
            if category.get('name') != 'passing':
                continue
            for entry in category.get('athletes', []):
                athlete = entry.get('athlete') or {}
                name = athlete.get('displayName')
                if name:
                    candidates.append((str(athlete.get('id', '')), canonical_name(name), entry.get('starter')))
    return candidates


def _ref_player_id(entry):
    id_value = entry.get('playerId')
    if id_value:
        return str(id_value)
    athlete = entry.get('athlete') or {}
    if athlete.get('id'):
        return str(athlete['id'])
    url = athlete.get('$ref', '')
    match = re.search(r'/athletes/(\d+)(?:[/?#]|$)', str(url))
    return match.group(1) if match else ''


def _roster_qb(game_roster, passers):
    """Require a *game-roster* starter flag AND same player's boxscore identity.

    A quarterback who comes off the bench can lead in attempts; this prevents
    calling that player the starter. An ambiguous or missing flag stays pending.
    """
    if not isinstance(game_roster, dict) or not isinstance(game_roster.get('entries'), list):
        raise ValueError('ESPN game roster has no entries')
    starters = [_ref_player_id(r) for r in game_roster['entries'] if r.get('starter') is True]
    ids = {p_id: name for p_id, name, _ in passers if p_id}
    candidates = {ids[player_id] for player_id in starters if player_id in ids}
    if len(candidates) != 1:
        raise ValueError('Game roster does not identify exactly one passing QB starter')
    return candidates.pop()


def verified_starters(payload, game, *, event=None, fetch_roster=fetch_game_roster):
    """Confirm final/identity, then verify starters via flags or game rosters."""
    teams = verified_contest(payload, game)
    result = {}
    for side in ('away', 'home'):
        passers = _passers(payload, side, game)
        explicitly_marked = {name for _, name, starter in passers if starter is True}
        if len(explicitly_marked) > 1:
            raise ValueError(f'Conflicting passing-QB starter flags: {side}')
        if len(explicitly_marked) == 1:
            result[side] = explicitly_marked.pop()
            continue
        if event is None:
            raise ValueError(f'QB starter flag unavailable: {side}')
        # Use a roster attached to this *completed game*, not projected starters.
        competitor_id = teams[side].get('id') or teams[side].get('team', {}).get('id')
        if not str(competitor_id or '').isdigit():
            raise ValueError(f'Missing ESPN competitor ID: {side}')
        name = _roster_qb(fetch_roster(event, competitor_id), passers)
        # If passing stats have any explicit starter flags, never silently
        # override them with a conflicting roster selection.
        result[side] = name
    if set(result) != {'away', 'home'}:
        raise ValueError('Both starters must be verified')
    return result


def _write(path, verified, issues, *, attempted, expected, pending):
    data = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'games': verified,
        'issues': list(sorted(issues.values(), key=lambda issue: issue['game_id'])),
        'verification_status': {
            'attempted_this_run': attempted, 'season_completed_games': expected,
            'verified_season_games': expected - pending, 'pending_season_games': pending,
        },
    }
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2))
    temp.replace(path)
    return data


def refresh_qbs(root, season, fetch=fetch_summary, fetch_board=fetch_scoreboard,
                fetch_roster=fetch_game_roster, game_ids=None, max_attempts=10):
    """Independently verify completed games; checkpoint, retry, retain issues.

    Existing hosted updater calls this automatically. `game_ids` limits an
    operator test to selected games without starting Scout or Gemini.
    """
    root = Path(root)
    folder = root / 'data/research_qbs'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'verified.json'
    previous = json.loads(path.read_text()) if path.exists() else {'games': {}, 'issues': []}
    verified = dict(previous.get('games', {}))
    issues = {issue['game_id']: issue for issue in previous.get('issues', []) if issue.get('game_id')}
    with (root / 'nfl_games.csv').open(newline='') as source:
        rows = list(csv.DictReader(source))
    completed = [game for game in rows if str(game.get('season')) == str(season)
                 and all(game.get(side + '_score') not in ('', None) for side in ('away', 'home'))]
    target_ids = set(game_ids) if game_ids is not None else None
    if target_ids is not None and not target_ids.issubset({g['game_id'] for g in completed}):
        raise ValueError('Some requested games are missing or not final in nfl_games.csv')
    # Remove stale evidence even before retry; never serve an old QB on revised game identity.
    for game in completed:
        identity = {field: game[field] for field in IDENTITY_KEYS}
        saved = verified.get(game['game_id'])
        if saved and saved.get('identity') != identity:
            verified.pop(game['game_id'], None)
            issues.pop(game['game_id'], None)
    pending_games = [g for g in completed if g['game_id'] not in verified]
    # New/unattempted games before rechecks, newest first. Failed games are
    # retried later; one problematic game cannot block the next week's results.
    fresh = sorted((g for g in pending_games if g['game_id'] not in issues),
                   key=lambda g: (g['gameday'], g['game_id']), reverse=True)
    retry = sorted((g for g in pending_games if g['game_id'] in issues),
                   key=lambda g: (issues[g['game_id']].get('last_attempt', ''), g['gameday']))
    queue = fresh + retry
    if target_ids is not None:
        queue = [g for g in queue if g['game_id'] in target_ids]
    else:
        queue = queue[:max_attempts]
    scoreboard_cache = {}
    attempted = 0
    for game in queue:
        attempted += 1
        identity = {field: game[field] for field in IDENTITY_KEYS}
        event = str(game.get('espn') or '').strip()
        try:
            if not event.isdigit():
                day = game['gameday']
                if day not in scoreboard_cache:
                    scoreboard_cache[day] = fetch_board(day)
                event = find_espn_id(game, scoreboard_cache[day])
            starters = verified_starters(fetch(event), game, event=event, fetch_roster=fetch_roster)
            verified[game['game_id']] = {
                'identity': identity, 'starters': starters,
                'source_url': 'https://www.espn.com/nfl/game/_/gameId/' + event,
                'starter_source': 'ESPN game roster / starter flags',
            }
            issues.pop(game['game_id'], None)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, URLError, HTTPError) as error:
            issues[game['game_id']] = {
                'game_id': game['game_id'], 'reason': str(error),
                'last_attempt': datetime.now(timezone.utc).isoformat(),
            }
        _write(path, verified, issues, attempted=attempted, expected=len(completed),
               pending=sum(g['game_id'] not in verified for g in completed))
    remaining = sum(g['game_id'] not in verified for g in completed)
    result = _write(path, verified, issues, attempted=attempted,
                    expected=len(completed), pending=remaining)
    # Give Render logs a useful single-line status even when some games are pending.
    print(f'QB verification: attempted={attempted} verified={len(completed)-remaining}/{len(completed)} pending={remaining}', flush=True)
    # Keep the existing updater's visible needs-attention signal if unresolved.
    pending_target = (sum(g['game_id'] not in verified for g in completed if g['game_id'] in target_ids)
                      if target_ids is not None else remaining)
    if pending_target:
        raise ValueError(f'{pending_target} requested/completed games still need QB verification; '
                         'see data/research_qbs/verified.json')
    return result


def main():
    parser = argparse.ArgumentParser(description='Source-verified postgame QB refresh; no Scout or Gemini')
    parser.add_argument('--root', default='.', help='Folder containing nfl_games.csv')
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--games', nargs='+', metavar='GAME_ID')
    args = parser.parse_args()
    try:
        data = refresh_qbs(args.root, args.season, game_ids=args.games)
    except ValueError as exc:
        print('PENDING:', exc)
        path = Path(args.root) / 'data/research_qbs/verified.json'
        if path.exists():
            data = json.loads(path.read_text())
            for issue in data.get('issues', []):
                if args.games is None or issue.get('game_id') in args.games:
                    print(' -', issue['game_id'], issue['reason'])
        raise SystemExit(1)
    ids = args.games or [gid for gid, obj in data['games'].items() if gid.startswith(str(args.season) + '_')]
    for gid in ids:
        obj = data['games'].get(gid)
        print(gid, obj['starters'] if obj else 'PENDING')
    print('QB verification complete; no game data or predictions modified.')


if __name__ == '__main__':
    main()
