"""Versioned scoring margins with separate immutable research components.

Scout scoring margin is distinct from the probability-only frozen ATS model.
No descriptive historical ranking, injury or weather bonus enters this blend.
"""
import argparse,hashlib,json,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .web import ROOT
from .stats import read_csv,eligible,number
from .ratings import build_ratings,matchup
from .totals import profiles,features,predict
from .shadow import kickoff,quote,load_stats,statistics_gate,seal,aware

CORE=('scout4/research_benchmarks.py','scout4/blend.py','scout4/ratings.py','scout4/totals.py','scout4/stats.py','scout4/shadow.py')


def combine(scout_margin,plug_margin,line,weights=None):
    values=[number(v) for v in (scout_margin,plug_margin,line)]
    if any(v is None for v in values):raise ValueError('Both finite scoring margins and a shared line are required')
    if weights is None:weights = {'scout_scoring':.5,'plug_points_only':.5}
    if not isinstance(weights,dict):raise ValueError('Forecast weights must be an object')
    scoring, points = number(weights.get('scout_scoring')), number(weights.get('plug_points_only'))
    if scoring is None or points is None or min(scoring, points)<0 or abs(scoring+points-1)>1e-9:
        raise ValueError('Forecast weights must be finite, nonnegative and sum to one')
    margin=scoring*values[0]+points*values[1]
    edge=margin+values[2]
    return {'away_margin':margin,'ats_edge':edge,'side':None if abs(edge)<1e-9 else 'away' if edge>0 else 'home'}


def plug_ats_pick(decision,game,line,always_pick=False):
    side=decision['side']
    if side is None and always_pick:side='away' if line>0 else 'home'
    return game[side+'_team'] if side else None


def plug_total_pick(prediction,always_pick=False):
    result=dict(prediction)
    if always_pick and result.get('lean')=='No Call':
        result.update(lean='Under',tie_break='Exact model tie: Under')
    return result


def plug_prediction(schedule,game):
    """Preserve Plug PF/PA rounding and points-only formula on earlier weeks."""
    output={};history={}
    for side in ('away','home'):
        team=game[side+'_team'];rows=[]
        for g in schedule:
            if not eligible(g,int(game['season']),int(game['week'])):continue
            if team==g['away_team']:rows.append((g['game_id'],float(g['away_score']),float(g['home_score'])))
            elif team==g['home_team']:rows.append((g['game_id'],float(g['home_score']),float(g['away_score'])))
        if len(rows)<3:return None
        output[side]={'games':len(rows),'pf':round(sum(r[1] for r in rows)/len(rows),1),'pa':round(sum(r[2] for r in rows)/len(rows),1)}
        history[side]=[r[0] for r in rows]
    a,h=output['away'],output['home']
    away=round((a['pf']+h['pa'])/2,1);home=round((h['pf']+a['pa'])/2,1)
    return {'away_points':away,'home_points':home,'away_margin':round(away-home,1),'history':history,'inputs':output}


def configuration(root):
    base=root/'data/scout4/blend';path=Path(os.environ['TREND_FINDAH_AUTO_MODEL_CONFIG']) if os.environ.get('TREND_FINDAH_AUTO_MODEL_CONFIG') else base/'config.json'
    if path.exists():config=json.loads(path.read_text())
    else:
        pointer=json.loads((root/'data/scout4/ratings_latest.json').read_text())
        for p,h in pointer['source_sha256'].items():
            if p.startswith('scout4/') and hashlib.sha256((root/p).read_bytes()).hexdigest()!=h:raise ValueError('Scoring model source changed')
        scores=json.loads((root/pointer['models_path']).read_text())['Scoring + matchup EPA']
        old=json.loads((root/'data/scout4/shadow/config.json').read_text())
        total_path=Path(old['totals_path']);total_path=total_path if total_path.is_absolute() else root/total_path
        if hashlib.sha256(total_path.read_bytes()).hexdigest()!=old['totals_sha256']:raise ValueError('Frozen totals model changed')
        config={'version':'scout4-plug-margin-blend-1','created_at':datetime.now(timezone.utc).isoformat(),
                'weights':{'scout_scoring':.5,'plug_points_only':.5},'score_model':scores,
                'totals_candidate':json.loads(total_path.read_text()),
                'score_model_file_sha256':hashlib.sha256((root/pointer['models_path']).read_bytes()).hexdigest(),
                'totals_model_file_sha256':old['totals_sha256'],
                'code_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in CORE},
                'policy':'First eligible capture per game; identical cutoff, inputs and quote for all components. Totals use Scout only.'}
        base.mkdir(parents=True,exist_ok=True)
        with path.open('x') as f:json.dump(config,f,indent=2)
    for p,h in config['code_sha256'].items():
        if hashlib.sha256((root/p).read_bytes()).hexdigest()!=h:raise ValueError('Blend pipeline changed; a new version is required')
    return config,hashlib.sha256(path.read_bytes()).hexdigest()


