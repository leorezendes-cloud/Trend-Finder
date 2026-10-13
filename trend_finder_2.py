from pregame_lines import effective_rows
#!/usr/bin/env python3
import math
from copy import deepcopy
from functools import lru_cache
from threading import RLock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import csv
import re
game_file = Path('nfl_games.csv')

# Exact-match columns supported by Check_Games and the web filter form.
CSV_FILTER_FIELDS = (
    'gameday', 'game_type', 'week', 'gametime', 'home_team', 'away_team',
    'home_score', 'away_score', 'result', 'game_id', 'overtime',
    'away_rest', 'home_rest', 'spread_line', 'total_line', 'roof', 'surface',
    'temp', 'wind', 'away_qb_name', 'home_qb_name', 'away_coach',
    'home_coach', 'referee', 'stadium', 'qb_name',
)
NUMERIC_FILTER_FIELDS = {
    'week', 'home_score', 'away_score', 'result', 'overtime',
    'away_rest', 'home_rest', 'spread_line', 'total_line', 'temp', 'wind',
}



def underdog_qb_name(game):
    try:
        spread = float(game.get('spread_line', ''))
    except (ValueError, TypeError):
        return None
    if spread == 0:
        return None
    field = 'home_qb_name' if spread < 0 else 'away_qb_name'
    return game.get(field) or None


def get_current_qb_options():
    with open(game_file, newline='') as source:
        games = effective_rows(csv.DictReader(source), game_file)
    current_season = max((int(game['season']) for game in games), default=None)
    return sorted({game[field] for game in games if int(game['season']) == current_season
                   for field in ('home_qb_name', 'away_qb_name') if game.get(field)})

def matches_csv_filters(game, filters):
    for field, expected in filters.items():
        if expected is None:
            continue
        if field == 'qb_name':
            if expected not in (game.get('away_qb_name'),game.get('home_qb_name')):return False
            continue
        actual = underdog_qb_name(game) if field == 'dog_qb_name' else game.get(field, '')
        if actual == '':
            return False
        if field in NUMERIC_FILTER_FIELDS:
            try:
                if float(actual) != float(expected):
                    return False
            except (ValueError, TypeError):
                return False
        elif str(actual) != str(expected):
            return False
    return True


def get_csv_filter_options():
    with open(game_file, newline='') as source:
        games = effective_rows(csv.DictReader(source), game_file)
    options = {}
    for field in CSV_FILTER_FIELDS:
        values = {game[field] for game in games if game.get(field, '') != ''}
        key = float if field in NUMERIC_FILTER_FIELDS else str
        options[field] = sorted(values, key=key)
    options['dog_qb_name'] = sorted({game[field] for game in games for field in ('home_qb_name', 'away_qb_name') if game.get(field)})
    options['qb_name'] = options['dog_qb_name']
    return options


def load_upcoming_games(filename='sunday_matchups_2026-10-11.csv'):
    upcoming_games = []
    with open(filename, newline='') as file:
        reader = csv.DictReader(file)
        for game in reader:
            game['dog_spread'] = float(game['dog_spread'])
            game['is_primetime'] = (game['is_primetime'].lower() == 'yes')
            upcoming_games.append(game)
    return upcoming_games

def scan_sunday_matchups(comparisons):
    matchups = load_upcoming_games()
    for game in matchups:
        matches = match_upcoming_game(
            comparisons,
            game['dog_location'],
            game['is_primetime'],
            game['dog_spread']
        )
        game['matches'] = matches
    return matchups

def get_choice(number_of_choices):
    try:
        choice = int(input('Please Enter The Number Of Your Choice: '))
    except ValueError:
        print(f'Your choice has to be a number between 1 and {number_of_choices}')
        return get_choice(number_of_choices)
    if 1 <= choice <= number_of_choices:
        return choice
    else:
        print(f'Your choice has to be a number between 1 and {number_of_choices}')
        return get_choice(number_of_choices)

def analyze_game(game):
    spread_line = float(game['spread_line'])
    home_score = int(game['home_score'])
    away_score = int(game['away_score'])
    result = float(game['result'])
    home_team = game['home_team']
    away_team = game['away_team']
    is_primetime = None
    is_pickem = False
    dog_won = False
    dog_covered = False
    dog_push = False
    dog_team = None
    dog_spread = abs(spread_line)
    dog_location = None
    pickem_winner = None
    pickem_location = None

    if game['gametime'] != '':
        if game['gametime'] >= '19:00':
            is_primetime = True
        else:
            is_primetime = False
    if spread_line == 0.0:
        is_pickem = True
        if home_score > away_score:
            pickem_winner = home_team
            pickem_location = 'Home'
        if home_score < away_score:
            pickem_winner = away_team
            pickem_location = 'Away'
        if home_score == away_score:
            pickem_winner = None
            pickem_location = None
    if spread_line < 0.0:
        dog_team = home_team
        dog_location = 'Home'
        if home_score > away_score:
            dog_won = True
        if result == spread_line:
            dog_push = True
        if result > spread_line:
            dog_covered = True
    if spread_line > 0.0:
        dog_team = away_team
        dog_location = 'Away'
        if home_score < away_score:
            dog_won = True
        if result == spread_line:
            dog_push = True
        if result < spread_line:
            dog_covered = True
        
    analysis = {
        "is_primetime": is_primetime,
        "is_pickem": is_pickem,
        "dog_team": dog_team,
        "dog_location": dog_location,
        'dog_spread': dog_spread,
        "dog_won": dog_won,
        "dog_push": dog_push,
        "dog_covered": dog_covered,
        "pickem_winner": pickem_winner,
        "pickem_location": pickem_location
        }
    return analysis

