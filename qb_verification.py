"""Independent postgame QB checks for public research, never model inputs."""
import csv,json
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from name_aliases import canonical_name


def verified_starters(payload,game):
    header=payload.get('header',{})
    contests=header.get('competitions',[])
    if len(contests)!=1:raise ValueError('Missing unique contest')
    contest=contests[0]
    if contest.get('status',{}).get('type',{}).get('completed') is not True:
        raise ValueError('Game is not confirmed final')
    from zoneinfo import ZoneInfo
    kickoff=datetime.fromisoformat(contest['date'].replace('Z','+00:00'))
    scheduled=datetime.fromisoformat(game['gameday']+'T'+game['gametime']).replace(tzinfo=ZoneInfo('America/New_York'))
    if kickoff!=scheduled:raise ValueError('Kickoff mismatch')
    teams={c['homeAway']:c for c in contest['competitors']}
    if any(teams[side]['team']['abbreviation']!=game[side+'_team'] for side in ('home','away')):
        raise ValueError('Team mismatch')
    if any(float(teams[side]['score'])!=float(game[side+'_score']) for side in ('home','away')):
        raise ValueError('Score mismatch')
    result={}
    for team in payload.get('boxscore',{}).get('players',[]):
        code=team.get('team',{}).get('abbreviation')
        side=next((s for s in ('home','away') if game[s+'_team']==code),None)
        if not side:continue
        # Require an explicit starter flag. Most attempts is not proof of a start.
        candidates={athlete['athlete']['displayName']
                    for category in team.get('statistics',[]) if category.get('name')=='passing'
                    for athlete in category.get('athletes',[])
                    if athlete.get('starter') is True and athlete.get('athlete',{}).get('displayName')}
        if len(candidates)!=1:raise ValueError('QB starter is missing or ambiguous')
        result[side]=canonical_name(candidates.pop())
    if set(result)!={'home','away'}:raise ValueError('Both starters must be verified')
    return result


def fetch_summary(event):
    if not str(event).isdigit():raise ValueError('Missing ESPN game ID')
    url='https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event='+str(event)
    with urlopen(Request(url,headers={'User-Agent':'TrendFindah/1.0'}),timeout=15) as response:
        return json.load(response)


def refresh_qbs(root,season,fetch=fetch_summary):
    root=Path(root);folder=root/'data/research_qbs';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'verified.json'
    previous=json.loads(path.read_text()) if path.exists() else {'games':{}}
    verified=previous.get('games',{});issues=[]
    with (root/'nfl_games.csv').open(newline='') as source:rows=list(csv.DictReader(source))
    for game in rows:
        if str(game.get('season'))!=str(season) or any(game.get(s+'_score') in ('',None) for s in ('home','away')):continue
        identity={k:game[k] for k in ('game_id','gameday','gametime','away_team','home_team','away_score','home_score')}
        saved=verified.get(game['game_id'])
        if saved and saved.get('identity')==identity:continue
        # A changed identity invalidates an earlier verification.
        verified.pop(game['game_id'],None)
        try:
            starters=verified_starters(fetch(game.get('espn')),game)
            verified[game['game_id']]={'identity':identity,'starters':starters,
                'source_url':'https://www.espn.com/nfl/game/_/gameId/'+game['espn']}
        except (OSError,ValueError,KeyError,TypeError) as error:
            issues.append({'game_id':game['game_id'],'reason':str(error)})
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'games':verified,'issues':issues}
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,indent=2));temporary.replace(path)
    if issues:raise ValueError(f'{len(issues)} games need QB verification; see data/research_qbs/verified.json')
    return result
