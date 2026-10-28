"""Opt-in updates on Render's persistent disk; never run on page requests."""
import json
import logging
from membership_backups import backup_database
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parent


def initialize_data(source, target):
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob('*.csv'):
        saved = target / path.name
        if not saved.exists():
            shutil.copy2(path, saved)
        if not path.is_symlink():
            temporary = path.with_suffix('.persistent-link')
            temporary.symlink_to(saved)
            temporary.replace(path)
    for relative in ('data/scout4', 'data/member_lines', 'data/research_qbs', 'logs'):
        original, saved = source / relative, target / relative
        if original.is_symlink():
            continue
        if not saved.exists():
            if original.exists():
                shutil.copytree(original, saved)
            else:
                saved.mkdir(parents=True)
        if original.exists():
            shutil.rmtree(original)
        original.parent.mkdir(parents=True, exist_ok=True)
        original.symlink_to(saved, target_is_directory=True)


def configure_persistent_data():
    enabled = os.environ.get('TREND_FINDAH_AUTO_UPDATE') == '1'
    production = os.environ.get('TREND_FINDAH_ENV') == 'production'
    target = Path('/var/data/site-data')
    if not enabled and not (production and target.exists()):
        return
    if not production:
        raise RuntimeError('Automatic updates require the hosted production environment')
    if not Path('/var/data').is_dir():
        raise RuntimeError('Automatic updates require the persistent /var/data disk')
    initialize_data(SOURCE, target)


