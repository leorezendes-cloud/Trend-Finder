"""Prospective official policy boundary. Legacy records remain a separate cohort.

Only an operator-created activation receipt admits future, newly observed games.
No environment toggle can turn old research into a published historical record.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from plug_dynamic_journal import _time, read, _lock, _path
from plug_dynamic_pregame import decide
from plug_dynamic_closing import read_closing
from plug_dynamic_closing_grade import grade_closing

POLICY = 'dynamic-plug-v1'
PIPELINE = 'dynamic-ready-v1'


def activation(root):
    path = Path(root)/'plug_dynamic_official'/'activation.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if value.get('policy') != POLICY or value.get('pipeline') != PIPELINE:
        raise ValueError('Invalid dynamic activation receipt')
    _time(value['activated_at_utc'])
    return value


def enroll(root, game_id, row, issued_at):
    """Called only after fresh verified observation against original receipts."""
    start = activation(root)
    if start is None:
        return
    issued = _time(issued_at)
    if not _time(start['activated_at_utc']) <= issued < _time(row['kickoff_utc']):
        return
    path = Path(root)/'plug_dynamic_official'/(game_id+'.json')
    if path.exists():
        return
    from plug_publication import immutable
    immutable(path, json.dumps(dict(policy=POLICY, game_id=game_id,
              issued_at_utc=issued_at, kickoff_utc=row['kickoff_utc'],
              revision_sha256=row['sha256']), sort_keys=True).encode())


def validated_revision(root, game_id, at):
    """Check stored decisions against their original immutable model sources.

    Verification uses saved pregame prices; it never issues retrospective picks.
    """
    from plug_ats_v5_weekly import read_week
    from plug_ou_receipts import read as read_ou
    history = read(root, game_id)
    valid = [r for r in history if _time(r['evaluated_utc']) <= _time(at)]
    if not valid:
        return None
    year, week, away, home = game_id.split('_')
    ats = read_week(int(year), int(week))
    ou = read_ou(root, game_id, verify_source=True)
    rows = [r for r in ats['games'] if r['game_id'] == game_id] if ats else []
    if len(rows) != 1 or not ou:
        raise ValueError('Official dynamic model sources unavailable')
    model = rows[0]
    if (model['away_team'], model['home_team'], ou['away_team'], ou['home_team']) != (away, home, away, home):
        raise ValueError('Dynamic model team identity mismatch')
    for row in valid:
        kick = _time(row['kickoff_utc'])
        evaluated = _time(row['evaluated_utc'])
        if (kick != _time(model['kickoff_utc']) or kick != _time(ou['kickoff_utc'])
                or _time(ats['issued_at_utc']) > evaluated
                or _time(ou['issued_at_utc']) > evaluated):
            raise ValueError('Dynamic decision predates verified model sources')
        expected = decide(away_team=away, home_team=home,
            model_away_spread=model['model_away_spread'], v14_total=ou['v14_total'],
            original_total_side=ou['original_scout_side'],
            market_away_spread=row['ats_away_line'], market_total=row['ou_market_total'],
            quote_observed_utc=row['quote_observed_utc'], evaluation_utc=row['evaluated_utc'],
            kickoff_utc=row['kickoff_utc'])
        if any(expected[k] != row[k] for k in expected):
            raise ValueError('Dynamic decision differs from verified model receipts')
    return valid[-1]


def official_state(root, game_id, *, as_of_utc):
    start = activation(root)
    if start is None:
        raise ValueError('Official dynamic picks require production activation verification')
    row = validated_revision(root, game_id, as_of_utc)
    if row is None:
        return None
    boundary = _time(start['activated_at_utc'])
    path = Path(root)/'plug_dynamic_official'/(game_id+'.json')
    if _time(row['kickoff_utc']) <= boundary or not path.exists():
        return None
    issued = json.loads(path.read_text())
    if (issued.get('game_id') != game_id or issued.get('policy') != POLICY
            or not boundary <= _time(issued['issued_at_utc']) < _time(row['kickoff_utc'])
            or _time(issued['issued_at_utc']) > _time(as_of_utc)
            or _time(issued['kickoff_utc']) != _time(row['kickoff_utc'])
            or not any(r['sha256']==issued['revision_sha256'] for r in read(root,game_id))):
        raise ValueError('Invalid official dynamic issuance receipt')
    if _time(as_of_utc) >= _time(row['kickoff_utc']) and read_closing(root, game_id) is None:
        raise ValueError('Awaiting immutable dynamic closing receipt')
    return row


def apply(root, item, *, as_of_utc=None):
    """One overlay used by dashboard, detail, comparison, and APIs."""
    if os.environ.get('TREND_FINDAH_DYNAMIC_OFFICIAL') != '1':
        return False
    at = as_of_utc or datetime.now(timezone.utc).isoformat()
    gid = item['scout']['game']['game_id']
    try:
        with _lock(_path(root, gid)):
            return _apply_locked(root, item, gid, at)
    except (OSError, ValueError, KeyError, TypeError):
        return _review(item)


def _apply_locked(root, item, gid, at):
    row = official_state(root, gid, as_of_utc=at)
    if row is None:
        start = activation(root)
        if start is not None and _time(item['scout']['game']['kickoff_utc']) > _time(start['activated_at_utc']):
            raise ValueError('Awaiting verified prospective dynamic issuance')
        return False
    from plug_dynamic_authoritative import attach
    attached = attach(root, item, as_of_utc=at)
    if not attached:
        raise ValueError('Validated dynamic selection could not be displayed')
    item.pop('plug_dynamic_review', None)
    return True


def _review(item):
    # Remove every effective legacy/dynamic selection and grade. Archived
    # saved_picks remain untouched, but cannot leak into official results.
    for key in ('plug_dynamic_grades', 'plug_ats_decision', 'plug_ats_policy',
                'plug_ou_receipt'):
        item.pop(key, None)
    item.setdefault('completed_grades', {}).update(plug_ats=None, plug_total=None)
    item.update(plug_dynamic_official=True, plug_dynamic_review=True,
                plug_ats_status='review', plug_ou_status='review',
                plug_ats_pick=None, plug_ou_pick=None,
                plug_ats_result=None, plug_ou_result=None,
                plug_dynamic_card={'status':'unavailable', 'ats':'Awaiting verified selection',
                                   'ou':'Awaiting verified selection', 'note':'Receipt needs review'})
    return False


def history(root, finals, *, as_of_utc=None):
    """Separate official dynamic record; never add these wins to legacy totals."""
    at = as_of_utc or datetime.now(timezone.utc).isoformat()
    rows = []
    for path in sorted((Path(root)/'plug_dynamic_research').glob('*.jsonl')):
        row = official_state(root, path.stem, as_of_utc=at)
        if row is None:
            continue
        year, week, away, home = path.stem.split('_')
        result = {'ats':None, 'ou':None}
        if _time(at) >= _time(row['kickoff_utc']) and path.stem in finals:
            a, h = finals[path.stem]
            result = grade_closing(root, path.stem, away_score=a, home_score=h)
        rows.append(dict(row, season=int(year), week=int(week), away_team=away,
                         home_team=home, ats_result=result['ats'] or 'Pending',
                         ou_result=result['ou'] or 'Pending', policy=POLICY))
    return rows


def record_context(root, finals, season, week, *, as_of_utc=None):
    if os.environ.get('TREND_FINDAH_DYNAMIC_OFFICIAL') != '1':
        return {'dynamic_record_enabled':False}
    try:
        rows = history(root, finals, as_of_utc=as_of_utc)
        selected = [r for r in rows if r['season']==season and r['week']==week]
        counts = {m:{k:sum(r[m+'_selected'] and r[m+'_result']==k for r in selected)
                     for k in ('Win','Loss','Push','Pending')} for m in ('ats','ou')}
        return dict(dynamic_record_enabled=True, dynamic_record_review=False,
                    dynamic_record_rows=selected, dynamic_record_counts=counts)
    except (OSError,ValueError,KeyError,TypeError):
        return dict(dynamic_record_enabled=True, dynamic_record_review=True,
                    dynamic_record_rows=[], dynamic_record_counts={})
