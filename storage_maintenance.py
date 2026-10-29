"""Reclaim duplicate immutable archive blocks without removing any logical file.

Defaults to a read-only estimate. --apply serializes with hosted updates and
market capture. Hashing and comparisons stream bounded chunks; no models or AI.
"""
import argparse
import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

from archive_storage import fingerprint, identical, share_file, sync_directory
from scheduler_runtime import exclusive, atomic_json

MIN_BYTES = 4096
MIN_AGE = 3600
STAMP = re.compile(r'^\d{8}T\d{6}\d*Z$')


def candidates(root):
    root = Path(root)
    # Only immutable raw responses, never the observation CSVs or manifests.
    for directory, pattern in (('ats_handle','*.html'),('odds_backup','*.json')):
        for path in sorted((root/'logs'/directory).glob(pattern)):
            if not path.name.endswith('-manifest.json'):
                yield path, True
    base = root/'data/scout4'
    for year in sorted(base.glob('[12][0-9][0-9][0-9]')):
        for snapshot in sorted(year.iterdir()) if year.is_dir() else []:
            if snapshot.is_dir() and STAMP.fullmatch(snapshot.name) and (snapshot/'manifest.json').is_file():
                for name in ('team.csv','player.csv'):
                    yield snapshot/name, False
    for year in sorted((base/'personnel').glob('[12][0-9][0-9][0-9]')):
        for snapshot in sorted(year.iterdir()) if year.is_dir() else []:
            if snapshot.is_dir() and STAMP.fullmatch(snapshot.name) and (snapshot/'manifest.json').is_file():
                for name in ('depth_charts.json','injuries.json','depth_charts.json.gz','injuries.json.gz'):
                    yield snapshot/name, False
    for folder in sorted((base/'blend/inputs').glob('*')):
        if folder.is_dir() and STAMP.fullmatch(folder.name):
            for name in ('nfl_games.csv','public_money_snapshots.csv'):
                yield folder/name, False
    # Incomplete/recoverable staging is excluded, even when old. Retain every
    # journal/candidate/source file and leave all manifests untouched.
    for folder in sorted((base/'blend/atomic_staging').glob('run-*')):
        journal = folder/'journal.json'
        try:
            if json.loads(journal.read_text()).get('state') != 'complete':
                continue
        except (OSError, ValueError, AttributeError):
            continue
        for path in sorted(folder.rglob('*')):
            if path.suffix in ('.csv','.json','.py') and path.name not in ('journal.json','status.json'):
                yield path, False


def _safe_file(root, path, cutoff):
    try:
        if not path.is_relative_to(root) or not path.resolve().is_relative_to(root):
            return None
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent):
            return None
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size < MIN_BYTES or info.st_mtime > cutoff:
            return None
        return info
    except OSError:
        return None


def compact(root, *, apply=False, min_age=MIN_AGE, now=None):
    """Caller owns the updater/capture leases; all changes preserve original bytes."""
    root = Path(root).resolve()
    now = time.time() if now is None else now
    free_before = shutil.disk_usage(root).free
    report = dict(state='ok', mode='apply' if apply else 'estimate',
                  scanned_files=0, shared_files=0, already_shared=0,
                  reclaimable_bytes=0, reclaimed_bytes=0, free_before_bytes=free_before)
    groups = {}
    seen = set()
    for path, raw in candidates(root):
        if path in seen:
            continue
        seen.add(path)
        info = _safe_file(root,path,now-min_age)
        if info is None:
            continue
        report['scanned_files'] += 1
        checksum = fingerprint(path)
        key = (info.st_dev,info.st_size,checksum,stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid)
        canonical = groups.get(key)
        if raw:
            pool = path.parent/'_objects'
            if pool.is_symlink():
                raise ValueError('Symlink in raw evidence pool')
            object_path = pool/(checksum+path.suffix)
            if object_path.exists() or object_path.is_symlink():
                # Never silently overwrite a damaged pool object.
                object_info = object_path.lstat()
                if (not stat.S_ISREG(object_info.st_mode) or not identical(object_path,path)):
                    raise ValueError('Invalid immutable evidence pool object: '+str(object_path))
                if (stat.S_IMODE(object_info.st_mode),object_info.st_uid,object_info.st_gid) == (
                        stat.S_IMODE(info.st_mode),info.st_uid,info.st_gid):
                    canonical = object_path
            elif apply:
                pool.mkdir(exist_ok=True)
                os.link(canonical or path,object_path,follow_symlinks=False)
                sync_directory(pool)
                canonical = object_path
        if canonical is None:
            groups[key] = path
            continue
        a, b = canonical.stat(),path.stat()
        if (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino):
            report['already_shared'] += 1
        else:
            if not identical(canonical,path):
                raise ValueError('Archive checksum collision or concurrent modification')
            report['shared_files'] += 1
            # Count each old inode once in estimates, regardless of its link count.
            # Applied accounting counts blocks only when the final old link goes away.
            report['reclaimable_bytes'] += info.st_blocks*512 if info.st_nlink==1 else 0
            if apply:
                report['reclaimed_bytes'] += share_file(canonical,path)
        groups[key] = canonical
    report['free_after_bytes'] = shutil.disk_usage(root).free
    report['reclaimed_mib'] = round(report['reclaimed_bytes']/(1024*1024),2)
    report['reclaimable_mib'] = round(report['reclaimable_bytes']/(1024*1024),2)
    report['free_after_mib'] = round(report['free_after_bytes']/(1024*1024),2)
    report['finished_at'] = time.time()
    if apply:
        atomic_json(root/'logs/storage_maintenance_status.json',report)
    return report


def maintain(root, *, force=False):
    """Run once per day, or before a low-space update. Caller holds auto_update.lock."""
    root=Path(root)
    try:
        previous=json.loads((root/'logs/storage_maintenance_status.json').read_text())
    except (OSError,ValueError):
        previous={}
    if (not force and shutil.disk_usage(root).free >= 256*1024*1024
            and time.time()-previous.get('finished_at',0)<86400):
        return {'state':'not_due'}
    with exclusive(root/'logs/ats_capture.lock') as acquired:
        if not acquired:
            return {'state':'busy'}
        return compact(root,apply=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/var/data/site-data'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.root.is_dir():
        parser.error('Data root does not exist')
    # Read-only estimates also take leases for a consistent, non-racing audit.
    with exclusive(args.root/'logs/auto_update.lock') as acquired:
        if not acquired:
            raise SystemExit('Updater busy; retry after it finishes')
        with exclusive(args.root/'logs/ats_capture.lock') as acquired:
            if not acquired:
                raise SystemExit('Market capture busy; retry after it finishes')
            print(json.dumps(compact(args.root,apply=args.apply),indent=2))

if __name__=='__main__':main()