def update_once(root, feed_lock_fd=None):
    root = Path(root)
    season = datetime.now(timezone.utc).year
    if datetime.now(timezone.utc).month < 8:
        season -= 1
    started = datetime.now(timezone.utc).isoformat()
    if shutil.disk_usage(root).free < 128 * 1024 * 1024:
        status = {'started':started, 'finished':started, 'state':'needs attention',
                  'stages':{'storage':'Updates paused: less than 128 MB free'}}
        (root/'logs/auto_update_status.json').write_text(json.dumps(status))
        return status
    stages = {}
    def attempt(name, action):
        from scheduler_runtime import atomic_json
        stages[name] = 'running'
        def progress():
            atomic_json(root/'logs/auto_update_status.json', {
                'started':started, 'checked_at':datetime.now(timezone.utc).isoformat(),
                'state':'running', 'pid':os.getpid(), 'stages':dict(stages)})
        progress()
        scheduler_event(root, 'scout-worker', 'stage_started', stage=name)
        try:
            action()
            stages[name] = 'ok'
        except Exception as error:
            stages[name] = 'failed: ' + type(error).__name__
            print(f'Automatic update {name} failed: {type(error).__name__}; returncode={getattr(error, "returncode", None)}', flush=True)
        progress()
        scheduler_event(root, 'scout-worker', 'stage_finished', stage=name, result=stages[name])
    attempt('account backup', lambda: backup_database(
        os.environ.get('TREND_FINDAH_DATABASE', '/var/data/members.sqlite3'),
        Path(os.environ.get('TREND_FINDAH_DATABASE', '/var/data/members.sqlite3')).resolve().parent/'account-backups'))
    def feed(kind):
        if feed_lock_fd is not None:
            # Child retains the shared lock even if this supervisor is killed.
            subprocess.run([sys.executable, str(SOURCE/'update_feed_worker.py'),
                kind, str(root), str(season)], check=True, timeout=180,
                pass_fds=(feed_lock_fd,), cwd=SOURCE,
                env={**os.environ, 'POLARS_MAX_THREADS':'1'})
        elif kind == 'finals':
            import update_nfl_games as finals
            finals.BACKUPS = root/'backups'
            finals.main(['--apply','--season',str(season),'--file',str(root/'nfl_games.csv')])
        elif kind == 'context':
            from scout4.context_model import refresh_sources
            refresh_sources(season, root)
        else:
            from scout4.collect import collect
            collect(season, root/'data/scout4')
    attempt('finals', lambda: feed('finals'))
    from qb_verification import refresh_qbs
    attempt('QB verification', lambda: refresh_qbs(root,season))
    attempt('stats', lambda: feed('stats'))
    def capture():
        from scheduled_ats_capture import run as quotes
        if quotes(root) != 0:
            raise RuntimeError('Market capture failed')
    attempt('quotes', capture)
    if os.environ.get('TREND_FINDAH_CONTEXT_RESEARCH') == '1' and stages['stats']=='ok':
        attempt('injury/weather collection', lambda: feed('context'))
    if all(stages[name]=='ok' for name in ('finals','stats','quotes')):
        from prediction_staging import run_staged as predictions
        attempt('predictions', lambda: predictions(root, SOURCE, SOURCE/'automatic_model.json'))
    else:
        stages['predictions'] = 'skipped: upstream update failed'
    # The Plug's totals selection is separate from immutable Scout forecasts.
    # A failure here never blocks ATS/Scout publication or the Expert queue.
    from plug_ou_receipts import issue_pending as issue_plug_totals
    attempt('Plug O/U selections', lambda: issue_plug_totals(root))
    # Versioned official shortlist: never backfill after first kickoff.
    from plug_ou_weekly import issue_weekly as issue_plug_ou_shortlist
    attempt('Plug O/U weekly shortlist', lambda: issue_plug_ou_shortlist(root))
    # Publication copies only sealed approved records, even if this refresh failed.
    # It never calls experimental engines or AI, and cannot publish review drafts.
    from plug_publication import publish
    expert_store = Path(os.environ.get('TREND_FINDAH_EXPERT_STORE',
        '/var/data/expert_beta' if os.environ.get('TREND_FINDAH_ENV')=='production'
        else str(root/'expert_beta')))
    attempt('Plug publication', lambda: publish(root, expert_store,
        SOURCE/'automatic_model.json'))
    # Expert drafting is explicitly opt-in and runs only after a successful production
    # import. It saves drafts for review, never auto-approves or publishes prose.
    if (stages.get('Plug publication') == 'ok'
            and os.environ.get('TREND_FINDAH_EXPERT_AUTO_DRAFT') == '1'):
        from expert_auto_queue import bounded_run
        def expert_drafts():
            result = bounded_run(
                expert_store,
                None,
                daily_limit=int(os.environ.get('TREND_FINDAH_EXPERT_DAILY_LIMIT', '16')),
                run_limit=int(os.environ.get('TREND_FINDAH_EXPERT_RUN_LIMIT', '1')),
                execute=True)
            if result['state'] == 'operator_review_required':
                raise RuntimeError('Expert draft requires operator review; will not retry')
        attempt('Expert draft queue', expert_drafts)
    def grade():
        from fan_views import prediction_performance
        from scout4.stats import read_csv
        records = [json.loads(p.read_text()) for p in (root/'data/scout4/blend/predictions').glob('*.json')]
        schedule_rows = read_csv(root/'nfl_games.csv')
        groups, recent, excluded = prediction_performance(records, schedule_rows)
        from scout4.research_benchmarks import grade_benchmarks
        schedule = {g['game_id']:g for g in schedule_rows}
        research = {}
        for record in records:
            try: outcomes = grade_benchmarks(record, schedule.get(record['game_id']))
            except (ValueError,KeyError,TypeError): continue
            for name, result in outcomes.items():
                key = record.get('version','Unknown')+' / '+name
                counts = research.setdefault(key, {})
                counts[result] = counts.get(result, 0)+1
        target = root/'data/scout4/blend/automatic_results.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'groups':groups,'recent':recent,'excluded':excluded,'research_benchmarks':research},indent=2))
        temporary.replace(target)
    attempt('grading', grade)
    # Optional research collection is separate from the locked prediction model.
    if os.environ.get('TREND_FINDAH_CONTEXT_RESEARCH') == '1':
        from scout4.context_model import capture as capture_context
        attempt('injury/weather research', lambda: capture_context(root))
    status = {'started':started,'finished':datetime.now(timezone.utc).isoformat(),
              'state':'ok' if all(v=='ok' for v in stages.values()) else 'needs attention','stages':stages}
    path = root/'logs/auto_update_status.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp');temp.write_text(json.dumps(status,indent=2));temp.replace(path)
    return status


