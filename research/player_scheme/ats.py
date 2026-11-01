"""Retrospective ATS audit of the unchanged research margin models."""
import argparse,csv,json,math
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from pathlib import Path
from .evaluate import Ridge
from .features import build,vector
from .store import connect,sha,team

EPS=1e-9

def grade(predicted_away_margin, market_home_margin, actual_away_margin):
    values=(predicted_away_margin,market_home_margin,actual_away_margin)
    if not all(math.isfinite(v) for v in values):raise ValueError('Non-finite ATS input')
    # nflverse spread_line = expected HOME margin: home favorite 3 means away +3.
    edge=predicted_away_margin+market_home_margin
    if abs(edge)<=EPS:return {'side':'No Call','result':'No Call'}
    side='away' if edge>0 else 'home'
    cover=(actual_away_margin+market_home_margin)*(1 if side=='away' else -1)
    return {'side':side,'result':'Push' if abs(cover)<=EPS else 'Win' if cover>0 else 'Loss'}

def record(rows,kind):
    c=Counter(r[kind]['result'] for r in rows);w,l,p,n=(c[k] for k in ('Win','Loss','Push','No Call'))
    return {'wins':w,'losses':l,'pushes':p,'no_calls':n,'cover_pct':100*w/(w+l) if w+l else None}

def audit(db,schedule,*,train_season=2022):
    markets={}
    with Path(schedule).open(newline='') as f:
        for r in csv.DictReader(f):
            if r.get('game_type')!='REG' or not r.get('spread_line'):continue
            if r['game_id'] in markets:raise ValueError('Duplicate market game')
            markets[r['game_id']]=r
    games=db.execute('SELECT gid,season,week,kickoff,end_at,away,home,away_score,home_score FROM games WHERE season>=? ORDER BY kickoff,gid',(train_season,)).fetchall()
    groups=defaultdict(list)
    for g in games:groups[g[1],g[2]].append(g)
    model=Ridge(8);pending=[];ledger=[];skipped=Counter()
    for (year,week),gg in sorted(groups.items()):
        cutoff=min(g[3] for g in gg);at=datetime.fromisoformat(cutoff);still=[]
        for ready,x,y in pending:
            if ready<at:model.update(x,y)
            else:still.append((ready,x,y))
        pending=still
        for gid,year,week,kick,end,away,home,a,h in gg:
            f=build(db,away,home,cutoff,mode='retrospective')
            if min(t['games'] for t in f['teams'])<3:
                skipped['team_warmup']+=1;continue
            x=vector(f);base=f['baseline']['away_points']-f['baseline']['home_points']
            enhanced=base+model.predict(x);actual=a-h
            pending.append((datetime.fromisoformat(end)+timedelta(hours=48),x,actual-base))
            if year<=train_season:continue
            r=markets.get(gid)
            if r is None:skipped['missing_line']+=1;continue
            if team(r['away_team'])!=away or team(r['home_team'])!=home or float(r['away_score'])!=a or float(r['home_score'])!=h:raise ValueError('Schedule/score mismatch: '+gid)
            line=float(r['spread_line'])
            ledger.append(dict(game_id=gid,season=year,week=week,cutoff=cutoff,away_team=away,home_team=home,
                market_home_margin=line,baseline_away_margin=base,enhanced_away_margin=enhanced,actual_away_margin=actual,
                baseline=grade(base,line,actual),enhanced=grade(enhanced,line,actual)))
    seasons={}
    for year in sorted({r['season'] for r in ledger}):
        rr=[r for r in ledger if r['season']==year]
        flips=[r for r in rr if r['baseline']['side']!=r['enhanced']['side']]
        common=[r for r in rr if r['baseline']['side']!='No Call' and r['enhanced']['side']!='No Call']
        seasons[str(year)]={'games':len(rr),'baseline':record(rr,'baseline'),'enhanced':record(rr,'enhanced'),
            'changed_decisions':len(flips),'changed_baseline':record(flips,'baseline'),'changed_enhanced':record(flips,'enhanced'),
            'common_action_games':len(common),'common_baseline':record(common,'baseline'),'common_enhanced':record(common,'enhanced')}
    return {'policy':'player-scheme-ats-v1','line_source_sha256':sha(schedule),'line_field':'nflverse schedule spread_line (expected home margin)',
        'warning':'Retrospective corrected inputs and archived closing lines. Original pregame quote capture times are NOT verified; this is not an official or timestamp-certified betting record.',
        'selection':'Full eligible slate; pick positive model-versus-market edge, exact agreement No Call. No threshold tuning; pushes excluded from cover percentage.',
        'training':'Unchanged 2022 warmup and expanding prior-outcome-only ridge margin enhancement from PR60. No spread enters model features or fitting.',
        'seasons':seasons,'skipped':dict(skipped),'games':ledger}

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--schedule',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    db=connect(a.db)
    try:result=audit(db,a.schedule)
    finally:db.close()
    ledger=result.pop('games');ledger_path=a.output.with_suffix('.games.csv')
    fields=['game_id','season','week','cutoff','away_team','home_team','market_home_margin','baseline_away_margin','enhanced_away_margin','actual_away_margin','baseline_side','baseline_result','enhanced_side','enhanced_result']
    with ledger_path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader()
        for row in ledger:
            row=dict(row)
            for kind in ('baseline','enhanced'):
                decision=row.pop(kind);row[kind+'_side']=decision['side'];row[kind+'_result']=decision['result']
            w.writerow(row)
    result['game_ledger']={'file':ledger_path.name,'sha256':sha(ledger_path),'rows':len(ledger)}
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['seasons'],indent=2))

if __name__=='__main__':main()
