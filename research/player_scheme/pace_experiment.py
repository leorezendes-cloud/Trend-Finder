"""Fixed pace/score-bonus ablations on the unchanged saved pregame score cohort."""
import argparse,csv,json,resource,sys,time
from collections import defaultdict,Counter
from pathlib import Path
from .store import connect,sha
from .pace import estimate
from .ats import grade,record
from .score_bands import total_grade

VARIANTS=('baseline','matchup_only','pace_direct','pace_conservative','pace_plus_matchup','conservative_plus_matchup')
SPEC={'policy':'pace-points-v1','variants':VARIANTS,
 'pace_measure':'Neutral game-clock seconds between adjacent scrimmage snaps: quarters 1–3, WP 20–80%, outside final 2 minutes of half, same offense/drive/quarter, 1–60s gap. Exclude visible timeouts, incompletions, out-of-bounds, spikes/kneels and intervening events.',
 'projection':'League drives/team × league neutral cadence / joint opponent cadence. Team cadences shrink by 60 pairs; historical offense/opponent-defense drive rates shrink by four games.',
 'baseline_adjustment':'Pace ratio = projected drives / each side baseline historical drive exposure, capped [.85,1.15]. Only excess/deficit versus embedded baseline pace is applied.',
 'points':'Direct: baseline score × ratio. Conservative: baseline score × (1 + .5×(ratio−1)). Matchup combination multiplies both baseline and existing combined matchup bonus by the corresponding ratio.',
 'interpretation':'Effective points/possession includes all scoreboard points, including defensive/ST scores; not an isolated offensive PPP estimate. This neutral cadence-to-possession relationship is an unvalidated structural hypothesis.',
 'controls':'Same earlier-game cutoffs and unchanged archived closing lines. No pace coefficient/threshold/cap search. Conservative half-strength was fixed before results.',
 'limits':'Retrospective corrected archives; original quote times unverified. Existing partial 2026 cache. No production impact.'}

def scores(base,bonus,ratios):
    half=[1+.5*(r-1) for r in ratios]
    return {'baseline':base[:],'matchup_only':[max(0,b+d) for b,d in zip(base,bonus)],
        'pace_direct':[max(0,b*r) for b,r in zip(base,ratios)],
        'pace_conservative':[max(0,b*r) for b,r in zip(base,half)],
        'pace_plus_matchup':[max(0,(b+d)*r) for b,d,r in zip(base,bonus,ratios)],
        'conservative_plus_matchup':[max(0,(b+d)*r) for b,d,r in zip(base,bonus,half)]}

def run(db,source):
    rows=[];skipped=Counter()
    with Path(source).open(newline='') as f:
        for r in csv.DictReader(f):
            gid=r['game_id'];away,home=gid.split('_')[-2:]
            from .store import team
            pace=estimate(db,team(away),team(home),r['cutoff'])
            if pace is None:skipped['insufficient_prior_pace']+=1;continue
            base=[float(r[k]) for k in ('baseline_away_score','baseline_home_score')]
            bonus=[float(r[k]) for k in ('combined_away_bonus','combined_home_bonus')]
            variants=scores(base,bonus,[t['ratio'] for t in pace['teams']]);actual_margin=float(r['actual_margin']);actual_total=float(r['actual_total'])
            totals={k:total_grade(sum(v),float(r['total_line']),actual_total) for k,v in variants.items()} if r['total_line'] else {}
            rows.append(dict(game_id=gid,season=int(r['season']),week=int(r['week']),cutoff=r['cutoff'],spread=float(r['spread']),total_line=float(r['total_line']) if r['total_line'] else None,pace=pace,scores=variants,
                actual_margin=actual_margin,actual_total=actual_total,totals=totals,
                **{k:grade(v[0]-v[1],float(r['spread']),actual_margin) for k,v in variants.items()}))
    seasons={}
    for y in sorted({r['season'] for r in rows}):
        rr=[r for r in rows if r['season']==y]
        seasons[str(y)]={'games':len(rr),'variants':{},'mean_expected_drives':sum(t['expected_drives'] for r in rr for t in r['pace']['teams'])/(2*len(rr)),
            'mean_embedded_drives':sum(t['baseline_drives'] for r in rr for t in r['pace']['teams'])/(2*len(rr))}
        for k in VARIANTS:
            seasons[str(y)]['variants'][k]={'ats':record(rr,k),'totals':record([{k:r['totals'][k]} for r in rr if r['totals']],k),
                'ats_changed':sum(r[k]['side']!=r['baseline']['side'] for r in rr),
                'totals_changed':sum(r['totals'][k]['side']!=r['totals']['baseline']['side'] for r in rr if r['totals']),
                'mean_abs_score_change':sum(abs(v-b) for r in rr for v,b in zip(r['scores'][k],r['scores']['baseline']))/(2*len(rr)),
                'margin_mae':sum(abs(r['actual_margin']-(r['scores'][k][0]-r['scores'][k][1])) for r in rr)/len(rr),
                'total_mae':sum(abs(r['actual_total']-sum(r['scores'][k])) for r in rr)/len(rr)}
    return {'specification':SPEC,'source_score_ledger_sha256':sha(source),'seasons':seasons,'skipped':dict(skipped),'games':rows}

def save(result,path):
    rows=result.pop('games');lp=path.with_suffix('.games.csv')
    fields=['game_id','season','week','cutoff','spread','total_line','actual_margin','actual_total']+[s+k for s in ('away_','home_') for k in ('neutral_seconds','pairs','baseline_drives','expected_drives','baseline_snaps','expected_snaps','ratio')]+[k+s for k in VARIANTS for s in ('_away_score','_home_score','_ats_side','_ats_result','_ou_side','_ou_result')]
    with lp.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader()
        for r in rows:
            row={k:r[k] for k in fields[:8]}
            for side,t in zip(('away_','home_'),r['pace']['teams']):
                for k in ('neutral_seconds','pairs','baseline_drives','expected_drives','baseline_snaps','expected_snaps','ratio'):row[side+k]=t[k]
            for k in VARIANTS:row.update({k+'_away_score':r['scores'][k][0],k+'_home_score':r['scores'][k][1],k+'_ats_side':r[k]['side'],k+'_ats_result':r[k]['result'],k+'_ou_side':r['totals'].get(k,{}).get('side','Missing line'),k+'_ou_result':r['totals'].get(k,{}).get('result','Missing line')})
            w.writerow(row)
    result['ledger']={'file':lp.name,'rows':len(rows),'sha256':sha(lp)};path.write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();start=time.monotonic();db=connect(a.db)
    try:r=run(db,a.source)
    finally:db.close()
    r['resources']={'elapsed_seconds':round(time.monotonic()-start,3),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),'database_bytes':a.db.stat().st_size}
    save(r,a.output);print(json.dumps(r['seasons'],indent=2))
