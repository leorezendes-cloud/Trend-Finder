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


def Check_Games(reader):
    all_total_games = 0
    total_games = 0
    all_pickems = 0
    pick_ems = 0
    pick_em_home = 0
    pick_em_away= 0
    prime_pickem_push = 0
    all_pickem_home = 0
    all_pickems_away = 0
    all_pickems_push = 0
    total_dogs = 0
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
    for game in reader:
        all_total_games += 1
        if game['gametime'] == '':
            continue
        if game['spread_line'] == '':
            continue
        if game['result'] == '':
            continue
        spread_line = float(game['spread_line'])
        home_team = game['home_team']
        home_score = int(game['home_score'])
        away_score = int(game['away_score'])
        result = float(game['result'])
        all_dogs += 1 
        if spread_line < 0.0:
            all_home_dog += 1
            if home_score > away_score:
                all_home_dog_wins += 1
            if result > spread_line:
                all_home_dog_covers += 1
            if result == spread_line:
                all_dog_home_push += 1
        elif spread_line == 0:
                all_pickems += 1
                if home_score > away_score:
                    all_pickem_home +=1
                if home_score < away_score:
                    all_pickems_away += 1
                if home_score == away_score:
                    all_pickems_push += 1
        elif  spread_line > 0.0:
            all_away_dogs += 1
            if home_score < away_score:
                all_away_dog_wins += 1
            if result < spread_line:
                all_away_dog_covers += 1
            if result == spread_line:
                all_dog_away_push += 1
        if game['gametime'] >= '19:00':
            total_games += 1
            if spread_line < 0.0:
                total_dogs += 1
                if home_score > away_score:
                    dog_wins += 1
                if result > spread_line:
                    covers += 1
                if result == spread_line:
                    push += 1
            elif spread_line == 0:
                pick_ems += 1
                if home_score > away_score:
                    pick_em_home += 1
                if home_score < away_score:
                    pick_em_away += 1
                if home_score == away_score:
                    prime_pickem_push += 1
            elif spread_line > 0.0:
                total_away_dogs += 1
                if home_score < away_score:
                    away_wins += 1
                if result < spread_line:
                    away_covers += 1
                if result == spread_line:
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

    primetime_dogs = total_away_dogs + total_dogs
    home_dog_losses = total_dogs - (covers + push) 
    away_dog_losses = total_away_dogs - (away_covers + away_push)          
    total_losses = away_dog_losses + home_dog_losses    
    primetime_dog_wins = away_wins + dog_wins 
    primetime_dog_covers = covers + away_covers
    primetime_push = away_push + push
    ats_cover_rate = (primetime_dog_covers / primetime_dogs) * 100 
    dog_win_rate = (primetime_dog_wins / primetime_dogs) * 100 
    dogs_no_push = primetime_dogs - primetime_push             
    ats_cover_rate_no_push = (primetime_dog_covers / dogs_no_push ) * 100 

    print(f'_________________________________')
    print(f'           PrimeTime Dogs')
    print(f'=================================')
    print()
    print(f'''Total PrimeTime Games: {total_games}
PrimeTime Dogs {primetime_dogs}
Total PrimeTime Home Dogs: {total_dogs}
PrimeTime Home Dog Straight Up Wins: {dog_wins}
PrimeTime Home Dog Covers: {covers}
PrimeTime Home Dog Pushes: {push}
PrimeTime Home Dog Losses: {home_dog_losses}
Total PrimeTime Away Dogs: {total_away_dogs}
PrimeTime Away Dog Straight Up Wins: {away_wins}
PrimeTime Away Dog Covers: {away_covers}
PrimeTime Away Dog Pushes: {away_push}
PrimeTime Away Dog Losses: {away_dog_losses}
Total PrimeTime Pick Em"s: {pick_ems}
PrimeTime Pick Em" Home Wins: {pick_em_home}
PrimeTime Pick Em" Away Wins: {pick_em_away}
PrimeTime Pick Em" Pushes: {prime_pickem_push}
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
    print(f'''Total Games: {all_total_games}
All Underdogs: {all_dogs}
All Home Dogs: {all_home_dog}
All Home Dog Straight Up Wins: {all_home_dog_wins}
All Home Dog Covers: {all_home_dog_covers}
All Home Dog Pushes: {all_dog_home_push}
All Home Dog Losses: {all_homedog_losses}
All Away Dogs: {all_away_dogs}
All Away Dog Straight Up Wins: {all_away_dog_wins}
All Away Dog Covers: {all_away_dog_covers}
All Away Dog Pushes: {all_dog_away_push}
All Away Dog Losses: {all_awaydog_losses}
All Pick Em"s: {all_total_pickems}
All Pick Em" Home Wins: {all_pickem_home}
All Pick Em" Away Wins: {all_pickems_away}
All Pick Em Pushes: {all_pickems_push}
All Total Dog Straight Up Wins: {all_dog_wins}
All Total Dog Covers: {all_dog_covers}
All Total Dog Losses: {all_dog_losses}
All Total Dog Pushes: {all_dog_push}
All Dog Straight Up Win Rate: {all_dog_win_rate:.2f}%
All Dog ATS Cover Rate: {all_dog_atsrate:.2f}%
All Dog ATS Cover Rate Excluding Pushes: {all_ats_no_push:.2f}%
''')

try:
    with open(game_file, "r") as game_check:
        reader = csv.DictReader(game_check)
        Check_Games(reader)
except FileNotFoundError:
    print('Error: Game file not found.')