def Check_Games(
    reader, season=None, 
    gameday=None, 
    game_type=None, 
    week=None, 
    gametime=None, 
    exact_spread=None, 
    location=None, 
    is_primetime=None, 
    min_spread=None, 
    max_spread=None, 
    home_team=None, 
    away_team=None, 
    home_score=None, 
    away_score=None, 
    result=None, 
    game_id=None, 
    overtime=None, 
    away_rest=None, 
    home_rest=None, 
    spread_line=None, 
    total_line=None, 
    roof=None, 
    surface=None, 
    temp=None, 
    wind=None, 
    away_qb_name=None, 
    home_qb_name=None, 
    away_coach=None, 
    home_coach=None, 
    referee=None, 
    stadium=None,
    dog_qb_name=None,
    qb_name=None,
    ):
    parameters = locals().copy()
    csv_filters = {field: parameters[field] for field in CSV_FILTER_FIELDS}
    csv_filters['dog_qb_name'] = dog_qb_name
    pickem_winners = []
    pickem_locations = []
    pickem_seasons = []

    stats = {
        'all_games': {
            'games': 0,
            'home': {
                'total': 0,
                'wins': 0,
                'covers': 0,
                'pushes': 0,
            },
            'away': {
                'total': 0,
                'wins': 0,
                'covers': 0,
                'pushes': 0,
            },
            "pickems": {
                'total': 0,
                'home_wins': 0,
                'away_wins': 0,
                'pushes': 0,
                'winners': pickem_winners,
                'locations': pickem_locations,
                'seasons': pickem_seasons,

            },
        },
        'primetime_games': {
            'games': 0,
            'home': {
                'total': 0,
                'wins': 0,
                'covers': 0,
                'pushes': 0,
            },
            'away': {
                'total': 0,
                'wins': 0,
                'covers': 0,
                'pushes': 0,
            },
            'pickems': {
                'total': 0,
                'home_wins': 0,
                'away_wins': 0,
                'pushes': 0,
            },
        },    
    }
    for game in reader:
        if game['home_score'] == '':
            continue
        if game['away_score'] == '':
            continue
        if game['spread_line'] == '':
            continue
        if game['result'] == '':
            continue
        if game_type is not None:
            if game['game_type'] != game_type:
                continue
        if season is not None:
            if isinstance(season, tuple):
                if not season[0] <= int(game['season']) <= season[1]:
                    continue
            elif game['season'] != str(season):
                continue
        if not matches_csv_filters(game, csv_filters):
            continue
        analysis = analyze_game(game)
        if is_primetime is not None and analysis['is_primetime'] != is_primetime:
            continue
        if location is not None and analysis['dog_location'] != location:
            continue
        if min_spread is not None and analysis['dog_spread'] < min_spread:
            continue
        if max_spread is not None and analysis['dog_spread'] > max_spread:
            continue
        if exact_spread is not None and analysis['dog_spread'] != exact_spread:
            continue 
        stats['all_games']['games'] += 1
        if analysis["dog_location"] == 'Home':
            stats['all_games']['home']['total'] += 1
            if analysis['dog_won']:
                stats['all_games']['home']['wins'] += 1
            if analysis['dog_covered']:
                stats['all_games']['home']['covers'] +=1
            if analysis['dog_push']:
                stats['all_games']['home']['pushes'] += 1
        elif analysis['is_pickem']:
                pickem_seasons.append(game['season'])
                stats['all_games']['pickems']['total'] += 1
                if analysis['pickem_winner'] is not None:
                    pickem_winners.append(analysis['pickem_winner'])
                if analysis['pickem_location'] is not None:
                    pickem_locations.append(analysis['pickem_location'])
                if analysis['pickem_location'] == 'Home':
                    stats['all_games']['pickems']['home_wins'] += 1
                if analysis['pickem_location'] == 'Away':
                    stats['all_games']['pickems']['away_wins'] += 1
                if analysis['pickem_winner'] == None:
                    stats['all_games']['pickems']['pushes'] += 1
        elif analysis['dog_location'] == 'Away':
            stats['all_games']['away']['total'] += 1
            if analysis['dog_won']:
                stats['all_games']['away']['wins'] += 1
            if analysis['dog_covered']:
                stats['all_games']['away']['covers'] += 1
            if analysis['dog_push']:
                stats['all_games']['away']['pushes'] += 1
        if analysis["is_primetime"]:
            stats['primetime_games']['games'] += 1
            if analysis['dog_location'] == 'Home':
                stats['primetime_games']['home']['total'] += 1
                if analysis['dog_won']:
                    stats['primetime_games']['home']['wins'] += 1
                if analysis['dog_covered']:
                    stats['primetime_games']['home']['covers'] += 1
                if analysis['dog_push']:
                    stats['primetime_games']['home']['pushes'] += 1
            elif analysis['is_pickem']:
                stats['primetime_games']['pickems']['total'] += 1
                if analysis['pickem_location'] == 'Home':
                    stats['primetime_games']['pickems']['home_wins'] += 1
                if analysis['pickem_location'] == 'Away':
                    stats['primetime_games']['pickems']['away_wins'] += 1
                if analysis['pickem_winner'] == None:
                    stats['primetime_games']['pickems']['pushes'] += 1
            elif analysis['dog_location'] == 'Away':
                stats['primetime_games']['away']['total'] += 1
                if analysis['dog_won']:
                    stats['primetime_games']['away']['wins'] +=1
                if analysis['dog_covered']:
                    stats['primetime_games']['away']['covers'] += 1
                if analysis['dog_push']:
                    stats['primetime_games']['away']['pushes'] += 1
                    
    return stats

def run_analysis(**filters):
    with open(game_file, 'r') as game_check:
        reader = effective_rows(csv.DictReader(game_check), game_file)
        return Check_Games(reader, **filters)

def load_finished_games(season='2026', game_type='REG'):
    finished_games = []
    with open(game_file, newline='') as game_check:
        reader = effective_rows(csv.DictReader(game_check), game_file)
        for game in reader:
            if game['season'] != str(season):
                continue
            if game['game_type'] != game_type:
                continue
            required_fields = (
                'gameday',
                'home_score',
                'away_score',
                'spread_line',
                'result',
            )
            if any(game[field] == '' for field in required_fields):
                   continue
            analysis = analyze_game(game)
            if analysis['is_pickem']:
                continue
            finished_games.append({
                "gameday": game["gameday"],
                "gametime": game["gametime"],
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "home_score": int(game["home_score"]),
                "away_score": int(game["away_score"]),
                "dog_team": analysis["dog_team"],
                "dog_location": analysis["dog_location"],
                "dog_spread": analysis["dog_spread"],
                "is_primetime": analysis["is_primetime"],
                "dog_won": analysis["dog_won"],
                "dog_covered": analysis["dog_covered"],
                "dog_push": analysis["dog_push"],
            })
    finished_games.sort(
        key=lambda game: game['gameday']
    )
    return finished_games

def find_active_streak(
        games, location=None, 
        is_primetime=None, min_spread=None,
        max_spread=None, metric='ats'):
    if metric not in ("ats", "su"):
        raise ValueError('Metric must be "ats" or "su"')
    streak = []
    for game in reversed(games):
        if location is not None and game['dog_location'] != location:
            continue
        if is_primetime is not None and game["is_primetime"] != is_primetime:
            continue

        if min_spread is not None and game["dog_spread"] < min_spread:
            continue

        if max_spread is not None and game["dog_spread"] > max_spread:
            continue
        if metric == 'ats':
            if game['dog_push']:
                continue
            won = game['dog_covered']
        else:
            won = game['dog_won']
        if not won:
            break
        streak.append(game)
    streak.reverse()
    return streak

def find_recent_form(
        games,
        window=5,
        location=None,
        is_primetime=None,
        min_spread=None,
        max_spread=None,
        metric='ats'
):
    if metric not in ('ats', 'su'):
        raise ValueError('Metric must be "ats" or "su"')
    
    if window < 1:
        raise ValueError("Window must be positive")

    recent_games = []

    for game in reversed(games):

        if location is not None and game["dog_location"] != location:
            continue

        if is_primetime is not None and game["is_primetime"] != is_primetime:
            continue

        if min_spread is not None and game["dog_spread"] < min_spread:
            continue

        if max_spread is not None and game["dog_spread"] > max_spread:
            continue

        if metric == "ats" and game["dog_push"]:
            continue

        recent_games.append(game)

        if len(recent_games) == window:
            break

    recent_games.reverse()

    wins = sum(
        game["dog_covered"] if metric == "ats"
        else game["dog_won"]
        for game in recent_games
    )

    total = len(recent_games)
    losses = total - wins

    rate = (wins / total) * 100 if total else 0

    return {
        "wins": wins,
        "losses": losses,
        "rate": rate,
        "sample": total,
        "complete": total == window,
        "games": recent_games
    }

def scan_hot_performance(games, comparisons, window=5):

    
    hot_trends = []

    for trend in comparisons:

        recent = find_recent_form(
            games,
            window=window,
            location=trend["location"],
            is_primetime=trend["primetime"],
            min_spread=trend['min_spread'],
            max_spread=trend['max_spread'],
            metric="ats",
        )

        if recent["sample"] < 3:
            continue

        if recent["rate"] < 70:
            continue
        ats_streak = find_active_streak(
            games,
            location=trend['location'],
            is_primetime=trend['primetime'],
            min_spread=trend['min_spread'],
            max_spread=trend['max_spread'],
            metric="ats",
        )
        
        hot_trends.append({
            "location": trend["location"],
            "primetime": trend["primetime"],
            "spread": trend["spread"],
            "recent": recent,
            "season_ats": trend["current_ats_rate"],
            "historical_ats": trend["historical_ats_rate"],
            "ats_streak": ats_streak,
            "dog_no_push": trend['dog_no_push'],
            "ci_low": trend['current_ci_low'],
        })

    hot_trends.sort(
        key=lambda trend: (
            trend['ci_low'],
            trend['dog_no_push'],
            trend['season_ats'] - trend['historical_ats'],
            len(trend['ats_streak']),
            trend["recent"]["rate"]
        ),
        reverse=True
    )

    return hot_trends

def scan_active_streaks(games,comparisons, min_streak=3):
    streaks = []
    for trend in comparisons:
        streak_games = find_active_streak(
            games,
            location=trend['location'],
            is_primetime=trend['primetime'],
            min_spread=trend['min_spread'],
            max_spread=trend['max_spread'],
            metric='ats'
            )
        streak_length = len(streak_games)

        if streak_length < min_streak:
            continue
        streaks.append({
            "location": trend['location'],
            "primetime": trend['primetime'],
            "spread": trend['spread'],
            "streak_length": streak_length,
            "games": streak_games,
            "season_ats": trend['current_ats_rate'],
            "historical_ats": trend['historical_ats_rate'],
            "dog_no_push": trend['dog_no_push'],
            "ci_low": trend['current_ci_low'],
        })
    streaks.sort(
        key=lambda trend: (
            trend['streak_length'],
            trend['ci_low'],
            trend['dog_no_push']
        ), reverse=True
    )
    return streaks

