#!/usr/bin/env python3

from pathlib import Path
import csv
import re
game_file = Path('nfl_games.csv')

def get_choice(number_of_choices):
    try:
        choice = int(input('Please enter the number of your answer: '))
    except ValueError:
        print(f'Your choice has to be a number between 1 and {number_of_choices}')
        return get_choice(number_of_choices)
    if 1 <= choice <= number_of_choices:
        return choice
    else:
        print(f'Your choice has to be a number between 1 and {number_of_choices}')
        return get_choice(number_of_choices)



print()
print(f'=================================')
print(f'*********************************')
print(f'||    The Trend Findah 3000    ||')
print(f'*********************************')
print(f'=================================')
print()



def analyze_game(game):
    spread_line = float(game['spread_line'])
    home_score = int(game['home_score'])
    away_score = int(game['away_score'])
    result = float(game['result'])
    home_team = game['home_team']
    away_team = game['away_team']
    is_primetime = False
    is_pickem = False
    dog_won = False
    dog_covered = False
    dog_push = False
    dog_team = None
    dog_location = None
    pickem_winner = None
    pickem_location = None

    if game['gametime'] >= '19:00':
        is_primetime = True
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
        "dog_won": dog_won,
        "dog_push": dog_push,
        "dog_covered": dog_covered,
        "pickem_winner": pickem_winner,
        "pickem_location": pickem_location
        }
    return analysis

        




def Check_Games(reader, season=None, week=None, gametime=None, location=None, is_primetime=None, min_spread=None, max_spread=None, home_team=None, away_team=None, home_score=None, away_score=None, result=None, game_id=None, overtime=None, away_rest=None, home_rest=None, spread_line=None, total_line=None, roof=None, surface=None, temp=None, wind=None, away_qb_name=None, home_qb_name=None, away_coach=None, home_coach=None, referee=None, stadium=None):
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
        if game['gametime'] == '':
            continue
        if game['spread_line'] == '':
            continue
        if game['result'] == '':
            continue
        if season is not None:
            if isinstance(season, tuple):
                game['season'] = int(game['season'])
                if not season[0] <= game['season'] <= season[1]:
                    continue
            elif game['season'] != season:
                continue
        analysis = analyze_game(game)
        if is_primetime is not None and analysis['is_primetime'] != is_primetime:
            continue
        if location is not None and analysis['dog_location'] != location:
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
                    
    print_report(stats)


def print_report(stats):
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
    all_no_push = total_all_dogs - all_dog_push
    all_dog_covers = stats['all_games']['away']['covers'] + stats['all_games']['home']['covers']
    all_ats_no_push = (all_dog_covers / all_no_push) * 100
    all_dog_atsrate = (all_dog_covers / total_all_dogs) * 100
    all_dog_win_rate = (all_dog_wins / total_all_dogs) * 100
    all_homedog_losses = stats['all_games']['home']['total'] - (stats['all_games']['home']['covers'] + stats['all_games']['home']['pushes'])
    all_awaydog_losses = stats['all_games']['away']['total'] - (stats['all_games']['away']['covers'] + stats['all_games']['away']['pushes'])
    all_dog_losses = all_homedog_losses + all_awaydog_losses    

    primetime_dogs = stats['primetime_games']['home']['total'] + stats['primetime_games']['away']['total']
    home_dog_losses = stats['primetime_games']['home']['total'] - (stats['primetime_games']['home']['covers'] + stats['primetime_games']['home']['pushes'])
    away_dog_losses = stats['primetime_games']['away']['total'] - (stats['primetime_games']['away']['pushes'] + stats['primetime_games']['away']['covers'])         
    total_losses = away_dog_losses + home_dog_losses    
    primetime_dog_wins = stats['primetime_games']['home']['wins'] + stats['primetime_games']['away']['wins']
    primetime_dog_covers = stats['primetime_games']['home']['covers'] + stats['primetime_games']['away']['covers']
    primetime_push = stats['primetime_games']['home']['pushes'] + stats['primetime_games']['away']['pushes']
    ats_cover_rate = (primetime_dog_covers / primetime_dogs) * 100 
    dog_win_rate = (primetime_dog_wins / primetime_dogs) * 100 
    dogs_no_push = primetime_dogs - primetime_push             
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
    while True:
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
        spread_line = None
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
        print()
        print('Choice')
        print()
        print(f'''1. All Seasons
2. Single Season
3. Season Range
4. PrimeTime Only
5. Home Dogs/Away Dogs
6. Quit
''')
        print()
        choice = get_choice(6)
        match choice:
            case 1:
                season = None
            case 2:
                try:
                    print()
                    season = int(input('Please Enter A Season: '))
                    print()
                except ValueError:
                    print('Please Enter A Valid Year From 1999 - 2026')
                    continue
                if 1999 <= season <= 2026:
                    print('Valid Season')
                    season = str(season)
                else: 
                    print('Please Enter A Valid Year From 1999 - 2026')
                    continue
            case 3:
                try:
                    start_season_limit = 1999
                    end_season_limit = 2026
                    print()
                    print('Please Select A Range')
                    print()
                    start_season = int(input('Enter Your Start Date: '))
                    print()
                    end_season = int(input('Enter Your End Date: '))
                except ValueError:
                    print('Please Enter A Valid Range From 1999 - 2026')
                    continue
                if start_season_limit <= start_season <= end_season <= end_season_limit:
                    print(f'Valid Range: {start_season} - {end_season}')
                    season = start_season, end_season
                else:
                    print('Enter A Valid Range From 1999 - 2026')
                    continue
            case 4:
                is_primetime = True
            case 5:
                print('Do You Want To See Home Or Away Dogs?')
                print()
                print('''1. Home Dogs'
2. Away Dogs
3. All Dogs
''')
                print()
                dog_choice = get_choice(3)
                match dog_choice:
                    case 1:
                        location = 'Home'
                    case 2:
                        location = 'Away'
                    case 3:
                        location = None 
            case 6:
                print('Trend Findah 3000 Signing Out!!')
                return
            
        try:
            with open(game_file, "r") as game_check:
                reader = csv.DictReader(game_check)
                Check_Games(reader, season=season, location=location, gametime=gametime, is_primetime=is_primetime, week=week, home_team=home_team, min_spread=min_spread, max_spread=max_spread, away_team=away_team, home_score=home_score, away_score=away_score, result=result, game_id=game_id, overtime=overtime, home_rest=home_rest, away_rest=away_rest, spread_line=spread_line, total_line=total_line, roof=roof, surface=surface, temp=temp, wind=wind, away_qb_name=away_qb_name, home_qb_name=home_qb_name, away_coach=away_coach, home_coach=home_coach, referee=referee, stadium=stadium)
        except FileNotFoundError:
            print('Error: Game file not found.')
main_menu()

