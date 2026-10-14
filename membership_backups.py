"""Private, consistent account backups with isolated restore verification."""
import json
from contextlib import closing
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex

TABLES = ('members', 'password_resets', 'auth_limits')


def checked_database(connection):
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('Database integrity check failed')
    if connection.execute('PRAGMA user_version').fetchone()[0] not in (2,3):
        raise ValueError('Unsupported account schema')
    tables = TABLES + (('watchlist',) if connection.execute('PRAGMA user_version').fetchone()[0] == 3 else ())
    return {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in tables}


def verify_restore(backup):
    backup = Path(backup)
    with tempfile.TemporaryDirectory(prefix='.restore-check-', dir=backup.parent) as folder:
        restored = Path(folder) / 'restored.sqlite3'
        with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as source:
            expected = checked_database(source)
            with closing(sqlite3.connect(restored)) as target:
                source.backup(target)
                if checked_database(target) != expected:
                    raise ValueError('Restored account counts do not match')
                # Compare complete rows, including hashes, tokens and preferences.
                for table in expected:
                    if source.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall() != target.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall():
                        raise ValueError('Restored account contents do not match')
    return expected


def backup_database(database, folder, keep=112):
    database, folder = Path(database).resolve(), Path(folder).resolve()
    if not database.is_file():
        raise FileNotFoundError('Account database is unavailable')
    if keep < 1:
        raise ValueError('Keep at least one backup')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    final = folder / f'accounts-{stamp}-{token_hex(4)}.sqlite3'
    temporary = final.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        started = time.monotonic()
        def progress(status, remaining, total):
            if time.monotonic() - started > 60:
                raise TimeoutError('Account backup timed out')
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=10)) as source:
            with closing(sqlite3.connect(temporary)) as target:
                source.backup(target, pages=128, progress=progress)
                checked_database(target)
        verify_restore(temporary)
        temporary.replace(final)
        with final.open('rb') as file:
            os.fsync(file.fileno())
        status = {'completed_at':datetime.now(timezone.utc).isoformat(),
                  'backup':final.name, 'restore_verified':True, 'retained_limit':keep}
        status_temp = folder / 'status.tmp'
        status_temp.write_text(json.dumps(status, indent=2))
        status_temp.chmod(0o600)
        status_temp.replace(folder/'status.json')
        # Prune only this utility's completed snapshots, after verification succeeds.
        for old in sorted((path for path in folder.glob('accounts-*.sqlite3')
                           if re.fullmatch(r'accounts-\d{8}T\d{12}Z-[0-9a-f]{8}\.sqlite3', path.name)), reverse=True)[keep:]:
            old.unlink()
        return status
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
