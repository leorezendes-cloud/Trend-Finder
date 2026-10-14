"""Owner-only summaries from existing status files; no background work."""
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta


def read_status(path):
    try:
        if path.stat().st_size>65536:return {}
        data=json.loads(path.read_text())
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}


def fresh(value,now,hours):
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.tzinfo is not None and timedelta(0)<=now-stamp<=timedelta(hours=hours)
    except (ValueError,TypeError,AttributeError):return False


def owner_health(root,database,now=None):
    now=now or datetime.now(timezone.utc)
    backup=read_status(Path(database).resolve().parent/'account-backups/status.json')
    updates=read_status(Path(root)/'logs/auto_update_status.json')
    backup_ok=backup.get('restore_verified') is True and fresh(backup.get('completed_at'),now,25)
    updates_ok=updates.get('state')=='ok' and fresh(updates.get('finished'),now,12)
    return [{'label':'Account backups','ok':backup_ok,'message':'Recent backup passed restore verification.' if backup_ok else 'Needs attention: no recent verified backup is recorded.'},
            {'label':'Data updates','ok':updates_ok,'message':'Recent automatic update completed successfully.' if updates_ok else 'Needs attention: the latest update is missing, overdue, or failed.'}]
