"""Fixed ablations for all supported player/PBP/charting features. Research only."""
import argparse,csv,json,math,resource,sys,time
from collections import defaultdict,Counter
from datetime import datetime,timedelta
from pathlib import Path
from .store import connect,sha,team
from .features import build,vector
from .ats import grade,record
from .evaluate import Ridge

VARIANTS=('baseline','limited','players','pbp','full_available')
SPEC={
 'policy':'player-scheme-full-ats-v1','ridge_penalty':100,'minimum_team_games':3,
 'player_features_per_team':['prior_QB_EPA_per_attempt','prior_QB_recent_passing_yards/300',
    'top3_WR_recent_yards/100','top3_WR_target_weighted_yards_per_target/10','top3_WR_defense_position_mismatch/1000',
    'top2_TE_recent_yards/100','top2_TE_target_weighted_yards_per_target/10','top2_TE_defense_position_mismatch/1000',
    'top2_RB_recent_rush_yards/100','top2_RB_receiving_matchup/1000'],
 'pbp_features_per_team':['neutral_pass_EPA/dropback','neutral_rush_EPA/run','neutral_CPOE/10',
    'own_sack_rate*opponent_sack_rate','prior_QB_hit_EPA*opponent_hit_rate','pass_share*opponent_hit_rate'],
 'charted_features_per_team':['prior_QB_pressure_EPA*opponent_five_plus_rusher_rate',
    'prior_QB_man_EPA*opponent_man_rate','prior_QB_zone_EPA*opponent_zone_rate'],
 'variants':{'baseline':'original PF/PA model','limited':'original eight-feature enhancement',
    'players':'limited + individual production and positional matchups','pbp':'players + neutral PBP/protection proxies',
    'full_available':'pbp + verified historical charting when available; missing scheme blocks contribute zero'},
 'missing':'Report exposure. Missing is not measured zero; charting terms gated by both player and opponent exposure.',
 'unavailable':['X/Z/slot alignment','YPRR','individual WR-CB assignment','verified current blitz designations','injury/availability projections'],
 'cohort':'Historical player-role proxies only; no claim of knowing next-game starters. No line enters features or fitting.',
 'validation':'Exploratory fixed feature set; no threshold/penalty search or automatic promotion.'}

class CachedRidge(Ridge):
    """Same ridge solution, cached until training observations change."""
    def predict(self,x):
        if self.n<32:return 0.
        if getattr(self,'cached_n',None)!=self.n:
            n=len(x);a=[self.a[i][:]+[self.b[i]] for i in range(n)]
            for i in range(n):
                pivot=max(range(i,n),key=lambda k:abs(a[k][i]));a[i],a[pivot]=a[pivot],a[i]
                d=a[i][i];a[i]=[v/d for v in a[i]]
                for j in range(n):
                    if j!=i:
                        d=a[j][i];a[j]=[a[j][k]-d*a[i][k] for k in range(n+1)]
            self.weights=[a[i][-1] for i in range(n)];self.cached_n=self.n
        return sum(a*b for a,b in zip(x,self.weights))

def val(metric):
    return metric['value'] if metric and metric['exposure']>0 else 0.

def inputs(f):
    player=[];pbp=[];chart=[];coverage=[]
    for p in f['teams']:
        qbs=sorted((r for r in p['players'] if r['position']=='QB'),key=lambda r:(-r['recent']['attempts'],r['player_id']))
        qb=qbs[0] if qbs else None
        player.extend([val(qb['passing_epa_per_attempt']) if qb else 0.,qb['recent']['passing_yards']/300 if qb else 0.])
        for pos,n in [('WR',3),('TE',2)]:
            rr=sorted((r for r in p['players'] if r['position']==pos),key=lambda r:(-r['recent']['targets'],r['player_id']))[:n]
            player.extend([sum(r['recent']['receiving_yards'] for r in rr)/100,
                sum(r['target_share']*val(r['receiving_yards_per_target']) for r in rr)/10,
                sum(r['recent']['targets'] for r in rr)*p['positions'][pos]['allowed_relative_to_league']/1000])
        rb=sorted((r for r in p['players'] if r['position']=='RB'),key=lambda r:(-r['recent']['carries'],r['player_id']))[:2]
        player.extend([sum(r['recent']['rushing_yards'] for r in rb)/100,
            sum(r['recent']['targets'] for r in rb)*p['positions']['RB']['allowed_relative_to_league']/1000])
        pbp.extend([val(p['neutral_pass_epa']),val(p['neutral_rush_epa']),val(p['neutral_cpoe'])/10,
            val(p['protection_sack_rate'])*val(p['opponent_sack_rate']),
            val(qb['hit_epa_response_proxy']) * val(p['opponent_hit_rate']) if qb else 0.,
            p['pass_share']*val(p['opponent_hit_rate'])])
        pressure=qb['verified_pressure_response'] if qb else None
        man=qb['man_response'] if qb else None;zone=qb['zone_response'] if qb else None
        rush=p['opponent_five_plus_rusher_rate'];defman=p['opponent_man_rate']
        pressure_ok=bool(pressure and pressure['exposure']>0 and rush['exposure']>0)
        man_ok=bool(man and man['exposure']>0 and defman['exposure']>0)
        zone_ok=bool(zone and zone['exposure']>0 and defman['exposure']>0)
        chart.extend([val(pressure)*val(rush) if pressure_ok else 0.,
            val(man)*val(defman) if man_ok else 0.,val(zone)*(1-val(defman)) if zone_ok else 0.])
        coverage.append({'team':p['team'],'prior_QB_id':qb['player_id'] if qb else None,
            'neutral_dropbacks':p['neutral_pass_epa']['exposure'],
            'pressure_matchup_available':pressure_ok,'man_matchup_available':man_ok,'zone_matchup_available':zone_ok})
    old=vector(f)
    vectors={'limited':old,'players':old+player,'pbp':old+player+pbp,'full_available':old+player+pbp+chart}
    if not all(math.isfinite(v) for x in vectors.values() for v in x):raise ValueError('Invalid feature')
    return vectors,coverage

