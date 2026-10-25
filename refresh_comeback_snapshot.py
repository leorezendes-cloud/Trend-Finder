"""Refresh the 2026 10+ lead/comeback snapshot OFFLINE on a Mac.

Runs outside Flask/Render, using the existing local Lead-Comeback-Pilot V3
scoring normalization. Only newly completed games are processed. A complete,
validated JSON snapshot replaces the old one atomically; failures preserve it.

No database, game results, forecast, or scheduled tasks are written.
"""
import csv
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from comeback_leads import SNAPSHOT, validated_snapshot, _finished, _score

ROOT = Path(__file__).resolve().parent
HOME_PROJECTS = Path.home() / 'IT-Lab/python_projects'
SAVED_CSV = HOME_PROJECTS / 'Sneaky-Trend-Finder/nfl_games.csv'
PILOT = HOME_PROJECTS / 'Lead-Comeback-Pilot'
SEASON = 2026


def saved_finals(csv_path):
    # Avoid same-day, potentially in-progress scores; this is not a gameday feed.
    today_et = datetime.now(ZoneInfo('America/New_York')).date()
    with csv_path.open(newline='', encoding='utf-8-sig') as f:
        records = {}
        for row in csv.DictReader(f):
            gid = row.get('game_id', '')
            gameday = row.get('gameday', '')
            if (gid.startswith(f'{SEASON}_') and _finished(row) and
                    row.get('game_type', 'REG') in ('REG', 'WC', 'DIV', 'CON', 'SB') and
                    gameday and date.fromisoformat(gameday) < today_et):
                records[gid] = row
        return records


def reconstruct(gid, plays, row, analyze, normalize_timeline, score):
    """Score-sequence verification, reusing already tested V3 normalization."""
    home, away = row['home_team'], row['away_team']
    final = (_score(row['home_score']), _score(row['away_score']))
    expected = dict(home_team=home, away_team=away, score=final)
    if analyze(plays, expected) is None:
        raise ValueError(f'{gid}: V3 scoring timeline rejected')
    timeline = normalize_timeline(plays)
    previous_quarter = 0
    last = (0, 0)
    saw_final_period = False
    halftime = None
    states = [(0, 0)]
    for index, event in enumerate(timeline):
        quarter = int(event['qtr'])
        h = score(event.get('total_home_score'))
        a = score(event.get('total_away_score'))
        description = str(event.get('desc') or '').strip().lower()
        if quarter < previous_quarter or quarter not in (1, 2, 3, 4, 5):
            raise ValueError(f'{gid}: inconsistent quarter on {event["play_id"]}')
        if (event['home_team'], event['away_team']) != (home, away):
            raise ValueError(f'{gid}: team disagreement on {event["play_id"]}')
        if h is None or a is None:
            raise ValueError(f'{gid}: missing scoring data on {event["play_id"]}')
        if h < last[0] or a < last[1]:
            administrative = description.startswith((
                'timeout', 'two-minute warning', 'end of',
                'end quarter', 'end game', 'end half')) or ' - no play' in description
            confirmed = administrative and any(
                score(later.get('total_home_score')) is not None
                and score(later.get('total_away_score')) is not None
                and score(later.get('total_home_score')) >= last[0]
                and score(later.get('total_away_score')) >= last[1]
                for later in timeline[index + 1:index + 5]
            )
            if not confirmed:
                raise ValueError(f'{gid}: unexplained score regression on {event["play_id"]}')
            continue
        previous_quarter = quarter
        saw_final_period = saw_final_period or quarter >= 4
        if (h, a) != last:
            delta = (h - last[0], a - last[1])
            words = ('touchdown', 'field goal is good', 'extra point is good',
                     'two-point', 'two point', '2-point', '2 point', 'safety')
            if (delta[0] and delta[1] or max(delta) not in (1, 2, 3, 6, 7, 8)
                    or not any(word in description for word in words)):
                raise ValueError(f'{gid}: scoring description needs review on {event["play_id"]}')
            last = (h, a)
            states.append(last)
        if quarter == 2:
            halftime = last
    if not saw_final_period or last != final or halftime is None:
        raise ValueError(f'{gid}: no verified halftime / final')

    home_deficit = max(a - h for h, a in states)
    away_deficit = max(h - a for h, a in states)
    winner = 'home' if final[0] > final[1] else 'away' if final[0] < final[1] else 'tie'
    home_comeback = int(winner == 'home' and home_deficit >= 10)
    away_comeback = int(winner == 'away' and away_deficit >= 10)
    return dict(home=home, away=away, winner=winner,
                home_pts=final[0], away_pts=final[1],
                home_ht=halftime[0], away_ht=halftime[1],
                home_deficit=home_deficit, away_deficit=away_deficit,
                home_comeback=home_comeback, away_comeback=away_comeback,
                home_blown=away_comeback, away_blown=home_comeback)