def group_active_streaks(streaks):
    groups = {}

    for trend in streaks:
        game_ids = tuple(
            sorted(
                (
                    game['gameday'],
                    game['away_team'],
                    game['home_team'],
                )
                for game in trend['games']
            )
        )
        key = (
            trend['location'],
            trend['primetime'],
                  game_ids
        )
        if key not in groups:
            groups[key] = {
                'main': trend,
                'related': [],
            }
        else:
            groups[key]['related'].append(trend)
    return list(groups.values())

def group_hot_trends(hot_trends):

    groups = {}

    for trend in hot_trends:

        game_ids = tuple(
            sorted(
                (
                    game["gameday"],
                    game["away_team"],
                    game["home_team"]
                )
                for game in trend["recent"]["games"]
            )
        )

        key = (
            trend["location"],
            trend["primetime"],
            game_ids
        )

        if key not in groups:
            groups[key] = {
                "main": trend,
                "related": []
            }

        else:
            groups[key]["related"].append(trend)

    return list(groups.values())

def print_report(stats):
    ats_cover_rate_no_push = 0
    dog_win_rate = 0
    ats_cover_rate = 0
    all_ats_no_push = 0
    all_dog_atsrate = 0
    all_dog_win_rate = 0
    all_games = stats['all_games']
    prime = stats['primetime_games']
    all_pickems = all_games['pickems']
    all_home = all_games['home']
    all_away = all_games['away']
    prime_home = prime['home']
    prime_away = prime['away']
    prime_pickems = prime['pickems']
    
    all_dog_wins = stats['all_games']['home']['wins'] + stats['all_games']['away']['wins']
    all_dog_push = stats['all_games']['home']['pushes'] + stats['all_games']['away']['pushes']
    total_all_dogs = stats['all_games']['home']['total'] + stats['all_games']['away']['total']
    all_dog_covers = stats['all_games']['away']['covers'] + stats['all_games']['home']['covers']
    all_homedog_losses = stats['all_games']['home']['total'] - (stats['all_games']['home']['covers'] + stats['all_games']['home']['pushes'])
    all_awaydog_losses = stats['all_games']['away']['total'] - (stats['all_games']['away']['covers'] + stats['all_games']['away']['pushes'])
    all_no_push = total_all_dogs - all_dog_push
    all_dog_losses = all_homedog_losses + all_awaydog_losses    
    if all_no_push != 0:
        all_ats_no_push = (all_dog_covers / all_no_push) * 100
    if total_all_dogs != 0:
        all_dog_atsrate = (all_dog_covers / total_all_dogs) * 100
        all_dog_win_rate = (all_dog_wins / total_all_dogs) * 100
       

    primetime_dogs = stats['primetime_games']['home']['total'] + stats['primetime_games']['away']['total']
    home_dog_losses = stats['primetime_games']['home']['total'] - (stats['primetime_games']['home']['covers'] + stats['primetime_games']['home']['pushes'])
    away_dog_losses = stats['primetime_games']['away']['total'] - (stats['primetime_games']['away']['pushes'] + stats['primetime_games']['away']['covers'])             
    primetime_dog_wins = stats['primetime_games']['home']['wins'] + stats['primetime_games']['away']['wins']
    primetime_dog_covers = stats['primetime_games']['home']['covers'] + stats['primetime_games']['away']['covers']
    primetime_push = stats['primetime_games']['home']['pushes'] + stats['primetime_games']['away']['pushes']
    total_losses = away_dog_losses + home_dog_losses
    dogs_no_push = primetime_dogs - primetime_push 
    if primetime_dogs != 0:
        ats_cover_rate = (primetime_dog_covers / primetime_dogs) * 100 
        dog_win_rate = (primetime_dog_wins / primetime_dogs) * 100    
    if dogs_no_push != 0:          
        ats_cover_rate_no_push = (primetime_dog_covers / dogs_no_push ) * 100 
    print(f'_________________________________')
    print(f'           PrimeTime Dogs')
    print(f'=================================')
    print()
    print(f'''Total PrimeTime Games: {prime['games']}
PrimeTime Dogs {primetime_dogs}
Total PrimeTime Home Dogs: {prime_home['total']}
PrimeTime Home Dog Straight Up Wins: {prime_home['wins']}
PrimeTime Home Dog Covers: {prime_home['covers']}
PrimeTime Home Dog Pushes: {prime_home['pushes']}
PrimeTime Home Dog Losses: {home_dog_losses}
Total PrimeTime Away Dogs: {prime_away['total']}
PrimeTime Away Dog Straight Up Wins: {prime_away['wins']}
PrimeTime Away Dog Covers: {prime_away['covers']}
PrimeTime Away Dog Pushes: {prime_away['pushes']}
PrimeTime Away Dog Losses: {away_dog_losses}
Total PrimeTime Pick Em"s: {prime_pickems['total']}
PrimeTime Pick Em" Home Wins: {prime_pickems['home_wins']}
PrimeTime Pick Em" Away Wins: {prime_pickems['away_wins']}
PrimeTime Pick Em" Pushes: {prime_pickems['pushes']}
PrimeTime Total Dog Straight Up Wins: {primetime_dog_wins}
PrimeTime Total Dog Covers: {primetime_dog_covers}
PrimeTime Total Dog Losses: {total_losses}
PrimeTime Total Dog Pushes: {primetime_push}
PrimeTime Dog Straight Up Win Rate: {dog_win_rate:.2f}%
PrimeTime Dog ATS Cover Rate: {ats_cover_rate:.2f}%
PrimeTime Dog ATS Cover Rate Excluding Pushes: {ats_cover_rate_no_push:.2f}%''')
    print()
    print(f'_________________________________')
    print(f'         All Underdogs')
    print(f'=================================')
    print(f'''Total Games: {all_games['games']}
All Underdogs: {total_all_dogs}
All Home Dogs: {all_home['total']}
All Home Dog Straight Up Wins: {all_home['wins']}
All Home Dog Covers: {all_home['covers']}
All Home Dog Pushes: {all_home['pushes']}
All Home Dog Losses: {all_homedog_losses}
All Away Dogs: {all_away['total']}
All Away Dog Straight Up Wins: {all_away['wins']}
All Away Dog Covers: {all_away['covers']}
All Away Dog Pushes: {all_away['pushes']}
All Away Dog Losses: {all_awaydog_losses}
All Pick Em"s: {all_pickems['total']}
All Pick Em" Home Wins: {all_pickems['home_wins']}
All Pick Em" Away Wins: {all_pickems['away_wins']}
All Pick Em Pushes: {all_pickems['pushes']}
All Total Dog Straight Up Wins: {all_dog_wins}
All Total Dog Covers: {all_dog_covers}
All Total Dog Losses: {all_dog_losses}
All Total Dog Pushes: {all_dog_push}
All Dog Straight Up Win Rate: {all_dog_win_rate:.2f}%
All Dog ATS Cover Rate: {all_dog_atsrate:.2f}%
All Dog ATS Cover Rate Excluding Pushes: {all_ats_no_push:.2f}%
''')

    print('_________________________________')
    print(f'        Pick Em"s')
    print(f'================================')
    for winner, location, seasons in zip(stats['all_games']['pickems']['winners'], stats['all_games']['pickems']['locations'], stats['all_games']['pickems']['seasons']):
        print(f'Pick Em" Winners: {winner:<5}-  {location} {seasons}')

