"""Read-only confirmed final scores shared by hosted public views."""
import math
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

def confirmed_score_rows(rows,updates,now=None):
 """Display-only ESPN finals; match both teams and the exact scheduled kickoff."""
 now=now or datetime.now(timezone.utc)
 indexed={}
 for update in updates or []:
  if update.get('state')!='post' or update.get('completed') is not True:continue
  try:
   kickoff=datetime.fromisoformat(update['date'].replace('Z','+00:00'))
   away=float(update['away_score']);home=float(update['home_score'])
   if kickoff.tzinfo is None or kickoff>now or not all(math.isfinite(n) and n>=0 and n.is_integer() for n in (away,home)):continue
  except (KeyError,TypeError,ValueError,AttributeError):continue
  key=(update.get('away'),update.get('home'),kickoff)
  status=str(update.get('status','')).upper()
  overtime=('1' if 'OT' in status else '0') if status.startswith('FINAL') else None
  value=(str(int(away)),str(int(home)),overtime)
  if key in indexed and indexed[key]!=value:indexed[key]=None
  else:indexed.setdefault(key,value)
 output=[]
 for original in rows:
  row=dict(original)
  if row.get('away_score') not in ('',None) and row.get('home_score') not in ('',None):output.append(row);continue
  try:
   kickoff=datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=ZoneInfo('America/New_York'))
   final=indexed.get((row['away_team'],row['home_team'],kickoff))
  except (KeyError,TypeError,ValueError):final=None
  if final:
   away,home,overtime=final
   row.update(away_score=away,home_score=home,result=str(int(home)-int(away)),total=str(int(home)+int(away)),score_source='ESPN confirmed final')
   if overtime is not None:row['overtime']=overtime
  output.append(row)
 return output


def request_finals(path):
    from flask import current_app,g,has_request_context
    if not has_request_context() or not current_app.config.get('HOSTED_READ_ONLY_DATA'):return []
    if Path(path).resolve()!=(Path(__file__).resolve().parent/'nfl_games.csv').resolve():return []
    if not hasattr(g,'public_confirmed_finals'):
        from fan_views import confirmed_final_feed
        g.public_confirmed_finals=confirmed_final_feed()
    return g.public_confirmed_finals


def public_final_rows(rows,path):
    return confirmed_score_rows(rows,request_finals(path))


def final_signature(path):
    return tuple(sorted((str(g.get('away')),str(g.get('home')),str(g.get('date')),str(g.get('away_score')),str(g.get('home_score'))) for g in request_finals(path)))
