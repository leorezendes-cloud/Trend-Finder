"""Pregame matchup measurements. No Scout/Plug imports, weights, odds or publications."""
from collections import defaultdict
from datetime import datetime
from .store import history, team

GAPS = ['receiver_X_Z_slot_alignment','individual_defender_assignment','yards_per_route_run',
        'current_blitz_rate']

def mean(values, default=0.):
    values=list(values)
    return sum(values)/len(values) if values else default

def rate(rows,num,den,prior=40.,center=0.):
    observed=[r for r in rows if r['values'].get(num) is not None and r['values'].get(den) is not None]
    n=sum(r['values'][den] for r in observed)
    return {'value':(sum(r['values'][num] for r in observed)+prior*center)/(n+prior) if n+prior else center,
            'exposure':n,'games':len(observed),'missing_games':len(rows)-len(observed)}

def build(db, away, home, cutoff, *, mode='observed'):
    rows=list(history(db,cutoff,mode=mode))
    trows=[r for r in rows if r['kind']=='team'];players=[r for r in rows if r['kind']=='player']
    pbp=[r for r in rows if r['kind']=='pbp' and not r['pid']]
    league_points=mean((r['points'] for r in trows),default=22.)
    by=defaultdict(list);defense=defaultdict(list)
    for r in trows:by[r['team']].append(r);defense[r['opponent']].append(r)
    def point_strength(t):
        own=by[t];allowed=defense[t]
        return ((sum(r['points'] for r in own)+4*league_points)/(len(own)+4),
                (sum(r['points'] for r in allowed)+4*league_points)/(len(allowed)+4))
    def profile(t,o):
        own=by[t];against=defense[o]
        out={'team':t,'opponent':o,'games':len(own),'opponent_games':len(against)}
        for name,num,den in [('pass','passing_epa','attempts'),('rush','rushing_epa','carries')]:
            center=rate(trows,num,den,prior=0,center=0)['value'] if trows else 0.
            attack=rate(own,num,den,center=center);allow=rate(against,num,den,center=center)
            # Remove opposing unit quality measured only from earlier observations.
            attack_res=[];def_res=[]
            for r in own:
                v=r['values'];n=v.get(den);val=v.get(num)
                if n and val is not None:
                    opp=rate(defense[r['opponent']],num,den,center=center)['value']
                    attack_res.append((val-n*opp,n))
            for r in against:
                v=r['values'];n=v.get(den);val=v.get(num)
                if n and val is not None:
                    opp=rate(by[r['team']],num,den,center=center)['value']
                    def_res.append((val-n*opp,n))
            adj_a=sum(a for a,n in attack_res)/(40+sum(n for a,n in attack_res))
            adj_d=sum(a for a,n in def_res)/(40+sum(n for a,n in def_res))
            recent=rate(own[-3:],num,den,center=center)
            out[name]={'offense':attack,'defense_allowed':allow,'opponent_adjusted_attack':adj_a,
                       'opponent_adjusted_allowed':adj_d,'matchup':adj_a+adj_d,
                       'recent_delta':recent['value']-attack['value']}
        attempts=sum(r['values'].get('attempts') or 0 for r in own)
        runs=sum(r['values'].get('carries') or 0 for r in own)
        out['pass_share']=(attempts+20)/(attempts+runs+40)
        ownpb=[r for r in pbp if r['team']==t];opppb=[r for r in pbp if r['opponent']==o]
        out['neutral_pass_epa']=rate(ownpb,'pass_epa','dropbacks')
        out['neutral_rush_epa']=rate(ownpb,'rush_epa','runs')
        out['protection_sack_rate']=rate(ownpb,'sacks','dropbacks',center=.06)
        out['opponent_sack_rate']=rate(opppb,'sacks','dropbacks',center=.06)
        out['opponent_hit_rate']=rate(opppb,'hits','dropbacks',center=.1)
        out['hit_epa_response_proxy']=rate(ownpb,'hit_epa','hit_dropbacks',prior=20)
        out['neutral_cpoe']=rate(ownpb,'cpoe_sum','cpoe_n',prior=50)
        chart=[r for r in rows if r['kind']=='charting' and not r['pid']]
        ownchart=[r for r in chart if r['team']==t];oppchart=[r for r in chart if r['opponent']==o]
        out['verified_pressure_response']=rate(ownchart,'pressure_epa','pressure_n',prior=20)
        out['opponent_five_plus_rusher_rate']=rate(oppchart,'five_plus_rushers','rushers_known',prior=40)
        out['opponent_man_rate']=rate(oppchart,'man_n','coverage_known',prior=40)
        out['scheme_note']='Historical charting only when provider fields and pregame availability permit. Five-plus rushers is not a verified blitz label.'
        out['positions']={};out['players']=[]
        for pos in ('WR','TE','RB','QB'):
            ownp=[r for r in players if r['team']==t and r['position']==pos]
            oppp=[r for r in players if r['opponent']==o and r['position']==pos]
            allp=[r for r in players if r['position']==pos]
            # Normalize by defense games, not count of receivers faced.
            center=sum(r['values'].get('receiving_yards') or 0 for r in allp)/max(1,len(trows))
            allowed=(sum(r['values'].get('receiving_yards') or 0 for r in oppp)+4*center)/(len(against)+4)
            offense=(sum(r['values'].get('receiving_yards') or 0 for r in ownp)+4*center)/(len(own)+4)
            out['positions'][pos]={'receiving_yards_allowed_per_game':allowed,'receiving_yards_per_game':offense,
                                   'allowed_relative_to_league':allowed-center,'opponent_games':len(against)}
        # Candidates come from history only. Same ID can transfer; latest team determines membership.
        latest={};byplayer=defaultdict(list)
        for r in players:
            latest[r['pid']]=r
            if r['team']==t:byplayer[r['pid']].append(r)
        ids={r['pid'] for r in players if r['team']==t and latest[r['pid']]['team']==t}
        targets=sum(r['values'].get('targets') or 0 for r in players if r['team']==t)
        for pid in sorted(ids):
            rr=byplayer[pid];last=rr[-1]
            metrics={k:mean(r['values'][k] for r in rr[-4:] if r['values'].get(k) is not None) for k in ('passing_yards','rushing_yards','receiving_yards','targets','receptions')}
            out['players'].append(dict(player_id=pid,name=last['name'],position=last['position'],games=len(rr),
                recent=metrics,receiving_yards_per_target=rate(rr,'receiving_yards','targets',prior=20),
                catch_rate=rate(rr,'receptions','targets',prior=20),passing_epa_per_attempt=rate(rr,'passing_epa','attempts',prior=40),target_share=sum(r['values'].get('targets') or 0 for r in rr)/max(1,targets),
                availability='unknown; prior participation is not an injury report',
                hit_epa_response_proxy=rate([r for r in rows if r['kind']=='pbp' and r['pid']==pid],'hit_epa','hit_dropbacks',prior=20) if last['position']=='QB' else None,
                verified_pressure_response=rate([r for r in rows if r['kind']=='charting' and r['pid']==pid],'pressure_epa','pressure_n',prior=20) if last['position']=='QB' else None))
        return out
    a,h=team(away),team(home);ap,ad=point_strength(a);hp,hd=point_strength(h)
    profiles=[profile(a,h),profile(h,a)]
    return {'policy':'player-scheme-v1','cutoff':cutoff,'availability_mode':mode,
            'historical_publication_verified':False,'capture_timestamp_gate_enforced':mode=='observed','gaps':GAPS,
            'baseline':{'away_points':(ap+hd)/2,'home_points':(hp+ad)/2},'teams':profiles,
            'last_input_kickoff':max((r['kickoff'] for r in rows),default=None)}

def vector(features):
    a,h=features['teams']
    # Fixed before evaluation. Ridge learns coefficients only from prior target games.
    def side(p):return [p['pass']['matchup'],p['rush']['matchup'],p['pass']['recent_delta'],
                        p['positions']['TE']['allowed_relative_to_league']/100]
    return side(a)+side(h)
