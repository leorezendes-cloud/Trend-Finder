"""Verified QB corrections for public research; never rewrites source/model data."""
import csv,json
from pathlib import Path
from urllib.parse import urlparse


def research_rows(rows, path):
    corrections=Path(path).resolve().parent/'research_qb_corrections.csv'
    output=[dict(row) for row in rows]
    # Independent checks run in the background updater, never on a page request.
    audit_path=Path(path).resolve().parent/'data/research_qbs/verified.json'
    audits=json.loads(audit_path.read_text()).get('games',{}) if audit_path.exists() else {}
    for row in output:
        audit=audits.get(row.get('game_id'),{})
        identity=audit.get('identity',{})
        if not identity or any(str(row.get(k,''))!=str(v) for k,v in identity.items()):continue
        for side in ('home','away'):
            name=audit.get('starters',{}).get(side)
            if name:
                row[side+'_qb_name']=name
                row[side+'_qb_source']=audit['source_url']
    if not corrections.exists():return output
    with corrections.open(newline='') as source:
        records=list(csv.DictReader(source))
    by_game={}
    for fix in records:
        if fix.get('side') not in ('home','away') or not fix.get('qb_name'):continue
        url=urlparse(fix.get('source_url',''))
        if url.scheme!='https' or not url.hostname:continue
        key=(fix['game_id'],fix['side'])
        if key in by_game:raise ValueError('Duplicate research QB correction: '+str(key))
        by_game[key]=fix
    for row in output:
        for side in ('away','home'):
            fix=by_game.get((row.get('game_id'),side))
            if not fix or row.get(side+'_team')!=fix['team'] or row.get('gameday')!=fix['gameday']:continue
            field=side+'_qb_name'
            # Do not overwrite a new, conflicting source assignment silently.
            if row.get(field,'') not in (fix['replaces'],fix['qb_name']):continue
            row[field]=fix['qb_name']
            row[side+'_qb_source']=fix['source_url']
    return output


def qb_coverage(rows):
    completed=[row for row in rows if all(row.get(s+'_score') not in ('',None) for s in ('home','away'))]
    season=max((int(row['season']) for row in rows),default=None)
    current=[row for row in completed if int(row['season'])==season]
    return {'season':season,'missing':sum(not row.get(s+'_qb_name') for row in current for s in ('home','away')),
            'unverified':sum(not row.get(s+'_qb_source') for row in current for s in ('home','away'))}
