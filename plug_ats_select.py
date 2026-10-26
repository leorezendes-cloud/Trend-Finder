"""Versioned, immutable Plug ATS shortlist over existing approved Scout forecasts.

Never retrains or modifies source models, reports, quotes or scores. The first
completed pre-kickoff weekly slate publishes exactly one atomic policy receipt.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import tempfile

POLICY = 'plug-ats-top-quarter-v1'
MODEL = 'plug-points-only-4'


def shortlist(rows):
    """Original research policy: nonzero edges; ceil(n/4) each season/week;
    descending absolute difference and ascending game_id tie break. No cutoff.
    """
    group = defaultdict(list)
    seen = set()
    for item in rows:
        game_id = item['game_id']
        key = (int(item['season']), int(item['week']), game_id)
        if key in seen:
            raise ValueError('Repeated game identity in Scout shortlist')
        seen.add(key)
        edge = float(item['edge'])
        if not math.isfinite(edge):
            raise ValueError('Nonfinite Scout ATS edge')
        if abs(edge) > 1e-9:
            group[key[:2]].append(item)
    winners = set()
    for eligible in group.values():
        ordered = sorted(eligible, key=lambda r: (-abs(float(r['edge'])), r['game_id']))
        winners.update(r['game_id'] for r in ordered[:math.ceil(len(ordered)/4)])
    return winners


def storage_root():
    value = os.environ.get('TREND_FINDAH_PLUG_ATS_STORE')
    if value:
        return Path(value)
    if Path('/var/data').is_dir():
        return Path('/var/data/plug_ats_selections')
    return Path(__file__).resolve().parent / 'instance' / 'plug_ats_selections'


def _iso(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


def _read(path):
    obj = json.loads(path.read_text())
    if obj.get('policy') != POLICY or obj.get('status') != 'PUBLISHED_BEFORE_FIRST_KICKOFF':
        raise ValueError('Unknown Plug policy receipt')
    expected = obj.pop('receipt_sha256', None)
    digest = hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest()
    if not expected or digest != expected:
        raise ValueError('Plug receipt integrity mismatch')
    obj['receipt_sha256'] = expected
    return obj


def _atomic_first(path, payload):
    """Crash-safe no-overwrite publish, under concurrent workers."""
    payload['receipt_sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.plug-ats-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)  # Never replace previously-issued picks
        except FileExistsError:
            pass
        else:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        os.unlink(name)
    return _read(path)


def _eligible_slate(items, now):
    """Require every scheduled game in this week before any kickoff."""
    if not items:
        return None
    rows = []
    for item in items:
        game = item['scout']['game']
        src = item.get('plug_ats_source')
        if (not src or item.get('pending') or item.get('forecast_pending')
                or _iso(game['kickoff_utc']) <= now
                or src.get('model_version') != MODEL
                or src.get('side') not in (game['away_team'], game['home_team'])):
            return None
        # Each archived source is already checked by official_sources;
        # repeat critical binding checks before issuing a new policy record.
        if not (_iso(src['captured_at_utc']) <= _iso(src['sealed_at_utc'])
                < _iso(game['kickoff_utc'])):
            return None
        edge = float(src['edge'])
        line = float(src['away_line'])
        if not math.isfinite(edge) or not math.isfinite(line):
            return None
        if abs(edge) > 1e-9 and src['side'] != (game['away_team'] if edge > 0 else game['home_team']):
            return None
        rows.append({'game_id': game['game_id'], 'season': int(game['season']),
                     'week': int(game['week']), 'away_team': game['away_team'],
                     'home_team': game['home_team'], 'kickoff_utc': game['kickoff_utc'],
                     'side': src['side'], 'edge': edge, 'away_line': line,
                     'source_sha256': src['source_sha256'],
                     'model_version': src['model_version'],
                     'captured_at_utc': src['captured_at_utc'],
                     'sealed_at_utc': src['sealed_at_utc']})
    return rows


def _published_receipt(items, now):
    g = items[0]['scout']['game']
    path = storage_root() / f"{int(g['season'])}_{int(g['week']):02}_{POLICY}.json"
    if path.exists():
        return _read(path)
    rows = _eligible_slate(items, now)
    if rows is None:
        return None
    chosen = shortlist(rows)
    payload = {
        'policy': POLICY, 'status': 'PUBLISHED_BEFORE_FIRST_KICKOFF',
        'issued_at_utc': now.astimezone(timezone.utc).isoformat(),
        'season': int(g['season']), 'week': int(g['week']),
        'total_games': len(rows), 'candidate_count': sum(abs(r['edge']) > 1e-9 for r in rows),
        'selected_ids': sorted(chosen),
        'policy_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'cohort_sha256': hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest(),
        'games': [{**r, 'selected': r['game_id'] in chosen} for r in sorted(rows, key=lambda r: r['game_id'])],
        'derivation': 'original top-quarter of weekly nonzero absolute spread disagreements; no cutoff or replacement',
    }
    return _atomic_first(path, payload)


def _grade(row, score):
    if not row['selected'] or score is None:
        return None
    a, h = float(score['away']), float(score['home'])
    actual = a - h + float(row['away_line'])
    predicted = row['side'] == row['away_team']
    direction = actual if predicted else -actual
    return 'Push' if abs(direction) < 1e-9 else 'Win' if direction > 0 else 'Loss'


def decorate_dashboard(sections, now):
    """Attach read-only presentation and certified grading from policy receipts.

    A complete, sealed, pre-kickoff slate may atomically publish a policy receipt.
    Partial slates and already-started weeks never gain hindsight selections.
    """
    groups = defaultdict(list)
    for label in ('games', 'underway_games', 'completed_games', 'awaiting_games'):
        for item in sections.get(label, []):
            g = item['scout']['game']
            groups[(int(g['season']), int(g['week']))].append(item)
    for items in groups.values():
        try:
            receipt = _published_receipt(items, now)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            # Fail closed without blocking the public dashboard. If corrupt,
            # operator can inspect receipt; never create inferred past picks.
            receipt = None
        decisions = {g['game_id']: g for g in receipt['games']} if receipt else {}
        for item in items:
            g = item['scout']['game']
            row = decisions.get(g['game_id'])
            item['plug_ats_policy'] = receipt['policy'] if row else None
            item['plug_ats_status'] = ('selected' if row['selected'] else 'stay_away') if row else 'pending'
            item['plug_ats_decision'] = row
            item['plug_ats_result'] = _grade(row, item.get('final_score')) if row else None
    return sections


def for_game(game_id):
    """Read only; comparison pages never issue or change ATS picks."""
    try:
        season, week, *_ = game_id.split('_')
        path = storage_root() / f'{int(season)}_{int(week):02}_{POLICY}.json'
        if not path.is_file():
            return None
        receipt = _read(path)
        return next((r for r in receipt['games'] if r['game_id'] == game_id), None)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def published_history(final_scores):
    """Grade only previously persisted, pregame-issued Plug shortlist selections."""
    from collections import Counter
    all_rows = []
    for path in sorted(storage_root().glob(f'*_{POLICY}.json')):
        receipt = _read(path)
        issued = _iso(receipt['issued_at_utc'])
        names = {r['game_id'] for r in receipt['games'] if r['selected']}
        if names != set(receipt['selected_ids']):
            raise ValueError('Selection receipt identity mismatch')
        for row in receipt['games']:
            if issued >= _iso(row['kickoff_utc']):
                raise ValueError('Post-kickoff shortlist receipt')
            if row['selected']:
                scores = final_scores.get(row['game_id'])
                score = {'away': scores[0], 'home': scores[1]} if scores is not None else None
                all_rows.append({**row, 'issued_at_utc':receipt['issued_at_utc'],
                                 'policy':receipt['policy'], 'result':_grade(row, score) or 'Pending'})
    all_rows.sort(key=lambda r:(r['kickoff_utc'],r['game_id']),reverse=True)
    by_season = defaultdict(Counter)
    for row in all_rows:
        by_season[row['season']][row['result']] += 1
    return all_rows, dict(sorted(((year, dict(ct)) for year,ct in by_season.items()), reverse=True))
