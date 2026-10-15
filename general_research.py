"""General historical NFL research: one matchup per game, explicit team contexts."""
import csv
import math
from flask import abort, render_template, request, url_for
from trend_finder_2 import CSV_FILTER_FIELDS, matches_csv_filters, get_csv_filter_options, game_file
from pregame_lines import effective_rows
from saved_trends import manual_trend_title
from trend_filter_groups import GROUP_OPTIONS, matches_group

SPREADS = {'':'All spreads', 'pickem':'Pick’em', 'short':'Up to 3 points', 'medium':'Over 3 through 7 points', 'large':'Over 7 through 10 points', 'double':'Over 10 points'}


def spread_matches(value, band):
    if not band:return True
    if value is None:return False
    value=abs(value)
    return {'pickem':value==0,'short':0<value<=3,'medium':3<value<=7,'large':7<value<=10,'double':value>10}[band]


ROLES = {'all':'Any role', 'home':'Home', 'away':'Away', 'favorite':'Favorite', 'underdog':'Underdog'}


def finite(value):
    try:value = float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) else None


def counter(label):
    return {'label':label,'games':0,'wins':0,'losses':0,'ties':0,'covers':0,'ats_losses':0,'pushes':0,'ats_missing':0}


def add_record(record, margin, edge):
    record['games'] += 1
    record['wins' if margin>0 else 'losses' if margin<0 else 'ties'] += 1
    record['ats_missing' if edge is None else 'covers' if edge>0 else 'ats_losses' if edge<0 else 'pushes'] += 1


def research_games(rows, *, season=None, filters=None, team='', role='all', primetime='', location='', spread_size=''):
    if role not in ROLES or primetime not in ('','yes','no'):raise ValueError('Invalid research role or time')
    if location not in ('','home','away') or spread_size not in SPREADS:raise ValueError('Invalid location or spread band')
    records={key:counter(label) for key,label in [('home','Home teams'),('away','Away teams'),('favorite','Favorites'),('underdog','Underdogs')]}
    if team:records['selected']=counter(team+' — '+ROLES[role])
    totals={'over':0,'under':0,'push':0,'missing':0};matches=[];pickems=0;missing_lines=0
    for g in rows:
        year=int(g['season'])
        if season is not None and (not season[0]<=year<=season[1] if isinstance(season,tuple) else year!=int(season)):continue
        if not matches_csv_filters(g,filters or {}):continue
        away,home=finite(g.get('away_score')),finite(g.get('home_score'))
        if away is None or home is None:continue
        if primetime:
            clock=g.get('gametime','')
            if not clock:continue
            if (clock>='19:00') != (primetime=='yes'):continue
        spread=finite(g.get('spread_line'));total_line=finite(g.get('total_line'))
        dog='away' if spread is not None and spread>0 else 'home' if spread is not None and spread<0 else None
        favorite='home' if dog=='away' else 'away' if dog=='home' else None
        selected='away' if team and g.get('away_team')==team else 'home' if team and g.get('home_team')==team else None
        if team and selected is None:continue
        if role in ('home','away') and team and selected!=role:continue
        if role in ('underdog','favorite'):
            subject=dog if role=='underdog' else favorite
            if subject is None or (team and subject!=selected):continue
        subject=selected or (dog if role=='underdog' else favorite if role=='favorite' else None)
        if location and subject and subject!=location:continue
        if location and role in ('favorite','underdog') and subject is None:continue
        if not spread_matches(spread,spread_size):continue
        away_margin=away-home;away_edge=None if spread is None else away_margin+spread
        add_record(records['away'],away_margin,away_edge)
        add_record(records['home'],-away_margin,None if away_edge is None else -away_edge)
        for key,side in [('favorite',favorite),('underdog',dog),('selected',selected)]:
            if side is not None and key in records:
                sign=1 if side=='away' else -1
                add_record(records[key],sign*away_margin,None if away_edge is None else sign*away_edge)
        if spread is None:missing_lines+=1
        elif spread==0:pickems+=1
        if total_line is None:totals['missing']+=1;total_result='Unavailable'
        else:
            difference=away+home-total_line;kind='over' if difference>0 else 'under' if difference<0 else 'push'
            totals[kind]+=1;total_result=kind.title()
        matches.append({**g,'away_score':away,'home_score':home,'spread':spread,'total':total_line,'total_result':total_result,
                        'away_ats':('Unavailable' if away_edge is None else 'Cover' if away_edge>0 else 'Loss' if away_edge<0 else 'Push'),
                        'home_ats':('Unavailable' if away_edge is None else 'Cover' if away_edge<0 else 'Loss' if away_edge>0 else 'Push'),
                        'dog_side':dog,'favorite_side':favorite,'selected_side':selected,
                        'favorite':g[favorite+'_team'] if favorite else None,'underdog':g[dog+'_team'] if dog else None})
    for record in records.values():
        decisions=record['covers']+record['ats_losses'];su=record['wins']+record['losses']
        record['ats_rate']=100*record['covers']/decisions if decisions else None
        record['su_rate']=100*record['wins']/su if su else None
    matches.sort(key=lambda g:(g.get('gameday',''),g.get('gametime',''),g['game_id']),reverse=True)
    return {'games':len(matches),'records':([records['selected']] if team else [])+[v for k,v in records.items() if k!='selected'],'totals':totals,'pickems':pickems,'missing_lines':missing_lines,'matches':matches}


