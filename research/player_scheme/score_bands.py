"""Pregame threshold mismatches translated into learned, bounded team-score points."""
import argparse,csv,json,math,resource,sys,time
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from pathlib import Path
from .features import build
from .store import connect,sha,team
from .ats import grade,record

VARIANTS=('baseline','passing_only','rushing_only','combined')
SPEC={'policy':'score-mismatch-bands-v1','thresholds_epa_per_opportunity':[.025,.075,.15],
 'gate':'Both opponent-adjusted offense and defense-allowed residual must have the same sign. Strength is the weaker absolute residual.',
 'bands':'Below .025: none; .025–.075: moderate; .075–.15: strong; >=.15: exceptional. Negative mirrors positive.',
 'volume':'Pass share/.55 or rush share/.45, clipped to [.5,1.5].',
 'calibration':'Nonnegative ridge on signed band indicators times volume; residual target is actual team points minus its pregame PF/PA projection. Symmetric favorable/adverse point magnitude.',
 'ridge_penalty':30,'minimum_band_team_games':20,'maximum_type_points':3,'maximum_combined_points':4,
 'combined':'Joint six-coefficient fit, rather than summing independently fitted pass and rush effects.',
 'cutoff':'Earliest kickoff in target week. Earlier outcomes only enter calibration 48h after estimated six-hour game end.',
 'selection':'Fixed before this run. No threshold/penalty/cap search or target-season parameter selection.',
 'limitations':'Retrospective corrected inputs; archived closing lines have unverified original timestamps. Not official Scout/Plug forecasts. No new home-field bonus.'}

def mismatch(profile,kind):
    p=profile[kind];a=p['opponent_adjusted_attack'];d=p['opponent_adjusted_allowed']
    if not all(math.isfinite(v) for v in (a,d)):raise ValueError('Invalid mismatch input')
    if a*d<=0:return 0
    strength=min(abs(a),abs(d));b=0 if strength<.025 else 1 if strength<.075 else 2 if strength<.15 else 3
    return b if a>0 else -b

def band_vector(band,volume):
    if band not in (-3,-2,-1,0,1,2,3) or not math.isfinite(volume):raise ValueError('Invalid band')
    out=[0.]*3
    if band:out[abs(band)-1]=(1 if band>0 else -1)*max(.5,min(1.5,volume))
    return out

class Points:
    def __init__(self,n):
        self.n=n;self.a=[[float(30 if i==j else 0) for j in range(n)] for i in range(n)];self.b=[0.]*n;self.count=[0]*n;self.version=0
    def update(self,x,residual):
        if len(x)!=self.n or not all(math.isfinite(v) for v in x+[residual]):raise ValueError('Invalid training row')
        for i in range(self.n):
            if x[i]:self.count[i]+=1
            self.b[i]+=x[i]*residual
            for j in range(self.n):self.a[i][j]+=x[i]*x[j]
        self.version+=1
    def weights(self):
        if getattr(self,'cached',None)!=self.version:
            w=[0.]*self.n
            for _ in range(200):
                change=0.
                for i in range(self.n):
                    value=0. if self.count[i]<20 else max(0.,min(3.,(self.b[i]-sum(self.a[i][j]*w[j] for j in range(self.n) if i!=j))/self.a[i][i]))
                    change=max(change,abs(value-w[i]));w[i]=value
                if change<1e-10:break
            self.w=w;self.cached=self.version
        return self.w[:]
    def adjustment(self,x):
        if len(x)!=self.n:raise ValueError('Wrong feature length')
        cap=4. if self.n==6 else 3.
        return max(-cap,min(cap,sum(a*b for a,b in zip(x,self.weights()))))

def total_grade(projected,line,actual):
    if not all(math.isfinite(v) for v in (projected,line,actual)):raise ValueError('Invalid total')
    if abs(projected-line)<=1e-9:return {'side':'No Call','result':'No Call'}
    over=projected>line;cover=(actual-line)*(1 if over else -1)
    return {'side':'Over' if over else 'Under','result':'Push' if abs(cover)<=1e-9 else 'Win' if cover>0 else 'Loss'}

