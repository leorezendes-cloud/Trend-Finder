"""Read-only broad, current-season ATS highlights with auditable game evidence."""
import csv
from datetime import datetime, date
from functools import lru_cache
from zoneinfo import ZoneInfo
from pathlib import Path
from general_research import research_games
from pregame_lines import effective_rows
from research_qbs import research_rows


def active_highlights(rows, as_of=None):
    as_of=as_of or datetime.now(ZoneInfo('America/New_York')).date()
    season=max((int(row['season']) for row in rows),default=as_of.year)
    # A future schedule may be present; never advertise a previous season as current.
    eligible=[row for row in rows if row.get('gameday') and row['gameday']<=as_of.isoformat()]
    output=[]
    for prime in ('yes','no'):
        for location in ('','home','away'):
            report=research_games(eligible,season=season,filters={'game_type':'REG'},
                                  role='underdog',primetime=prime,location=location)
            games=report['matches']
            if not games:continue
            age=(as_of-date.fromisoformat(games[0]['gameday'])).days
            if not 0<=age<=21:continue
            recent=games[:5]
            results=[g[g['dog_side']+'_ats'] for g in recent]
            wins=results.count('Cover');losses=results.count('Loss');pushes=results.count('Push')
            streak=0
            for game in games:
                if game[game['dog_side']+'_ats']!='Cover':break
                streak+=1
            # Five actual latest games, including pushes. No cherry-picked spread ranges.
            if streak<3 and not (len(recent)==5 and wins>=4):continue
            record=next(r for r in report['records'] if r['label']=='Underdogs')
            output.append(dict(title=('Primetime' if prime=='yes' else 'Non-primetime')+
                               (' '+location if location else '')+' underdogs',
                               season=season,primetime=prime,location=location,
                               wins=wins,losses=losses,pushes=pushes,sample=len(recent),
                               streak=streak,record=record,latest=games[0]['gameday']))
    # QB totals use both teams' combined score in games started by the QB.
    names=sorted({r.get(side+'_qb_name') for r in eligible if int(r['season'])==season
                  for side in ('home','away') if r.get(side+'_qb_name')})
    qb_games={name:[] for name in names}
    for row in eligible:
        for name in {row.get('away_qb_name'),row.get('home_qb_name')}:
            if name in qb_games:qb_games[name].append(row)
    for qb in names:
        report=research_games(qb_games[qb],filters={'game_type':'REG','qb_name':qb})
        games=report['matches']
        if not games or int(games[0]['season'])!=season or not 0<=(as_of-date.fromisoformat(games[0]['gameday'])).days<=21:continue
        outcome=games[0]['total_result']
        if outcome not in ('Over','Under'):continue
        streak=0
        for game in games:
            if game['total_result']!=outcome:break
            streak+=1
        if streak<3:continue
        recent=games[:5]
        output.append(dict(title=qb,kind='qb_total',qb_name=qb,outcome=outcome,
                           season=season,primetime='',location='',streak=streak,
                           wins=sum(g['total_result']==outcome for g in recent),
                           losses=sum(g['total_result'] in ('Over','Under') and g['total_result']!=outcome for g in recent),
                           pushes=sum(g['total_result']=='Push' for g in recent),sample=len(recent),
                           totals=research_games(qb_games[qb],season=season,filters={'game_type':'REG','qb_name':qb})['totals'],latest=games[0]['gameday']))
    return sorted(output,key=lambda t:(t['streak'],t['wins'],not t['location']),reverse=True)


@lru_cache(maxsize=8)
def _cached_highlights(path, signature, today):
    with open(path,newline='') as source:
        rows=research_rows(list(effective_rows(csv.DictReader(source),path)),path)
    return active_highlights(rows,date.fromisoformat(today))


def qb_source_signature(path):
    root=Path(path).resolve().parent
    paths=(root/'research_qb_corrections.csv',root/'data/research_qbs/verified.json')
    return tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) if p.exists()
                 else (str(p),None,None) for p in paths)


def load_highlights():
    from trend_finder_2 import game_file, _trend_data_signature
    today=datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    return _cached_highlights(str(game_file),(_trend_data_signature(),qb_source_signature(game_file)),today)
