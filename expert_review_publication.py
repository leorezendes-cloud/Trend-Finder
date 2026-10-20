"""Publish operator-approved Gemini reviews and select two weekly free reports.

No provider requests, no forecast generation, no source refresh, and no HTTP work.
Only sealed production imports with future kickoffs are eligible. A reviewer
must separately inspect the saved Gemini draft and create a *.review.json whose
only differences are review_status, reviewer, and reviewed_at.

The deployed site's existing Store and CLI are the single source of truth for
validation, immutable expert records, and featured-access enforcement.
"""
import argparse
import fcntl
import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from expert_beta import Store, canonical, clock, identity, instant, validate_expert

EDITORIAL_FIELDS = frozenset(('review_status', 'reviewer', 'reviewed_at'))


def candidates(root, now=None):
    """Validate reviewed draft/production pair before any write; fail closed."""
    now = now or clock()
    root = Path(root)
    records = Store(root).records()
    published = {
        hashlib.sha256(canonical(row['scout'])).hexdigest()
        for row in records if row.get('expert') is not None
    }
    by_game = {}
    for row in records:
        if row.get('kind') != 'production_import':
            continue
        scout = row['scout']
        if instant(scout['game']['kickoff_utc']) <= now:
            continue
        name = identity(scout)
        old = by_game.get(name)
        if old is None or (row['generated_at'], row['version']) > (old['generated_at'], old['version']):
            by_game[name] = row

    ready = []
    stats = {'imported_upcoming': len(by_game), 'already_published': 0,
             'awaiting_draft': 0, 'awaiting_review': 0,
             'rejected_or_pending_review': 0, 'approved_ready': 0}
    for row in by_game.values():
        if hashlib.sha256(canonical(row['scout'])).hexdigest() in published:
            stats['already_published'] += 1
            continue
        version = row['version']
        draft_path = root/'drafts'/(version+'.json')
        review_path = root/'drafts'/(version+'.review.json')
        if not review_path.exists():
            stats['awaiting_review' if draft_path.exists() else 'awaiting_draft'] += 1
            continue
        if not draft_path.is_file():
            raise ValueError('Reviewed Expert file lacks original draft: '+version)
        try:
            original = json.loads(draft_path.read_text())
            reviewed = json.loads(review_path.read_text())
        except (OSError, ValueError) as error:
            raise ValueError('Unreadable saved Expert review: '+version) from error
        if not isinstance(original, dict) or not isinstance(reviewed, dict):
            raise ValueError('Malformed saved Expert review: '+version)
        if reviewed.get('review_status') != 'approved':
            stats['rejected_or_pending_review'] += 1
            continue
        # The reviewer can approve or reject; changing evidence or AI claims
        # silently is not allowed. Revised claims require a new verified draft.
        a = {k:v for k,v in original.items() if k not in EDITORIAL_FIELDS}
        b = {k:v for k,v in reviewed.items() if k not in EDITORIAL_FIELDS}
        if a != b:
            raise ValueError('Saved Expert review changed AI claims: '+version)
        validate_expert(reviewed, row['scout'])
        if instant(reviewed['reviewed_at']) > now + timedelta(minutes=1):
            raise ValueError('Expert review timestamp is in the future: '+version)
        ready.append((row, reviewed))
    ready.sort(key=lambda pair: (instant(pair[0]['scout']['game']['kickoff_utc']), identity(pair[0]['scout'])))
    stats['approved_ready'] = len(ready)
    return ready, stats


def feature_two(root, now=None, execute=False):
    """Freeze two *published, upcoming* Expert games per week, if enough exist.

    Never replace an existing featured selection. In a <2-game week, leave the
    feature file absent: existing Store.featured() deliberately requires two.
    """
    now = now or clock()
    root = Path(root)
    grouped = defaultdict(dict)
    for row in Store(root).records():
        if not row.get('expert'):
            continue
        scout = row['scout']
        if instant(scout['game']['kickoff_utc']) <= now:
            continue
        game = scout['game']
        key = (int(game['season']), int(game['week']))
        name = identity(scout)
        grouped[key][name] = (instant(game['kickoff_utc']), name)

    selected = {}
    for (season, week), items in sorted(grouped.items()):
        path = root/'featured'/f'{season}-{week}.json'
        if path.exists():
            # Existing selections are immutable; validate rather than overwrite.
            Store(root).featured(season, week)
            continue
        if len(items) < 2:
            continue
        chosen = [name for _, name in sorted(items.values())[:2]]
        selected[f'{season}-{week}'] = chosen
        if execute:
            # Reuse existing authoritative freeze / validation logic.
            from expert_beta_cli import feature
            feature(root, season, week, [x.split('/')[-1] for x in chosen])
    return selected


def run(root, *, execute=False, auto_feature=True):
    """Idempotent sync, locked alongside Gemini draft queue."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError('Expert archive directory missing: '+str(root))
    with (root/'automation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = clock()
        ready, stats = candidates(root, now)
        if execute:
            # Existing Store.append validates the complete report and records
            # a new immutable version; never alters source forecast or draft.
            for row, report in ready:
                Store(root).append(row['scout'], expert=report, kind='development')
        features = feature_two(root, now, execute=execute) if auto_feature else {}
        result = {'checked_at':now.isoformat(), **stats,
                  'published_now':len(ready) if execute else 0,
                  'featured_selected':features,
                  'state':'complete' if execute else 'preview'}
        if execute:
            temp = root/'review_publication_status.tmp'
            temp.write_text(json.dumps(result, indent=2))
            temp.replace(root/'review_publication_status.json')
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--no-auto-feature', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(run(args.store, execute=args.execute,
                         auto_feature=not args.no_auto_feature), indent=2))


if __name__ == '__main__':
    main()
