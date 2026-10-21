"""Persistent, local-disk scheduling coordination; no collection or models."""
import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def due_job(root, job, action, interval, timeout, clock=time.time, on_recovery=None):
    """Reserve before spawning; retain a bounded recovery lease on interruption."""
    logs = Path(root)/'logs'
    with exclusive(logs/(job+'.job.lock')) as acquired:
        if not acquired:
            return 75
        path = logs/(job+'.schedule.json')
        saved = json.loads(path.read_text()) if path.exists() else {}
        now = clock()
        # Owning this lock proves the prior supervising action no longer owns it.
        # An orphan child may still exist: retain the full recovery lease.
        if saved.get('state') == 'running':
            saved.update(state='interrupted', detected_at=now)
            atomic_json(path, saved)
            if on_recovery is not None:
                on_recovery(dict(saved))
        # Migrate the last known successful pre-patch runs without rerunning them.
        if not saved:
            legacy = {'automatic-data-updates':('auto_update_status.json','finished'),
                      'expert-only-updates':('expert_automation_status.json','checked_at')}.get(job)
            if legacy and (logs/legacy[0]).exists():
                from datetime import datetime
                previous = json.loads((logs/legacy[0]).read_text())
                if previous.get('state') == 'ok' and previous.get(legacy[1]):
                    finished = datetime.fromisoformat(previous[legacy[1]].replace('Z','+00:00')).timestamp()
                    saved = {'state':'migrated', 'next_due':finished+interval}
                    atomic_json(path, saved)
        if now < saved.get('next_due', 0):
            return 'not_due'
        atomic_json(path, {'state':'running', 'attempted_at':now,
                           'next_due':now+timeout+60})
        try:
            result = action()
        except Exception:
            atomic_json(path, {'state':'failure', 'attempted_at':now,
                               'finished_at':clock(), 'next_due':clock()+interval})
            raise
        if result == 'not_due':
            atomic_json(path, {'state':'interrupted', 'next_due':clock()})
            return result
        atomic_json(path, {'state':'lock_busy' if result == 75 else 'success',
                           'attempted_at':now, 'finished_at':clock(),
                           'next_due':clock()+(60 if result == 75 else interval)})
        return result