def find_combinations(rows, *, team='', role='all', minimum=10, limit=30):
    """Bounded three-feature discovery; evaluate both team sides and totals."""
    memberships={}
    for i,g in enumerate(rows):
        features=[]
        for field in ('game_type','home_team','away_team','roof','surface',
                      'home_coach','away_coach','home_qb_name','away_qb_name','referee'):
            if g.get(field):features.append((field,g[field]))
        for field in ('gametime','temp','wind'):
            features.extend((field,value) for value in GROUP_OPTIONS[field] if matches_group(g,field,value))
        for feature in features:memberships.setdefault(feature,set()).add(i)
    features=sorted(f for f,ids in memberships.items() if len(ids)>=minimum)
    evaluated={};beam=[((),set(range(len(rows))))]
    for depth in range(1,4):
        candidates=[]
        for conditions,ids in beam:
            for feature in features:
                if conditions and feature<=conditions[-1]:continue
                if any(f[0]==feature[0] for f in conditions):continue
                subset=ids & memberships[feature]
                if len(subset)<minimum:continue
                key=conditions+(feature,)
                report=research_games([rows[i] for i in sorted(subset)],team=team,role=role)
                records=report['records'][:1] if team else report['records']
                if not team and role!='all':
                    label={'home':'Home teams','away':'Away teams','favorite':'Favorites','underdog':'Underdogs'}[role]
                    records=[record for record in records if record['label']==label]
                metrics=[(v['label']+' ATS',v['covers'],v['ats_losses'],v['pushes']) for v in records]
                totals=report['totals']
                metrics += [('Over',totals['over'],totals['under'],totals['push']),('Under',totals['under'],totals['over'],totals['push'])]
                best=None
                for label,wins,losses,pushes in metrics:
                    n=wins+losses
                    if n<minimum or wins/n<.55:continue
                    # Wilson lower bound avoids ranking tiny perfect samples first.
                    rate=wins/n;z=1.96
                    lower=(rate+z*z/(2*n)-z*((rate*(1-rate)+z*z/(4*n))/n)**.5)/(1+z*z/n)
                    candidate={'conditions':dict(key),'label':label,'wins':wins,'losses':losses,'pushes':pushes,
                               'rate':100*rate,'sample':len(subset),'score':lower,'membership':tuple(sorted(subset))}
                    if best is None or lower>best['score']:best=candidate
                score=best['score'] if best else 0
                candidates.append((score,len(subset),key,subset))
                if best:evaluated[key]=best
        candidates.sort(key=lambda v:(v[0],v[1],v[2]),reverse=True)
        beam=[(key,ids) for _,_,key,ids in candidates[:40]]
    unique={}
    for trend in sorted(evaluated.values(),key=lambda v:(len(v['conditions']),tuple(v['conditions'].items()))):
        unique.setdefault((trend['label'],trend['membership']),trend)
    return sorted(unique.values(),key=lambda v:(v['score'],v['sample']),reverse=True)[:limit]


