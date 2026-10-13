"""Local-only comparison exports and grading; never rewrites sealed predictions."""
import csv,hashlib,json
from collections import Counter
from datetime import datetime,timezone
from .blend import view
from .web import ROOT
from .stats import read_csv,number


def total_result(record,game):
    if not game or any(record[k]!=game.get(k) for k in ('game_id','away_team','home_team')):raise ValueError('Outcome identity mismatch')
    total=record.get('totals')
    if not total:return 'Unavailable'
    a,h=number(game.get('away_score')),number(game.get('home_score'))
    if a is None or h is None:return 'Pending'
    actual=a+h-total['quote']['line'];lean=total['prediction']['lean']
    if abs(actual)<1e-9:return 'Push'
    if lean=='No Call':return 'No Call'
    return 'Win' if (lean=='Over')==(actual>0) else 'Loss'


def export(root=ROOT):
    records=view(root);games={g['game_id']:g for g in read_csv(root/'nfl_games.csv')}
    folder=root/'data/scout4/blend/comparisons'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');folder.mkdir(parents=True,exist_ok=False)
    groups={name:[] for name in ('Scout scoring','The Plug','Blend','Scout totals')}
    for r in records:
        common={k:r[k] for k in ('game_id','away_team','home_team','decision_cutoff_utc','sealed_at_utc','configuration_sha256')}
        for name,c in r['components'].items():groups[name].append({**common,'line':r['quote']['line'],**c,'result':r['results'][name]})
        total=r.get('totals')
        if total:
            try:result=total_result(r,games.get(r['game_id']))
            except ValueError:result='Review needed'
            groups['Scout totals'].append({**common,'line':total['quote']['line'],'estimated_total':total['prediction']['total'],'pick':total['prediction']['lean'],'result':result})
    summary={}
    for name,rows in groups.items():
        counts=Counter(r['result'] for r in rows);n=counts['Win']+counts['Loss']
        summary[name]={'records':len(rows),'results':dict(counts),'accuracy':100*counts['Win']/n if n else None}
        path=folder/(name.lower().replace(' ','_')+'.csv')
        if rows:
            with path.open('x',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (folder/'summary.json').write_text(json.dumps(summary,indent=2))
    paths=list((root/'data/scout4/blend/predictions').glob('*.json'))+[root/'nfl_games.csv',root/'scout4/blend_results.py']
    (folder/'manifest.json').write_text(json.dumps({'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2))
    return folder,summary

if __name__=='__main__':
    folder,summary=export();print(folder);print(json.dumps(summary,indent=2))
