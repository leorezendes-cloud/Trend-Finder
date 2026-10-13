"""Separate totals research model; no injury/weather or true clock-pace claims.

Volume proxy = attempts + sacks suffered + carries. It is not seconds per play.
Continuous normal-error probabilities have no modeled push mass; report and
calibration grading exclude pushes and do not establish reliable confidence.
"""
import math
from collections import defaultdict
from .stats import team_records,mean_metric,number
from .ratings import build_ratings,fit as fit_linear,shrink

VERSION='scout4-totals-1'
LABELS={'league_total':'Earlier-game league scoring baseline',
        'off_score_sum':'Combined adjusted scoring offense',
        'def_score_sum':'Combined adjusted scoring defense',
        'recent_total_deviation':'Recent combined-score deviation',
        'off_pass_sum':'Combined passing EPA strength','off_rush_sum':'Combined rushing EPA strength',
        'def_pass_sum':'Combined passing suppression','def_rush_sum':'Combined rushing suppression',
        'volume_deviation':'Offensive play-volume proxy deviation','pass_share_deviation':'Passing-share deviation',
        'neutral_site':'Neutral venue','market_total':'Quoted total'}
BASE=('league_total','off_score_sum','def_score_sum','recent_total_deviation','neutral_site')
PRODUCTION=BASE+('off_pass_sum','off_rush_sum','def_pass_sum','def_rush_sum','volume_deviation','pass_share_deviation')
MODELS={'Scoring totals':BASE,'Production + volume':PRODUCTION,'Market + statistics':PRODUCTION+('market_total',)}


def profiles(schedule,feed,season,before_week):
    ratings,league=build_ratings(schedule,feed,season,before_week)
    records=team_records(schedule,feed,season,before_week)
    if league is None:return {},None
    histories=defaultdict(list)
    for r in records:histories[r['team']].append(r)
    def volume(r):
        vals=[r.get(c) for c in ('attempts','sacks_suffered','carries')]
        return sum(vals) if all(x is not None for x in vals) else None
    vols=[volume(r) for r in records if volume(r) is not None]
    shares=[(r['attempts']+r['sacks_suffered'])/volume(r) for r in records if volume(r) is not None and volume(r)>0]
    league_volume=sum(vols)/len(vols) if vols else None
    league_share=sum(shares)/len(shares) if shares else None
    output={}
    for team,rating in ratings.items():
        history=histories[team];recent=history[-3:]
        vv=[volume(r) for r in history if volume(r) is not None]
        ss=[(r['attempts']+r['sacks_suffered'])/volume(r) for r in history if volume(r) is not None and volume(r)>0]
        output[team]={**rating,'recent_total_deviation':shrink(sum(r['points_for']+r['points_against'] for r in recent)/len(recent)-2*league,len(recent)),
                      'volume_deviation':shrink(sum(vv)/len(vv)-league_volume,len(vv)) if vv else None,
                      'pass_share_deviation':shrink(sum(ss)/len(ss)-league_share,len(ss)) if ss else None,
                      'volume_games':len(vv),'pass_share_games':len(ss)}
    return output,league


def features(teams,league,away,home,neutral,line):
    if away not in teams or home not in teams or min(teams[away]['games'],teams[home]['games'])<3:return None
    a,h=teams[away],teams[home]
    result={'league_total':2*league,'neutral_site':float(neutral),'market_total':line}
    for key in ('off_scoring','def_scoring','off_pass','off_rush','def_pass','def_rush'):
        name={'off_scoring':'off_score_sum','def_scoring':'def_score_sum'}.get(key,key+'_sum')
        result[name]=a[key]+h[key] if a[key] is not None and h[key] is not None else None
    for key in ('recent_total_deviation','volume_deviation','pass_share_deviation'):
        result[key]=(a[key]+h[key])/2 if a[key] is not None and h[key] is not None else None
    # Volume is a combined-team deviation, while shares and recent totals are averages.
    if result['volume_deviation'] is not None:result['volume_deviation']*=2
    return result


