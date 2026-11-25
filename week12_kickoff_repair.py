"""Narrow, idempotent correction of three unsealed Week 12 kickoff times.

Caller holds auto_update.lock. Never changes scores, prices, forecasts or picks.
Both ESPN's event time and the exact original row must match before applying.
"""
import csv
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from scheduler_runtime import atomic_json

SOURCE = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=2026&seasontype=2&week=12&limit=100'
CORRECTIONS = {
    '2026_12_LV_CLE': ('LV', 'CLE', '13:00', '20:20'),
    '2026_12_TEN_JAX': ('TEN', 'JAX', '16:05', '13:00'),
    '2026_12_NE_LAC': ('NE', 'LAC', '20:20', '16:05'),
}


def repair(root, *, apply=False, now=None, fetch=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    path = root/'nfl_games.csv'
    if not path.exists():
        return {'state': 'not_needed', 'changed': []}
    if path.is_symlink():
        raise ValueError('Repair requires the persistent data root, not a symlink')
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    fields = reader.fieldnames
    rows = list(reader)
    proposed = []
    for gid, (away, home, old, new) in CORRECTIONS.items():
        matches = [r for r in rows if r.get('game_id') == gid]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError('Duplicate repair game: '+gid)
        row = matches[0]
        if row.get('gametime') == new:
            continue
        if (row.get('away_team'), row.get('home_team'), row.get('gameday'), row.get('gametime')) != (away, home, '2026-11-29', old):
            raise ValueError('Unexpected schedule row: '+gid)
        if row.get('away_score') or row.get('home_score'):
            raise ValueError('Cannot correct a scored game: '+gid)
        stamp = datetime.fromisoformat('2026-11-29T'+new).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        old_stamp = datetime.fromisoformat('2026-11-29T'+old).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        if now >= min(stamp, old_stamp):
            raise ValueError('Cannot correct a started game: '+gid)
        if (root/'data/scout4/blend/predictions'/(gid+'.json')).exists():
            raise ValueError('Existing sealed forecast requires manual review: '+gid)
        proposed.append((row, stamp, new))
    if not proposed:
        return {'state': 'not_needed', 'changed': []}
    report = {'state': 'preview', 'source': SOURCE, 'changed': [r['game_id'] for r, _, _ in proposed]}
    if not apply:
        return report
    if fetch is None:
        with urlopen(SOURCE, timeout=25) as response:
            payload = json.load(response)
    else:
        payload = fetch()
    for row, expected, new in proposed:
        verified = []
        for event in payload.get('events', []):
            for comp in event.get('competitions', []):
                sides = {c['homeAway']: c['team']['abbreviation'] for c in comp.get('competitors', [])}
                if sides != {'away': row['away_team'], 'home': row['home_team']}:
                    continue
                at = datetime.fromisoformat(comp['date'].replace('Z', '+00:00'))
                if at == expected and event.get('date') == comp['date'] and comp.get('status', {}).get('type', {}).get('state') == 'pre':
                    verified.append(at)
        if len(verified) != 1:
            raise ValueError('ESPN did not uniquely verify corrected kickoff: '+row['game_id'])
    originals = [dict(row) for row, _, _ in proposed]
    for row, _, new in proposed:
        row['gametime'] = new
    report.update(state='applied', verified_at=datetime.now(timezone.utc).isoformat(),
                  original_rows=originals, original_sha256=hashlib.sha256(raw).hexdigest())
    # Save the exact old rows before the atomic CSV replacement; retry is safe.
    atomic_json(root/'logs/week12_kickoff_repair.json', report)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, newline='', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
            stream.flush(); os.fsync(stream.fileno())
            if path.read_bytes() != raw:
                raise ValueError('Schedule changed during correction')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return report
