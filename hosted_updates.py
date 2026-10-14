"""Opt-in updates on Render's persistent disk; never run on page requests."""
import json
from membership_backups import backup_database
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
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
    for relative in ('data/scout4', 'data/member_lines', 'logs'):
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


def update_once(root):
    import update_nfl_games as finals
    from scout4.collect import collect
    from scheduled_ats_capture import run as quotes
    from scout4.blend import run as predictions, CORE
    from fan_views import prediction_performance
    from scout4.stats import read_csv
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
        try:
            action()
            stages[name] = 'ok'
        except Exception as error:
            stages[name] = 'failed: ' + type(error).__name__
            print(f'Automatic update {name} failed: {type(error).__name__}', flush=True)
    attempt('account backup', lambda: backup_database(
        os.environ.get('TREND_FINDAH_DATABASE', '/var/data/members.sqlite3'),
        Path(os.environ.get('TREND_FINDAH_DATABASE', '/var/data/members.sqlite3')).resolve().parent/'account-backups'))
    finals.BACKUPS = root / 'backups'
    attempt('finals', lambda: finals.main(['--apply','--season',str(season),'--file',str(root/'nfl_games.csv')]))
    attempt('stats', lambda: collect(season, root/'data/scout4'))
    def capture():
        if quotes(root) != 0:
            raise RuntimeError('Market capture failed')
    attempt('quotes', capture)
    if all(stages[name]=='ok' for name in ('finals','stats','quotes')):
        for name in CORE:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE/name, path)
        os.environ['TREND_FINDAH_AUTO_MODEL_CONFIG'] = str(SOURCE/'automatic_model.json')
        attempt('predictions', lambda: predictions(root))
    else:
        stages['predictions'] = 'skipped: upstream update failed'
    def grade():
        records = [json.loads(p.read_text()) for p in (root/'data/scout4/blend/predictions').glob('*.json')]
        groups, recent, excluded = prediction_performance(records, read_csv(root/'nfl_games.csv'))
        target = root/'data/scout4/blend/automatic_results.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'groups':groups,'recent':recent,'excluded':excluded},indent=2))
        temporary.replace(target)
    attempt('grading', grade)
    status = {'started':started,'finished':datetime.now(timezone.utc).isoformat(),
              'state':'ok' if all(v=='ok' for v in stages.values()) else 'needs attention','stages':stages}
    path = root/'logs/auto_update_status.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp');temp.write_text(json.dumps(status,indent=2));temp.replace(path)
    return status


def start_scheduler():
    if os.environ.get('TREND_FINDAH_AUTO_UPDATE') != '1':
        return
    def weekly_loop():
        # Separate timer: a long statistics update cannot delay the 8 a.m. check.
        from site_week import week_window
        checked=None
        while True:
            now=datetime.now(timezone.utc)
            cutoff=week_window(now)[0].astimezone(timezone.utc)
            if checked!=cutoff:
                try:
                    subprocess.run([sys.executable,str(SOURCE/'weekly_pick_lines.py')],
                        cwd=SOURCE,timeout=180,check=True,env={**os.environ,'POLARS_MAX_THREADS':'1'})
                    status=Path('/var/data/site-data/logs/weekly_lines_status.json')
                    if status.exists():
                        result=json.loads(status.read_text())
                        if result.get('state')=='ready' and result.get('scheduled_cutoff')==cutoff.isoformat():checked=cutoff
                except (OSError,ValueError,subprocess.SubprocessError) as error:
                    path=Path('/var/data/site-data/logs/weekly_lines_status.json')
                    path.write_text(json.dumps({'state':'pending','reason':type(error).__name__}))
            threading.Event().wait(30)
    def loop():
        while True:
            # Keep the shared update lock free around the scheduled weekly capture.
            from site_week import week_window
            now=datetime.now(timezone.utc)
            current_cutoff,next_cutoff=week_window(now)
            current_cutoff=current_cutoff.astimezone(timezone.utc)
            next_cutoff=next_cutoff.astimezone(timezone.utc)
            if 0<=(now-current_cutoff).total_seconds()<180:
                threading.Event().wait(180-(now-current_cutoff).total_seconds())
            if 0<=(next_cutoff-now).total_seconds()<=600:
                threading.Event().wait((next_cutoff-now).total_seconds()+180)
            try:
                subprocess.run([sys.executable,str(SOURCE/'hosted_updates.py'),'--once'],
                    cwd=SOURCE, timeout=600, check=True,
                    env={**os.environ, 'POLARS_MAX_THREADS':'1'})
            except (OSError, subprocess.SubprocessError) as error:
                path=Path('/var/data/site-data/logs/auto_update_status.json')
                path.write_text(json.dumps({'finished':datetime.now(timezone.utc).isoformat(),
                    'state':'needs attention','stages':{'worker':type(error).__name__}}))
            threading.Event().wait(21600)
    threading.Thread(target=weekly_loop,name='automatic-weekly-lines',daemon=True).start()
    threading.Thread(target=loop, name='automatic-data-updates', daemon=True).start()


if __name__ == '__main__':
    if sys.argv[1:] != ['--once'] or os.environ.get('TREND_FINDAH_AUTO_UPDATE') != '1':
        raise SystemExit('This updater is enabled only through hosted automatic updates')
    import fcntl
    root=Path('/var/data/site-data')
    with (root/'logs/auto_update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(0)
        update_once(root)
