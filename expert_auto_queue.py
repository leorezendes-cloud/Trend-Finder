"""Opt-in, budget-limited Gemini drafts for sealed production Scout forecasts.

Runs after Plug publication, never during a page request. Only makes drafts; it
never approves/publishes Expert prose or chooses free featured games.

Fail-closed defaults: no calls without both TREND_FINDAH_EXPERT_AUTO_DRAFT=1 and
EXPERT_GEMINI_FREE_TIER_CONFIRMED=1 in the environment. The latter is an operator
attestation, NOT a substitute for verifying that billing really is disabled.
"""
import argparse
import fcntl
import hashlib
import json
import os
import time
from datetime import timedelta
from pathlib import Path

from expert_beta import Store, canonical, clock, identity, instant


def production_queue(store_path, now=None):
    """Return unhandled production imports with future kickoffs, earliest first."""
    now = now or clock()
    records = Store(store_path).records()
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
        key = identity(scout)
        # Keep the latest sealed production import if more than one is present.
        previous = by_game.get(key)
        if previous is None or row['generated_at'] > previous['generated_at']:
            by_game[key] = row
    drafts = Path(store_path) / 'drafts'
    queue, counts = [], {'imported_upcoming': len(by_game), 'published': 0,
                         'draft_saved': 0, 'attempt_requires_review': 0}
    for row in by_game.values():
        version = row['version']
        digest = hashlib.sha256(canonical(row['scout'])).hexdigest()
        if digest in published:
            counts['published'] += 1
        elif (drafts / (version + '.json')).exists():
            counts['draft_saved'] += 1
        elif (drafts / (version + '.attempt.json')).exists():
            # Even a failed or timed-out attempt may have consumed free quota.
            counts['attempt_requires_review'] += 1
        else:
            queue.append(row)
    queue.sort(key=lambda r: (instant(r['scout']['game']['kickoff_utc']), identity(r['scout'])))
    counts['ready'] = len(queue)
    return queue, counts


def recent_attempts(store_path, now, hours=24):
    """Use persistent attempt reservations, including failures, as a conservative cap."""
    recent = []
    for path in (Path(store_path) / 'drafts').glob('*.attempt.json'):
        try:
            started = instant(json.loads(path.read_text())['started_at'])
        except (ValueError, TypeError, KeyError, OSError) as error:
            # An unreadable reservation must not silently free quota capacity.
            raise ValueError('Unreadable Gemini attempt record; operator review required: ' + path.name) from error
        if started > now + timedelta(minutes=1):
            raise ValueError('Future-dated Gemini attempt; operator review required: ' + path.name)
        if started > now - timedelta(hours=hours):
            recent.append(started)
    return sorted(recent)


def bounded_run(store_path, model, *, daily_limit=2, run_limit=1, execute=False):
    """Safely handle a small number of drafts without touching any Scout model."""
    store_path = Path(store_path)
    if not 1 <= daily_limit <= 16 or not 1 <= run_limit <= 4:
        raise ValueError('daily_limit must be 1..16 and run_limit must be 1..4')
    if not model or not model.strip():
        raise ValueError('Explicit Gemini model required')
    if execute and (os.environ.get('TREND_FINDAH_EXPERT_AUTO_DRAFT') != '1'
                    or os.environ.get('EXPERT_GEMINI_FREE_TIER_CONFIRMED') != '1'):
        raise ValueError('Gemini drafting disabled: explicit operator opt-in and verified free-tier billing settings required')
    if not store_path.is_dir():
        raise ValueError('Expert store does not exist: ' + str(store_path))
    # Lock across both scheduled and manual instances on this persistent disk.
    with (store_path / 'automation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = clock()
        queue, counts = production_queue(store_path, now)
        used = len(recent_attempts(store_path, now))
        capacity = max(0, daily_limit - used)
        planned = min(capacity, run_limit, len(queue))
        output = {'checked_at': now.isoformat(), 'model': model, **counts,
                  'attempts_last_24h': used, 'limit_24h': daily_limit,
                  'planned_requests': planned, 'saved_drafts': 0,
                  'state': 'preview' if not execute else 'complete'}
        if execute and planned:
            from expert_beta_cli import draft
            # Pace multi-game batches (one request every 75s or slower). Automatic
            # default stays at one request; operators may increase it only after
            # verifying their project's actual free-tier rate and daily limits.
            for index, row in enumerate(queue[:planned]):
                if index:
                    time.sleep(75)
                if instant(row['scout']['game']['kickoff_utc']) <= clock():
                    output['state'] = 'kickoff_reached'
                    break
                try:
                    draft(store_path, row['version'], approved=False,
                          model=model, provider_name='gemini')
                except Exception as error:
                    # The existing provider writes .attempt.json before calling
                    # Gemini. Leave it in place; never auto-retry an unknown result.
                    output['state'] = 'operator_review_required'
                    output['error_type'] = type(error).__name__
                    break
                output['saved_drafts'] += 1
        elif execute and not planned:
            output['state'] = 'nothing_due_or_budget_exhausted'
        # Atomic status update; no API keys, provider prompts or report bodies.
        if execute:
            temporary = store_path / 'automation_status.tmp'
            temporary.write_text(json.dumps(output, indent=2))
            temporary.replace(store_path / 'automation_status.json')
        return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--model', default='gemini-2.5-flash')
    parser.add_argument('--daily-limit', type=int, default=2)
    parser.add_argument('--run-limit', type=int, default=1)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(bounded_run(args.store, args.model, daily_limit=args.daily_limit,
                                 run_limit=args.run_limit, execute=args.execute), indent=2))


if __name__ == '__main__':
    main()