def summarize_teams(games):
    teams = defaultdict(lambda: dict(games=0, comeback_wins_10_plus=0,
        blown_leads_10_plus=0, leading_ht_W=0, leading_ht_L=0,
        trailing_ht_W=0, trailing_ht_L=0))
    for g in games.values():
        for side, opp in (('home', 'away'), ('away', 'home')):
            t = teams[g[side]]
            t['games'] += 1
            t['comeback_wins_10_plus'] += int(g[side + '_comeback'])
            t['blown_leads_10_plus'] += int(g[side + '_blown'])
            difference = int(g[side + '_ht']) - int(g[opp + '_ht'])
            if difference and g['winner'] != 'tie':
                bucket = 'leading_ht_' if difference > 0 else 'trailing_ht_'
                t[bucket + ('W' if g['winner'] == side else 'L')] += 1
    return dict(sorted(teams.items()))


def refresh(csv_path=SAVED_CSV, pilot=PILOT, root=ROOT):
    root = Path(root)
    path = root / SNAPSHOT
    if not path.is_file() or not Path(csv_path).is_file():
        raise SystemExit('Missing beta snapshot or original saved NFL CSV. No changes made.')
    doc = json.loads(path.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='tf-comeback-source-') as temp:
        comparison = Path(temp)
        (comparison / SNAPSHOT).parent.mkdir(parents=True)
        (comparison / SNAPSHOT).write_text(json.dumps(doc), encoding='utf-8')
        (comparison / 'nfl_games.csv').symlink_to(Path(csv_path).resolve())
        if validated_snapshot(comparison) is None:
            raise SystemExit('Original CSV no longer validates the saved 2026 cohort. No changes made.')

    completed = saved_finals(Path(csv_path))
    old_ids = set(doc['games'])
    pending = sorted(set(completed) - old_ids)
    if not pending:
        print(f'Already current: {len(old_ids)} audited games, '
              f'{sum(v["comeback_wins_10_plus"] for v in doc["teams"].values())} comebacks.')
        return 0
    print(f'{len(pending)} new completed games require scoring validation.', flush=True)
    pilot_code = Path(pilot) / 'lead_pilot_v3.py'
    if not pilot_code.is_file():
        raise SystemExit(f'Missing trusted local V3 normalizer: {pilot_code}')
    sys.path.insert(0, str(pilot))
    from lead_pilot_v3 import analyze, normalize_timeline, score
    try:
        import nflreadpy as nfl
        import polars as pl
    except ImportError as exc:
        raise SystemExit(f'Missing offline update dependency: {exc}') from exc

    columns = ['game_id', 'play_id', 'qtr', 'time', 'home_team', 'away_team',
               'total_home_score', 'total_away_score', 'desc']
    print('Loading 2026 play-by-play on this Mac, NOT on Render...', flush=True)
    raw = (nfl.load_pbp(SEASON)
           .filter(pl.col('game_id').is_in(pending))
           .select(columns))
    grouped = defaultdict(list)
    for event in raw.iter_rows(named=True):
        grouped[event['game_id']].append(event)

    updated = dict(doc['games'])
    for gid in pending:
        if not grouped[gid]:
            raise SystemExit(f'{gid}: no play-by-play yet; old snapshot preserved.')
        try:
            updated[gid] = reconstruct(gid, grouped[gid], completed[gid],
                                       analyze, normalize_timeline, score)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SystemExit(f'New game requires review; old snapshot preserved: {exc}') from exc
    output = dict(doc)
    output['games'] = dict(sorted(updated.items()))
    output['games_checked'] = len(updated)
    output['teams'] = summarize_teams(updated)
    output['status'] = 'requires_manual_review'
    output['refreshed_at_utc'] = datetime.now(timezone.utc).isoformat()
    output['latest_verified_gameday'] = max(
        (completed[gid].get('gameday', '') for gid in updated), default='')

    with tempfile.TemporaryDirectory(prefix='tf-comeback-verify-') as temp:
        stage = Path(temp)
        (stage / SNAPSHOT).parent.mkdir(parents=True)
        (stage / SNAPSHOT).write_text(json.dumps(output), encoding='utf-8')
        (stage / 'nfl_games.csv').symlink_to(Path(csv_path).resolve())
        if validated_snapshot(stage) is None:
            raise SystemExit('Rebuilt snapshot failed full final-score audit. Old snapshot preserved.')

    target = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', suffix='.tmp',
                prefix='.comeback-', dir=path.parent, delete=False) as f:
            target = Path(f.name)
            json.dump(output, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(target, path)
        target = None
    finally:
        if target is not None:
            target.unlink(missing_ok=True)

    count = sum(v['comeback_wins_10_plus'] for v in output['teams'].values())
    print(f'Updated local beta: {len(updated)} audited games; {count} comeback wins.')
    print('Saved only the compact JSON. No original CSV, Scout, Render or production writes.')
    return len(pending)


if __name__ == '__main__':
    refresh()
