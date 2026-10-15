"""Read-only current-season trend alerts matched to unstarted scheduled games."""
import csv,math
from datetime import datetime
from zoneinfo import ZoneInfo
from pregame_lines import effective_rows
from general_research import research_games
from site_views import upcoming_rows

EASTERN=ZoneInfo('America/New_York')

def home_dog_alert(root, now=None):
    now=now or datetime.now(EASTERN)
    if now.tzinfo is None:raise ValueError('Alert clock needs a timezone')
    now=now.astimezone(EASTERN)
    with (root/'nfl_games.csv').open(newline='') as source:
        rows=effective_rows(csv.DictReader(source),root/'nfl_games.csv')
    upcoming=[]
    for game in upcoming_rows(root,now):
        if not game.get('gameday') or not game.get('gametime'):continue
        try:
            kickoff=datetime.fromisoformat(game['gameday']+'T'+game['gametime']).replace(tzinfo=EASTERN)
            spread=float(game.get('spread_line',''))
        except (ValueError,TypeError):continue
        if (kickoff>now and (kickoff.date()-now.date()).days<=7 and kickoff.hour>=19 and spread<0
                and math.isfinite(spread) and game.get('game_type')=='REG' and game.get('location')!='Neutral' and not game.get('away_score') and not game.get('home_score')):
            upcoming.append((kickoff,game,spread))
    if not upcoming:return None
    kickoff,game,spread=min(upcoming,key=lambda item:item[0])
    season=int(game['season'])
    eligible=[]
    for row in rows:
        if row.get('location')=='Neutral' or not row.get('gameday') or not row.get('gametime'):continue
        try:started=datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=EASTERN)
        except ValueError:continue
        if started<now:eligible.append(row)
    report=research_games(eligible,season=season,filters={'game_type':'REG'},role='underdog',location='home',primetime='yes')
    record=next(r for r in report['records'] if r['label']=='Underdogs')
    if not (3<=record['games']<15 and record['wins']==record['games']):return None
    return {'season':season,'record':record,'game':game,'spread':abs(spread),
            'tonight':kickoff.date()==now.date(),'kickoff':kickoff.strftime('%b %d, %I:%M %p ET')}
