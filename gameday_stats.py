"""Additional game-day feed refresh; never runs predictions or AI providers."""
import csv
import fcntl
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def game_day_season(root, now=None):
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    with (Path(root)/'nfl_games.csv').open(newline='', encoding='utf-8-sig') as source:
        seasons = {int(row['season']) for row in csv.DictReader(source)
                   if row.get('gameday') == today and row.get('game_type') in {'REG','WC','DIV','CON','SB'}}
    return max(seasons) if seasons else None


def run(root, now=None):
    from hosted_updates import scheduler_event, SOURCE
    root = Path(root)
    season = game_day_season(root, now)
    if season is None:
        return 0
    logs = root/'logs'
    logs.mkdir(parents=True, exist_ok=True)
    with (logs/'auto_update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        if shutil.disk_usage(root).free < 128*1024*1024:
            raise RuntimeError('Stats refresh paused: less than 128 MiB free')
        pointer = root/'data/scout4'/str(season)/'latest.json'
        if pointer.exists():
            try:
                retrieved = datetime.fromisoformat(json.loads(pointer.read_text())['retrieved_at'].replace('Z','+00:00'))
                age = ((now or datetime.now(timezone.utc))-retrieved).total_seconds()
                if 0 <= age < 3600:
                    return 0
            except (KeyError, ValueError, TypeError):
                pass
        for kind in ('finals', 'stats'):
            scheduler_event(root, 'game-day-stats', 'stage_started', stage=kind)
            subprocess.run([sys.executable, str(SOURCE/'update_feed_worker.py'), kind, str(root), str(season)],
                           check=True, timeout=180, pass_fds=(lock.fileno(),), cwd=SOURCE,
                           env={**os.environ, 'POLARS_MAX_THREADS':'1'})
            scheduler_event(root, 'game-day-stats', 'stage_finished', stage=kind)
    return 0


if __name__ == '__main__':
    if os.environ.get('TREND_FINDAH_AUTO_UPDATE') != '1' or os.environ.get('TREND_FINDAH_ENV') != 'production':
        raise SystemExit('Enabled only for hosted automatic updates')
    raise SystemExit(run(Path('/var/data/site-data')))