def refresh_game_day_market(root, now=None):
    """Refresh public splits on game days without running models or AI."""
    from scheduled_ats_capture import upcoming_games, run
    from zoneinfo import ZoneInfo
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    import csv
    with (Path(root)/'nfl_games.csv').open(newline='',encoding='utf-8-sig') as source:
        ids = {row['game_id'] for row in csv.DictReader(source) if row.get('gameday') == today}
    if ids.intersection(upcoming_games(Path(root), now)):
        if run(Path(root), now) != 0:
            raise RuntimeError('Game-day market refresh failed')


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
HOSTED_ROOT = Path('/var/data/site-data')
LOCK_BUSY = 75
_START_LOCK = threading.Lock()
_SCHEDULER_THREAD = None


def scheduler_event(root, job, state, **details):
    """Append durable attempt history; logging trouble must not kill a timer."""
    details.setdefault('pid', os.getpid())
    event = dict(at=datetime.now(timezone.utc).isoformat(), job=job,
                 state=state, **details)
    LOGGER.info('Hosted scheduler %s', json.dumps(event))
    try:
        logs = Path(root)/'logs'
        logs.mkdir(parents=True, exist_ok=True)
        with (logs/(job + '_scheduler.jsonl')).open('a') as stream:
            stream.write(json.dumps(event) + '\n')
    except Exception:
        LOGGER.exception('Cannot persist scheduler event for %s', job)


def scheduler_loop(job, action, interval, root=HOSTED_ROOT, stop=None, log_poll=True):
    stop = stop or threading.Event()
    while not stop.is_set():
        if log_poll:
            scheduler_event(root, job, 'attempt')
        delay = interval
        try:
            result = action()
            if result == LOCK_BUSY:
                scheduler_event(root, job, 'lock_busy', retry_seconds=60)
                delay = 60
                if job == 'automatic-data-updates':
                    scout_status(root, 'waiting for lock', 'lock contention; retry in 60 seconds')
            elif result != 'not_due':
                scheduler_event(root, job, 'success')
        except Exception as error:
            LOGGER.exception('Hosted scheduler %s failed', job)
            scheduler_event(root, job, 'failure', error_type=type(error).__name__,
                            error=str(error))
            if job == 'automatic-data-updates':
                reason = type(error).__name__
                if isinstance(error, subprocess.TimeoutExpired):
                    reason += f' after {error.timeout} seconds'
                elif isinstance(error, subprocess.CalledProcessError):
                    reason += f' (exit {error.returncode})'
                scout_status(root, 'needs attention', reason)
            delay = interval
        stop.wait(delay)


def run_worker(script, arguments=(), timeout=180):
    result = subprocess.run([sys.executable, str(SOURCE/script), *arguments],
        cwd=SOURCE, timeout=timeout, check=False,
        env={**os.environ, 'POLARS_MAX_THREADS':'1'})
    if result.returncode not in (0, LOCK_BUSY):
        raise subprocess.CalledProcessError(result.returncode, result.args)
    return result.returncode


def scout_status(root, state, reason):
    from scheduler_runtime import atomic_json
    try:
        path = Path(root)/'logs/auto_update_status.json'
        report = {'checked_at':datetime.now(timezone.utc).isoformat(),
                  'state':state, 'stages':{'scheduler':reason}}
        if state == 'needs attention' and path.exists():
            previous = json.loads(path.read_text())
            report['stages'] = {**previous.get('stages', {}), 'scheduler':reason}
        atomic_json(path, report)
    except Exception:
        LOGGER.exception('Cannot persist Scout scheduler status')


def start_scheduler():
    global _SCHEDULER_THREAD
    if os.environ.get('TREND_FINDAH_AUTO_UPDATE') != '1':
        return
    with _START_LOCK:
        if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
            return
        _SCHEDULER_THREAD = threading.Thread(target=leadership_loop,
                                            name='scheduler-leadership', daemon=True)
        _SCHEDULER_THREAD.start()