def main_menu():
    print()
    print(f'=================================')
    print(f'*********************************')
    print(f'||    The Trend Findah 3000    ||')
    print(f'*********************************')
    print(f'=================================')
    print()


    season = None
    week = None
    location = None
    is_primetime = None
    min_spread = None
    max_spread = None
    home_team = None
    away_team = None
    home_score = None
    away_score = None
    result = None
    game_id = None
    overtime = None
    home_rest = None
    away_rest = None
    exact_spread = None
    total_line = None
    roof = None
    surface = None
    temp = None
    wind = None
    away_qb_name = None
    home_qb_name = None
    away_coach = None
    home_coach = None
    referee = None
    stadium = None
    gametime = None
    spread_mode = None

    
    while True:
        print()
        print(f'CURRENT FILTERS')
        print()
        print(f'''1. Season : {season} 
2. Home Dogs/Away Dogs: {location}
3. PrimeTime Status: {is_primetime}
4. Spreads: {display_spread_filter(spread_mode, min_spread, max_spread, exact_spread)}
5. CLEAR FILTERS
6. SEARCH
7. QUIT
''')
        print()
        choice = get_choice(7)
        match choice:
            case 1:
                print('***********************************')
                print()
                print(f'Current Status: {season}')
                print()
                print('Select By Season Or By Range')
                print()
                print('1. Single Season')
                print('2. Range Of Seasons')
                print('3. All Seasons')
                print('4. Back')
                print()
                season_choice = get_choice(4)
                match season_choice:
                    case 1:
                        while True:
                            print('***********************************')
                            print(f'Current Status: {season}')
                            print()
                            print('or "back" to go back')
                            print()
                            season_input = input('Please Enter A Season: ')
                            print()
                            if season_input.lower() == 'back':
                                break
                            try:
                                season = int(season_input)
                            except ValueError:
                                print('Please Enter A Valid Year From 1999 - 2026')
                                continue
                            if 1999 <= season <= 2026:
                                print('Valid Season')
                                season = str(season)
                                break
                            else: 
                                print('Please Enter A Valid Year From 1999 - 2026')
                                continue
                    case 2:
                        while True:
                            print('***********************************')
                            start_season_limit = 1999
                            end_season_limit = 2026
                            print(f'Current Status: {season}')
                            print()
                            print('Please Select A Range')
                            print()
                            print('or "back" to go back')
                            start_season_input = input('Enter Your Start Date: ')
                            if start_season_input.lower() == 'back':
                                break
                            print()
                            end_season_input = input('Enter Your End Date: ')
                            print()
                            if end_season_input.lower() == 'back':
                                break
                            try:
                                start_season = int(start_season_input)
                                end_season = int(end_season_input)
                            except ValueError:
                                print('Please Enter A Valid Range From 1999 - 2026')
                                continue
                            if start_season_limit <= start_season <= end_season <= end_season_limit:
                                print(f'Valid Range: {start_season} - {end_season}')
                                season = start_season, end_season
                                break
                            else:
                                print('Enter A Valid Range From 1999 - 2026')
                                continue
                    case 3:
                        print(f'***********************************')
                        print()
                        print('No Filer - All Seasons')
                        print()
                        season = None

                    case 4:
                        continue
            case 2:
                while True:
                    print('***********************************')
                    print()
                    print(f'Current Status : {location}')
                    print()
                    print('Choose A Side..Or Not')
                    print()
                    print('1. Home Dog')
                    print('2. Away Dog')
                    print('3. No Dog')
                    print('4. Back')
                    print()
                    dog_choice = get_choice(4)
                    match dog_choice:
                        case 1:
                            location = 'Home'
                            break
                        case 2:
                            location = 'Away'
                            break
                        case 3:
                            location = None 
                            break
                        case 4:
                            break
            case 3:
               print('***********************************')
               print()
               print(f'Current PrimeTime Status: {is_primetime}')
               print()
               print('Choose PrimeTime Status')
               print()
               print('1. PrimeTime ')
               print('2. Not Primetime')
               print('3. None')
               print('4. Back')
               print()
               prime_choice = get_choice(4)
               match prime_choice:
                    case 1:
                        print('***********************************')
                        is_primetime = True
                        print()
                        print('PrimeTime Active')
                        print()
                    case 2: 
                       print('************************************')
                       is_primetime = False 
                       print()
                       print('PrimeTime Not Active') 
                       print()
                    case 3:
                       print('************************************')
                       is_primetime = None
                    case 4:
                       continue
            case 4:
                print('************************************')
                print()
                print(f'Current Status: {min_spread} - {max_spread} - {exact_spread}')
                print("Filter By Spread(s)")
                print()
                print('1. Filter By Min. Max. Or Exact Spread')
                print('2. Filter By Range Of Spread')
                print('3. All Spreads')
                print('4. Back')
                print()
                spread_choice = get_choice(4)
                match spread_choice:
                    case 1:
                            print('************************************')
                            print()
                            print('Choose Between | Min. - Max. - Exact |')
                            print(f'---------------> {min_spread} - {max_spread} - {exact_spread}')
                            print()
                            print('1. Min. Spread')
                            print('2. Max. Spread')
                            print('3. Exact Spread')
                            print('4. Back')
                            print()
                            single_spread_choice = get_choice(4)
                            match single_spread_choice:
                                case 1:
                                    while True:
                                        spread_mode = 'min'
                                        print('************************************')
                                        print()
                                        print(f'Current Status: {min_spread} - {max_spread} - {exact_spread}')
                                        print()
                                        print('or "back" to go back')
                                        min_spread_input = (input('Please Enter A Min. Spread: '))
                                        print()
                                        if min_spread_input.lower() == 'back':
                                            break
                                        try:
                                            min_spread = float(min_spread_input)
                                        except ValueError:
                                            print('Please Enter A Valid Min. Spread (Float)')
                                            continue
                                        if 0.0 <= min_spread <= 25.0:
                                            max_spread = None
                                            exact_spread = None
                                            print('Valid Spread')
                                            break
                                        else: 
                                            print('Please Enter A Valid Min. Spread (Float)')
                                            continue
                                case 2:
                                    while True:
                                            spread_mode = 'max'
                                            print('************************************')
                                            print()
                                            print(f'Current Status: {min_spread} - {max_spread} - {exact_spread}')
                                            print()
                                            print('or "back" to go back')
                                            max_spread_input = (input('Please Enter A Max. Spread: '))
                                            print()
                                            if max_spread_input.lower() == 'back':
                                                break
                                            try:
                                                max_spread = float(max_spread_input)
                                            except ValueError:
                                                print('Please Enter A Valid Max. Spread (Float)')
                                                continue
                                            if 0.0 <= max_spread <= 25.0:
                                                min_spread = None
                                                exact_spread = None
                                                print('Valid Spread')
                                                break
                                            else: 
                                                print('Please Enter A Valid Max. Spread (Float)')
                                                continue
                                case 3:
                                    while True:
                                        spread_mode = 'exact'
                                        print('************************************')
                                        print()
                                        print(f'Current Status: {min_spread} - {max_spread} - {exact_spread}')
                                        print()
                                        print('or "back" to go back')
                                        spread_line_input = input('Please Enter A Spread: ')
                                        print()
                                        if spread_line_input.lower() == 'back':
                                            break
                                        try:
                                            exact_spread = float(spread_line_input)
                                        except ValueError:
                                            print('Please Enter A Valid Spread (Float)')
                                            continue
                                        if 0.0 <= exact_spread <= 25.0:
                                            print('Valid Spread')
                                            min_spread = None
                                            max_spread = None
                                            break
                                        else: 
                                            print('Please Enter A Valid Spread (Float)')
                                            continue
                                case 4:
                                    break
                    case 2:
                        while True:
                            spread_mode = 'range'
                            print('************************************')
                            print()
                            print(f'Current Status: {min_spread} - {max_spread} - {exact_spread}')
                            min_spread_limit = 0.0
                            max_spread_limit = 25.0
                            print()
                            print('Please Select A Range')
                            print()
                            print('or "back" to go back')
                            min_spread_input_2 = input('Enter Your Min. Spread: ')
                            if min_spread_input_2.lower() == 'back':
                                break
                            print()
                            max_spread_input_2 = input('Enter Your Max. Spread: ')
                            print()
                            if max_spread_input_2.lower() == 'back':
                                break
                            try:
                                min_spread = float(min_spread_input_2)
                                max_spread = float(max_spread_input_2)
                            except ValueError:
                                print('Please Enter A Valid Range From 0.0 to 25.0')
                                continue
                            if min_spread_limit <= min_spread <= max_spread <= max_spread_limit:
                                exact_spread = None
                                print(f'Valid Range: {min_spread} - {max_spread}')
                                break
                            else:
                                print('Enter A Valid Range From 0.0 to 25.0')
                                continue
                    case 3:
                        print('***********************************')
                        print()
                        print(f'Current Status: {min_spread} - {max_spread} - {exact_spread}')
                        print()
                        min_spread = None
                        max_spread = None
                        exact_spread = None
                        print('No Filter - All Spreads')
                        print()
                        continue
                    case 4:
                        continue
            case 5:
                print('***********************************')
                print()
                print('Are You Sure You Want To CLEAR The Filters?')
                print()
                print('''1. Yes
2. No
''')
                print()
                clear_choice = get_choice(2)
                match clear_choice:
                    case 1:
                        print('************************************')
                        print()
                        print('Confirm')
                        print()
                        print('1. Yes')
                        print('2. No')
                        print()
                        confirm_choice = get_choice(2)
                        match confirm_choice:
                            case 1:
                                print('************************************')
                                print()
                                print('CLEARED FILTERS')
                                print()
                                season = None
                                location = None
                                is_primetime = None
                                min_spread = None
                                max_spread = None
                                spread_line = None
                            case 2:
                                continue
                    case 2:
                        continue
            case 6:
                try:
                    stats = run_analysis(season=season, location=location, is_primetime=is_primetime, gametime=gametime, week=week, home_team=home_team, min_spread=min_spread, max_spread=max_spread, away_team=away_team, home_score=home_score, away_score=away_score, result=result, game_id=game_id, overtime=overtime, home_rest=home_rest, away_rest=away_rest, exact_spread=exact_spread, total_line=total_line, roof=roof, surface=surface, temp=temp, wind=wind, away_qb_name=away_qb_name, home_qb_name=home_qb_name, away_coach=away_coach, home_coach=home_coach, referee=referee, stadium=stadium)
                    print_report(stats)
                except FileNotFoundError:
                    print('Error: Game file not found.')
            case 7:
                print('Trend Findah 3000 Signing Out!!')
                return
