"""Frozen v14 primitives from user's independently validated 2026 research package."""
import csv,math,sys
from collections import defaultdict
from pathlib import Path
TRAIN_START=2016
FIRST_REPORT=2019
LAST_YEAR=2026
PREGAME_RIDGE=35.0

def num(value):
    try:
        val=float(value)
        return val if math.isfinite(val) else None
    except (TypeError,ValueError):
        return None

def average(values,default=0.0):
    return sum(values)/len(values) if values else default

def latest_season_week(season,week):
    return week==17 if season<=2020 else week==18

def load_games(path):
    by_id={}
    with Path(path).open(newline='',encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if str(r.get('game_type','')).upper() not in ('REG','REGULAR'):continue
            try:year=int(r['season']);week=int(r['week'])
            except (KeyError,ValueError,TypeError):continue
            if year<2014 or year>LAST_YEAR:continue
            gid=r['game_id']
            if gid in by_id:raise RuntimeError('Duplicate nfl_games game_id: '+gid)
            by_id[gid]={
                'id':gid,'year':year,'week':week,'away':r['away_team'],'home':r['home_team'],
                'date':r.get('gameday',''),'rest_away':num(r.get('away_rest')),
                'rest_home':num(r.get('home_rest')),'market':num(r.get('total_line')),
                'a_score':num(r.get('away_score')),'h_score':num(r.get('home_score')),
                'division':str(r.get('div_game','')).lower() in ('true','1','yes'),
                'neutral':str(r.get('location','')).lower()=='neutral',
                'source':'nfl_games.csv total_line'}
    if not by_id:raise RuntimeError('No regular season games in '+str(path))
    return sorted(by_id.values(),key=lambda g:(g['year'],g['week'],g['id']))

def solve(A,b):
    n=len(b);m=[list(A[i])+[b[i]] for i in range(n)]
    for i in range(n):
        piv=max(range(i,n),key=lambda j:abs(m[j][i]))
        m[i],m[piv]=m[piv],m[i]
        if abs(m[i][i])<1e-12:raise RuntimeError('Singular regression')
        scale=m[i][i]
        for k in range(i,n+1):m[i][k]/=scale
        for j in range(n):
            if i==j:continue
            fac=m[j][i]
            for k in range(i,n+1):m[j][k]-=fac*m[i][k]
    return [r[-1] for r in m]

def fit(data):
    if len(data)<400:raise RuntimeError('Insufficient past-season training: '+str(len(data)))
    n=len(data[0][0]);A=[[0.0]*n for _ in range(n)];b=[0.0]*n
    for x,y in data:
        for i in range(n):
            b[i]+=x[i]*y
            for j in range(n):A[i][j]+=x[i]*x[j]
    for i in range(1,n):A[i][i]+=PREGAME_RIDGE
    return solve(A,b)

def team_rates(team,prior,current,league_half):
    prev=prior.get(team,[]);now=current.get(team,[])
    prev_att=(3.0*league_half+sum(x[0] for x in prev))/(3.0+len(prev))
    prev_def=(3.0*league_half+sum(x[1] for x in prev))/(3.0+len(prev))
    off=(5.0*prev_att+sum(x[0] for x in now))/(5.0+len(now))
    defence=(5.0*prev_def+sum(x[1] for x in now))/(5.0+len(now))
    recent=average([a+d for a,d in now[-3:]],2.0*league_half)
    if now:recent=(2.0*(off+defence)+sum(a+d for a,d in now[-3:]))/(2.0+len(now[-3:]))
    return off,defence,recent

def is_complete(g):
    return g['a_score'] is not None and g['h_score'] is not None and g['market'] is not None

base=sys.modules[__name__]

def normal_rest(g):
    ra=g['rest_away'] if g['rest_away'] is not None else 7
    rh=g['rest_home'] if g['rest_home'] is not None else 7
    return min(21,max(0,ra))+min(21,max(0,rh))

def common_features(g,league_total,a_off,a_def,a_recent,h_off,h_def,h_recent):
    return [1.0,(league_total-44.0)/8.0,
            (a_off+h_def-league_total)/10.0,(h_off+a_def-league_total)/10.0,
            (0.5*(a_recent+h_recent)-league_total)/10.0,
            (normal_rest(g)-14.0)/14.0,float(g['division']),float(g['neutral']),
            (min(17,g['week'])-9.0)/9.0]

def season_week_blocks(games):
    by_year=defaultdict(lambda:defaultdict(list))
    for g in games:by_year[g['year']][g['week']].append(g)
    for season in sorted(by_year):
        for week in sorted(by_year[season]):yield season,week,by_year[season][week]

def completed(g):
    return g['a_score'] is not None and g['h_score'] is not None

def build_v2(games):
    prior_raw=defaultdict(list);prior_adj=defaultdict(list)
    current_raw=defaultdict(list);current_adj=defaultdict(list)
    past_league=44.0;season_scores=[];output=[];last_year=None
    for season,week,block in season_week_blocks(games):
        if season!=last_year:
            if last_year is not None:
                prior_raw=current_raw;prior_adj=current_adj
                if season_scores:past_league=base.average(season_scores)
            current_raw=defaultdict(list);current_adj=defaultdict(list)
            season_scores=[];last_year=season
        league_total=(64*past_league+sum(season_scores))/(64+len(season_scores))
        half=league_total/2
        snapshots={}
        for g in block:
            a_off,a_def,a_rec=base.team_rates(g['away'],prior_raw,current_raw,half)
            h_off,h_def,h_rec=base.team_rates(g['home'],prior_raw,current_raw,half)
            x=common_features(g,league_total,a_off,a_def,a_rec,h_off,h_def,h_rec)
            aa_off,aa_def,_=base.team_rates(g['away'],prior_adj,current_adj,half)
            ah_off,ah_def,_=base.team_rates(g['home'],prior_adj,current_adj,half)
            x += [((aa_off+ah_def)-(a_off+h_def))/10.0,((ah_off+aa_def)-(h_off+a_def))/10.0]
            output.append((g,x))
            snapshots[g['id']]=(a_off,a_def,h_off,h_def,half)
        for g in block:
            if not completed(g):continue
            a,h=g['a_score'],g['h_score']
            a_off,a_def,h_off,h_def,half=snapshots[g['id']]
            def penalty(r):return min(12.0,max(-12.0,0.65*(r-half)))
            current_raw[g['away']].append((a,h))
            current_raw[g['home']].append((h,a))
            current_adj[g['away']].append((a-penalty(h_def),h-penalty(h_off)))
            current_adj[g['home']].append((h-penalty(a_def),a-penalty(a_off)))
            season_scores.append(a+h)
    return output