def leadership_loop(root=None, stop=None):
    from scheduler_runtime import exclusive
    root = Path(root or HOSTED_ROOT)
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            with exclusive(root/'logs/scheduler-leader.lock') as leader:
                if leader:
                    scheduler_event(root, 'leadership', 'acquired', pid=os.getpid())
                    run_leader(root, stop)
                else:
                    scheduler_event(root, 'leadership', 'standby', pid=os.getpid())
        except Exception as error:
            scheduler_event(root, 'leadership', 'failure', error_type=type(error).__name__)
        stop.wait(5)


def run_leader(root, stop):
    from scheduler_runtime import due_job
    checked = None
    observed_cutoff = None
    next_weekly_attempt = None

    def weekly_due():
        """Cheap 30-second poll; avoid a worker and disk lease for idle polls."""
        nonlocal checked, observed_cutoff, next_weekly_attempt
        from site_week import week_window
        now = datetime.now(timezone.utc)
        cutoff = week_window(now)[0].astimezone(timezone.utc)
        if cutoff != observed_cutoff:
            # The new Wednesday window must not inherit last week's backoff.
            observed_cutoff, checked, next_weekly_attempt = cutoff, None, None
        if checked == cutoff:
            return False
        capture_window = cutoff <= now < cutoff + timedelta(minutes=10)
        if not capture_window and next_weekly_attempt is not None and now < next_weekly_attempt:
            return False
        status = root/'logs/weekly_lines_status.json'
        try:
            saved = json.loads(status.read_text()) if status.exists() else {}
        except (OSError, ValueError):
            saved = {}
        if (isinstance(saved, dict) and saved.get('state') == 'ready'
                and saved.get('published') is True
                and saved.get('scheduled_cutoff') == cutoff.isoformat()):
            checked = cutoff
            return False
        return True

    def weekly():
        nonlocal checked, next_weekly_attempt
        from site_week import week_window
        now = datetime.now(timezone.utc)
        start, end = (part.astimezone(timezone.utc) for part in week_window(now))
        if start <= now < start + timedelta(minutes=10):
            next_weekly_attempt = now + timedelta(seconds=30)
        else:
            # Recheck pending snapshots within 15 minutes, but never sleep past
            # Wednesday's 8 a.m. ET cutoff. Other game-day jobs are unchanged.
            next_weekly_attempt = min(now + timedelta(minutes=15), end)
        worker_result = run_worker('weekly_pick_lines.py')
        if worker_result == LOCK_BUSY:
            # Let the existing durable job lease handle 60-second lock retries.
            next_weekly_attempt = None
            return LOCK_BUSY
        status = root/'logs/weekly_lines_status.json'
        try:
            saved = json.loads(status.read_text()) if status.exists() else {}
        except (OSError, ValueError):
            saved = {}
        if (isinstance(saved, dict) and saved.get('state') == 'ready'
                and saved.get('published') is True
                and saved.get('scheduled_cutoff') == start.isoformat()):
            checked = start
        return worker_result

    def scout():
        from site_week import week_window
        now = datetime.now(timezone.utc)
        current, upcoming = (value.astimezone(timezone.utc) for value in week_window(now))
        # Recheck after each wait so we never run inside the weekly capture window.
        while (0 <= (now-current).total_seconds() < 180
               or 0 <= (upcoming-now).total_seconds() <= 600):
            delay = (180-(now-current).total_seconds() if now >= current
                     and (now-current).total_seconds() < 180
                     else (upcoming-now).total_seconds()+180)
            if stop.wait(delay):
                return 'not_due'
            now = datetime.now(timezone.utc)
            current, upcoming = (value.astimezone(timezone.utc) for value in week_window(now))
        scout_status(root, 'running', 'scheduled update started')
        return run_worker('hosted_updates.py', ['--once'], timeout=600)


    def newsletter_draft():
        # Both editions use the existing worker and Scout exclusion lock.
        from newsletter import (wednesday_draft_due, prepare_wednesday_draft,
                                completed_month_draft_due, prepare_completed_month_draft)
        now = datetime.now(timezone.utc)
        weekly = (os.environ.get('TREND_FINDAH_NEWSLETTER_WEDNESDAY_PREP', '1') == '1'
                  and wednesday_draft_due(now))
        monthly = (os.environ.get('TREND_FINDAH_NEWSLETTER_MONTHLY_PREP', '1') == '1'
                   and completed_month_draft_due(now))
        if not (weekly or monthly):
            return 'not_due'

        from scheduler_runtime import exclusive
        with exclusive(root / 'logs/auto_update.lock') as acquired:
            if not acquired:
                return LOCK_BUSY
            from wsgi import app
            results = []
            if weekly:
                results.append(prepare_wednesday_draft(app, now=now))
            if monthly:
                results.append(prepare_completed_month_draft(app, now=now))
            return 'prepared' if any(result != 'not_due' for result in results) else 'not_due'

    jobs = (
        ('game-day-stats', lambda: run_worker('gameday_stats.py', [], 420), 3600),
        ('expert-only-updates', lambda: run_worker('expert_automation.py', ['--once'], 900), 300),
        ('game-day-market', lambda: run_worker('hosted_updates.py', ['--game-day-market']), 900),
        ('automatic-weekly-lines', weekly, 30),
        ('automatic-data-updates', scout, 21600),
        ('weekly-newsletter-draft', newsletter_draft, 300),
    )
    threads = []
    try:
        for name, action, interval in jobs:
            timeout = 480 if name == 'game-day-stats' else 900 if name == 'expert-only-updates' else 1500 if name == 'automatic-data-updates' else 180
            def scheduled(name=name, action=action, interval=interval, timeout=timeout):
                if name == 'weekly-newsletter-draft':
                    return action()
                if name == 'automatic-weekly-lines' and not weekly_due():
                    return 'not_due'
                def execute():
                    scheduler_event(root, name, 'attempt')
                    return action()
                def recovery(saved):
                    scheduler_event(root, name, 'interrupted', reservation=saved)
                    if name == 'automatic-data-updates':
                        scout_status(root, 'needs attention',
                            'Previous supervisor exited without completion; recovery lease retained until '
                            + datetime.fromtimestamp(saved['next_due'], timezone.utc).isoformat())
                return due_job(root, name, execute, interval, timeout, on_recovery=recovery)
            thread = threading.Thread(target=scheduler_loop,
                args=(name, scheduled, min(interval, 30), root, stop, False), name=name, daemon=True)
            thread.start()
            threads.append(thread)
        # Keep leadership until every owned loop has stopped.
        for thread in threads:
            thread.join()
    finally:
        stop.set()
        for thread in threads:
            thread.join()