def display_spread_filter(spread_mode, min_spread, max_spread, exact_spread):
    if spread_mode == 'min':
        return f'Minimum: {min_spread}'
    if spread_mode == 'max':
        return f'Maximun: {max_spread}'
    if spread_mode == 'exact':
        return f'Exact: {exact_spread}'
    if spread_mode == 'range':
        return f'Range: {min_spread} - {max_spread}'
    return 'All Spreads'
def evaluate_trend(stats):
    all_games = stats['all_games']

    total_dogs = (all_games['home']['total']
    + all_games['away']['total'])

    dog_wins = (
        all_games['home']['wins']
        + all_games['away']['wins']
    )

    dog_covers = (
        all_games['home']['covers']
        + all_games['away']['covers']
    )
    
    dog_pushes = (
        all_games['home']['pushes']
        + all_games['away']['pushes']
    )
    dogs_no_push = total_dogs - dog_pushes
    if dogs_no_push == 0:
        return None
    ats_decimal = dog_covers / dogs_no_push
    ats_rate = ats_decimal * 100
    breakeven_rate = 52.38
    ats_edge = ats_rate - breakeven_rate
    if total_dogs > 0:
        win_rate = (dog_wins / total_dogs) * 100

    z = 1.96
    n = dogs_no_push
    p = ats_decimal

    denominator = 1 + (z ** 2 / n)

    center = (p + (z ** 2 / (2 * n))) / denominator

    margin = (z / denominator) * math.sqrt((p * (1 - p) / n) + (z ** 2 / (4 * n ** 2)))

    ci_low = max(0, (center - margin) * 100)
    ci_high = min(100, (center + margin) * 100)

    if ci_low > breakeven_rate:
        signal = "Positive"
    elif ci_high < breakeven_rate:
        signal = "Negative"
    else:
        signal = "Inconclusive"
    return {
        "sample": total_dogs,
        "ats_rate": ats_rate,
        "ats_wins": dog_covers,
        "ats_losses": dogs_no_push - dog_covers,
        "ats_pushes": dog_pushes,
        "dog_no_push": dogs_no_push,
        "ats_edge": ats_edge,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "signal": signal,
        "su_wins": dog_wins,
        "su_rate": win_rate,
    }
def describe_combination(trend, season=None, **scope):
    """Explain the actual historical sample, including manual restrictions."""
    def clause(field, value):
        if field == 'Underdog QB':
            return f'{value} quarterbacks the underdog'
        if field == 'Game Type':
            return {'REG': 'it is a regular-season game', 'WC': 'it is a wild-card game',
                    'DIV': 'it is a divisional playoff game', 'CON': 'it is a conference championship game',
                    'SB': 'it is a Super Bowl'}.get(value, f'the game type is {value}')
        if field == 'Dog location':
            return f'the underdog plays {"at home" if value == "Home" else "away"}'
        if field == 'Primetime':
            return 'it is a primetime game' if value == 'Yes' else 'it is a non-primetime game'
        if field in ('Home team', 'Away team'):
            return f'{value} is the {field.lower()}'
        if field in ('Home team rest', 'Away team rest'):
            return f'the {field.lower().replace(" rest", "")} has {value.replace("<", "less than ").replace(">", "more than ")} of rest'
        if field == 'Stadium roof':
            return {'dome': 'the game is played in a dome', 'outdoors': 'the game is played outdoors',
                    'closed': 'the stadium roof is closed', 'open': 'the stadium roof is open'}.get(value, f'the stadium roof is {value}')
        if field == 'Weekday':
            return f'the game is played on {value}'
        if field == 'Month':
            import calendar
            return f'the game is played in {calendar.month_name[int(value)]}'
        if field == 'Div Game':
            return 'it is a division matchup' if value == '1' else 'it is a non-division matchup'
        if field == 'Game time':
            return f'kickoff is in the {value.split(" (")[0].lower()}'
        return f'the {field.lower()} is {value}'

    conditions = [clause(*label.split(': ', 1)) for label in trend['filters']]
    manual_labels = {
        'dog_qb_name': 'Underdog QB', 'game_type': 'Game Type', 'home_team': 'Home team', 'away_team': 'Away team',
        'home_rest': 'Home team rest', 'away_rest': 'Away team rest', 'roof': 'Stadium roof',
    }
    for field, value in scope.items():
        if value is None:
            continue
        if field == 'location':
            condition = clause('Dog location', value)
        elif field == 'is_primetime':
            condition = clause('Primetime', 'Yes' if value else 'No')
        elif field in ('min_spread', 'max_spread', 'exact_spread'):
            wording = {'min_spread': 'at least', 'max_spread': 'at most', 'exact_spread': 'exactly'}[field]
            condition = f'the underdog spread is {wording} {value:g}'
        else:
            label = manual_labels.get(field, field.replace('_', ' '))
            condition = clause(label, f'{value} days' if field in ('home_rest', 'away_rest') else str(value))
        if condition not in conditions:
            conditions.append(condition)
    period = 'Historically'
    if isinstance(season, tuple):
        period = f'In seasons {season[0]}–{season[1]}'
    elif season is not None:
        period = f'In {season}'
    when = ' and '.join(conditions)
    return f'{period}, when {when}, the underdog covered the spread {trend["ats_rate"]:.2f}% of the time, excluding pushes.'


def combination_min_games(season):
    return 3 if str(season) == '2026' or season == (2026, 2026) else 10


