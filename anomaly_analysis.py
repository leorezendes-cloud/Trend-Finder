"""Sourced event categories and venue-aware international-game context."""
import csv,math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from public_money import tally

CATEGORIES={'game':'Game Anomalies','world':'World Anomalies','player':'Player Anomalies','team':'Team Anomalies'}
FIELDS=['event_id','category','event_date','title','team','player','game_id','status','description','source_url']
NFL_SOURCE='https://amp.nfl.com/news/2026-nfl-schedule-release-nine-international-games-dates-times-matchups'
VENUES=[('wembley','London','United Kingdom','Europe/London'),('tottenham','London','United Kingdom','Europe/London'),('twickenham','London','United Kingdom','Europe/London'),('melbourne cricket','Melbourne','Australia','Australia/Melbourne'),('maracana','Rio de Janeiro','Brazil','America/Sao_Paulo'),('stade de france','Paris','France','Europe/Paris'),('bernab','Madrid','Spain','Europe/Madrid'),('munich','Munich','Germany','Europe/Berlin'),('allianz arena','Munich','Germany','Europe/Berlin'),('deutsche bank','Frankfurt','Germany','Europe/Berlin'),('azteca','Mexico City','Mexico','America/Mexico_City'),('banorte','Mexico City','Mexico','America/Mexico_City'),('rogers centre','Toronto','Canada','America/Toronto'),('arena corinthians','São Paulo','Brazil','America/Sao_Paulo'),('croke park','Dublin','Ireland','Europe/Dublin'),('olympiastadion','Berlin','Germany','Europe/Berlin')]

def venue(game):
    text=game.get('stadium','').lower()
    for key,city,country,zone in VENUES:
        if key in text:return dict(city=city,country=country,zone=zone)
    return None

def team_result(game,team):
    if not game.get('away_score') or not game.get('home_score') or not game.get('spread_line'):return 'Pending'
    away=float(game['away_score'])-float(game['home_score'])+float(game['spread_line'])
    margin=away if team==game['away_team'] else -away
    return 'Cover' if margin>1e-8 else 'Loss' if margin<-1e-8 else 'Push'

def summarize_results(results):
    wins=results.count('Cover');losses=results.count('Loss');pushes=results.count('Push')
    return dict(wins=wins,losses=losses,pushes=pushes,pending=results.count('Pending'),rate=round(100*wins/(wins+losses),1) if wins+losses else None)

def international_card(game,all_games,international):
    location=venue(game);card=dict(game,**location,matchup=f"{game['away_team']} @ {game['home_team']}",neutral=True,teams=[])
    if game.get('gametime'):
        kickoff=datetime.fromisoformat(game['gameday']+'T'+game['gametime']).replace(tzinfo=ZoneInfo('America/New_York'))
        local=kickoff.astimezone(ZoneInfo(location['zone']))
        card.update(local_kickoff=local.strftime('%b %d, %H:%M %Z'),zone_difference=(local.utcoffset()-kickoff.utcoffset()).total_seconds()/3600)
    for side in ['away','home']:
        team=game[f'{side}_team'];prior=[g for g in international if g['gameday']<game['gameday'] and team in [g['away_team'],g['home_team']]]
        following=sorted([g for g in all_games if g['game_type']=='REG' and g['season']==game['season'] and g['gameday']>game['gameday'] and team in [g['away_team'],g['home_team']]],key=lambda g:g['gameday'])
        next_game=following[0] if following else None
        gap=(datetime.fromisoformat(next_game['gameday'])-datetime.fromisoformat(game['gameday'])).days if next_game else None
        card['teams'].append(dict(team=team,designation='Designated home' if side=='home' else 'Designated away',rest=game.get(f'{side}_rest') or None,result=team_result(game,team),prior=summarize_results([team_result(g,team) for g in prior]),prior_games=len(prior),next_matchup=f"{next_game['away_team']} @ {next_game['home_team']}" if next_game else None,next_date=next_game['gameday'] if next_game else None,next_result=team_result(next_game,team) if next_game else None,gap=gap))
    try:spread=float(game['spread_line']);card['dog']=game['away_team'] if spread>0 else game['home_team'] if spread<0 else None;card['dog_spread']=abs(spread)
    except (ValueError,TypeError):card['dog']=None;card['dog_spread']=None
    card['source_url']=NFL_SOURCE if game['season']=='2026' else 'https://nflreadr.nflverse.com/articles/dictionary_schedules.html'
    return card

