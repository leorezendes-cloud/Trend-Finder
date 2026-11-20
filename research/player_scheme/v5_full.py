"""Chronological player/PBP/charting residual research over pinned, unchanged ATS v5."""
import argparse,copy,json,resource,sys,time
from pathlib import Path
from .full_ats import run,save,SPEC,VARIANTS
from .ats import record
from .store import connect
from .v5_matchup import load_model,qualifies,BASELINE_COMMIT,MODEL_SHA256

class V5Baseline:
    def __init__(self,model,schedule):self.model=model;self.schedule=schedule;self.key=None;self.values={}
    def __call__(self,year,week,gid):
        if self.key!=(year,week):
            self.values=self.model.projections(self.schedule,year,week);self.key=(year,week)
        return -self.values[gid]  # v5 outputs expected HOME margin.

def evaluate(db,schedule,model,*,train_season=2022,last_season=2026):
    result=run(db,schedule,train_season=train_season,last_season=last_season,
        baseline_provider=V5Baseline(model,schedule))
    spec=copy.deepcopy(SPEC)
    spec.update(policy='player-scheme-v5-residual-v1',baseline_commit=BASELINE_COMMIT,model_sha256=MODEL_SHA256,
        training='Unchanged fixed features, ridge penalty 100 and minimum 32 earlier completed targets. Fit actual away scoring margin minus frozen v5 away-margin projection; release targets only after game end proxy plus 48 hours, before weekly cutoff. No current game spread in residual fitting. v5 retains its own original prior-season market-label training.',
        variants={'baseline':'pinned actual ATS v5','limited':'v5 + original team matchup features',
        'players':'v5 + team matchup and individual QB/WR/RB/TE features',
        'pbp':'v5 + players and neutral PBP/protection proxies',
        'full_available':'v5 + PBP and verified charting only where samples exist'})
    result['specification']=spec
    result['warning']+=' Same eligible cohort, not full-season official Plug records. All variants exploratory; no tuning or production promotion. No pace or transferred score-band bonuses.'
    for year,summary in result['seasons'].items():
        rows=[r for r in result['games'] if str(r['season'])==year]
        selected=[r for r in rows if qualifies(-r['margins']['baseline'],r['line'])]
        summary['same_original_v5_shortlist']={'games':len(selected),
            'variants':{k:record(selected,k) for k in VARIANTS}}
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--schedule',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--train-season',type=int,default=2022);p.add_argument('--last-season',type=int,default=2026);a=p.parse_args()
    start=time.monotonic();model=load_model(a.model);db=connect(a.db)
    try:r=evaluate(db,a.schedule,model,train_season=a.train_season,last_season=a.last_season)
    finally:db.close()
    r['resources']={'elapsed_seconds':round(time.monotonic()-start,3),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),'database_bytes':a.db.stat().st_size}
    save(r,a.output);print(json.dumps(r['seasons'],indent=2))