def grouped_game_features(game, analysis):
    """Pregame features only: final scores/results would encode the outcome."""
    features = {
        'Dog location': analysis['dog_location'],
        'Primetime': ('Yes' if analysis['is_primetime'] else 'No')
                     if analysis['is_primetime'] is not None else None,
    }
    labels = {
        'home_team': 'Home team', 'away_team': 'Away team',
        'home_rest': 'Home team rest', 'away_rest': 'Away team rest',
        'home_coach': 'Home team coach', 'away_coach': 'Away team coach',
        'roof': 'Stadium roof', 'total_line': 'Pregame total line',
    }
    categorical = ('game_type', 'weekday', 'home_team', 'away_team', 'roof',
                   'surface', 'away_coach',
                   'home_coach', 'referee', 'stadium', 'div_game')
    for field in categorical:
        if game.get(field, '') != '':
            features[labels.get(field, field.replace('_', ' ').title())] = game[field]
    if analysis['dog_location'] in ('Home', 'Away'):
        qb_field = 'home_qb_name' if analysis['dog_location'] == 'Home' else 'away_qb_name'
        if game.get(qb_field, ''):
            features['Underdog QB'] = game[qb_field]
    if game.get('gametime'):
        hour = int(game['gametime'].split(':')[0])
        features['Game time'] = 'Morning (<12:00)' if hour < 12 else 'Day (12:00–18:59)' if hour < 19 else 'Night (19:00+)'
    if game.get('gameday'):
        features['Month'] = game['gameday'][5:7]
    buckets = {
        'week': [(6, '1–5'), (12, '6–11'), (19, '12–18'), (math.inf, '19+')],
        'home_rest': [(7, '<7 days'), (8, '7 days'), (math.inf, '>7 days')],
        'away_rest': [(7, '<7 days'), (8, '7 days'), (math.inf, '>7 days')],
        'temp': [(32, '<32°F'), (60, '32–<60°F'), (80, '60–<80°F'), (math.inf, '80°F+')],
        'wind': [(10, '<10 mph'), (20, '10–<20 mph'), (math.inf, '20 mph+')],
    }
    for field, ranges in buckets.items():
        if game.get(field, '') == '':
            continue
        value = float(game[field])
        for upper, label in ranges:
            if value < upper:
                features[labels.get(field, field.replace('_', ' ').title())] = label
                break
    return {(field, value) for field, value in features.items() if value is not None}



def current_feature_contexts(rows, scope):
    """Use the newest CSV season as a proxy for currently relevant contexts."""
    current_season = max((int(game['season']) for game in rows), default=None)
    contexts = []
    category_fields = ('game_type', 'home_team', 'away_team', 'roof', 'surface',
                       'away_qb_name', 'home_qb_name', 'away_coach', 'home_coach',
                       'referee', 'stadium', 'dog_qb_name')
    category_scope = {field: scope[field] for field in category_fields if scope.get(field) is not None}
    for game in rows:
        if int(game['season']) != current_season or not game.get('spread_line'):
            continue
        if not matches_csv_filters(game, category_scope):
            continue
        # Upcoming rows have no scores; these placeholders only derive dog side.
        analysis = analyze_game(dict(game, home_score='0', away_score='0', result='0'))
        if analysis['is_pickem']:
            continue
        if scope.get('location') is not None and scope['location'] != analysis['dog_location']:
            continue
        if scope.get('is_primetime') is not None and scope['is_primetime'] != analysis['is_primetime']:
            continue
        contexts.append(grouped_game_features(game, analysis))
    return contexts


def upcoming_combination_contexts(rows, scope, now=None):
    """Known, unstarted games in the next seven days, using CSV Eastern times."""
    now = now or datetime.now(ZoneInfo('America/New_York'))
    contexts = []
    csv_scope = {key: value for key, value in scope.items() if key in CSV_FILTER_FIELDS or key == 'dog_qb_name'}
    for game in rows:
        if game.get('home_score', '') != '' or game.get('away_score', '') != '':
            continue
        if not game.get('gameday') or not game.get('gametime') or not game.get('spread_line'):
            continue
        try:
            kickoff = datetime.fromisoformat(f"{game['gameday']}T{game['gametime']}").replace(tzinfo=ZoneInfo('America/New_York'))
        except ValueError:
            continue
        if not now < kickoff <= now + timedelta(days=7):
            continue
        if not matches_csv_filters(game, csv_scope):
            continue
        analysis = analyze_game(dict(game, home_score='0', away_score='0', result='0'))
        if analysis['is_pickem']:
            continue
        if scope.get('location') is not None and scope['location'] != analysis['dog_location']:
            continue
        if scope.get('is_primetime') is not None and scope['is_primetime'] != analysis['is_primetime']:
            continue
        spread = analysis['dog_spread']
        if scope.get('min_spread') is not None and spread < scope['min_spread']:
            continue
        if scope.get('max_spread') is not None and spread > scope['max_spread']:
            continue
        if scope.get('exact_spread') is not None and spread != scope['exact_spread']:
            continue
        labels = {f'{field}: {value}' for field, value in grouped_game_features(game, analysis)}
        contexts.append((kickoff, labels, {
            'matchup': f"{game['away_team']} at {game['home_team']}",
            'kickoff': kickoff.strftime('%b %d, %I:%M %p ET'),
            'dog_team': analysis['dog_team'],
            'dog_location': analysis['dog_location'],
            'is_primetime': analysis['is_primetime'],
            'dog_spread': analysis['dog_spread'],
        }))
    contexts.sort(key=lambda item: item[0])
    return contexts


def prioritize_upcoming_combinations(trends, contexts):
    for trend in trends:
        conditions = set(trend['filters'])
        trend['upcoming_games'] = [info for _, labels, info in contexts if conditions <= labels]
        trend['coming_soon'] = bool(trend['upcoming_games'])
    trends.sort(key=lambda trend: (trend['coming_soon'], trend['ci_low'], trend['sample']), reverse=True)
    return trends


def group_related_combinations(trends, memberships, evaluate, evaluated=None):
    """Group by a recurring identity and compare subsets with its full baseline."""
    groups = {}
    priority = {'Underdog QB': 0, 'Home team': 1, 'Away team': 1, 'Dog location': 2}
    cache = {}
    for trend in trends:
        features = trend['_features']
        anchor = min(features, key=lambda feature: (
            priority.get(feature[0], 3), -len(memberships[feature]), feature))
        if anchor not in cache:
            cache[anchor] = evaluate(memberships[anchor])
        baseline_stats = cache[anchor]
        if anchor not in groups:
            baseline = dict(baseline_stats, filters=[f'{anchor[0]}: {anchor[1]}'])
            groups[anchor] = {'baseline': baseline, 'variants': []}
        if trend['_ids'] != memberships[anchor]:
            groups[anchor]['variants'].append(dict(
                trend, ats_difference=trend['ats_rate'] - baseline_stats['ats_rate'],
                added_filters=[f'{field}: {value}' for field, value in features if (field, value) != anchor],
            ))
    # Keep weaker subsets in the comparison too; they are not separate result cards.
    for trend in evaluated or []:
        features = trend['_features']
        anchor = min(features, key=lambda feature: (
            priority.get(feature[0], 3), -len(memberships[feature]), feature))
        if anchor not in groups or trend['_ids'] == memberships[anchor]:
            continue
        if any(variant['_ids'] == trend['_ids'] for variant in groups[anchor]['variants']):
            continue
        groups[anchor]['variants'].append(dict(
            trend, ats_difference=trend['ats_rate'] - cache[anchor]['ats_rate'],
            added_filters=[f'{field}: {value}' for field, value in features if (field, value) != anchor],
        ))
    result = []
    displayed_samples = {}
    for anchor, family in groups.items():
        baseline = family['baseline']
        variants = family['variants']
        variants.sort(key=lambda trend: (trend['coming_soon'], trend['ci_low'], trend['sample']), reverse=True)
        if baseline['ats_rate'] >= 55:
            leader = dict(baseline, status='Emerging' if baseline['sample'] < 10 else 'Established Sample', note=None)
        elif any(variant['ats_rate'] >= 55 for variant in variants):
            leader = dict(next(variant for variant in variants if variant['ats_rate'] >= 55))
        else:
            continue
        leader_ids = memberships[anchor] if leader['filters'] == baseline['filters'] else leader['_ids']
        if leader_ids in displayed_samples:
            displayed_samples[leader_ids]['equivalent_filters'].append(leader['filters'])
            continue
        leader['_ids'] = leader_ids
        leader['equivalent_filters'] = []
        displayed_samples[leader_ids] = leader
        leader['baseline'] = baseline
        variants.sort(key=lambda trend: (trend['coming_soon'], abs(trend['ats_difference']), trend['sample']), reverse=True)
        leader['related'] = variants[:8]
        leader['related_count'] = len(variants)
        leader['baseline_is_main'] = leader['filters'] == baseline['filters']
        result.append(leader)
    return result


