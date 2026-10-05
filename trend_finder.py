#!/usr/bin/env python3

from pathlib import Path
import csv

game_file = Path('nfl_games.csv')



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

        




def Check_Games(reader):
    all_total_games = 0
    primetime_games = 0
    all_pickems = 0
    pick_ems = 0
    pick_em_home = 0
    pick_em_away= 0
    prime_pickem_push = 0
    all_pickem_home = 0
    all_pickems_away = 0
    all_pickems_push = 0
    total_home_dogs = 0
    total_away_dogs = 0
    all_dogs = 0
    all_home_dog = 0
    all_away_dogs = 0
    dog_wins = 0
    away_wins = 0
    all_home_dog_wins = 0
    all_away_dog_wins = 0
    covers = 0
    away_covers = 0
    all_home_dog_covers = 0
    all_away_dog_covers = 0
    push = 0
    away_push = 0
    all_dog_home_push = 0
    all_dog_away_push = 0
    pickem_winners = []
    pickem_locations = []
    pickem_seasons = []

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
        all_total_games += 1
        analysis = analyze_game(game)
        if analysis["dog_location"] == 'Home':
            all_dogs += 1  
            all_home_dog += 1
            if analysis['dog_won']:
                all_home_dog_wins += 1
            if analysis['dog_covered']:
                all_home_dog_covers += 1
            if analysis['dog_push']:
                all_dog_home_push += 1
        elif analysis['is_pickem']:
                pickem_seasons.append(game['season'])
                all_pickems += 1
                if analysis['pickem_winner'] is not None:
                    pickem_winners.append(analysis['pickem_winner'])
                if analysis['pickem_location'] is not None:
                    pickem_locations.append(analysis['pickem_location'])
                if analysis['pickem_location'] == 'Home':
                    all_pickem_home +=1
                if analysis['pickem_location'] == 'Away':
                    all_pickems_away += 1
                if analysis['pickem_winner'] == None:
                    all_pickems_push += 1
        elif analysis['dog_location'] == 'Away':
            all_dogs += 1 
            all_away_dogs += 1
            if analysis['dog_won']:
                all_away_dog_wins += 1
            if analysis['dog_covered']:
                all_away_dog_covers += 1
            if analysis['dog_push']:
                all_dog_away_push += 1
        if analysis["is_primetime"]:
            primetime_games += 1
            if analysis['dog_location'] == 'Home':
                total_home_dogs += 1
                if analysis['dog_won']:
                    dog_wins += 1
                if analysis['dog_covered']:
                    covers += 1
                if analysis['dog_push']:
                    push += 1
            elif analysis['is_pickem']:
                pick_ems += 1
                if analysis['pickem_location'] == 'Home':
                    pick_em_home += 1
                if analysis['pickem_location'] == 'Away':
                    pick_em_away += 1
                if analysis['pickem_winner'] == None:
                    prime_pickem_push += 1
            elif analysis['dog_location'] == 'Away':
                total_away_dogs += 1
                if analysis['dog_won']:
                    away_wins += 1
                if analysis['dog_covered']:
                    away_covers += 1
                if analysis['dog_push']:
                    away_push += 1

    all_dog_wins = all_home_dog_wins + all_away_dog_wins
    all_dog_push = all_dog_away_push + all_dog_home_push
    total_all_dogs = all_home_dog + all_away_dogs
    all_no_push = total_all_dogs - all_dog_push
    all_dog_covers = all_away_dog_covers + all_home_dog_covers
    all_ats_no_push = (all_dog_covers / all_no_push) * 100
    all_dog_atsrate = (all_dog_covers / total_all_dogs) * 100
    all_dog_win_rate = (all_dog_wins / total_all_dogs) * 100
    all_homedog_losses = all_home_dog - (all_home_dog_covers + all_dog_home_push)
    all_awaydog_losses = all_away_dogs - (all_away_dog_covers + all_dog_away_push)
    all_dog_losses = all_homedog_losses + all_awaydog_losses    
    all_total_pickems = all_pickems_push + all_pickems_away + all_pickem_home

    primetime_dogs = total_away_dogs + total_home_dogs
    home_dog_losses = total_home_dogs - (covers + push) 
    away_dog_losses = total_away_dogs - (away_covers + away_push)          
    total_losses = away_dog_losses + home_dog_losses    
    primetime_dog_wins = away_wins + dog_wins 
    primetime_dog_covers = covers + away_covers
    primetime_push = away_push + push
    ats_cover_rate = (primetime_dog_covers / primetime_dogs) * 100 
    dog_win_rate = (primetime_dog_wins / primetime_dogs) * 100 
    dogs_no_push = primetime_dogs - primetime_push             
    ats_cover_rate_no_push = (primetime_dog_covers / dogs_no_push ) * 100 
   
    

    stats = {
        'all_total_games': all_total_games,
        'all_dogs': all_dogs,
        'all_home_dog': all_home_dog,
        'all_home_dog_wins': all_home_dog_wins,
        'all_home_dog_covers': all_home_dog_covers,
        'all_dog_home_push': all_dog_home_push,
        'all_homedog_losses': all_homedog_losses,
        'all_away_dogs': all_away_dogs,
        'all_away_dog_wins': all_away_dog_wins,
        'all_away_dog_covers': all_away_dog_covers,
        'all_dog_away_push': all_dog_away_push,
        'all_awaydog_losses': all_awaydog_losses,
        'all_total_pickems': all_total_pickems,
        'all_pickem_home': all_pickem_home,
        'all_pickems_away': all_pickems_away,
        'all_pickems_push': all_pickems_push,
        'all_dog_wins': all_dog_wins,
        'all_dog_covers': all_dog_covers,
        'all_dog_losses': all_dog_losses,
        'all_dog_push': all_dog_push,
        'all_dog_win_rate': all_dog_win_rate,
        'all_dog_atsrate': all_dog_atsrate,
        'all_ats_no_push': all_ats_no_push,
        'primetime_games': primetime_games,
        'primetime_dogs': primetime_dogs,
        'total_home_dogs': total_home_dogs,
        'dog_wins': dog_wins,
        'covers': covers,
        'push': push,
        'home_dog_losses': home_dog_losses,
        'total_away_dogs': total_away_dogs,
        'away_wins': away_wins,
        'away_covers': away_covers,
        'away_push': away_push,
        'away_dog_losses': away_dog_losses,
        'pick_ems': pick_ems,
        'pick_em_home': pick_em_home,
        'pick_em_away': pick_em_away,
        'prime_pickem_push': prime_pickem_push,
        'primetime_dog_wins': primetime_dog_wins,
        'primetime_dog_covers': primetime_dog_covers,
        'total_losses': total_losses,
        'primetime_push': primetime_push,
        'dog_win_rate': dog_win_rate,
        'ats_cover_rate': ats_cover_rate,
        'ats_cover_rate_no_push': ats_cover_rate_no_push,
        'pickem_winners': pickem_winners,
        'pickem_locations': pickem_locations,
        'pickem_seasons': pickem_seasons
    }
    print_report(stats)


