"""Verify the Mac-only Scout legacy archive against the ATS-only issued receipts.

Read-only and completely offline. Confirms every ATS revision, line, timestamp,
and original source SHA against the original signed JSON inside the Mac archive.
Does NOT create online files, remove Render journals, or publish ATS picks.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from scout_dynamic_store import canonical, digest, validate, utc
from scout5_retire_legacy import verify_backup


ATS_KEYS = ('revision','evaluated_at','model_as_of','ats_side','spread',
            'projection','inputs_sha256','decision_id')


def verified_signed(obj, label):
    if not isinstance(obj, dict) or obj.get('sha256') != digest(
            {k:v for k,v in obj.items() if k != 'sha256'}):
        raise ValueError('Invalid signed '+label)
    return obj


def inspect(archive_path, manifest_path, evidence_path, *, now=None):
    manifest=json.loads(Path(manifest_path).read_text())
    evidence=json.loads(Path(evidence_path).read_text())
    if digest(manifest['manifest']) != manifest['manifest_sha256']:
        raise ValueError('Manifest digest mismatch')
    if evidence.get('schema') != 'scout5-legacy-ats-evidence-v1':
        raise ValueError('Unexpected ATS export schema')
    if evidence.get('sha256') != digest({k:v for k,v in evidence.items() if k!='sha256'}):
        raise ValueError('ATS export digest mismatch')
    archive_sha=verify_backup(archive_path,manifest)
    records={}
    with tarfile.open(archive_path,'r:*') as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe archive path')
            parts=name.parts
            if parts and parts[0]=='scout_dynamic':
                parts=parts[1:]
            if len(parts)!=2 or parts[1] not in ('revisions.json','issued.json','closing.json'):
                continue
            if (parts[0],parts[1]) in records:
                raise ValueError('Duplicate archive member')
            stream=archive.extractfile(member)
            if stream is None:raise ValueError('Missing archive data')
            records[(parts[0],parts[1])]=stream.read()
    seen=set()
    active=[]
    count=0
    now=now or datetime.now(timezone.utc)
    for game in evidence['games']:
        gid=game['game_id']
        if gid in seen:raise ValueError('Duplicate ATS game '+gid)
        seen.add(gid)
        raw=records.get((gid,'revisions.json'))
        issue=records.get((gid,'issued.json'))
        if not raw or not issue:raise ValueError('Missing signed game evidence: '+gid)
        if hashlib.sha256(raw).hexdigest()!=game['original_journal_file_sha256']:
            raise ValueError('ATS journal source changed: '+gid)
        if hashlib.sha256(issue).hexdigest()!=game['issued_file_sha256']:
            raise ValueError('ATS issuance source changed: '+gid)
        journal_obj=verified_signed(json.loads(raw),'ATS journal')
        issued_obj=verified_signed(json.loads(issue),'ATS issuance')
        rows=journal_obj['rows']
        if not rows or len(rows)!=len(game['ats_revisions']):
            raise ValueError('ATS revision count mismatch: '+gid)
        if issued_obj['sha256']!=game['issued_sha256'] or issued_obj['issued_at']!=game['issued_at']:
            raise ValueError('ATS issued timestamp mismatch: '+gid)
        if issued_obj['game_id']!=gid or issued_obj['kickoff_utc']!=game['kickoff_utc']:
            raise ValueError('ATS issued identity mismatch: '+gid)
        if not utc(issued_obj['issued_at'])<utc(game['kickoff_utc']):
            raise ValueError('Not a pregame ATS issuance: '+gid)
        for original, reduced in zip(rows,game['ats_revisions']):
            verified_signed(original,'ATS revision')
            validate(original,gid)
            for key in ATS_KEYS:
                if original[key]!=reduced[key]:
                    raise ValueError('ATS '+key+' differs for '+gid)
            if original['sha256']!=reduced['original_revision_sha256']:
                raise ValueError('ATS revision SHA mismatch: '+gid)
            if any(key in reduced for key in ('totals','ou_side','total_quote')):
                raise ValueError('Retired O/U leaked into ATS evidence')
            count+=1
        if utc(game['kickoff_utc'])>now:
            active.append(gid)
    if len(seen)!=len(manifest['manifest']['entries']):
        raise ValueError('Not all archived journals have ATS evidence')
    return {'result':'PASS','archive_sha256':archive_sha,
            'ats_evidence_sha256':evidence['sha256'],
            'games_verified':len(seen),'ats_revisions_verified':count,
            'pregame_games_at_check':len(active),'pregame_game_ids':active,
            'retired_ou_in_export':False,
            'render_files_changed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True)
    p.add_argument('--manifest',required=True)
    p.add_argument('--evidence',required=True)
    a=p.parse_args()
    print(json.dumps(inspect(a.archive,a.manifest,a.evidence),indent=2))
