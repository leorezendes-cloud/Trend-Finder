"""Full-week results from canonical games; saved predictions retain their lines."""
import csv,math,json
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from ats_money_analysis import load_games

def read_csv(path):
 if not path.exists():return []
 with path.open(newline='') as f:return list(csv.DictReader(f))
def grade(margin):return 'Cover' if margin>1e-8 else 'Loss' if margin<-1e-8 else 'Push'
def underdog_records(rows,season,before_week):
 """Current-season regular-season W-L-P when a team was a dog before this week."""
 records={}
 for row in rows:
  try:
   if int(row['season'])!=season or int(row['week'])>=before_week or row['game_type']!='REG':continue
   spread=float(row['spread_line']);away=float(row['away_score']);home=float(row['home_score'])
   if not all(math.isfinite(value) for value in (spread,away,home)) or spread==0 or min(away,home)<0 or not away.is_integer() or not home.is_integer():continue
  except (KeyError,ValueError,TypeError):continue
  team=row['away_team'] if spread>0 else row['home_team']
  margin=away-home if spread>0 else home-away
  result=grade(margin+abs(spread))
  record=records.setdefault(team,{'Cover':0,'Loss':0,'Push':0})
  record[result]+=1
 return records

def build_results(root,week=None):
 rows=list(load_games(root/'nfl_games.csv').values())
 all_frozen={}
 for path in (root/'data/scout4/blend/predictions').glob('*.json'):
  record=json.loads(path.read_text());all_frozen[record['game_id']]=record
 present={g['game_id'] for g in rows}
 seasons=[int(g['season']) for g in rows if g.get('away_score') not in ('',None)] + [r['season'] for r in all_frozen.values() if r['game_id'] in present]
 season=max(seasons) if seasons else max(int(g['season']) for g in rows)
 weeks=sorted({int(g['week']) for g in rows if int(g['season'])==season and g['game_type']=='REG'})
 completed=[int(g['week']) for g in rows if int(g['season'])==season and g['game_type']=='REG' and g.get('away_score') not in ('',None)]
 frozen={k:r for k,r in all_frozen.items() if r.get('season')==season and k in present}
 latest=max(completed+[r['week'] for r in frozen.values()],default=min(weeks))
 from site_week import active_week
 current=active_week(rows)
 if current and current[0]==season:latest=current[1]
 try:selected=int(week) if week else latest
 except (ValueError,TypeError):selected=latest
 if selected not in weeks:selected=latest
 reports=read_csv(root/'sunday_results_comparison.csv') if season==2026 and selected==5 else []
 ranks={g['matchup']:g for g in reports}
 scouts=read_csv(root/'sunday_scout_pregame_2026-10-11.csv') if season==2026 and selected==5 else []
 picks={(s['away'],s['home']):s for s in scouts}
 has_blend=any(r['week']==selected for r in frozen.values())
 model_label='Blended ATS' if has_blend else 'Original Plug ATS' if scouts else 'Saved ATS picks'
 model_note='Scout 4.0 scoring + The Plug points-only · fixed 50/50 blend · version 1' if has_blend else 'Original points-only Plug snapshot · October 11, 2026' if scouts else 'No saved model forecasts for this week.'
 dog_records=underdog_records(rows,season,selected)
 games=[]
 for g in sorted(rows,key=lambda g:(g['gameday'],g.get('gametime',''))):
  if int(g['season'])!=season or g['game_type']!='REG' or int(g['week'])!=selected:continue
  g=dict(g)
  record=frozen.get(g['game_id'])
  if record and all(record.get(k)==g.get(k) for k in ('away_team','home_team')):
   g['spread_line']=str(record['quote']['line']);g['line_source']='Frozen public blend quote';g['line_capture']=record['quote']['captured_at_utc']
   from scout4.shadow import aware
   g['line_minutes']=round((aware(record['kickoff_utc'])-aware(record['quote']['captured_at_utc'])).total_seconds()/60,1)
  final=g.get('away_score') not in ('',None) and g.get('home_score') not in ('',None)
  try:spread=float(g['spread_line']);spread=spread if math.isfinite(spread) else None
  except (ValueError,TypeError):spread=None
  dog=g['away_team'] if spread is not None and spread>0 else g['home_team'] if spread is not None and spread<0 else None
  margin=float(g['away_score'])-float(g['home_score']) if final else None
  dog_margin=margin if dog==g['away_team'] else -margin if margin is not None else None
  matchup=f"{g['away_team']} @ {g['home_team']}"
  item=dict(g,matchup=matchup,underdog=dog or ('Pick’em' if spread==0 else 'Unavailable'),spread=abs(spread) if spread is not None else None,ats_result=grade(dog_margin+abs(spread)) if final and dog else 'Pick’em' if spread==0 else 'Unavailable' if spread is None else 'Pending',su_result='Win' if dog_margin is not None and dog_margin>0 else 'Loss' if dog_margin is not None and dog_margin<0 else 'Tie' if dog_margin==0 else 'Pending',game_status='Final' if final else 'Scheduled',live_score=f"{g['away_team']} {g['away_score']} – {g['home_team']} {g['home_score']}" if final else '—',scout_pick='No saved pick',scout_result='—',scout_cushion='—')
  dog_record=dog_records.get(dog,{'Cover':0,'Loss':0,'Push':0})
  item['dog_ats_record']=f"{dog_record['Cover']}–{dog_record['Loss']}–{dog_record['Push']}" if dog else '—'
  try:started=datetime.fromisoformat(g['gameday']+'T'+g.get('gametime','13:00')).replace(tzinfo=ZoneInfo('America/New_York'))<=datetime.now(timezone.utc)
  except ValueError:started=True
  item['pending_note']='Awaiting verified final score' if started else 'Not played yet'
  rank=ranks.get(matchup,{})
  for key in ['rank_3y','rank_5y','rank_10y','rank_all']:item[key]=rank.get(key,'—')
  item['has_rankings']=bool(rank)
  s=picks.get((g['away_team'],g['home_team']))
  if s:
   lean=s['form_lean'];team=s['underdog'] if lean=='Form leans underdog' else s['favorite'] if lean=='Form leans favorite' else None
   if team:
    line=abs(float(s['spread']))*(1 if lean=='Form leans underdog' else -1)
    item['scout_pick']=f'{team} {line:+g}';item['scout_cushion']=f"{abs(float(s['form_cover_cushion'])):+.1f}"
    result=grade((margin if team==g['away_team'] else -margin)+line) if final else 'Pending'
    item['scout_result']={'Cover':'Correct','Loss':'Wrong','Push':'Push','Pending':'Pending'}[result]
   else:item['scout_pick']='No pick recorded';item['scout_result']='Not graded'
  item.update(total_pick='No saved total',total_result='—',model_name=model_label)
  if record:
   from scout4.blend import grade_components
   from scout4.blend_results import total_result
   try:
    results=grade_components(record,g);component=record['components']['Blend'];team=component['pick']
    line=record['quote']['line'] if team==g['away_team'] else -record['quote']['line']
    item['scout_pick']=f'{team} {line:+g}' if team else 'No pick recorded'
    item['scout_result']={'Win':'Correct','Loss':'Wrong','No Call':'Not graded'}.get(results['Blend'],results['Blend'])
    item['scout_cushion']=f"{abs(component['ats_edge']):.1f}"
    if record.get('totals'):
     total=record['totals'];item['total_pick']='No pick recorded' if total['prediction']['lean']=='No Call' else f"{total['prediction']['lean']} {total['quote']['line']:g}"
     tr=total_result(record,g);item['total_result']={'Win':'Correct','Loss':'Wrong','No Call':'Not graded'}.get(tr,tr)
   except ValueError:
    item['scout_pick']='Review needed';item['scout_result']='Review needed';item['total_result']='Review needed'
  games.append(item)
 tally=dict(covers=sum(g['ats_result']=='Cover' for g in games),losses=sum(g['ats_result']=='Loss' for g in games),pushes=sum(g['ats_result']=='Push' for g in games),correct=sum(g['scout_result']=='Correct' for g in games),wrong=sum(g['scout_result']=='Wrong' for g in games),pick_pushes=sum(g['scout_result']=='Push' for g in games),finals=sum(g['game_status']=='Final' for g in games),games=len(games))
 tally.update(total_correct=sum(g['total_result']=='Correct' for g in games),total_wrong=sum(g['total_result']=='Wrong' for g in games),total_pushes=sum(g['total_result']=='Push' for g in games))
 return dict(model_label=model_label,model_note=model_note,has_blend=has_blend,latest_completed_week=max(completed,default=None),games=games,selected_week=selected,season=season,weeks=weeks,tally=tally,performance=read_csv(root/'sunday_window_performance.csv') if selected==5 and season==2026 else [])
