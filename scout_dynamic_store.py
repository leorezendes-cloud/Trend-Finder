"""Bounded Scout-only revisions and immutable closing snapshots. No model code."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import hashlib
import json
import math
import os

POLICY = 'scout-dynamic-v1'
MAX_REVISIONS = 32
MAX_BYTES = 512 * 1024


def utc(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timezone required')
    return stamp.astimezone(timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def folder(root, gid):
    parts = gid.split('_')
    if (len(parts) != 4 or not parts[0].isdigit() or not parts[1].isdigit()
            or not all(p.isalnum() for p in parts)):
        raise ValueError('Invalid Scout game identity')
    return Path(root) / 'scout_dynamic' / gid


def checked_read(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Oversized Scout record')
    data = json.loads(path.read_bytes())
    signature = data.pop('sha256', None)
    if signature != digest(data):
        raise ValueError('Scout record checksum mismatch')
    data['sha256'] = signature
    return data


def signed(value):
    return dict(value, sha256=digest(value))


@contextmanager
def locked(path):
    path.mkdir(parents=True, exist_ok=True)
    with (path / 'lock').open('a+b') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def validate(row, gid):
    if 'revision' in row and (type(row['revision']) is not int or row['revision'] < 1):
        raise ValueError('Invalid Scout revision number')
    if row['game_id'] != gid or row['policy'] != POLICY or row['model_family'] != 'Scout 4.0':
        raise ValueError('Scout identity mismatch')
    if not utc(row['model_as_of']) <= utc(row['evaluated_at']) < utc(row['kickoff_utc']):
        raise ValueError('Scout model is not pregame')
    away, home = gid.split('_')[-2:]
    if (row['away_team'], row['home_team']) != (away, home):
        raise ValueError('Scout team identity mismatch')
    numbers = [row['projection'][k] for k in ('away_points', 'home_points', 'away_margin')]
    numbers += [row['totals']['total'], row['spread']['line'], row['total_quote']['line']]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numbers):
        raise ValueError('Nonfinite Scout prediction or market')
    if any(row['projection'][k] < 0 for k in ('away_points', 'home_points')) or row['totals']['total'] < 0:
        raise ValueError('Negative projected score')
    if row['ats_side'] not in (None, away, home) or row['ou_side'] not in (None, 'Over', 'Under'):
        raise ValueError('Invalid Scout selection')
    for key in ('spread', 'total_quote'):
        if not utc(row[key]['captured_at_utc']) <= utc(row['evaluated_at']) < utc(row[key]['kickoff_utc']):
            raise ValueError('Invalid Scout market timestamp')
        if utc(row[key]['kickoff_utc']) != utc(row['kickoff_utc']):
            raise ValueError('Scout kickoff changed')


def journal(root, gid):
    path = folder(root, gid) / 'revisions.json'
    if not path.exists():
        return []
    data = checked_read(path)
    rows = data['rows']
    if not 1 <= len(rows) <= MAX_REVISIONS:
        raise ValueError('Invalid Scout revision count')
    for i, row in enumerate(rows):
        validate(row, gid)
        if row['sha256'] != digest({k:v for k,v in row.items() if k != 'sha256'}):
            raise ValueError('Scout revision checksum mismatch')
        if i and (row['revision'] != rows[i-1]['revision'] + 1
                  or utc(row['evaluated_at']) < utc(rows[i-1]['evaluated_at'])
                  or row['kickoff_utc'] != rows[i-1]['kickoff_utc']):
            raise ValueError('Scout revision sequence changed')
    return rows


def closing(root, gid):
    path = folder(root, gid) / 'closing.json'
    if not path.exists():
        return None
    data = checked_read(path)
    if data['kind'] != 'scout-closing-v1' or utc(data['closed_at']) < utc(data['row']['kickoff_utc']):
        raise ValueError('Invalid Scout closing')
    row = data['row']
    validate(row, gid)
    if row['sha256'] != digest({k:v for k,v in row.items() if k != 'sha256'}):
        raise ValueError('Scout closing revision changed')
    return row


def append(root, gid, decision, *, clock=None):
    from scheduler_runtime import atomic_json
    path = folder(root, gid)
    with locked(path):
        if (path / 'closing.json').exists():
            raise ValueError('Scout game already closed')
        rows = journal(root, gid)
        row = dict(decision)
        now = clock() if clock else datetime.now(timezone.utc)
        # Validate again after acquiring the lock: no backdated live writes.
        if utc(row['evaluated_at']) > now or now >= utc(row['kickoff_utc']):
            raise ValueError('Scout commit is outside pregame window')
        validate(row, gid)
        if rows:
            last = rows[-1]
            if (row['kickoff_utc'] != last['kickoff_utc']
                    or utc(row['evaluated_at']) < utc(last['evaluated_at'])
                    or any(utc(row[k]['captured_at_utc']) < utc(last[k]['captured_at_utc'])
                           for k in ('spread', 'total_quote'))):
                raise ValueError('Out-of-order Scout observation')
            if row['decision_id'] == last['decision_id']:
                return last
        row = signed(dict(row, revision=rows[-1]['revision'] + 1 if rows else 1))
        payload = signed({'rows':(rows + [row])[-MAX_REVISIONS:]})
        if len(json.dumps(payload, indent=2, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError('Scout revision size limit')
        atomic_json(path / 'revisions.json', payload)
        return row


def finalize(root, gid, *, now):
    from plug_publication import immutable
    path = folder(root, gid)
    with locked(path):
        existing = closing(root, gid)
        if existing is not None:
            return existing
        rows = journal(root, gid)
        if not rows or now < utc(rows[-1]['kickoff_utc']):
            return None
        immutable(path / 'closing.json', canonical(signed(dict(
            kind='scout-closing-v1', closed_at=now.isoformat(), row=rows[-1]))))
        return closing(root, gid)


def grade(row, scores):
    validate(row, row['game_id'])
    if scores is None:
        return dict(ats='Pending', ou='Pending', su='Pending')
    a, h = scores
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           or v < 0 or int(v) != v for v in (a, h)):
        raise ValueError('Invalid Scout final score')
    def outcome(side, edge):
        return 'No Call' if side is None else 'Push' if abs(edge) < 1e-9 else 'Win' if edge > 0 else 'Loss'
    away = row['away_team']
    margin = row['projection']['away_margin']
    return dict(ats=outcome(row['ats_side'], (a-h+row['spread']['line']) * (1 if row['ats_side']==away else -1)),
                ou=outcome(row['ou_side'], (a+h-row['total_quote']['line']) * (1 if row['ou_side']=='Over' else -1)),
                su='No Call' if abs(margin) < 1e-9 else 'Tie' if a==h else 'Win' if (a>h)==(margin>0) else 'Loss')
