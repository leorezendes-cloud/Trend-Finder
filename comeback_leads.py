"""Read-only comeback / lead research. Uses only precomputed scoring audits.

No play-by-play downloads, background tasks, or Scout dependencies in Flask.
"""
import csv
import json
import os
from datetime import date
from pathlib import Path

from flask import abort, render_template, request

ROOT = Path(__file__).resolve().parent
SNAPSHOT = Path('data/comeback_leads/2026_snapshot.json')

TEAM_NAMES = {
    'ARI': 'Cardinals', 'ATL': 'Falcons', 'BAL': 'Ravens',
    'BUF': 'Bills', 'CAR': 'Panthers', 'CHI': 'Bears',
    'CIN': 'Bengals', 'CLE': 'Browns', 'DAL': 'Cowboys',
    'DEN': 'Broncos', 'DET': 'Lions', 'GB': 'Packers',
    'HOU': 'Texans', 'IND': 'Colts', 'JAX': 'Jaguars',
    'KC': 'Chiefs', 'LA': 'Rams', 'LAC': 'Chargers',
    'LV': 'Raiders', 'MIA': 'Dolphins', 'MIN': 'Vikings',
    'NE': 'Patriots', 'NO': 'Saints', 'NYG': 'Giants',
    'NYJ': 'Jets', 'PHI': 'Eagles', 'PIT': 'Steelers',
    'SEA': 'Seahawks', 'SF': '49ers', 'TB': 'Buccaneers',
    'TEN': 'Titans', 'WAS': 'Commanders',
}


def _score(value):
    """Accept saved integer finals; reject blanks/invalid fractions."""
    number = float(value)
    if not number.is_integer() or number < 0:
        raise ValueError('Not a non-negative integer score')
    return int(number)


def _finished(row):
    try:
        home, away = _score(row.get('home_score')), _score(row.get('away_score'))
        margin = float(row['result'])
        return margin == home - away
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def validated_snapshot(root=ROOT):
    """Fail closed for tampering or mismatched saved finals in the audited cohort.

    Additional completed games are tracked separately as pending, never silently
    counted as audited comebacks. The snapshot can grow past its initial 94 games.
    """
    root = Path(root)
    try:
        doc = json.loads((root / SNAPSHOT).read_text(encoding='utf-8'))
        games = doc['games']
        if (doc['season'] != 2026 or doc['threshold_points'] != 10 or
                not isinstance(games, dict) or len(games) < 94 or
                doc['games_checked'] != len(games) or
                not isinstance(doc.get('teams'), dict)):
            return None
        with (root / 'nfl_games.csv').open(newline='', encoding='utf-8-sig') as fp:
            rows = {r['game_id']: r for r in csv.DictReader(fp)
                    if r.get('game_id') in games}
        if len(rows) != len(games):
            return None
        by_team = {}
        for gid, g in games.items():
            r = rows[gid]
            if (r['home_team'] != g['home'] or r['away_team'] != g['away'] or
                    _score(r['home_score']) != _score(g['home_pts']) or
                    _score(r['away_score']) != _score(g['away_pts'])):
                return None
            winner = ('home' if int(g['home_pts']) > int(g['away_pts']) else
                      'away' if int(g['home_pts']) < int(g['away_pts']) else 'tie')
            if g['winner'] != winner:
                return None
            for side in ('home', 'away'):
                team = g[side]
                if not isinstance(team, str) or not team:
                    return None
                t = by_team.setdefault(team, dict(games=0, comeback_wins_10_plus=0,
                    blown_leads_10_plus=0, leading_ht_W=0, leading_ht_L=0,
                    trailing_ht_W=0, trailing_ht_L=0))
                t['games'] += 1
                opposite = 'away' if side == 'home' else 'home'
                won = winner == side
                came_back = int(g[side + '_comeback'])
                blown = int(g[side + '_blown'])
                if came_back not in (0, 1) or blown not in (0, 1):
                    return None
                if came_back and (not won or int(g[side + '_deficit']) < 10):
                    return None
                if blown and (won or int(g[opposite + '_deficit']) < 10):
                    return None
                t['comeback_wins_10_plus'] += came_back
                t['blown_leads_10_plus'] += blown
                diff = int(g[side + '_ht']) - int(g[opposite + '_ht'])
                if diff and winner != 'tie':
                    t[('leading_ht_' if diff > 0 else 'trailing_ht_') +
                      ('W' if won else 'L')] += 1
        if by_team != doc['teams']:
            return None
        # A blown 10+ lead and an opponent's 10+ comeback are the same game.
        wins = sum(t['comeback_wins_10_plus'] for t in by_team.values())
        blown = sum(t['blown_leads_10_plus'] for t in by_team.values())
        if wins != blown:
            return None
        return doc
    except (OSError, json.JSONDecodeError, KeyError, TypeError,
            ValueError, OverflowError):
        return None