def run(root=ROOT,now=None):
    now=now or datetime.now(timezone.utc);config,model_hash=configuration(root)
    base=root/'data/scout4/blend';stamp=now.strftime('%Y%m%dT%H%M%S%fZ');folder=base/'inputs'/stamp;folder.mkdir(parents=True,exist_ok=False)
    for filename in ('nfl_games.csv','public_money_snapshots.csv'):(folder/filename).write_bytes((root/filename).read_bytes())
    schedule=read_csv(folder/'nfl_games.csv');quotes=read_csv(folder/'public_money_snapshots.csv');cache={};saved=preserved=0;pending=[]
    for g in schedule:
        if g['game_type']!='REG' or not g.get('gameday') or not g.get('gametime'):continue
        ko=kickoff(g)
        if not 0<(ko-now).total_seconds()<=7*86400:continue
        path=base/'predictions'/(g['game_id']+'.json')
        if path.exists():preserved+=1;continue
        year,week=int(g['season']),int(g['week'])
        try:
            if year not in cache:cache[year]=load_stats(root,year)
            feed,manifest=cache[year];block=statistics_gate(schedule,feed,manifest,year,week,now)
            if block:raise ValueError(block)
            q=quote(quotes,g,'Spread',now)
            if q is None:raise ValueError('No fresh verified spread quote')
            ratings,_=build_ratings(schedule,feed,year,week)
            scout=matchup(config['score_model'],ratings,g['away_team'],g['home_team'],'Neutral' if g.get('location')=='Neutral' else 'Away')
            plug=plug_prediction(schedule,g)
            if not scout or not plug or not scout['first_estimate']['plausible'] or not scout['second_estimate']['plausible']:raise ValueError('Missing or implausible component estimates')
            combined=combine(scout['margin_first'],plug['away_margin'],q['line'],config['weights'])
            components={}
            for name,margin in [('Scout scoring',scout['margin_first']),('The Plug',plug['away_margin']),('Blend',combined['away_margin'])]:
                decision=combine(margin,margin,q['line'])
                components[name]={'away_margin':margin,'ats_edge':decision['ats_edge'],'pick':plug_ats_pick(decision,g,q['line'],config.get('always_pick',False) and name=='Blend')}
                if name=='Blend' and config.get('always_pick') and decision['side'] is None:components[name]['tie_break']='Exact model tie: underdog, or home at pick’em'
            benchmarks = {}
            if config.get('research_benchmarks'):
                from .research_benchmarks import recent_epa
                old = combine(scout['margin_first'],plug['away_margin'],q['line'])
                benchmarks['Previous 50/50'] = {**old, 'pick':plug_ats_pick(old,g,q['line'],True),
                                               'version':'equal-scoring-points-1'}
                try:epa = recent_epa(schedule,feed,g)
                except (ValueError,TypeError,KeyError):epa = None
                if epa is None:
                    benchmarks['EPA Recent Form'] = {'pick':None,'status':'Insufficient prior matched EPA rows'}
                else:
                    direction = combine(epa['away_margin'],epa['away_margin'],q['line'])
                    benchmarks['EPA Recent Form'] = {**epa,'ats_edge':direction['ats_edge'],
                                                     'pick':plug_ats_pick(direction,g,q['line'],True)}
            tq=quote(quotes,g,'Total',now);total=None
            if tq:
                teams,league=profiles(schedule,feed,year,week);values=features(teams,league,g['away_team'],g['home_team'],g.get('location')=='Neutral',tq['line'])
                if values:total=predict(config['totals_candidate']['model'],values,tq['line'])
                if total is not None:total={'quote':tq,'prediction':plug_total_pick(total,config.get('always_pick',False)),'features':values,'model':'Scout totals only; not blended'}
            record={'game_id':g['game_id'],'away_team':g['away_team'],'home_team':g['home_team'],'season':year,'week':week,
                    'kickoff_utc':ko.isoformat(),'decision_cutoff_utc':now.isoformat(),'version':config['version'],
                    'configuration_sha256':model_hash,'weights':config['weights'],
                    'published_formula':config.get('published_formula','Equal scoring/points blend'),
                    'research_benchmarks':benchmarks,'quote':q,'components':components,
                    'scout_scoring':scout,'plug_points_only':plug,'totals':total,'stats_manifest':manifest,
                    'input_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()},
                    'limitations':['Experimental forecast weights; no validated probability or confidence.',
                                   'Scout scoring component is not the separate frozen ATS probability model.',
                                   'No injury, confirmed QB replacement or weather adjustments.']}
            if seal(path,record):saved+=1
        except (ValueError,OSError) as exc:pending.append({'game_id':g['game_id'],'reason':str(exc)})
    status={'checked_at':now.isoformat(),'saved':saved,'preserved':preserved,'pending':pending}
    (base/'status.json').write_text(json.dumps(status,indent=2));return status


def grade_components(record,game):
    if not game or any(record.get(k)!=game.get(k) for k in ('game_id','away_team','home_team')):raise ValueError('Outcome identity mismatch')
    a,h=number(game.get('away_score')),number(game.get('home_score'));result={}
    actual=None if a is None or h is None else a-h+record['quote']['line']
    for name,r in record['components'].items():
        result[name]='Pending' if actual is None else 'Push' if abs(actual)<1e-9 else 'No Call' if r['pick'] is None else 'Win' if r['pick']==(record['away_team'] if actual>0 else record['home_team']) else 'Loss'
    return result


def view(root=ROOT):
    games={g['game_id']:g for g in read_csv(root/'nfl_games.csv')};records=[]
    for path in (root/'data/scout4/blend/predictions').glob('*.json'):
        r=json.loads(path.read_text())
        try:r['results']=grade_components(r,games.get(r['game_id']))
        except ValueError:r['results']={n:'Review needed' for n in r['components']}
        records.append(r)
    return sorted(records,key=lambda r:(r['kickoff_utc'],r['game_id']))


def refresh_and_run(root=ROOT):
    from .collect import collect
    from scheduled_ats_capture import run as capture
    years={int(g['season']) for g in read_csv(root/'nfl_games.csv') if g['game_type']=='REG' and g.get('gameday') and g.get('gametime') and 0<(kickoff(g)-datetime.now(timezone.utc)).total_seconds()<=7*86400}
    for year in years:collect(year,root/'data/scout4')
    capture(root)
    return run(root)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--refresh',action='store_true');args=parser.parse_args()
    print(json.dumps(refresh_and_run() if args.refresh else run(),indent=2))