def render_general(form, games_page=False):
    form=dict(form)
    if form.get('research_role') in ('home','away') and not form.get('research_location'):
        form['research_location']=form['research_role'];form['research_role']='all'
    with open(game_file,newline='') as source:rows=list(effective_rows(csv.DictReader(source),game_file))
    options=get_csv_filter_options()
    for field in ('gametime','temp','wind'):options[field]=list(GROUP_OPTIONS[field])
    years=sorted({int(g['season']) for g in rows},reverse=True)
    teams=sorted({g[key] for g in rows for key in ('away_team','home_team') if g.get(key)})
    location=form.get('research_location','');spread_size=form.get('spread_size','')
    if location not in ('','home','away') or spread_size not in SPREADS:abort(400,description='Choose a valid location and spread range.')
    role=form.get('research_role','all');team=form.get('research_team','');prime=form.get('primetime','')
    if role not in ROLES or team and team not in teams or prime not in ('','yes','no'):abort(400,description='Choose a valid team, role and time filter.')
    mode=form.get('season_mode','single')
    if mode not in ('single','range'):abort(400,description='Choose a valid season mode.')
    season=None;filters={}
    try:
        if mode=='single' and form.get('season'):
            season=int(form['season'])
            if season not in years:raise ValueError
        elif mode=='range':
            low=int(form.get('start_season') or min(years));high=int(form.get('end_season') or max(years))
            if low not in years or high not in years or low>high:raise ValueError
            season=(low,high)
    except (ValueError,TypeError):abort(400,description='Choose a valid season or season range.')
    primary=('game_type','gametime','temp','wind','roof','qb_name')
    allowed=[f for f in CSV_FILTER_FIELDS if f not in ('dog_coast','game_id')]
    for field in allowed:
        value=form.get(field,'').strip()
        if value:
            if value not in options[field]:abort(400,description='Choose a listed value for '+field.replace('_',' ')+'.')
            filters[field]=value
    analyze=request.method=='POST' or form.get('run')=='analyze'
    report=research_games(rows,season=season,filters=filters,team=team,role=role,primetime=prime,location=location,spread_size=spread_size) if analyze else None
    combinations=None
    if analyze and form.get('action')=='combinations':
        combinations=find_combinations(report['matches'],team=team,role=location if not team and role=='all' and location else role)
    try:page=max(1,int(form.get('page',1)))
    except ValueError:abort(400,description='Invalid results page.')
    pages=max(1,(report['games']+99)//100) if report else 1;page=min(page,pages)
    selection={k:v for k,v in form.items() if v and k not in ('page','run','action','csrf_token','combination_conditions','game_id','evidence','evidence_metric')}
    selection.update(research_view='general',run='analyze')
    for trend in combinations or []:
        params={**selection,**trend['conditions']}
        trend['url']=url_for('trend_finder',**params,_anchor='matching-games')
        trend['evidence_url']=url_for('trend_finder',**params,evidence='1',evidence_metric=trend['label'])
    filter_chips=[]
    chip_scope={**selection,'action':'combinations' if combinations is not None else 'analyze'}
    def chip(label,fields):
        remaining={key:value for key,value in chip_scope.items() if key not in fields}
        filter_chips.append({'label':label,'url':url_for('trend_finder',**remaining,_anchor='research-results')})
    if mode=='range' and season:
        chip(f'Seasons {season[0]}–{season[1]}',('season_mode','season','start_season','end_season'))
    elif season is not None:
        chip(f'Season {season}',('season',))
    if team:chip('Team: '+team,('research_team',))
    if role!='all':chip('Role: '+ROLES[role],('research_role',))
    if location:chip('Location: '+location.title(),('research_location',))
    if prime:chip('Primetime' if prime=='yes' else 'Non-primetime',('primetime',))
    if spread_size:chip('Spread: '+SPREADS[spread_size],('spread_size',))
    labels={'game_type':'Season stage','gametime':'Kickoff','temp':'Temperature','wind':'Wind','qb_name':'QB'}
    stages={'REG':'Regular Season','WC':'Wild Card','DIV':'Divisional Playoffs','CON':'Conference Championship','SB':'Super Bowl'}
    for field,value in filters.items():
        display=stages.get(value,value) if field=='game_type' else value
        chip(labels.get(field,field.replace('_',' ').title().replace('Qb','QB'))+': '+display,(field,))
    target=url_for('trend_finder',**selection)
    page_url=lambda number:url_for('general_trend_games' if games_page else 'trend_finder',**selection,page=number,evidence='1' if form.get('evidence')=='1' else None,evidence_metric=form.get('evidence_metric') or None,_anchor=None if form.get('evidence')=='1' else 'matching-games')
    if form.get('evidence')=='1':
        if report is None:abort(400)
        return render_template('_general_games.html',games=report['matches'][:10],total=report['games'],page=1,pages=1,page_url=page_url,evidence_metric=form.get('evidence_metric',''),preview=True,all_games_url=url_for('general_trend_games',**selection,evidence_metric=form.get('evidence_metric') or None))
    if games_page:
        return render_template('general_trend_games.html',games=report['matches'][(page-1)*100:page*100],total=report['games'],page=page,pages=pages,page_url=page_url,evidence_metric=form.get('evidence_metric',''),filter_chips=filter_chips,back_url=target)
    return render_template('general_trends.html',options=options,years=years,teams=teams,roles={key:ROLES[key] for key in ('all','favorite','underdog')},form=form,
        filter_chips=filter_chips,spreads=SPREADS,combinations=combinations,primary=primary,advanced=[f for f in allowed if f not in primary and f!='spread_line'],report=report,
        games=report['matches'][(page-1)*100:page*100] if report else [],page=page,pages=pages,page_url=page_url,
        has_advanced=any(form.get(f) for f in allowed if f not in primary),
        manual_search_url=target,manual_search_title=manual_trend_title(target))