def coverage(doc, root=ROOT):
    """Status of the precomputed snapshot versus independently saved final scores.

    This performs a small CSV scan and *never* infers leads from final scores.
    """
    tracked = set(doc['games'])
    latest = ''
    snapshot_latest = ''
    pending = 0
    final_count = 0
    with (Path(root) / 'nfl_games.csv').open(newline='', encoding='utf-8-sig') as fp:
        for row in csv.DictReader(fp):
            gid = row.get('game_id', '')
            if not gid.startswith(f"{doc['season']}_") or not _finished(row):
                continue
            final_count += 1
            gameday = row.get('gameday', '')
            if gameday > latest:
                latest = gameday
            if gid in tracked:
                if gameday > snapshot_latest:
                    snapshot_latest = gameday
            else:
                pending += 1
    return dict(pending=pending, final_count=final_count,
                last_verified=snapshot_latest, latest_final=latest,
                current=not pending and final_count == len(tracked))


def records(doc, sort='comebacks'):
    output = []
    for team, t in doc['teams'].items():
        evidence = []
        for gid, g in doc['games'].items():
            if team not in (g['home'], g['away']):
                continue
            side = 'home' if g['home'] == team else 'away'
            other = 'away' if side == 'home' else 'home'
            if g[side + '_comeback'] or g[side + '_blown']:
                evidence.append(dict(game_id=gid, opponent=g[other],
                    outcome='Comeback win' if g[side + '_comeback'] else 'Blown lead',
                    is_comeback=bool(g[side + '_comeback']),
                    points=int(g[side + '_deficit']) if g[side + '_comeback'] else
                           int(g[other + '_deficit']),
                    final=f"{g['away']} {g['away_pts']} @ {g['home']} {g['home_pts']}"))
        output.append(dict(team=team, name=TEAM_NAMES.get(team, team), **t,
            evidence=sorted(evidence, key=lambda item: item['game_id'], reverse=True)))
    if sort == 'blown':
        output.sort(key=lambda t: (-t['blown_leads_10_plus'],
                                   -t['comeback_wins_10_plus'], t['team']))
    elif sort == 'team':
        output.sort(key=lambda t: t['team'])
    else:
        output.sort(key=lambda t: (-t['comeback_wins_10_plus'],
                                    t['blown_leads_10_plus'], t['team']))
    return output


def friendly_day(iso):
    try:
        day = date.fromisoformat(iso)
        return f'{day:%b} {day.day}, {day.year}'
    except (TypeError, ValueError):
        return 'the latest audited games'


def init_app(app):
    app.config['COMEBACK_LEADS_ENABLED'] = (
        os.environ.get('COMEBACK_LEADS_ENABLED', '') == '1')

    @app.get('/trend-finder/comebacks')
    def comeback_lead_research():
        if not app.config.get('COMEBACK_LEADS_ENABLED', False):
            abort(404)
        doc = validated_snapshot(ROOT)
        if doc is None:
            abort(503, description='Comeback snapshot unavailable or mismatched with saved finals.')
        status = coverage(doc, ROOT)
        sort = request.args.get('sort', 'comebacks')
        if sort not in ('comebacks', 'blown', 'team'):
            sort = 'comebacks'
        view = request.args.get('view', 'events')
        if view not in ('events', 'all'):
            view = 'events'
        rows = records(doc, sort=sort)
        if view == 'events':
            rows = [r for r in rows if r['comeback_wins_10_plus'] or r['blown_leads_10_plus']]
        return render_template('comeback_leads.html', rows=rows,
            season=doc['season'], count=doc['games_checked'],
            teams_count=len(doc['teams']), sort=sort, view=view,
            status=status, last_verified=friendly_day(status['last_verified']),
            comebacks=sum(v['comeback_wins_10_plus'] for v in doc['teams'].values()))
