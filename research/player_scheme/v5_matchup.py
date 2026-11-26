"""Transfer one fixed pregame matchup bonus onto the unchanged PR36 ATS v5 model."""
import argparse,csv,importlib.util,json,math,resource,sys,time
from collections import defaultdict
from pathlib import Path
from .ats import grade,record
from .store import sha,team

MODEL_SHA256='0ff7b68e6b0a6649e7f0be9da08cd872c6a0d9274c207b1a6f13f80c213e25fe'
BASELINE_COMMIT='cd491df29ebedd9ca626e879731261b26c05e613'

def load_model(path):
    if sha(path)!=MODEL_SHA256:raise ValueError('Model differs from pinned PR36 v5 baseline')
    spec=importlib.util.spec_from_file_location('research_frozen_ats_v5',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def qualifies(model_away_spread,away_line):
    gap=model_away_spread-away_line
    return abs(away_line)>7 and 1e-9<abs(gap)<1

def comparison(model_away_spread,away_line,actual_margin,away_bonus,home_bonus):
    if not all(math.isfinite(v) for v in (model_away_spread,away_line,actual_margin,away_bonus,home_bonus)):raise ValueError('Invalid comparison input')
    baseline_margin=-model_away_spread
    delta=away_bonus-home_bonus;adjusted_margin=baseline_margin+delta
    return {'v5_away_spread':model_away_spread,'baseline_away_margin':baseline_margin,
        'fixed_matchup_margin_adjustment':delta,'adjusted_away_margin':adjusted_margin,
        'baseline':grade(baseline_margin,away_line,actual_margin),
        'adjusted':grade(adjusted_margin,away_line,actual_margin),
        'baseline_selected':qualifies(model_away_spread,away_line),
        'adjusted_selected':qualifies(-adjusted_margin,away_line)}

def audit(schedule,source,model):
    companion=Path(source).with_name(Path(source).name.replace('.games.csv','.json'))
    metadata=json.loads(companion.read_text())
    if sha(source)!=metadata['ledger']['sha256'] or sha(schedule)!=metadata['line_sha256']:raise ValueError('Source ledger/schedule hash mismatch')
    with Path(schedule).open(newline='') as f:market={r['game_id']:r for r in csv.DictReader(f)}
    with Path(source).open(newline='') as f:inputs=list(csv.DictReader(f))
    if len({r['game_id'] for r in inputs})!=len(inputs):raise ValueError('Duplicate source game')
    projections={};ledger=[]
    for row in inputs:
        gid=row['game_id'];y,w=int(row['season']),int(row['week']);g=market[gid]
        if g.get('game_type')!='REG' or int(g['season'])!=y or int(g['week'])!=w:raise ValueError('Game identity mismatch')
        line=float(row['spread']);actual=float(row['actual_margin'])
        if line!=float(g['spread_line']) or actual!=float(g['away_score'])-float(g['home_score']):raise ValueError('Line/outcome mismatch')
        key=(y,w)
        if key not in projections:projections[key]=model.projections(schedule,y,w)
        baseline=projections[key][gid]
        bonus_a=float(row['combined_away_bonus']);bonus_h=float(row['combined_home_bonus'])
        ledger.append(dict(game_id=gid,season=y,week=w,cutoff=row['cutoff'],away_team=team(g['away_team']),home_team=team(g['home_team']),
            away_line=line,actual_margin=actual,away_bonus=bonus_a,home_bonus=bonus_h,
            **comparison(baseline,line,actual,bonus_a,bonus_h)))
    seasons={}
    for y in sorted({r['season'] for r in ledger}):
        rows=[r for r in ledger if r['season']==y];selected=[r for r in rows if r['baseline_selected']]
        flips=[r for r in rows if r['baseline']['side']!=r['adjusted']['side']]
        changes=[]
        for r in flips:
            changes.append({k:r[k] for k in ('game_id','away_line','baseline_away_margin','fixed_matchup_margin_adjustment','adjusted_away_margin','baseline','adjusted','baseline_selected')})
        seasons[str(y)]={'games':len(rows),'full_cohort':{k:record(rows,k) for k in ('baseline','adjusted')},
            'same_original_shortlist':{'games':len(selected),**{k:record(selected,k) for k in ('baseline','adjusted')},
                'candidate_still_qualifies':sum(r['adjusted_selected'] for r in selected)},
            'reapplied_rule_secondary':{k:record([r for r in rows if r[k+'_selected']],k) for k in ('baseline','adjusted')},
            'changed_decisions':len(flips),'changed_games':changes,
            'margin_mae':{k:sum(abs(r['actual_margin']-r[k+'_away_margin']) for r in rows)/len(rows) for k in ('baseline','adjusted')},
            'mean_abs_margin_adjustment':sum(abs(r['fixed_matchup_margin_adjustment']) for r in rows)/len(rows)}
    return {'policy':'v5-fixed-matchup-transfer-v1','baseline_commit':BASELINE_COMMIT,'model_sha256':MODEL_SHA256,
        'schedule_sha256':sha(schedule),'score_bonus_ledger_sha256':sha(source),
        'adjustment':'Previously specified combined passing/rushing score-band bonus: away bonus minus home bonus, added to the unchanged v5 away-margin projection. No pace, no refit, no new tuning.',
        'important':'Point bonuses were learned against the earlier PF/PA team-score baseline; this measures transfer to v5, not a newly trained v5 residual model. v5 itself predicts market spread and has no absolute team-score output.',
        'cohort':'Same 703 eligible games, after earlier matchup warmup; not full-season v5 or official Plug records. Original shortlist held fixed for primary selected-game comparison. Secondary rule reapplication uses different candidate cohorts.',
        'warning':'Retrospective corrected inputs and archived closing spreads without certified original quote times. Original v5 prior-season-label training and preweek feature logic remain unchanged. No published predictions are altered.',
        'seasons':seasons,'games':ledger}

def save(result,path):
    rows=result.pop('games');lp=path.with_suffix('.games.csv')
    fields=['game_id','season','week','cutoff','away_team','home_team','away_line','actual_margin','v5_away_spread','baseline_away_margin','away_bonus','home_bonus','fixed_matchup_margin_adjustment','adjusted_away_margin','baseline_selected','adjusted_selected','baseline_side','baseline_result','adjusted_side','adjusted_result']
    with lp.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader()
        for r in rows:
            row={k:r[k] for k in fields[:-4]}
            for k in ('baseline','adjusted'):row[k+'_side']=r[k]['side'];row[k+'_result']=r[k]['result']
            w.writerow(row)
    result['ledger']={'file':lp.name,'rows':len(rows),'sha256':sha(lp)};path.write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--schedule',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();start=time.monotonic()
    model=load_model(a.model);r=audit(a.schedule,a.source,model)
    r['resources']={'elapsed_seconds':round(time.monotonic()-start,3),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)}
    save(r,a.output);print(json.dumps(r['seasons'],indent=2))