def selected_finished_games(rows, season, scope):
    """One selection rule for discovery, evidence, and the matching-games page."""
    csv_scope = {key: value for key, value in scope.items() if key in CSV_FILTER_FIELDS or key == 'dog_qb_name'}
    for game in rows:
        if any(game.get(field, '') == '' for field in ('home_score', 'away_score', 'result', 'spread_line')):
            continue
        if season is not None:
            year = int(game['season'])
            if isinstance(season, (tuple, list)):
                if not season[0] <= year <= season[1]:
                    continue
            elif year != int(season):
                continue
        if not matches_csv_filters(game, csv_scope):
            continue
        analysis = analyze_game(game)
        if analysis['is_pickem']:
            continue
        if scope.get('location') is not None and scope['location'] != analysis['dog_location']:
            continue
        if scope.get('is_primetime') is not None and scope['is_primetime'] != analysis['is_primetime']:
            continue
        spread = analysis['dog_spread']
        if scope.get('min_spread') is not None and spread < scope['min_spread']:
            continue
        if scope.get('max_spread') is not None and spread > scope['max_spread']:
            continue
        if scope.get('exact_spread') is not None and spread != scope['exact_spread']:
            continue
        yield game, analysis


def evidence_game(game, analysis):
    return {
        'game_id': game['game_id'], 'season': int(game['season']),
        'gameday': game['gameday'], 'away_team': game['away_team'],
        'home_team': game['home_team'], 'away_score': int(game['away_score']),
        'home_score': int(game['home_score']), 'dog_team': analysis['dog_team'],
        'dog_spread': analysis['dog_spread'],
        'ats_result': 'Push' if analysis['dog_push'] else 'Win' if analysis['dog_covered'] else 'Loss',
    }


def summarize_evidence_games(games):
    wins = sum(game['ats_result'] == 'Win' for game in games)
    losses = sum(game['ats_result'] == 'Loss' for game in games)
    pushes = sum(game['ats_result'] == 'Push' for game in games)
    decisions = wins + losses
    return dict(sample=len(games), ats_wins=wins, ats_losses=losses, ats_pushes=pushes,
                ats_rate=(wins / decisions) * 100 if decisions else None)


def build_trend_evidence(games, current_season):
    years = sorted({game['season'] for game in games}, reverse=True)
    periods = [
        ('All selected seasons', games),
        (f'Before {current_season}', [game for game in games if game['season'] < current_season]),
        (f'{current_season-3}–{current_season-1} (subset)', [game for game in games if current_season-3 <= game['season'] < current_season]),
        (f'{current_season} season', [game for game in games if game['season'] == current_season]),
    ]
    return dict(
        periods=[dict(summarize_evidence_games(subset), label=label) for label, subset in periods],
        seasons=[dict(summarize_evidence_games([game for game in games if game['season'] == year]), label=str(year)) for year in years],
        first_game=min((game['gameday'] for game in games), default=None),
        latest_game=max((game['gameday'] for game in games), default=None),
    )


def find_matching_trend_games(conditions, season=None, **scope):
    with open(game_file, newline='') as source:
        rows = effective_rows(csv.DictReader(source), game_file)
    matches = []
    for game, analysis in selected_finished_games(rows, season, scope):
        labels = {f'{field}: {value}' for field, value in grouped_game_features(game, analysis)}
        if set(conditions) <= labels:
            matches.append(evidence_game(game, analysis))
    matches.sort(key=lambda game: (game['gameday'], game['game_id']), reverse=True)
    return matches


def trend_data_status():
    with open(game_file, newline='') as source:
        rows = effective_rows(csv.DictReader(source), game_file)
    finished = [game['gameday'] for game in rows if game.get('home_score', '') != '' and game.get('away_score', '') != '']
    return dict(
        modified=datetime.fromtimestamp(game_file.stat().st_mtime, ZoneInfo('America/New_York')).strftime('%b %d, %Y, %I:%M %p ET'),
        latest_result=max(finished, default='No completed games'),
        current_season=max((int(game['season']) for game in rows), default=None),
    )


def scan_grouped_combinations(season=None, max_depth=3, beam_width=150, limit=100, **scope):
    """Bounded feature intersections; prune rare groups before expanding."""
    minimum = combination_min_games(season)
    with open(game_file, newline='') as source:
        rows = effective_rows(csv.DictReader(source), game_file)
    current_contexts = current_feature_contexts(rows, scope)
    current_memberships = {}
    for index, context in enumerate(current_contexts):
        for feature in context:
            current_memberships.setdefault(feature, set()).add(index)
    if not current_contexts:
        return []
    analyses = []
    memberships = {}
    selected_rows = []
    for game, analysis in selected_finished_games(rows, season, scope):
        selected_rows.append(game)
        index = len(analyses)
        analyses.append(analysis)
        for feature in grouped_game_features(game, analysis):
            memberships.setdefault(feature, set()).add(index)
    memberships = {feature: frozenset(ids) for feature, ids in memberships.items() if len(ids) >= minimum and feature in current_memberships}

    def evaluate(ids):
        total = len(ids)
        wins = sum(analyses[i]['dog_won'] for i in ids)
        covers = sum(analyses[i]['dog_covered'] for i in ids)
        pushes = sum(analyses[i]['dog_push'] for i in ids)
        zero = dict(total=0, wins=0, covers=0, pushes=0)
        return evaluate_trend({'all_games': {
            'home': dict(total=total, wins=wins, covers=covers, pushes=pushes),
            'away': zero,
        }})

    frontier = [((), frozenset(range(len(analyses))))]
    seen = set()
    found = []
    evaluated = []
    features = sorted(memberships)
    for depth in range(1, max_depth + 1):
        candidates = []
        for selected, parent_ids in frontier:
            for feature in features:
                if selected and feature <= selected[-1]:
                    continue
                if any(field == feature[0] for field, _ in selected):
                    continue
                viable = current_memberships[feature].copy()
                for existing in selected:
                    viable.intersection_update(current_memberships[existing])
                if not viable:
                    continue
                ids = parent_ids & memberships[feature]
                if len(ids) < minimum or ids in seen:
                    continue
                seen.add(ids)
                stats = evaluate(ids)
                if stats is None:
                    continue
                chosen = selected + (feature,)
                candidates.append((chosen, ids, stats))
                candidate = dict(stats, filters=[f'{field}: {value}' for field, value in chosen],
                                 _features=chosen, _ids=ids,
                                 status='Emerging' if len(ids) < 10 else 'Established Sample', note=None)
                evaluated.append(candidate)
                if stats['ats_rate'] >= 55:
                    found.append(candidate)
        candidates.sort(key=lambda item: (item[2]['ci_low'], item[2]['sample']), reverse=True)
        frontier = [(chosen, ids) for chosen, ids, _ in candidates[:beam_width]]
        if not frontier:
            break
    contexts = upcoming_combination_contexts(rows, scope)
    prioritize_upcoming_combinations(evaluated, contexts)
    prioritize_upcoming_combinations(found, contexts)
    retained = found[:limit]
    groups = group_related_combinations(retained, memberships, evaluate, evaluated)
    prioritize_upcoming_combinations(groups, contexts)
    current_season = max(int(game['season']) for game in rows)
    for group in groups:
        group['retained_count'] = len(retained)
        matching_games = [evidence_game(selected_rows[index], analyses[index]) for index in group['_ids']]
        group['evidence'] = build_trend_evidence(matching_games, current_season)
        group['validation_label'] = 'Emerging · Exploratory' if group['sample'] < 30 else 'Exploratory historical pattern' 
    return groups

_basic_trends_lock = RLock()


def _trend_data_signature():
    root = game_file.resolve().parent
    paths = (game_file.resolve(), root / 'manual_spread_overrides.csv',
             root / 'public_money_snapshots.csv')
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                 if path.exists() else (str(path), None, None) for path in paths)


@lru_cache(maxsize=32)
def _cached_basic_trends(signature, season, scope):
    return _scan_basic_trends(season=season, **dict(scope))


def scan_basic_trends(season=None, **scope):
    # Avoid duplicate scans on concurrent visits; callers receive their own copy.
    if isinstance(season, list):
        season = tuple(season)
    with _basic_trends_lock:
        return deepcopy(_cached_basic_trends(
            _trend_data_signature(), season, tuple(sorted(scope.items()))))


