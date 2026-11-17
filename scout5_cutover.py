"""Atomic-guarded Scout 5.0 legacy journal cutover.

Consumes the ATS-only evidence from stdin. Validates every original signed
journal and issuance against the Mac-verified compact export before permitting
retirement. Never touches separate ATS/Plug/Expert source seals.
Requires a deployed worker that shares the global Scout directory lock.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from scout_dynamic_store import canonical, checked_read, journal, locked
from scout5_totals import load_bundle

ATS_KEYS=('revision','evaluated_at','model_as_of','ats_side','spread',
          'projection','inputs_sha256','decision_id')


def validate_evidence(root, evidence):
    if evidence.get('schema')!='scout5-legacy-ats-evidence-v1':
        raise ValueError('Unexpected ATS-only evidence schema')
    from scout_dynamic_store import digest
    if evidence.get('sha256')!=digest({k:v for k,v in evidence.items() if k!='sha256'}):
        raise ValueError('Invalid ATS-only evidence checksum')
    base=Path(root)/'scout_dynamic'
    games=evidence.get('games')
    if not isinstance(games,list) or not games:
        raise ValueError('No ATS evidence games')
    on_disk={p.name for p in base.iterdir() if p.is_dir()}
    exported={g['game_id'] for g in games}
    if len(exported)!=len(games) or exported!=on_disk:
        raise ValueError('ATS export does not cover the exact legacy journal directory set')
    if any(not p.isalnum() for g in games for p in g['game_id'].split('_')):
        raise ValueError('Unsafe game directory')
    checked=0
    for game in games:
        gid=game['game_id']
        path=base/gid
        if path.is_symlink() or not path.is_dir():
            raise ValueError('Unsafe game directory '+gid)
        for f in path.rglob('*'):
            if f.is_symlink():raise ValueError('Symlink in journal '+gid)
        raw=(path/'revisions.json').read_bytes()
        issue=(path/'issued.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=game['original_journal_file_sha256']:
            raise ValueError('Journal changed after Mac export: '+gid)
        if hashlib.sha256(issue).hexdigest()!=game['issued_file_sha256']:
            raise ValueError('Issuance changed after Mac export: '+gid)
        issued=checked_read(path/'issued.json')
        if issued['sha256']!=game['issued_sha256'] or issued['issued_at']!=game['issued_at']:
            raise ValueError('Issued ATS record mismatch: '+gid)
        rows=journal(root,gid)
        if len(rows)!=len(game['ats_revisions']):
            raise ValueError('ATS revisions changed: '+gid)
        if any(r.get('totals',{}).get('model')=='scout5-ou-v1' for r in rows):
            raise ValueError('Refusing to retire live Scout 5.0 journal: '+gid)
        for row,reduced in zip(rows,game['ats_revisions']):
            if any(row[k]!=reduced[k] for k in ATS_KEYS):
                raise ValueError('ATS evidence fields changed: '+gid)
            if row['sha256']!=reduced['original_revision_sha256']:
                raise ValueError('Original ATS SHA changed: '+gid)
            if any(x in reduced for x in ('totals','total_quote','ou_side')):
                raise ValueError('Retired O/U present in ATS export')
            checked+=1
        if (path/'closing.json').exists():
            closing=checked_read(path/'closing.json')
            original_sha=game['original_closing_file_sha256']
            if hashlib.sha256((path/'closing.json').read_bytes()).hexdigest()!=original_sha:
                raise ValueError('Closing changed after Mac export: '+gid)
            if closing.get('row',{}).get('game_id')!=gid:
                raise ValueError('Closing identity differs: '+gid)
        elif game['original_closing_file_sha256'] is not None:
            raise ValueError('Missing originally closed record: '+gid)
    return {'games':len(games),'ats_revisions':checked,'ats_export_sha256':evidence['sha256']}


def cutover(root,evidence,*,apply=False):
    root=Path(root).resolve()
    if not (root/'scout5_totals.py').is_file():
        raise ValueError('Scout 5.0 release absent')
    bundle=load_bundle(root/'scout5_ou_bundle.json')
    if len(bundle.get('replay_history',[]))!=70:
        raise ValueError('Scout 5.0 historical replay missing')
    base=root/'scout_dynamic'
    if not base.is_dir():raise ValueError('Scout journal folder absent')
    # The deployed scout_dynamic.cycle() MUST acquire this same directory lock.
    with locked(base):
        result=validate_evidence(root,evidence)
        dest=base/'legacy_ats_evidence.json'
        if dest.exists():
            raise ValueError('ATS migration receipt already exists; refuse overwrite')
        if apply:
            data=canonical(evidence)
            if len(data)>1024*1024:raise ValueError('ATS evidence unexpectedly large')
            fd,name=tempfile.mkstemp(prefix='.scout5-ats-',dir=base)
            try:
                with os.fdopen(fd,'wb') as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(name,dest)
            finally:
                if os.path.exists(name):os.unlink(name)
            # Durable receipt is present. Directory removal touches only
            # the validated old game directories; top-level activation remains.
            for game in evidence['games']:
                target=base/game['game_id']
                if target.is_symlink() or not target.is_dir():
                    raise ValueError('Unsafe directory after evidence installation: '+str(target))
                shutil.rmtree(target)
            result['directories_removed']=len(evidence['games'])
        result['mode']='APPLIED' if apply else 'CHECK_ONLY'
        result['ats_receipt_path']=str(dest)
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default=str(Path(__file__).resolve().parent))
    p.add_argument('--apply',action='store_true')
    p.add_argument('--confirm')
    a=p.parse_args()
    if a.apply and a.confirm!='RETIRE-ALL-LEGACY-SCOUT-JOURNALS':
        p.error('Explicit --confirm RETIRE-ALL-LEGACY-SCOUT-JOURNALS required')
    evidence=json.load(sys.stdin)
    print(json.dumps(cutover(a.root,evidence,apply=a.apply),indent=2))