def build_anomalies(root,games,season,category='world',year=None):
    category=category if category in CATEGORIES else 'world';year=str(year or season)
    rows=[g for g in games.values() if g['game_type']=='REG']
    international=[g for g in rows if venue(g)]
    selected=[g for g in international if year=='all' or g['season']==year]
    cards=[international_card(g,rows,international) for g in sorted(selected,key=lambda g:g['gameday'],reverse=True)] if category=='world' else []
    dogs=[]
    for g in selected:
        try:s=float(g['spread_line'])
        except (TypeError,ValueError):continue
        if s:dogs.append(team_result(g,g['away_team'] if s>0 else g['home_team']))
    world_notes=[]
    note_path=root/'world_event_notes.csv'
    if note_path.exists():
        with note_path.open(newline='') as f:world_notes=list(csv.DictReader(f))
    for card in cards:
        card['highlights']=[note for note in world_notes if note['game_id']==card['game_id']]
    cards.sort(key=lambda card: not bool(card['highlights']))
    events=[];path=root/'anomaly_events.csv'
    if path.exists():
        from urllib.parse import urlparse
        with path.open(newline='',encoding='utf-8-sig') as f:
            for event in csv.DictReader(f):
                if event.get('category')!=category:continue
                try:datetime.fromisoformat(event['event_date'])
                except (ValueError,KeyError):continue
                if event.get('status') not in {'Confirmed','Reported'} or urlparse(event.get('source_url','')).scheme not in {'http','https'}:continue
                if year!='all' and not event['event_date'].startswith(year):continue
                linked=games.get(event.get('game_id'))
                event=dict(event,matchup=f"{linked['away_team']} @ {linked['home_team']}" if linked else None)
                events.append(event)
    if category=='game':
        finals=[g for g in rows if g.get('away_score') and g.get('home_score')]
        cutoff_cache={}
        for g in finals:
            if year!='all' and g['season']!=year:continue
            key=(g['season'],g['gameday'])
            if key not in cutoff_cache:
                cutoff_cache[key]=[p for p in finals if int(g['season'])-3<=int(p['season'])<=int(g['season']) and p['gameday']<g['gameday']]
            prior=cutoff_cache[key]
            if len(prior)<100:continue
            for label,value,values in [('High scoring',float(g['away_score'])+float(g['home_score']),[float(p['away_score'])+float(p['home_score']) for p in prior]),('Large winning margin',abs(float(g['away_score'])-float(g['home_score'])),[abs(float(p['away_score'])-float(p['home_score'])) for p in prior])]:
                values.sort();cutoff=values[math.ceil(.95*len(values))-1]
                if value<=cutoff:continue
                scoring=None
                if label=='High scoring':
                    try:betting_total=float(g.get('total_line',''))
                    except (TypeError,ValueError):betting_total=None
                    if betting_total is not None and (not math.isfinite(betting_total) or betting_total<=0):betting_total=None
                    scoring=dict(actual=value,betting_total=betting_total,average=round(sum(values)/len(values),1),sample=len(values),cutoff=cutoff,difference=round(value-betting_total,1) if betting_total is not None else None)
                events.append(dict(scoring=scoring,event_id=g['game_id']+label,category='game',event_date=g['gameday'],title=label,team='',player='',game_id=g['game_id'],status='Calculated',description=f'{value:g} points; above the prior-game 95th percentile of {cutoff:g}, based on {len(prior)} regular-season games in the current and previous three seasons.',source_url='',matchup=f"{g['away_team']} @ {g['home_team']}"))
    if category=='game':
        from penalty_analysis import penalty_events
        events.extend(penalty_events(root,games,year))
    return dict(category=category,category_name=CATEGORIES[category],categories=CATEGORIES,year=year,years=sorted({g['season'] for g in rows},reverse=True),international=cards,dog_record=summarize_results(dogs),events=sorted(events,key=lambda e:e['event_date'],reverse=True),count=len(cards)+len(events))