def print_report(stats):
    print(f'_________________________________')
    print(f'           PrimeTime Dogs')
    print(f'=================================')
    print()
    print(f'''Total PrimeTime Games: {stats['primetime_games']}
PrimeTime Dogs {stats['primetime_dogs']}
Total PrimeTime Home Dogs: {stats['total_home_dogs']}
PrimeTime Home Dog Straight Up Wins: {stats['dog_wins']}
PrimeTime Home Dog Covers: {stats['covers']}
PrimeTime Home Dog Pushes: {stats['push']}
PrimeTime Home Dog Losses: {stats['home_dog_losses']}
Total PrimeTime Away Dogs: {stats['total_away_dogs']}
PrimeTime Away Dog Straight Up Wins: {stats['away_wins']}
PrimeTime Away Dog Covers: {stats['away_covers']}
PrimeTime Away Dog Pushes: {stats['away_push']}
PrimeTime Away Dog Losses: {stats['away_dog_losses']}
Total PrimeTime Pick Em"s: {stats['pick_ems']}
PrimeTime Pick Em" Home Wins: {stats['pick_em_home']}
PrimeTime Pick Em" Away Wins: {stats['pick_em_away']}
PrimeTime Pick Em" Pushes: {stats['prime_pickem_push']}
PrimeTime Total Dog Straight Up Wins: {stats['primetime_dog_wins']}
PrimeTime Total Dog Covers: {stats['primetime_dog_covers']}
PrimeTime Total Dog Losses: {stats['total_losses']}
PrimeTime Total Dog Pushes: {stats['primetime_push']}
PrimeTime Dog Straight Up Win Rate: {stats['dog_win_rate']:.2f}%
PrimeTime Dog ATS Cover Rate: {stats['ats_cover_rate']:.2f}%
PrimeTime Dog ATS Cover Rate Excluding Pushes: {stats['ats_cover_rate_no_push']:.2f}%''')
    print()
    print(f'_________________________________')
    print(f'         All Underdogs')
    print(f'=================================')
    print(f'''Total Games: {stats['all_total_games']}
All Underdogs: {stats['all_dogs']}
All Home Dogs: {stats['all_home_dog']}
All Home Dog Straight Up Wins: {stats['all_home_dog_wins']}
All Home Dog Covers: {stats['all_home_dog_covers']}
All Home Dog Pushes: {stats['all_dog_home_push']}
All Home Dog Losses: {stats['all_homedog_losses']}
All Away Dogs: {stats['all_away_dogs']}
All Away Dog Straight Up Wins: {stats['all_away_dog_wins']}
All Away Dog Covers: {stats['all_away_dog_covers']}
All Away Dog Pushes: {stats['all_dog_away_push']}
All Away Dog Losses: {stats['all_awaydog_losses']}
All Pick Em"s: {stats['all_total_pickems']}
All Pick Em" Home Wins: {stats['all_pickem_home']}
All Pick Em" Away Wins: {stats['all_pickems_away']}
All Pick Em Pushes: {stats['all_pickems_push']}
All Total Dog Straight Up Wins: {stats['all_dog_wins']}
All Total Dog Covers: {stats['all_dog_covers']}
All Total Dog Losses: {stats['all_dog_losses']}
All Total Dog Pushes: {stats['all_dog_push']}
All Dog Straight Up Win Rate: {stats['all_dog_win_rate']:.2f}%
All Dog ATS Cover Rate: {stats['all_dog_atsrate']:.2f}%
All Dog ATS Cover Rate Excluding Pushes: {stats['all_ats_no_push']:.2f}%
''')

    print('_________________________________')
    print(f'        Pick Em"s')
    print(f'================================')
    for winner, location, seasons in zip(stats['pickem_winners'], stats['pickem_locations'], stats['pickem_seasons']):
        print(f'Pick Em" Winners: {winner:<5}-  {location} {seasons}')
    

    
try:
    with open(game_file, "r") as game_check:
        reader = csv.DictReader(game_check)
        Check_Games(reader)
except FileNotFoundError:
    print('Error: Game file not found.')

