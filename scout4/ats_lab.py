"""Symmetric spread-relative logistic regression research engine.

Predicts away ATS cover conditional on a nonpush. Inputs are prior-week football
ratings plus a saved away handicap. No outcome, starter identity or injury flag
enters a target game's features. Historical line availability is unverified.
"""
import math
from .margin_lab import build_features, COLUMNS, LABELS
from .ratings import solve
from .stats import number

VERSION = 'scout4-ats-1'
RIDGE = 8.0
MODEL_COLUMNS = {'Spread only':('away_handicap','venue_indicator'),
                 'Football + spread':tuple(COLUMNS)+('away_handicap',)}
TEMPERATURES = (0.5,1.0,2.0,4.0)
FEATURE_LABELS = {**LABELS,'away_handicap':'Saved away handicap'}


def feature_rows(schedule,feed,season):
    games={g['game_id']:g for g in schedule}
    rows=[]
    for row in build_features(schedule,feed,season):
        g=games[row['game_id']]
        line=number(g.get('spread_line'))
        if line is None:continue
        rows.append({**row,'features':{**row['features'],'away_handicap':line},
                     'away_team':g['away_team'],'home_team':g['home_team'],
                     'feature_cutoff_before_week':row['week'],
                     'status':'RETROSPECTIVE_REPLAY — original feature availability unverified'})
    return rows


def label_rows(rows,schedule):
    """Attach results separately after features have been constructed."""
    games={g['game_id']:g for g in schedule};result=[]
    for row in rows:
        g=games[row['game_id']];a,h=number(g.get('away_score')),number(g.get('home_score'))
        if a is None or h is None:continue
        ats=a-h+row['features']['away_handicap']
        result.append({**row,'actual_ats_margin':ats,'label':None if abs(ats)<1e-9 else int(ats>0)})
    return result


def sigmoid(z):
    if z>=0:return 1/(1+math.exp(-min(z,700)))
    e=math.exp(max(z,-700));return e/(1+e)


def fit(rows,columns):
    usable=[r for r in rows if r['label'] is not None]
    if len(usable)<150:raise ValueError('Need at least 150 nonpush training games')
    if {r['label'] for r in usable}!={0,1}:raise ValueError('Both cover classes are required')
    if any(any(number(r['features'].get(c)) is None for c in columns) for r in usable):
        raise ValueError('Missing or nonfinite training features')
    # Zero-centered odd features, no intercept: exchanging sides complements p.
    scales=[max(1e-6,math.sqrt(sum(r['features'][c]**2 for r in usable)/len(usable))) for c in columns]
    vectors=[[r['features'][c]/s for c,s in zip(columns,scales)] for r in usable]
    coefficients=[0.0]*len(columns)
    converged=False
    for iteration in range(50):
        gradient=[RIDGE*b for b in coefficients]
        hessian=[[RIDGE if i==j else 0.0 for j in range(len(columns))] for i in range(len(columns))]
        for row,v in zip(usable,vectors):
            p=sigmoid(sum(b*x for b,x in zip(coefficients,v)))
            for i,vi in enumerate(v):
                gradient[i]+=(p-row['label'])*vi
                for j,vj in enumerate(v):hessian[i][j]+=p*(1-p)*vi*vj
        step=solve(hessian,gradient)
        coefficients=[b-d for b,d in zip(coefficients,step)]
        if max(abs(d) for d in step)<1e-9:
            converged=True;break
    if not converged:raise ValueError('Logistic fitting did not converge')
    return {'version':VERSION,'columns':list(columns),'scales':scales,'coefficients':coefficients,
            'intercept':0.0,'temperature':1.0,'ridge':RIDGE,'training_games':len(usable),
            'training_seasons':sorted({r['season'] for r in usable}), 'iterations':iteration+1,
            'probability_definition':'Away ATS cover conditional on nonpush',
            'status':'EXPERIMENTAL — probability reliability not established'}


def predict(model,values):
    temperature=model.get('temperature',1.0)
    if number(temperature) is None or temperature<=0:raise ValueError('Temperature must be positive')
    contributions=[]
    for c,s,b in zip(model['columns'],model['scales'],model['coefficients']):
        if number(values.get(c)) is None:return None
        contributions.append({'feature':c,'label':FEATURE_LABELS[c],'input':values[c],
                              'log_odds':b*values[c]/s/temperature})
    logit=sum(r['log_odds'] for r in contributions)
    return {'probability':sigmoid(logit),'log_odds':logit,'contributions':contributions,
            'status':model['status']}


def predictions(model,rows):
    result=[]
    for row in rows:
        p=predict(model,row['features'])
        if p is None:continue
        chosen=None if abs(p['probability']-.5)<1e-12 else int(p['probability']>.5)
        outcome=('Push' if row['label'] is None else 'No Call' if chosen is None else
                 'Correct' if chosen==row['label'] else 'Wrong')
        result.append({**row,**p,'selected_side':None if chosen is None else row['away_team'] if chosen else row['home_team'],
                       'ats_result':outcome})
    return result


def metrics(rows):
    usable=[r for r in rows if r['label'] is not None]
    w=sum(r['ats_result']=='Correct' for r in rows);l=sum(r['ats_result']=='Wrong' for r in rows)
    confidence=[r for r in usable if abs(r['probability']-.5)>=.05]
    bins=[]
    for low,high in ((0,.45),(.45,.5),(.5,.55),(.55,1.0000001)):
        group=[r for r in usable if low<=r['probability']<high]
        bins.append({'low':low,'high':min(high,1),'n':len(group),
                     'mean_probability':sum(r['probability'] for r in group)/len(group) if group else None,
                     'observed_away_cover':sum(r['label'] for r in group)/len(group) if group else None})
    return {'games':len(rows),'nonpush_games':len(usable),'wins':w,'losses':l,
            'pushes':sum(r['label'] is None for r in rows),'no_calls':sum(r['ats_result']=='No Call' for r in rows),
            'ats_pct':100*w/(w+l) if w+l else None,
            'brier':sum((r['probability']-r['label'])**2 for r in usable)/len(usable) if usable else None,
            'log_loss':-sum(r['label']*math.log(max(1e-15,r['probability']))+(1-r['label'])*math.log(max(1e-15,1-r['probability'])) for r in usable)/len(usable) if usable else None,
            'confidence_sample':len(confidence),'confidence_wins':sum(r['ats_result']=='Correct' for r in confidence),
            'confidence_ats_pct':100*sum(r['ats_result']=='Correct' for r in confidence)/len(confidence) if confidence else None,
            'reliability_bins':bins}


def choose_temperature(model,validation):
    if not any(r['label'] is not None for r in validation):raise ValueError('Empty calibration sample')
    options=[]
    for temperature in TEMPERATURES:
        trial={**model,'temperature':temperature}
        options.append((metrics(predictions(trial,validation))['brier'],temperature))
    _,selected=min(options,key=lambda x:(x[0],abs(math.log(x[1]))))
    return {**model,'temperature':selected,'calibration_seasons':sorted({r['season'] for r in validation}),
            'calibration_trials':[{'temperature':t,'brier':b} for b,t in options]}


def constant_baseline(rows):
    return [{**r,'probability':.5,'ats_result':'Push' if r['label'] is None else 'No Call'} for r in rows]