def run(db,schedule,*,train_season=2022,last_season=2026):
    with Path(schedule).open(newline='') as f:
        markets={}
        for r in csv.DictReader(f):
            if r.get('game_type')!='REG':continue
            if r['game_id'] in markets:raise ValueError('Duplicate market game')
            markets[r['game_id']]=r
    games=db.execute('SELECT gid,season,week,kickoff,end_at,away,home,away_score,home_score FROM games WHERE season BETWEEN ? AND ? ORDER BY kickoff,gid',(train_season,last_season)).fetchall()
    groups=defaultdict(list)
    for g in games:groups[g[1],g[2]].append(g)
    models={'passing_only':Points(3),'rushing_only':Points(3),'combined':Points(6)}
    pending=[];ledger=[];calibration=[];skipped=Counter()
    for (year,week),gg in sorted(groups.items()):
        cutoff=min(g[3] for g in gg);at=datetime.fromisoformat(cutoff);still=[]
        for ready,features,y in pending:
            if ready<at:
                for k,x in features.items():models[k].update(x,y)
            else:still.append((ready,features,y))
        pending=still
        calibration.append(dict(season=year,week=week,cutoff=cutoff,models={k:{'coefficients':v.weights(),'band_team_games':v.count[:]} for k,v in models.items()}))
        for gid,year,week,kick,end,away,home,a,h in gg:
            f=build(db,away,home,cutoff,mode='retrospective')
            if min(p['games'] for p in f['teams'])<3:skipped['team_warmup']+=1;continue
            scores={k:[] for k in VARIANTS};bonuses={k:[] for k in VARIANTS};bands=[]
            for side,profile,actual in zip(('away','home'),f['teams'],(a,h)):
                pb,rb=mismatch(profile,'pass'),mismatch(profile,'rush')
                pv=band_vector(pb,profile['pass_share']/.55);rv=band_vector(rb,(1-profile['pass_share'])/.45)
                xs={'passing_only':pv,'rushing_only':rv,'combined':pv+rv};base=f['baseline'][side+'_points']
                scores['baseline'].append(base);bonuses['baseline'].append(0.)
                for k,x in xs.items():
                    adj=models[k].adjustment(x);scores[k].append(max(0.,base+adj));bonuses[k].append(adj)
                bands.append({'passing':pb,'rushing':rb})
                pending.append((datetime.fromisoformat(end)+timedelta(hours=48),xs,actual-base))
            if year<=train_season:continue
            market=markets.get(gid)
            if market is None or not market.get('spread_line'):skipped['missing_spread']+=1;continue
            if team(market['away_team'])!=away or team(market['home_team'])!=home or float(market['away_score'])!=a or float(market['home_score'])!=h:raise ValueError('Market/game mismatch')
            spread=float(market['spread_line']);total=float(market['total_line']) if market.get('total_line') else None
            if total is None:skipped['missing_total']+=1
            decisions={k:grade(v[0]-v[1],spread,a-h) for k,v in scores.items()}
            totals={k:total_grade(sum(v),total,a+h) for k,v in scores.items()} if total is not None else {}
            ledger.append(dict(game_id=gid,season=year,week=week,cutoff=cutoff,spread=spread,total_line=total,
                actual_margin=a-h,actual_total=a+h,scores=scores,bonuses=bonuses,bands=bands,totals=totals,**decisions))
    seasons={}
    for year in sorted({r['season'] for r in ledger}):
        rows=[r for r in ledger if r['season']==year];summary={}
        for k in VARIANTS:
            tr=[{k:r['totals'][k]} for r in rows if r['totals']]
            summary[k]={'ats':record(rows,k),'totals':record(tr,k),
                'ats_changed_vs_baseline':sum(r[k]['side']!=r['baseline']['side'] for r in rows),
                'totals_changed_vs_baseline':sum(r['totals'][k]['side']!=r['totals']['baseline']['side'] for r in rows if r['totals']),
                'games_with_score_adjustment':sum(any(abs(v)>1e-9 for v in r['bonuses'][k]) for r in rows),
                'mean_abs_team_adjustment':sum(abs(v) for r in rows for v in r['bonuses'][k])/(2*len(rows)),
                'margin_mae':sum(abs(r['actual_margin']-(r['scores'][k][0]-r['scores'][k][1])) for r in rows)/len(rows),
                'total_mae':sum(abs(r['actual_total']-sum(r['scores'][k])) for r in rows)/len(rows)}
        seasons[str(year)]={'games':len(rows),'variants':summary}
    return {'specification':SPEC,'train_season':train_season,'last_season':last_season,'line_sha256':sha(schedule),
        'seasons':seasons,'skipped':dict(skipped),'calibration_by_week':calibration,'games':ledger}

def save(result,path):
    games=result.pop('games');lp=path.with_suffix('.games.csv')
    fields=['game_id','season','week','cutoff','spread','total_line','actual_margin','actual_total','away_pass_band','home_pass_band','away_rush_band','home_rush_band']+[k+s for k in VARIANTS for s in ('_away_score','_home_score','_away_bonus','_home_bonus','_ats_side','_ats_result','_ou_side','_ou_result')]
    with lp.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader()
        for r in games:
            row={k:r[k] for k in fields[:8]}
            for i,s in enumerate(('away','home')):row[s+'_pass_band']=r['bands'][i]['passing'];row[s+'_rush_band']=r['bands'][i]['rushing']
            for k in VARIANTS:
                row.update({k+'_away_score':r['scores'][k][0],k+'_home_score':r['scores'][k][1],k+'_away_bonus':r['bonuses'][k][0],k+'_home_bonus':r['bonuses'][k][1],k+'_ats_side':r[k]['side'],k+'_ats_result':r[k]['result'],k+'_ou_side':r['totals'].get(k,{}).get('side','Missing line'),k+'_ou_result':r['totals'].get(k,{}).get('result','Missing line')})
            w.writerow(row)
    result['ledger']={'file':lp.name,'rows':len(games),'sha256':sha(lp)};path.write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--schedule',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--train-season',type=int,default=2022);p.add_argument('--last-season',type=int,default=2026);a=p.parse_args()
    start=time.monotonic();db=connect(a.db)
    try:r=run(db,a.schedule,train_season=a.train_season,last_season=a.last_season)
    finally:db.close()
    r['resources']={'elapsed_seconds':round(time.monotonic()-start,3),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)}
    save(r,a.output);print(json.dumps(r['seasons'],indent=2))