def feature_rows(schedule,feed,season):
    output=[]
    for week in range(5,19):
        teams,league=profiles(schedule,feed,season,week)
        for g in schedule:
            if g['season']!=str(season) or g['game_type']!='REG' or int(g['week'])!=week:continue
            line=number(g.get('total_line'))
            values=features(teams,league,g['away_team'],g['home_team'],g.get('location')=='Neutral',line)
            if values is not None:
                output.append({'game_id':g['game_id'],'season':season,'week':week,'features':values,
                               'history_away':teams[g['away_team']]['history_game_ids'],
                               'history_home':teams[g['home_team']]['history_game_ids']})
    return output


def labels(rows,schedule):
    games={g['game_id']:g for g in schedule};output=[]
    for r in rows:
        g=games[r['game_id']];a,h=number(g.get('away_score')),number(g.get('home_score'))
        if a is None or h is None or r['features']['market_total'] is None:continue
        output.append({**r,'actual_total':a+h,'over_label':None if abs(a+h-r['features']['market_total'])<1e-9 else int(a+h>r['features']['market_total'])})
    return output


def fit(rows,columns):
    usable=[r for r in rows if all(number(r['features'].get(c)) is not None for c in columns)]
    model=fit_linear([(r['features'],r['actual_total']) for r in usable],list(columns))
    model.update(version=VERSION,training_seasons=sorted({r['season'] for r in usable}),bias=0.0,sigma=None,
                 status='EXPERIMENTAL TOTALS — reliability not established')
    return model


def point_estimate(model,values):
    if any(number(values.get(c)) is None for c in model['columns']):return None
    contributions=[{'label':'Fitted total baseline','feature':'intercept','input':1,'points':model['coefficients'][0]},
                   {'label':'Prior-validation bias adjustment','feature':'validation_bias','input':1,'points':model.get('bias',0)}]
    for c,m,s,b in zip(model['columns'],model['means'],model['scales'],model['coefficients'][1:]):
        contributions.append({'label':LABELS[c],'feature':c,'input':values[c],'points':b*(values[c]-m)/s})
    return {'total':sum(r['points'] for r in contributions),'contributions':contributions}


def calibrate(model,validation):
    usable=[]
    for r in validation:
        p=point_estimate(model,r['features'])
        if p is not None:usable.append(r['actual_total']-p['total'])
    if len(usable)<75:raise ValueError('Need 75 validation games')
    bias=sum(usable)/len(usable)
    sigma=max(1.0,math.sqrt(sum((e-bias)**2 for e in usable)/len(usable)))
    return {**model,'bias':bias,'sigma':sigma,'calibration_seasons':sorted({r['season'] for r in validation}),
            'probability_assumption':'Continuous normal residual model; push mass unmodeled, nonpush grading only'}


def predict(model,values,line):
    result=point_estimate(model,values)
    if result is None or number(line) is None or not model.get('sigma'):return None
    p=.5*(1+math.erf((result['total']-line)/model['sigma']/math.sqrt(2)))
    return {**result,'line':line,'over_probability':p,'under_probability':1-p,
            'lean':'No Call' if abs(p-.5)<1e-12 else 'Over' if p>.5 else 'Under','plausible':result['total']>=0}


def calls(model,rows):
    output=[]
    for r in rows:
        p=predict(model,r['features'],r['features']['market_total'])
        if p is None:continue
        outcome='Push' if r['over_label'] is None else 'No Call' if p['lean']=='No Call' else 'Correct' if (p['lean']=='Over')==bool(r['over_label']) else 'Wrong'
        output.append({**r,**p,'result':outcome,'error':p['total']-r['actual_total']})
    return output


def summary(rows):
    binary=[r for r in rows if r['over_label'] is not None];w=sum(r['result']=='Correct' for r in rows);l=sum(r['result']=='Wrong' for r in rows)
    return {'games':len(rows),'wins':w,'losses':l,'pushes':sum(r['result']=='Push' for r in rows),
            'no_calls':sum(r['result']=='No Call' for r in rows),'accuracy':100*w/(w+l) if w+l else None,
            'mae':sum(abs(r['error']) for r in rows)/len(rows) if rows else None,
            'brier':sum((r['over_probability']-r['over_label'])**2 for r in binary)/len(binary) if binary else None,
            'mean_predicted_total':sum(r['total'] for r in rows)/len(rows) if rows else None}
