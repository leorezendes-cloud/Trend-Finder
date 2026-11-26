"""Expanding chronological residual models; fixed priors, no target-season tuning."""
from collections import defaultdict
from datetime import datetime,timedelta
import json
import math
import random
from .features import build,vector,mean

class Ridge:
    def __init__(self,n,penalty=100.):
        self.a=[[float(penalty if i==j else 0) for j in range(n)] for i in range(n)]
        self.b=[0.]*n;self.n=0
    def update(self,x,y):
        self.n+=1
        for i in range(len(x)):
            self.b[i]+=x[i]*y
            for j in range(len(x)):self.a[i][j]+=x[i]*x[j]
    def predict(self,x):
        if self.n<32:return 0.
        n=len(x);a=[self.a[i][:]+[self.b[i]] for i in range(n)]
        for i in range(n):
            pivot=max(range(i,n),key=lambda k:abs(a[k][i]));a[i],a[pivot]=a[pivot],a[i]
            d=a[i][i];a[i]=[v/d for v in a[i]]
            for j in range(n):
                if j!=i:
                    d=a[j][i];a[j]=[a[j][k]-d*a[i][k] for k in range(n+1)]
        return sum(x[i]*a[i][-1] for i in range(n))

def summarize(rows):
    if not rows:return {'n':0}
    base=mean(r['baseline_error'] for r in rows);enh=mean(r['enhanced_error'] for r in rows)
    blocks=defaultdict(list)
    for r in rows:blocks[r['week']].append(r['enhanced_error']-r['baseline_error'])
    blocks=list(blocks.values());rng=random.Random(17);boots=[]
    for _ in range(300):
        sample=[v for b in rng.choices(blocks,k=len(blocks)) for v in b];boots.append(mean(sample))
    boots.sort()
    return {'n':len(rows),'baseline_mae':base,'enhanced_mae':enh,'mae_delta':enh-base,
            'week_block_bootstrap_95pct_delta':[boots[7],boots[292]],
            'exploratory_interval_below_zero':len(blocks)>=8 and boots[292]<0}

def evaluate(db,*,train_season=2022,mode='retrospective'):
    games=db.execute('SELECT gid,season,week,kickoff,end_at,away,home,away_score,home_score,available FROM games WHERE season>=? ORDER BY kickoff,gid',(train_season,)).fetchall()
    groups=defaultdict(list)
    for g in games:groups[g[1],g[2]].append(g)
    models={k:Ridge(8 if k in ('margin','total') else 2) for k in ('margin','total','passing_yards','rushing_yards','receiving_yards')}
    pending=[];results=[];skipped=defaultdict(int)
    for (year,week),gg in sorted(groups.items()):
        cutoff=min(g[3] for g in gg);at=datetime.fromisoformat(cutoff)
        # Outcomes from games less than 54h old are unavailable even for fitting.
        still=[]
        for ready,kind,x,y in pending:
            if ready<at:models[kind].update(x,y)
            else:still.append((ready,kind,x,y))
        pending=still
        for g in gg:
            gid,year,week,kick,end,away,home,ascore,hscore,captured=g
            f=build(db,away,home,cutoff,mode=mode)
            if min(p['games'] for p in f['teams'])<3:skipped['team_warmup']+=1;continue
            x=vector(f);b=f['baseline'];ready=datetime.fromisoformat(end)+timedelta(hours=48)
            if mode=='observed':ready=max(ready,datetime.fromisoformat(captured))
            for kind,baseline,actual in [('margin',b['away_points']-b['home_points'],ascore-hscore),('total',b['away_points']+b['home_points'],ascore+hscore)]:
                pred=baseline+models[kind].predict(x)
                if year>train_season:results.append(dict(game_id=gid,season=year,week=week,kind=kind,baseline_error=abs(actual-baseline),enhanced_error=abs(actual-pred)))
                pending.append((ready,kind,x,actual-baseline))
            actuals={r[0]:(r[1],json.loads(r[2])) for r in db.execute("SELECT pid,team,payload FROM observations WHERE kind='player' AND gid=?",(gid,))}
            for p in f['teams']:
                for player in p['players']:
                    actual=actuals.get(player['player_id'])
                    if actual is None or actual[0]!=p['team']:
                        skipped['prior_player_missing_target_boxscore']+=1;continue
                    for kind in ('passing_yards','rushing_yards','receiving_yards'):
                        if (kind=='passing_yards' and player['position']!='QB') or (kind=='receiving_yards' and player['position']=='QB'):continue
                        y=actual[1].get(kind)
                        if y is None:skipped['missing_player_outcome']+=1;continue
                        baseline=player['recent'][kind]
                        if kind=='receiving_yards':gap=p['positions'][player['position']]['allowed_relative_to_league']*player['target_share']
                        else:gap=p['pass' if kind=='passing_yards' else 'rush']['matchup']*10
                        px=[gap,player['target_share']]
                        pred=max(0.,baseline+models[kind].predict(px))
                        if year>train_season:results.append(dict(game_id=gid,season=year,week=week,kind=kind,position=player['position'],baseline_error=abs(y-baseline),enhanced_error=abs(y-pred)))
                        label_ready=ready
                        if mode=='observed':
                            captured_player=db.execute("SELECT available FROM observations WHERE kind='player' AND gid=? AND pid=? AND team=?",(gid,player['player_id'],p['team'])).fetchone()[0]
                            label_ready=max(label_ready,datetime.fromisoformat(captured_player))
                        pending.append((label_ready,kind,px,y-baseline))
    summaries={}
    for year in sorted({r['season'] for r in results}):
        summaries[str(year)]={kind:summarize([r for r in results if r['season']==year and r['kind']==kind]) for kind in models}
    positions={str(year):{kind:{pos:summarize([r for r in results if r['season']==year and r['kind']==kind and r.get('position')==pos]) for pos in ('QB','RB','WR','TE')} for kind in ('passing_yards','rushing_yards','receiving_yards')} for year in sorted({r['season'] for r in results})}
    return {'policy':'player-scheme-v1','availability_mode':mode,'training_start_season':train_season,
        'warning':'Retrospective corrected data; 48h after estimated end is assumed availability, NOT timestamp-certified historical replay.' if mode=='retrospective' else 'Only source captures observed before cutoff admitted.',
        'player_cohort':'Prior observed IDs on same latest historical team, conditional on target boxscore presence; no injury/participation forecast.',
        'inference':'Exploratory paired week-block bootstrap; no multiple-comparison correction or confirmatory holdout. Small deltas do not establish production value.',
        'parameters':{'ridge':100,'minimum_team_games':3,'minimum_model_targets':32,'history_days':180,'recent_player_games':4},
        'seasons':summaries,'player_position_breakdown':positions,'skipped':dict(skipped),'evaluated_rows':len(results),
        'conclusion':'Research only. No automatic model promotion, season priority change, or production adjustments.'}
