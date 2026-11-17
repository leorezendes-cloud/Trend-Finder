"""Export verified pregame ATS receipts from legacy Scout journals.

Read-only on Render: stdout JSON only. Captures the complete ATS revision chain
of each issued legacy journal, without reproducing any Scout 4 O/U fields.
This is an evidence export, NOT new pregame issuance and NOT a Scout ATS
formula change.
"""
import argparse
import hashlib
import json
from pathlib import Path
from scout_dynamic_store import canonical, checked_read, journal, utc


def export(root):
    root=Path(root)
    base=root/'scout_dynamic'
    if not base.is_dir():
        raise ValueError('Scout directory not found')
    games=[]
    for path in sorted(base.iterdir()):
        if not path.is_dir() or not (path/'revisions.json').is_file():
            continue
        rows=journal(root,path.name)
        if not rows:
            continue
        if any(row.get('totals',{}).get('model')=='scout5-ou-v1' for row in rows):
            continue
        if not (path/'issued.json').exists():
            continue
        issued=checked_read(path/'issued.json')
        if issued.get('game_id')!=path.name or issued.get('policy')!='scout-dynamic-v1':
            raise ValueError('Invalid issuance identity for '+path.name)
        if utc(issued['issued_at'])>=utc(issued['kickoff_utc']):
            raise ValueError('Post-kickoff ATS issuance for '+path.name)
        first=rows[0]
        if first['kickoff_utc']!=issued['kickoff_utc'] or first['configuration_sha256']!=issued['configuration_sha256']:
            raise ValueError('Issuance mismatch for '+path.name)
        abridged=[]
        for row in rows:
            if row['kickoff_utc']!=issued['kickoff_utc'] or row['configuration_sha256']!=issued['configuration_sha256']:
                raise ValueError('ATS revision identity changed for '+path.name)
            abridged.append({
                'revision':row['revision'],
                'evaluated_at':row['evaluated_at'],
                'model_as_of':row['model_as_of'],
                'ats_side':row['ats_side'],
                'spread':row['spread'],
                'projection':row['projection'],
                'inputs_sha256':row['inputs_sha256'],
                'decision_id':row['decision_id'],
                'original_revision_sha256':row['sha256'],
            })
        raw=(path/'revisions.json').read_bytes()
        original_closing=path/'closing.json'
        games.append({
            'game_id':path.name,'away_team':first['away_team'],'home_team':first['home_team'],
            'kickoff_utc':first['kickoff_utc'],
            'issued_at':issued['issued_at'],
            'issued_sha256':issued['sha256'],
            'issued_file_sha256':hashlib.sha256((path/'issued.json').read_bytes()).hexdigest(),
            'original_journal_file_sha256':hashlib.sha256(raw).hexdigest(),
            'original_closing_file_sha256':hashlib.sha256(original_closing.read_bytes()).hexdigest() if original_closing.exists() else None,
            'ats_revisions':abridged,
        })
    payload={'schema':'scout5-legacy-ats-evidence-v1',
             'meaning':'ATS-only extract of historical issued Scout journals; original sealed journal archived on Mac',
             'games':games}
    payload['sha256']=hashlib.sha256(canonical(payload)).hexdigest()
    return payload


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(Path(__file__).resolve().parent))
    args=parser.parse_args()
    print(json.dumps(export(args.root),sort_keys=True,separators=(',',':')))