def locked_update(root, market=False):
    """Return a distinct retryable code on contention; keep the shared lock."""
    import fcntl
    root = Path(root)
    (root/'logs').mkdir(parents=True, exist_ok=True)
    job = 'market-worker' if market else 'scout-worker'
    scheduler_event(root, job, 'attempt')
    with (root/'logs/auto_update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            scheduler_event(root, job, 'lock_busy')
            return LOCK_BUSY
        try:
            result = (refresh_game_day_market(root) if market
                      else update_once(root, feed_lock_fd=lock.fileno()))
            failed = isinstance(result, dict) and result.get('state') != 'ok'
            scheduler_event(root, job, 'failure' if failed else 'success')
            return 1 if failed else 0
        except Exception as error:
            LOGGER.exception('Hosted worker %s failed', job)
            scheduler_event(root, job, 'failure', error_type=type(error).__name__, error=str(error))
            if not market:
                try:
                    status = {'finished': datetime.now(timezone.utc).isoformat(),
                              'state': 'needs attention',
                              'stages': {'worker': type(error).__name__ + ': ' + str(error)}}
                    path = root/'logs/auto_update_status.json'
                    temporary = path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(status, indent=2))
                    temporary.replace(path)
                except Exception:
                    LOGGER.exception('Cannot persist Scout failure status')
            return 1


if __name__ == '__main__':
    if sys.argv[1:] not in (['--once'], ['--game-day-market']) or os.environ.get('TREND_FINDAH_AUTO_UPDATE') != '1':
        raise SystemExit('This updater is enabled only through hosted automatic updates')
    raise SystemExit(locked_update(HOSTED_ROOT, market=sys.argv[1:] == ['--game-day-market']))
