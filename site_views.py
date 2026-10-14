"""Read-only public schedule/quote views; never modifies canonical or frozen data."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from scout4.stats import read_csv,number
from scout4.shadow import kickoff,aware

ROOT=Path(__file__).resolve().parent


def upcoming_rows(root=ROOT,now=None):
    now=now or datetime.now(timezone.utc)
    from market_views import market_games
    output=[]
    for saved in market_games(root,now):
        game=dict(saved)
        game['spread_line']='' if saved['spread'] is None else str(saved['spread'])
        game['total_line']='' if saved['total'] is None else str(saved['total'])
        game['public_line_source']=saved['spread_source'];game['public_line_time']=saved['spread_time'];game['public_line_stale']=saved['spread_stale']
        output.append(game)
    return output


def public_matchups(comparisons,root=ROOT,now=None):
    from trend_finder_2 import match_upcoming_game
    rows=upcoming_rows(root,now);result=[];pending=[]
    for g in rows:
        line=number(g['spread_line'])
        if line is None or line==0:
            pending.append({'game_id':g['game_id'],'away_team':g['away_team'],'home_team':g['home_team'],'reason':'Spread unavailable' if line is None else 'Pick’em: no underdog trend'});continue
        dog=g['away_team'] if line>0 else g['home_team'];side='Away' if line>0 else 'Home';prime=g['gametime']>='19:00'
        game={'game_id':g['game_id'],'gameday':g['gameday'],'gametime_et':g['gametime'],'away_team':g['away_team'],'home_team':g['home_team'],
              'dog_team':dog,'dog_spread':abs(line),'dog_location':side,'is_primetime':prime,
              'line_source':g['public_line_source'],'line_time':g['public_line_time'],'line_stale':g['public_line_stale'],
              'neutral':g.get('location')=='Neutral','matches':match_upcoming_game(comparisons,side,prime,abs(line))}
        result.append(game)
    return result,pending
