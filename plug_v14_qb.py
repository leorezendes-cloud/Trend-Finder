"""Frozen QB-history proxy for independent v14 market reconstruction."""
import csv
from collections import defaultdict
from pathlib import Path
import plug_v14_baseline as base
old=base

def read_qb_ids(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream);names=set(reader.fieldnames or ())
        needed={'game_id','away_qb_id','home_qb_id'}
        if not needed.issubset(names):
            raise RuntimeError('QB feature input missing: '+', '.join(sorted(needed-names)))
        return {r['game_id']:(r.get('away_qb_id','').strip(),r.get('home_qb_id','').strip()) for r in reader}

def attach_qb_ids(games,mapping):
    covered=0
    for game in games:
        a,h=mapping.get(game['id'],('',''))
        game['qb_away_id']=a;game['qb_home_id']=h
        if a and h:covered+=1
    n=len(games)
    if covered<0.70*n:raise RuntimeError(f'Historical QB coverage too low: {covered}/{n}')
    return {'historical_games':n,'both_qb_ids':covered,
            'historical_qb_id_coverage_pct':round(100*covered/n,2)}

def prior_qb_features(games):
    qb_past=defaultdict(list);team_qbs=defaultdict(list)
    previous=defaultdict(list);current=defaultdict(list)
    previous_league=44.0;season_totals=[];last_year=None
    output={};known_team_proxies=0;possible_team_proxies=0
    for season,week,block in old.season_week_blocks(games):
        if season!=last_year:
            if last_year is not None:
                previous=current
                if season_totals:previous_league=base.average(season_totals)
            current=defaultdict(list);season_totals=[];last_year=season
        league_total=(64.0*previous_league+sum(season_totals))/(64.0+len(season_totals))
        half=league_total/2.0;past_expectations={}
        for game in block:
            a_off,a_def,_=base.team_rates(game['away'],previous,current,half)
            h_off,h_def,_=base.team_rates(game['home'],previous,current,half)
            expected_a=(a_off+h_def)/2.0;expected_h=(h_off+a_def)/2.0
            past_expectations[game['id']]=(expected_a,expected_h)
            values=[]
            for team in (game['away'],game['home']):
                history=team_qbs[team]
                last_known=history[-1][2] if history else ''
                record=qb_past[last_known][-16:] if last_known else []
                n=len(record)
                off_effect=sum(x[0] for x in record)/(8.0+n)
                total_effect=sum(x[1] for x in record)/(12.0+n)
                recent=[qb for yr,wk,qb in history if yr==season and wk<week][-4:]
                prev=[qb for yr,wk,qb in history if yr==season-1][-4:]
                if recent:continuity=sum(qb==last_known for qb in recent)/len(recent)
                else:continuity=float(bool(prev and prev[-1]==last_known))
                observed_games=min(n,16)/16.0
                values.append((off_effect,total_effect,continuity,observed_games))
                if season>=2019:
                    possible_team_proxies+=1;known_team_proxies+=bool(last_known)
            output[game['id']]=[(values[0][0]+values[1][0])/10.0,
                               (values[0][1]+values[1][1])/12.0,
                               values[0][2]+values[1][2]-1.0,
                               values[0][3]+values[1][3]-1.0]
        for game in block:
            if not old.completed(game):continue
            a=game['a_score'];h=game['h_score']
            expected_a,expected_h=past_expectations[game['id']]
            total_residual=(a+h)-(expected_a+expected_h)
            for team,qb,scored,expected in (
                (game['away'],game['qb_away_id'],a,expected_a),
                (game['home'],game['qb_home_id'],h,expected_h)):
                if not qb:continue
                qb_past[qb].append((max(-21.0,min(21.0,scored-expected)),
                                    max(-28.0,min(28.0,total_residual))))
                team_qbs[team].append((season,week,qb))
            current[game['away']].append((a,h))
            current[game['home']].append((h,a))
            season_totals.append(a+h)
    coverage={'pregame_known_last_qb_teams':known_team_proxies,
              'pregame_candidate_teams':possible_team_proxies,
              'pregame_known_last_qb_pct':round(100*known_team_proxies/max(1,possible_team_proxies),2),
              'note':'Proxy is previous recorded QB, never verified target-game starting QB.'}
    return output,coverage

def _weighted_mean_recent(seq,index,decay=0.80,prior_strength=5.0):
    values=seq[-10:]
    weights=[decay**(len(values)-1-i) for i in range(len(values))]
    return sum(w*sample[index] for w,sample in zip(weights,values))/(prior_strength+sum(weights))

def v10_qb_features(games):
    qb_past=defaultdict(list);team_qbs=defaultdict(list)
    previous=defaultdict(list);current=defaultdict(list)
    previous_league=44.0;season_totals=[];last_year=None;out={};regime={}
    for season,week,block in old.season_week_blocks(games):
        if season!=last_year:
            if last_year is not None:
                previous=current
                if season_totals:previous_league=base.average(season_totals)
            current=defaultdict(list);season_totals=[];last_year=season
        league_total=(64.0*previous_league+sum(season_totals))/(64.0+len(season_totals))
        half=league_total/2.0;expected={}
        for g in block:
            a_off,a_def,_=base.team_rates(g['away'],previous,current,half)
            h_off,h_def,_=base.team_rates(g['home'],previous,current,half)
            expected[g['id']]=((a_off+h_def)/2.0,(h_off+a_def)/2.0)
            x=[];recent_switch=False;both_stable=True
            for team in (g['away'],g['home']):
                history=team_qbs[team]
                last=history[-1][2] if history else ''
                records=qb_past[last] if last else []
                off=_weighted_mean_recent(records,0,prior_strength=5.0)
                total=_weighted_mean_recent(records,1,prior_strength=7.0)
                past_three=[q for _,_,q in history[-3:]]
                team_stable=len(past_three)==3 and len(set(past_three))==1
                team_switched=len(past_three)>=2 and len(set(past_three))>1
                recent_switch|=team_switched;both_stable&=team_stable
                last_four=[q for _,_,q in history[-4:]]
                if last_four:
                    weights=[0.65**(len(last_four)-1-i) for i in range(len(last_four))]
                    cont=sum(w for w,q in zip(weights,last_four) if q==last)/sum(weights)
                else:cont=0.0
                experience=min(len(records),24)/24.0
                x.append((off,total,cont,experience))
            out[g['id']]=[(x[0][0]+x[1][0])/10.0,(x[0][1]+x[1][1])/12.0,
                          x[0][2]+x[1][2]-1.0,x[0][3]+x[1][3]-1.0]
            regime[g['id']]='recent_prior_qb_switch' if recent_switch else (
                'stable_prior_qbs' if both_stable else 'limited_prior_qb_history')
        for g in block:
            if not old.completed(g):continue
            a,h=g['a_score'],g['h_score'];exp_a,exp_h=expected[g['id']]
            total_resid=(a+h)-(exp_a+exp_h)
            for team,qb,scored,exp in (
                (g['away'],g['qb_away_id'],a,exp_a),
                (g['home'],g['qb_home_id'],h,exp_h)):
                if qb:
                    qb_past[qb].append((max(-21.,min(21.,scored-exp)),
                                         max(-28.,min(28.,total_resid))))
                    team_qbs[team].append((season,week,qb))
            current[g['away']].append((a,h));current[g['home']].append((h,a))
            season_totals.append(a+h)
    return out,regime