def run(db,schedule,*,train_season=2022,last_season=2026,baseline_provider=None):
    with Path(schedule).open(newline='') as f:
        markets={r['game_id']:r for r in csv.DictReader(f) if r.get('game_type')=='REG' and r.get('spread_line')}
    games=db.execute('SELECT gid,season,week,kickoff,end_at,away,home,away_score,home_score FROM games WHERE season BETWEEN ? AND ? ORDER BY kickoff,gid',(train_season,last_season)).fetchall()
    groups=defaultdict(list)
    for g in games:groups[g[1],g[2]].append(g)
    models={};pending=[];ledger=[];skipped=Counter()
    for (_,week),gg in sorted(groups.items()):
        cutoff=min(g[3] for g in gg);now=datetime.fromisoformat(cutoff);still=[]
        for ready,xs,y in pending:
            if ready<now:
                for key,x in xs.items():models[key].update(x,y)
            else:still.append((ready,xs,y))
        pending=still
        for gid,year,week,kick,end,away,home,a,h in gg:
            f=build(db,away,home,cutoff,mode='retrospective')
            if min(t['games'] for t in f['teams'])<3:skipped['team_warmup']+=1;continue
            xs,cov=inputs(f)
            if not models:models={key:CachedRidge(len(x)) for key,x in xs.items()}
            base=(baseline_provider(year,week,gid) if baseline_provider else
                f['baseline']['away_points']-f['baseline']['home_points']);actual=a-h
            if not math.isfinite(base):raise ValueError('Invalid baseline margin')
            margins={'baseline':base,**{key:base+models[key].predict(x) for key,x in xs.items()}}
            pending.append((datetime.fromisoformat(end)+timedelta(hours=48),xs,actual-base))
            if year<=train_season:continue
            market=markets.get(gid)
            if market is None:skipped['missing_line']+=1;continue
            if team(market['away_team'])!=away or team(market['home_team'])!=home or float(market['away_score'])!=a or float(market['home_score'])!=h:raise ValueError('Market cohort mismatch')
            line=float(market['spread_line'])
            ledger.append(dict(game_id=gid,season=year,week=week,cutoff=cutoff,line=line,actual_margin=actual,
                margins=margins,coverage=cov,**{k:grade(v,line,actual) for k,v in margins.items()}))
    seasons={}
    for y in sorted({r['season'] for r in ledger}):
        rows=[r for r in ledger if r['season']==y]
        # Strict charted cohort needs both sides to have every charting interaction.
        covered=[r for r in rows if all(all(t[k] for k in ('pressure_matchup_available','man_matchup_available','zone_matchup_available')) for t in r['coverage'])]
        seasons[str(y)]={'games':len(rows),'variants':{},'fully_charted_games':len(covered),
            'charted_cohort':{k:record(covered,k) for k in VARIANTS},
            'games_with_pbp_both_sides':sum(all(t['neutral_dropbacks']>0 for t in r['coverage']) for r in rows)}
        for k in VARIANTS:
            seasons[str(y)]['variants'][k]={**record(rows,k),
                'changed_vs_baseline':sum(r[k]['side']!=r['baseline']['side'] for r in rows),
                'margin_mae':sum(abs(r['actual_margin']-r['margins'][k]) for r in rows)/len(rows)}
    return {'specification':SPEC,'train_season':train_season,'last_season':last_season,
        'line_sha256':sha(schedule),'warning':'Retrospective corrected snapshots and untimestamped archived closing lines, not official betting records. Charting unavailable in current-season cache.',
        'seasons':seasons,'skipped':dict(skipped),'games':ledger}

def save(result,path):
    rows=result.pop('games');lp=path.with_suffix('.games.csv')
    fields=['game_id','season','week','cutoff','line','actual_margin','fully_charted']+[k+s for k in VARIANTS for s in ('_margin','_side','_result')]
    with lp.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader()
        for r in rows:
            row={k:r[k] for k in fields[:6]};row['fully_charted']=all(all(t[k] for k in ('pressure_matchup_available','man_matchup_available','zone_matchup_available')) for t in r['coverage'])
            for k in VARIANTS:row.update({k+'_margin':r['margins'][k],k+'_side':r[k]['side'],k+'_result':r[k]['result']})
            w.writerow(row)
    result['ledger']={'path':lp.name,'rows':len(rows),'sha256':sha(lp)}
    path.write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--schedule',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--train-season',type=int,default=2022);p.add_argument('--last-season',type=int,default=2026);a=p.parse_args()
    started=time.monotonic();db=connect(a.db)
    try:result=run(db,a.schedule,train_season=a.train_season,last_season=a.last_season)
    finally:db.close()
    result['resources']={'elapsed_seconds':round(time.monotonic()-started,3),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),'database_bytes':a.db.stat().st_size}
    save(result,a.output);print(json.dumps(result['seasons'],indent=2))