def _scan_basic_trends(season=None, **scope):
    trends = []
    with open(game_file, newline='') as game_check:
        games = effective_rows(csv.DictReader(game_check), game_file)

    csv_scope = {key: value for key, value in scope.items() if key in CSV_FILTER_FIELDS or key == 'dog_qb_name'}
    games = [game for game in games if matches_csv_filters(game, csv_scope)]

    spread_ranges = [
        ('All Spreads', None, None),
        ('0.5-3', 0.5, 3.0),
        ('3.5-6.5', 3.5, 6.5),
        ('7-9.5', 7.0, 9.5),
        ('10+', 10.0, None),
    ]
    existing_ranges = {
        (minimum, maximum)
        for _, minimum, maximum in spread_ranges}
    for half_point in range(1, 46):
        minimum = half_point / 2
        maximum = minimum + 2.5
        if (minimum, maximum) in existing_ranges:
            continue
        label = f'{minimum:g}-{maximum:g}'
        spread_ranges.append((label, minimum, maximum))
    

    for location in ['Home', 'Away']:
        if scope.get('location') is not None and scope['location'] != location:
            continue
        for is_primetime in [True, False]:
            if scope.get('is_primetime') is not None and scope['is_primetime'] != is_primetime:
                continue
            for spread_label, min_spread, max_spread in spread_ranges: 
                filters = {
                    "location": location,
                    "is_primetime": is_primetime,
                    "game_type": "REG",               
                }
                if min_spread is not None:
                    filters['min_spread'] = min_spread
                if max_spread is not None:
                    filters['max_spread'] = max_spread
                if season is not None:
                    filters['season'] = season
                if 'game_type' in csv_scope:
                    filters['game_type'] = csv_scope['game_type']
                if scope.get('min_spread') is not None:
                    filters['min_spread'] = max(min_spread or 0, scope['min_spread'])
                if scope.get('max_spread') is not None:
                    filters['max_spread'] = min(max_spread if max_spread is not None else math.inf, scope['max_spread'])
                if scope.get('exact_spread') is not None:
                    filters['exact_spread'] = scope['exact_spread']
                stats = Check_Games(games, **filters)
                trend = evaluate_trend(stats)


                if trend is None:
                    continue
                if trend['dog_no_push'] < 10:
                    trend_status = 'Emerging'
                    note = 'Very Small Sample Size - Inetersting But Uncertain'
                elif trend['dog_no_push'] < 30:
                    trend_status = 'Small Sample'
                    note = 'Early Trend - Need More Games'
                else:
                    trend_status = 'Established Sample'
                    note = None
                trends.append({
                    "location": location,
                    "primetime": is_primetime,
                    "spread": spread_label,
                    "sample": trend['sample'],
                    "ats_rate": trend['ats_rate'],
                    "ats_edge": trend['ats_edge'],
                    "ci_low": trend['ci_low'],
                    "ci_high": trend['ci_high'],
                    "signal": trend['signal'],
                    "status": trend_status,
                    "note": note,
                    "season": season if season is not None else 'All',
                    "su_wins": trend['su_wins'],
                    "su_rate": trend['su_rate'],
                    "min_spread": min_spread,
                    "max_spread": max_spread,
                    "dog_no_push": trend['dog_no_push'],
                })
    trends.sort(
        key=lambda trend: trend['ci_low'], reverse=True
    )        
    return trends
def compare_trends(current_trends, historical_trends):
    historical_lookup = {}
   
    for trend in historical_trends:
        key = (
            trend['location'],
            trend['primetime'],
            trend['spread']
        )
        historical_lookup[key] = trend
    comparisons = []

    for current in current_trends:
        key = (
            current['location'],
            current['primetime'],
            current['spread']
        )
        historical = historical_lookup.get(key)

        if historical is None:
            continue
        su_difference = (
            current['su_rate'] - historical['su_rate']
        )
        ats_difference = (
            current['ats_rate'] - historical['ats_rate']
        )
        if ats_difference > 0:
            direction = 'Above Historical'
        elif ats_difference < 0:
            direction = 'Below Historical'
        else:
            direction = 'Matches Historical'
        comparisons.append({
            "location": current["location"],
            "primetime": current["primetime"],
            "spread": current["spread"],

            "current_sample": current["sample"],
            "current_su_wins": current['su_wins'],
            "current_su_rate": current["su_rate"],
            "current_ats_rate": current["ats_rate"],

            "historical_sample": historical["sample"],
            "historical_su_wins": historical['su_wins'],
            "historical_su_rate": historical["su_rate"],
            "historical_ats_rate": historical["ats_rate"],
            "historical_ci_low": historical['ci_low'],

            "su_difference": su_difference,
            "ats_difference": ats_difference,
            "dog_no_push": current['dog_no_push'],
            "historical_ats_decisions": historical['dog_no_push'],
            "current_ci_low": current['ci_low'],
           
            "status": current["status"],
            "note": current["note"],
            "direction": direction,
            "min_spread": current['min_spread'],
            "max_spread": current['max_spread'],
        })
    
    return comparisons

def match_upcoming_game(
        comparisons,
        dog_location,
        is_primetime,
        dog_spread,
):
    matches = []
    for trend in comparisons:
        if trend['location'] != dog_location:
            continue
        if trend['primetime'] != is_primetime:
            continue
        minimun = trend['min_spread']
        maximum = trend['max_spread']
        if minimun is not None and dog_spread < minimun:
            continue
        if maximum is not None and dog_spread > maximum:
            continue
        matches.append(trend)
    return matches

def print_comparisons(comparisons):
    comparisons.sort(key=lambda comparison: abs(comparison['ats_difference']), reverse=True)
    print()
    print("========== CURRENT VS HISTORICAL ==========")

    for index, comparison in enumerate(comparisons, start=1):
        primetime_label = (
            "PrimeTime"
            if comparison["primetime"]
            else "Non-PrimeTime"
        )

        current_losses = (
            comparison["current_sample"]
            - comparison["current_su_wins"]
        )

        historical_losses = (
            comparison["historical_sample"]
            - comparison["historical_su_wins"]
        )

        print()
        print(
            f"{index}. {comparison['location']} | "
            f"{primetime_label} | "
            f"Spread: {comparison['spread']}"
        )

        print()
        print("   2026")
        print(f"   Sample: {comparison['current_sample']}")
        print(
            f"   SU: {comparison['current_su_wins']}-"
            f"{current_losses} "
            f"({comparison['current_su_rate']:.2f}%)"
        )
        print(
            f"   ATS Rate: "
            f"{comparison['current_ats_rate']:.2f}%"
        )

        print()
        print("   HISTORICAL")
        print(f"   Sample: {comparison['historical_sample']}")
        print(
            f"   SU: {comparison['historical_su_wins']}-"
            f"{historical_losses} "
            f"({comparison['historical_su_rate']:.2f}%)"
        )
        print(
            f"   ATS Rate: "
            f"{comparison['historical_ats_rate']:.2f}%"
        )

        print()
        print(
            f"   SU Difference: "
            f"{comparison['su_difference']:+.2f} pts"
        )
        print(
            f"   ATS Difference: "
            f"{comparison['ats_difference']:+.2f} pts"
        )

        print(f"   Status: {comparison['status']}")

        if comparison["note"] is not None:
            print(f"   Note: {comparison['note']}")
        print(f"   Direction: {comparison['direction']}")


def print_trends(trends, title):
    print()
    print(f'============== {title} ===============')

    for index, trend in enumerate(trends, start=1):
        primetime_label = 'PrimeTime' if trend['primetime'] else 'Non-PrimeTime'

        print()
        print(f'''{index}. {trend['location']} | {primetime_label} | Spread: {trend['spread']} | {trend['season']} 
    Sample : {trend['sample']}
    SU: {trend['su_wins']}-{trend['sample'] - trend['su_wins']} ({trend['su_rate']:.2f}%)
    ATS Rate: {trend['ats_rate']:.2f}%
    
    95% CI: {trend['ci_low']:.2f}% - {trend['ci_high']:.2f}%
    Signal: {trend['signal']}
    Status: {trend['status']}
    {trend['note']}
    ''')

    
            
if __name__ == '__main__':
    
    main_menu()

