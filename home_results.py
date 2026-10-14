from pregame_lines import effective_rows
"""Compact year-grouped evidence for the standard home-page analysis."""
import csv
from pathlib import Path
from collections import defaultdict
from trend_finder_2 import game_file, Check_Games, analyze_game, matches_combination_conditions

def matching_game_groups(**selection):
    conditions = selection.pop("combination_conditions", None)
    grouped=defaultdict(list)
    selected_qbs={selection.get(key) for key in ('dog_qb_name','away_qb_name','home_qb_name','qb_name') if selection.get(key)}
    # Use the standard analyzer itself so this list includes exactly its games,
    # including pick'ems when selected, rather than combination discovery rules.
    with open(game_file,newline='') as f:
        for row in effective_rows(csv.DictReader(f),game_file):
            if Check_Games([row], **selection)['all_games']['games']==0: continue
            if conditions and not matches_combination_conditions(row, conditions):continue
            analysis=analyze_game(row)
            qb_results=[]
            for side in ('away','home'):
                name=row.get(side+'_qb_name')
                if name not in selected_qbs:continue
                spread=float(row['spread_line']) * (1 if side=='away' else -1)
                own=row.get(side+'_score');opponent=row.get(('home' if side=='away' else 'away')+'_score')
                if own in ('',None) or opponent in ('',None):result='Pending'
                else:
                    margin=float(own)-float(opponent)+spread
                    result='Cover' if margin>1e-8 else 'Loss' if margin<-1e-8 else 'Push'
                qb_results.append(dict(name=name,team=row[side+'_team'],spread=spread,result=result))
            grouped[int(row['season'])].append(dict(
                row, qb_results=qb_results,dog_team=analysis['dog_team'],dog_spread=analysis['dog_spread'],
                ats_result='Pick’em' if analysis['is_pickem'] else 'Push' if analysis['dog_push'] else 'Cover' if analysis['dog_covered'] else 'Loss'))
    return [dict(year=year,show_qb_ats=bool(selected_qbs),games=sorted(rows,key=lambda r:(r['gameday'],r['game_id']),reverse=True)) for year,rows in sorted(grouped.items(),reverse=True)]


def qb_summaries(groups):
    records={}
    for group in groups:
        for game in group['games']:
            for qb in game['qb_results']:
                item=records.setdefault(qb['name'],dict(name=qb['name'],covers=0,losses=0,pushes=0,pending=0))
                item[{'Cover':'covers','Loss':'losses','Push':'pushes','Pending':'pending'}[qb['result']]]+=1
    for item in records.values():
        decisions=item['covers']+item['losses']
        item['rate']=round(100*item['covers']/decisions,1) if decisions else None
    return list(records.values())

def results_freshness():
    with open(game_file,newline='') as f:rows=list(csv.DictReader(f))
    finals=[g for g in rows if g.get('away_score') not in ('',None) and g.get('home_score') not in ('',None) and g.get('game_type')=='REG']
    if not finals:return None
    season=max(int(g['season']) for g in finals);current=[g for g in finals if int(g['season'])==season]
    assignments_path=Path(game_file).parent/'referee_assignments.csv'
    assigned=set()
    if assignments_path.exists():
        with assignments_path.open(newline='') as f:assigned={g['game_id'] for g in csv.DictReader(f) if g.get('referee')}
    return dict(missing_spreads=sum(not g.get('spread_line') for g in current),missing_totals=sum(not g.get('total_line') for g in current),season=season,week=max(int(g['week']) for g in current),date=max(g['gameday'] for g in current),missing_refs=sum(not g.get('referee') and g['game_id'] not in assigned for g in current))
