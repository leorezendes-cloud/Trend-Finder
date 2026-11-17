"""Scout legacy journal retirement: inventory/verify on Mac, delete ONLY after cutover.

This file writes nothing in inventory mode. Backup via SSH tar stream to Mac.
Never removes official forecast seals, ATS/Plug/Expert stores, Scout 5 rows,
the activation gate, or a legacy journal containing a future pregame issuance.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
from datetime import datetime, timezone

from scout_dynamic_store import checked_read, closing, folder, journal, utc

def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def snapshot(root):
    base=Path(root).resolve()/'scout_dynamic'
    now=datetime.now(timezone.utc)
    entries=[];blocked=[]
    if not base.is_dir():
        raise ValueError('Missing scout_dynamic directory')
    for path in sorted(base.iterdir()):
        if not path.is_dir():continue
        parts=path.name.split('_')
        if len(parts)!=4 or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError('Unexpected directory inside Scout store: '+path.name)
        if path.is_symlink():raise ValueError('Symlink Scout directory refused')
        files={}
        for f in sorted(path.rglob('*')):
            if f.is_symlink():raise ValueError('Symlink inside Scout directory: '+str(f))
            if f.is_file():
                rel=f.relative_to(base).as_posix()
                files[rel]=hashlib.sha256(f.read_bytes()).hexdigest()
        reason=None
        try:
            rows=journal(root,path.name)
            kinds={r.get('totals',{}).get('model','legacy') for r in rows}
            if not rows:reason='missing signed journal'
            elif 'scout5-ou-v1' in kinds:reason='contains Scout 5.0 (not retired)'
            elif any(utc(r['kickoff_utc'])>now for r in rows):
                reason='pregame legacy journal: possible live ATS evidence'
            elif (path/'issued.json').exists():
                issued=checked_read(path/'issued.json')
                if utc(issued['kickoff_utc'])>now:
                    reason='pregame issued legacy ATS selection'
            if (path/'closing.json').exists():
                closing(root,path.name)
        except (ValueError,OSError,KeyError,TypeError) as err:
            reason='unverified signed record: '+str(err)
        if reason:blocked.append({'game_id':path.name,'reason':reason})
        entries.append({'game_id':path.name,'classification':'blocked' if reason else 'retirable',
                        'reason':reason,'files':files})
    body={'policy':'scout5-legacy-retirement-v1','entries':entries}
    return {'manifest':body,'manifest_sha256':digest(body),'blocked':blocked,
            'retirable_count':sum(x['classification']=='retirable' for x in entries),
            'blocked_count':len(blocked)}

def verify_backup(archive,report):
    expected={p:h for item in report['manifest']['entries'] for p,h in item['files'].items()}
    actual={}
    with tarfile.open(archive,'r:*') as tar:
        for member in tar.getmembers():
            if not member.isfile():continue
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:raise ValueError('Unsafe tar archive path')
            if name.parts[0]=='scout_dynamic':
                name=PurePosixPath(*name.parts[1:])
            stream=tar.extractfile(member)
            if not stream:raise ValueError('Unreadable tar member')
            rel=str(name)
            if rel in actual:raise ValueError('Duplicate tar member: '+rel)
            actual[rel]=hashlib.sha256(stream.read()).hexdigest()
    if actual!=expected:
        missing=sorted(set(expected)-set(actual))
        extra=sorted(set(actual)-set(expected))
        bad=sorted(k for k in expected.keys()&actual.keys() if expected[k]!=actual[k])
        raise ValueError(f'Archive mismatch: missing={missing[:5]}, extra={extra[:5]}, changed={bad[:5]}')
    return hashlib.sha256(Path(archive).read_bytes()).hexdigest()

def retire(root,report,expected_digest,backup_digest):
    if digest(report['manifest'])!=expected_digest:
        raise ValueError('Manifest digest mismatch')
    if len(backup_digest)!=64 or any(c not in '0123456789abcdef' for c in backup_digest):
        raise ValueError('Verified local backup SHA-256 required')
    current=snapshot(root)
    if current['manifest_sha256']!=expected_digest:
        raise ValueError('Scout journal contents changed since backup; re-archive and re-verify')
    if current['blocked_count']:
        raise ValueError('Unsafe to retire: '+json.dumps(current['blocked'][:6]))
    entries=current['manifest']['entries']
    if not entries:raise ValueError('No Scout journals to retire')
    base=Path(root).resolve()/'scout_dynamic'
    # This command MUST only be run after the new Scout 5 release is deployed
    # and the dynamic writer has been paused for cutover.
    for entry in entries:
        target=base/entry['game_id']
        if target.is_symlink() or not target.is_dir():raise ValueError('Scout path changed during cutover')
        shutil.rmtree(target)
    return {'retired':len(entries),'backup_sha256':backup_digest,'manifest_sha256':expected_digest}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=('manifest','verify','retire'))
    ap.add_argument('--root',default=str(Path(__file__).resolve().parent))
    ap.add_argument('--manifest-file')
    ap.add_argument('--archive')
    ap.add_argument('--manifest-sha256')
    ap.add_argument('--backup-sha256')
    a=ap.parse_args()
    if a.command=='manifest':
        print(json.dumps(snapshot(a.root),indent=2,sort_keys=True))
    elif a.command=='verify':
        if not a.manifest_file or not a.archive:ap.error('verify requires --manifest-file and --archive')
        report=json.loads(Path(a.manifest_file).read_text())
        if digest(report['manifest'])!=report['manifest_sha256']:
            raise ValueError('Manifest signature mismatch')
        print(json.dumps({'archive_sha256':verify_backup(a.archive,report),
                          'manifest_sha256':report['manifest_sha256'],
                          'retirable_count':report['retirable_count'],
                          'blocked':report['blocked']},indent=2))
    else:
        if not a.manifest_sha256 or not a.backup_sha256:ap.error('retire requires both verified digests')
        print(json.dumps(retire(a.root,snapshot(a.root),a.manifest_sha256,a.backup_sha256),indent=2))

if __name__=='__main__':
    main()
