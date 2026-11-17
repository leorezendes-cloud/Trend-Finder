"""Compact, dependency-free Scout 5.0 O/U runtime (ATS is not modified).

Model and weekly EPA ratings are exported locally and then deployed as one
small JSON file. Never substitutes a stale rating week or the retired total.
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

MODEL_FIELDS = ('scout_total', 'off_sum', 'def_sum')
ALIAS = {'JAC':'JAX','LAR':'LA','STL':'LA','OAK':'LV','SD':'LAC','WSH':'WAS'}


def _code(s):
    return ALIAS.get(s, s)


def load_bundle(path):
    p=Path(path)
    doc=json.loads(p.read_text())
    if doc.get('version') != 'scout5-ou-v1' or doc.get('fields') != list(MODEL_FIELDS):
        raise ValueError('Unexpected Scout 5.0 version or feature order')
    if any(len(doc[k]) != n for k,n in (('means',3),('scales',3),('coef',4))):
        raise ValueError('Scout 5.0 coefficients incomplete')
    if not doc.get('ratings') or any(not isinstance(v,dict) or len(v)!=32 for v in doc['ratings'].values()):
        raise ValueError('Incomplete weekly Scout 5.0 team ratings')
    for seq in (doc['means'],doc['scales'],doc['coef']):
        if not all(isinstance(n,(float,int)) and math.isfinite(n) for n in seq):
            raise ValueError('Non-finite Scout 5.0 weights')
    if any(n<=0 for n in doc['scales']):
        raise ValueError('Invalid Scout 5.0 scaling')
    return doc


def team_history(schedule_path,season,week):
    history=defaultdict(list)
    with Path(schedule_path).open(newline='',encoding='utf-8-sig') as f:
        for g in csv.DictReader(f):
            if g.get('game_type')!='REG': continue
            try:
                if int(g['season'])!=int(season) or int(g['week'])>=int(week):continue
                a,h=float(g['away_score']),float(g['home_score'])
                if not all(math.isfinite(x) and x>=0 and x.is_integer() for x in (a,h)):
                    continue
                away,home=_code(g['away_team']),_code(g['home_team'])
                history[away].append((a,h));history[home].append((h,a))
            except (KeyError,TypeError,ValueError):continue
    return history


def projected_total(bundle,schedule_path,season,week,away,home):
    if int(season)!=int(bundle['season']):
        raise ValueError('No Scout 5.0 model for requested NFL season')
    weekly=bundle['ratings'].get(str(int(week)))
    if weekly is None:
        raise ValueError('No pre-week EPA snapshot for W'+str(week)+'; Scout O/U unavailable')
    away,home=_code(away),_code(home)
    if away==home or away not in weekly or home not in weekly:
        raise ValueError('Missing valid team ratings')
    history=team_history(schedule_path,season,week)
    ah,hh=history[away],history[home]
    if min(len(ah),len(hh))<3:
        raise ValueError('Need 3 completed prior games per team')
    apf=round(sum(r[0] for r in ah)/len(ah),1)
    apa=round(sum(r[1] for r in ah)/len(ah),1)
    hpf=round(sum(r[0] for r in hh)/len(hh),1)
    hpa=round(sum(r[1] for r in hh)/len(hh),1)
    apred=round((apf+hpa)/2,1)
    hpred=round((hpf+apa)/2,1)
    values=[apred+hpred,weekly[away][0]+weekly[home][0],weekly[away][1]+weekly[home][1]]
    result=bundle['coef'][0]+sum(c*(v-m)/s for v,m,s,c in zip(values,bundle['means'],bundle['scales'],bundle['coef'][1:]))
    if not math.isfinite(result) or not 0<result<150:
        raise ValueError('Implausible Scout 5.0 O/U')
    return result


def side(total,line):
    line=float(line)
    if not math.isfinite(line) or line<=0:raise ValueError('Invalid total quote')
    return 'Over' if total>line else 'Under' if total<line else None
