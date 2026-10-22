"""Opt-in, persistent-budget Expert drafting after sealed forecast publication.

Defaults to OpenAI. No approvals/publications or HTTP page work. Request
reservations survive restarts and ambiguous failures; only explicit 429s retry.
"""
import argparse
import fcntl
import json
import os
import time
from datetime import timedelta
from pathlib import Path

from expert_beta import Store, canonical, clock, identity, instant


def production_queue(store_path, now=None, *, allow_retries=False):
    """Return unhandled production imports with future kickoffs, earliest first."""
    now = now or clock()
    records = Store(store_path).records()
    published = {
        identity(row['scout']) for row in records if row.get('expert') is not None
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
        if previous is None or (row['generated_at'], row['version']) > (previous['generated_at'], previous['version']):
            by_game[key] = row
    drafts = Path(store_path) / 'drafts'
    versions_by_game = {}
    for record in records:
        versions_by_game.setdefault(identity(record['scout']), set()).add(record['version'])
    queue, counts = [], {'imported_upcoming': len(by_game), 'published': 0,
                         'draft_saved': 0, 'attempt_requires_review': 0, 'retry_wait': 0}
    for row in by_game.values():
        version = row['version']
        versions = versions_by_game[identity(row['scout'])]
        if identity(row['scout']) in published:
            counts['published'] += 1
        elif any((drafts / (v + '.json')).exists() for v in versions):
            counts['draft_saved'] += 1
        elif any((drafts / (v + '.attempt.json')).exists() for v in versions) and not (
                allow_retries and versions_with_attempts(drafts, versions) == {version}
                and retry_ready(drafts, version, now)):
            # Even a failed or timed-out attempt may have consumed quota/spend.
            if (allow_retries and versions_with_attempts(drafts, versions) == {version}
                    and retry_pending(drafts, version)):
                counts['retry_wait'] += 1
            else:
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
            raise ValueError('Unreadable Expert attempt record; operator review required: ' + path.name) from error
        if started > now + timedelta(minutes=1):
            raise ValueError('Future-dated Expert attempt; operator review required: ' + path.name)
        if started > now - timedelta(hours=hours):
            recent.append(started)
    return sorted(recent)


def _gemini_run(store_path, model, *, daily_limit=2, run_limit=1, execute=False):
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


# Standard uncached text prices, USD / million tokens, verified 2026-10-22:
# https://developers.openai.com/api/docs/models/{gpt-4.1-mini,gpt-5-mini,gpt-4o-mini}
PRICES = {'gpt-4.1-mini': ('0.40', '1.60'), 'gpt-5-mini': ('0.25', '2.00'),
          'gpt-4o-mini': ('0.15', '0.60'),
          'gpt-4.1-mini-2025-04-14': ('0.40', '1.60'),
          'gpt-5-mini-2025-08-07': ('0.25', '2.00'),
          'gpt-4o-mini-2024-07-18': ('0.15', '0.60')}


def versions_with_attempts(folder, versions):
    return {v for v in versions if (folder/(v+'.attempt.json')).exists()}


def retry_pending(folder, version):
    path = folder/(version+'.outcome.json')
    if not path.exists():
        return False
    data = json.loads(path.read_text())
    attempts = list(folder.glob(version+'*.attempt.json'))
    return (data.get('state') == 'rate_limited' and data.get('provider') == 'openai'
            and data.get('attempts') == len(attempts) == 1)


def retry_ready(folder, version, now):
    if not retry_pending(folder, version):
        return False
    data = json.loads((folder/(version+'.outcome.json')).read_text())
    return instant(data['retry_at']) <= now


def positive_decimal(value):
    from decimal import Decimal
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError('Invalid nonnegative budget/rate')
    return number


def request_reserve(model, body):
    """One token/UTF-8 byte + framing, full output cap, doubled; no cache discounts."""
    from decimal import Decimal, ROUND_CEILING
    prices = PRICES.get(model)
    custom = os.environ.get('TREND_FINDAH_EXPERT_OPENAI_PRICING')
    if custom:
        custom = json.loads(custom)
        if custom.get('model') != model:
            raise ValueError('Pricing configuration must match the exact configured model')
        prices = (custom['input'], custom['output'])
    if prices is None:
        raise ValueError('Unknown model pricing; configure exact model rates before automation')
    input_rate, output_rate = map(positive_decimal, prices)
    if not input_rate or not output_rate:
        raise ValueError('Positive input/output prices required')
    input_bound = len(canonical(body)) + 1024
    return (((input_bound * input_rate + body['max_output_tokens'] * output_rate)
             * 2 / Decimal(1000000)).quantize(Decimal('0.000001'), rounding=ROUND_CEILING))


def immutable_json(path, data):
    """Durable, atomic, create-only JSON (a crash cannot leave a partial draft)."""
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.expert-', delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(canonical(data)); stream.flush(); os.fsync(stream.fileno())
            os.link(temp, path)  # Fails if any writer already reserved/saved this file.
            directory = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            temp.unlink(missing_ok=True)


def week_usage(root, records, week):
    """Never refund a reservation, even for failed, uncertain or rejected calls."""
    from decimal import Decimal
    versions = {r['version']: [int(r['scout']['game']['season']), int(r['scout']['game']['week'])]
                for r in records}
    total, requests = Decimal(0), 0
    for path in (root/'drafts').glob('*.attempt.json'):
        data = json.loads(path.read_text())
        version = data.get('version', path.name.split('.')[0])
        saved_week = data.get('nfl_week', versions.get(version))
        if (version != path.name.split('.')[0] or not isinstance(saved_week, list)
                or len(saved_week) != 2 or any(type(x) is not int for x in saved_week)
                or not 2000 <= saved_week[0] <= 2100 or not 1 <= saved_week[1] <= 22
                or (version in versions and saved_week != versions[version])):
            raise ValueError('Unattributed/inconsistent reservation needs operator review')
        if saved_week != list(week):
            continue
        requests += 1
        provider = data.get('provider')
        if provider == 'gemini':
            continue
        # Legacy paid requests without costs consume the entire initial allowance.
        reserve = positive_decimal(data.get('reserved_usd', '1'))
        if reserve <= 0:
            raise ValueError('Invalid paid reservation')
        total += reserve
    return total, requests


def openai_draft(root, row, records, model, weekly_limit, weekly_requests, daily_limit):
    from expert_beta import generate_draft, validate_expert
    from expert_provider import OpenAIProvider, RateLimited
    from scheduler_runtime import atomic_json
    version, scout = row['version'], row['scout']
    folder = root/'drafts'; folder.mkdir(exist_ok=True)
    attempts = list(folder.glob(version+'*.attempt.json'))
    if attempts and (not retry_ready(folder, version, clock())
                     or json.loads(attempts[0].read_text()).get('model') != model):
        raise ValueError('Previous request requires operator review')
    number = len(attempts) + 1
    outcome = folder/(version+'.outcome.json')
    provider = OpenAIProvider(approved=True, model=model)
    if not provider.api_key or not provider.model:
        raise ValueError('OpenAI credentials/model missing; no request reserved')
    sent = False
    def reserved_provider(packet):
        nonlocal sent
        if (instant(scout['game']['kickoff_utc'])-clock()).total_seconds() <= 125:
            raise ValueError('Insufficient pre-kickoff request window')
        body = provider.request_body(packet)
        cost = request_reserve(model, body)
        week = (int(scout['game']['season']), int(scout['game']['week']))
        spent, requests = week_usage(root, records, week)
        if spent + cost > weekly_limit or requests >= weekly_requests:
            raise BudgetExhausted('NFL week budget exhausted')
        if len(recent_attempts(root, clock())) >= daily_limit:
            raise BudgetExhausted('Daily request budget exhausted')
        name = version + ('' if number == 1 else '.retry-'+str(number)) + '.attempt.json'
        immutable_json(folder/name, dict(version=version, started_at=clock().isoformat(),
            model=model, provider='openai', nfl_week=list(week), reserved_usd=str(cost)))
        sent = True
        return provider(packet)
    try:
        result = generate_draft(scout, reserved_provider)
        # Pure validation envelope only: these approval fields are NEVER persisted.
        validate_expert({**result, 'review_status':'approved', 'reviewer':'structure-check-only',
                         'reviewed_at':clock().isoformat()}, scout)
        if not isinstance(result.get('summary'), str) or not result['summary'].strip():
            raise ValueError('Nonempty report summary required')
        if clock() >= instant(scout['game']['kickoff_utc']):
            raise ValueError('Report completed after kickoff; nothing saved')
        immutable_json(folder/(version+'.json'), result)
        atomic_json(outcome, dict(state='pending_review', provider='openai', attempts=number))
        return 'saved'
    except RateLimited as error:
        atomic_json(outcome, dict(state='rate_limited' if number < 2 else 'review_required',
            provider='openai', attempts=number,
            retry_at=(clock()+timedelta(seconds=error.retry_after)).isoformat()))
        return 'retry_wait' if number < 2 else 'operator_review_required'
    except Exception:
        if sent:
            atomic_json(outcome, dict(state='uncertain', provider='openai', attempts=number))
        raise


class BudgetExhausted(RuntimeError):
    pass


def bounded_run(store_path, model=None, *, daily_limit=16, run_limit=1,
                execute=False, provider_name=None, weekly_limit=None, weekly_requests=None):
    provider_name = provider_name or os.environ.get('TREND_FINDAH_EXPERT_AUTO_PROVIDER', 'openai')
    if provider_name == 'gemini':
        return _gemini_run(store_path, model or os.environ.get('TREND_FINDAH_EXPERT_GEMINI_MODEL',
                           'gemini-2.5-flash'), daily_limit=daily_limit, run_limit=run_limit, execute=execute)
    if provider_name != 'openai':
        raise ValueError('Unsupported automatic Expert provider')
    # Fallback is allowed only BEFORE transmission, never after an uncertain call.
    if (not os.environ.get('OPENAI_API_KEY') and
            os.environ.get('TREND_FINDAH_EXPERT_FALLBACK_PROVIDER') == 'gemini'):
        return _gemini_run(store_path, os.environ.get('TREND_FINDAH_EXPERT_GEMINI_MODEL',
                           'gemini-2.5-flash'), daily_limit=daily_limit, run_limit=run_limit, execute=execute)
    if execute and os.environ.get('TREND_FINDAH_EXPERT_AUTO_DRAFT') != '1':
        raise ValueError('Automatic OpenAI drafting disabled: explicit opt-in required')
    model = model or os.environ.get('EXPERT_AI_MODEL')
    weekly_requests = weekly_requests if weekly_requests is not None else int(
        os.environ.get('TREND_FINDAH_EXPERT_WEEKLY_REQUEST_LIMIT', '32'))
    if not 1 <= daily_limit <= 16 or not 1 <= run_limit <= 4 or not 1 <= weekly_requests <= 32:
        raise ValueError('Request limits outside conservative bounds')
    budget = positive_decimal(weekly_limit if weekly_limit is not None else
                              os.environ.get('TREND_FINDAH_EXPERT_WEEKLY_BUDGET_USD', '1'))
    if budget > 1:
        raise ValueError('Initial automatic weekly allowance cannot exceed $1')
    root = Path(store_path)
    if not root.is_dir():
        raise ValueError('Expert store does not exist')
    with (root/'automation.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {'state':'lock_busy', 'saved_drafts':0}
        queue, counts = production_queue(root, allow_retries=True)
        used = len(recent_attempts(root, clock()))
        planned = min(run_limit, max(0, daily_limit-used), len(queue))
        output = dict(checked_at=clock().isoformat(), provider='openai', model=model,
            **counts, attempts_last_24h=used, planned_requests=planned,
            weekly_budget_usd=str(budget), weekly_request_limit=weekly_requests,
            saved_drafts=0, state='preview' if not execute else 'nothing_due_or_budget_exhausted')
        if execute and planned:
            records = Store(root).records()
            for row in queue[:planned]:
                try:
                    state = openai_draft(root, row, records, model, budget, weekly_requests, daily_limit)
                    output['state'] = 'complete' if state == 'saved' else state
                    if state == 'saved': output['saved_drafts'] += 1
                    else: break
                except BudgetExhausted:
                    output['state'] = 'budget_exhausted'; break
                except Exception as error:
                    output.update(state='operator_review_required', error_type=type(error).__name__)
                    break
        if execute:
            from scheduler_runtime import atomic_json
            atomic_json(root/'automation_status.json', output)
        return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--model')
    parser.add_argument('--provider', choices=('openai','gemini'), default=None)
    parser.add_argument('--daily-limit', type=int, default=16)
    parser.add_argument('--run-limit', type=int, default=1)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(bounded_run(args.store, args.model, daily_limit=args.daily_limit,
                                 run_limit=args.run_limit, execute=args.execute, provider_name=args.provider), indent=2))


if __name__ == '__main__':
    main()
