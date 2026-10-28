"""Independent market ATS v5 (ported from 2026-10-27 research package).
The target market quote is never a model feature. Historical labels end at
the previous completed season. Current-week results/QBs are never features.
"""
from collections import defaultdict
from pathlib import Path
import csv
import math

RIDGE = 35.0
ALIASES = {'LAR':'LA','STL':'LA','OAK':'LV','SD':'LAC','JAC':'JAX','WSH':'WAS'}

def number(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError): return None

def read_games(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as file:
        raw=list(csv.DictReader(file))
    games=[]
    for r in raw:
        if r.get('game_type') not in ('REG','REGULAR'):continue
        try: y,w=int(r['season']),int(r['week'])
        except (KeyError,TypeError,ValueError):continue
        if y<2014:continue
        games.append(dict(id=r['game_id'],season=y,week=w,
            away=ALIASES.get(r['away_team'],r['away_team']),
            home=ALIASES.get(r['home_team'],r['home_team']),
            a_score=number(r.get('away_score')),h_score=number(r.get('home_score')),
            spread=number(r.get('spread_line')),
            a_rest=number(r.get('away_rest')),h_rest=number(r.get('home_rest')),
            a_qb=r.get('away_qb_id') or '',h_qb=r.get('home_qb_id') or ''))
    return sorted(games,key=lambda g:(g['season'],g['week'],g['id']))

def opponent_ratings(games):
    if not games:return {},{},0.
    teams=sorted({g[k] for g in games for k in ('away','home')})
    ppg=sum(g['a_score']+g['h_score'] for g in games)/(2*len(games))
    by=defaultdict(list)
    for g in games:
        by[g['away']].append((g['a_score'],g['h_score'],g['home']))
        by[g['home']].append((g['h_score'],g['a_score'],g['away']))
    off={t:0. for t in teams};defense={t:0. for t in teams}
    for _ in range(5):
        no={t:sum(pf-ppg+defense[op] for pf,pa,op in rows)/(len(rows)+4.)
            for t,rows in by.items()}
        nd={t:sum(ppg+no[op]-pa for pf,pa,op in rows)/(len(rows)+4.)
            for t,rows in by.items()}
        off,defense=no,nd
    return off,defense,ppg

def solve(A,b):
    n=len(b);M=[list(A[i])+[b[i]] for i in range(n)]
    for i in range(n):
        k=max(range(i,n),key=lambda j:abs(M[j][i]))
        M[i],M[k]=M[k],M[i]
        if abs(M[i][i])<1e-10:raise ValueError('Singular v5 fit')
        val=M[i][i]
        for c in range(i,n+1):M[i][c]/=val
        for j in range(n):
            if j==i:continue
            val=M[j][i]
            for c in range(i,n+1):M[j][c]-=val*M[i][c]
    return [M[i][-1] for i in range(n)]

def fit(rows):
    if len(rows)<500:raise ValueError('Insufficient prior-season market labels')
    n=len(rows[0][0]);A=[[0.]*n for _ in range(n)];b=[0.]*n
    for x,y in rows:
        for i in range(n):
            b[i]+=x[i]*y
            for j in range(n):A[i][j]+=x[i]*x[j]
    for i in range(1,n):A[i][i]+=RIDGE
    return solve(A,b)

def features(games, target_season, target_week):
    """Mirror historical v5 v1-v4 + last-known QB proxy in 14 dimensions.

    For a prospective target, only earlier weeks have observed outcomes. Target
    week's scores/actual QB labels are always masked, even when CSV was updated.
    """
    history=defaultdict(list);elo=defaultdict(lambda:1500.)
    completed=defaultdict(list);qb_seen=defaultdict(list);qb_last=defaultdict(list)
    qb_margin=defaultdict(list);team_qb_last={}
    priors={};previous={};result=[];last_season=None
    for season in sorted({g['season'] for g in games if g['season']<=target_season}):
        if last_season is not None:
            for team in list(elo):elo[team]=1500.+0.65*(elo[team]-1500.)
        last_season=season
        weeks=sorted({g['week'] for g in games if g['season']==season})
        prior_season_scores=[]
        for week in weeks:
            if season==target_season and week>target_week:break
            block=[g for g in games if g['season']==season and g['week']==week]
            off,defense,_=opponent_ratings(completed[season])
            for g in block:
                a,h=g['away'],g['home']
                ah,hh=history[(season,a)],history[(season,h)]
                mean=lambda xs:sum(xs)/len(xs) if xs else 0.
                base=[1.,(elo[a]-elo[h])/100.,mean(ah)-mean(hh),
                      mean(ah[-3:])-mean(hh[-3:]),
                      min(len(ah),8)-min(len(hh),8),
                      max(-7,min(7,(g['a_rest'] or 7)-(g['h_rest'] or 7))),
                      min(week,10)]
                # v2 opponent adjusted rating difference
                base.extend([off.get(a,0)-off.get(h,0),
                             defense.get(a,0)-defense.get(h,0)])
                # v3 last known QB continuity/experience/returning
                pairs=[]
                for team in (a,h):
                    prior=qb_last[team]
                    recent=[qb for sy,w,qb in prior if sy==season and w<week and qb]
                    previous_qbs=[qb for sy,w,qb in prior if sy==season-1 and qb]
                    newest=recent[-1] if recent else (previous_qbs[-1] if previous_qbs else '')
                    cont=sum(qb==newest for qb in recent[-4:])/len(recent[-4:]) if recent and newest else 0.
                    exp=min(len(recent),6)/6.
                    returning=float(bool(previous_qbs and newest and newest==previous_qbs[-1]))
                    pairs.append((cont,exp,returning))
                base.extend(pairs[0][i]-pairs[1][i] for i in range(3))
                # v4 prior-season adjusted offense/defense
                aoff,adef=previous.get(a,(0.,0.));hoff,hdef=previous.get(h,(0.,0.))
                decay=max(0.,(9.-week)/8.)
                base.extend([decay*(aoff-hoff)/10.,decay*(adef-hdef)/10.,
                             decay*((aoff+hdef)-(hoff+adef))/10.])
                # v5 previous-known QB average margin and experience-share
                qvals=[]
                for team in (a,h):
                    qb=team_qb_last.get(team,'')
                    recent_qb=qb_margin.get(qb,[])[-16:] if qb else []
                    value=sum(recent_qb)/(len(recent_qb)+8.) if recent_qb else 0.
                    share=min(len(recent_qb),16)/16.
                    qvals.append((value,share))
                base.extend(qvals[0][i]-qvals[1][i] for i in range(2))
                result.append((g,base))
            # Update histories only after every game this week is featured.
            for g in block:
                if (season==target_season and week>=target_week or
                    g['a_score'] is None or g['h_score'] is None):continue
                a,h=g['away'],g['home'];margin=g['a_score']-g['h_score']
                completed[season].append(g)
                history[(season,a)].append(margin)
                history[(season,h)].append(-margin)
                expected=1/(1+10**((elo[h]+55-elo[a])/400))
                observed=1 if margin>0 else 0 if margin<0 else .5
                change=20*(observed-expected)*min(2.,1+abs(margin)/30)
                elo[a]+=change;elo[h]-=change
                for team,qb,m in ((a,g['a_qb'],margin),(h,g['h_qb'],-margin)):
                    if qb:
                        qb_last[team].append((season,week,qb))
                        qb_margin[qb].append(m)
                        team_qb_last[team]=qb
        # Previous season's opponent-strength priors for next season.
        off,defense,_=opponent_ratings(completed[season])
        previous={team:(off.get(team,0.),defense.get(team,0.))
                  for team in set(off)|set(defense)}
    return result

def projections(schedule_path,season,week):
    games=read_games(schedule_path)
    if season<2019:raise ValueError('v5 requires established previous-season training')
    rows=features(games,season,week)
    training=[(x,-g['spread']) for g,x in rows if 2016<=g['season']<season
              and g['spread'] is not None and g['a_score'] is not None
              and g['h_score'] is not None]
    coefficients=fit(training)
    return {g['id']:round(-sum(a*b for a,b in zip(coefficients,x)),3)
            for g,x in rows if g['season']==season and g['week']==week}
