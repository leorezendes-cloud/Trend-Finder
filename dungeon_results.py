"""Dungeon views with a temporary editing preview and Week 6 running record."""
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from ats_money_analysis import GAMES, analyze, load_games, summarize

EDITING_PREVIEW = False

PANELS = {'money': "Mike's Fade the Public", 'primetime': 'Primetime Dogs',
          'movement': 'Reverse Line Movement', 'anomalies': 'NFL Anomalies'}


def weekly_window(now=None):
    now = now or datetime.now(ZoneInfo('America/New_York'))
    if now.tzinfo is None: raise ValueError('Timezone-aware time required')
    now = now.astimezone(ZoneInfo('America/New_York'))
    start = now.date() - timedelta(days=(now.weekday()-3)%7)
    if now.weekday()==2 and now.hour>=12: start += timedelta(days=7)
    return start, start+timedelta(days=7)


def primetime_records(games, only_primetime=True):
    records=[]
    for game in games.values():
        if game.get('game_type') not in {'REG','WC','DIV','CON','SB'}: continue
        if only_primetime and (not game.get('gametime') or game['gametime']<'19:00'): continue
        try: spread=float(game['spread_line'])
        except (ValueError,TypeError): continue
        if not math.isfinite(spread) or spread==0: continue
        away_dog=spread>0
        dog=game['away_team'] if away_dog else game['home_team']
        result='Pending'
        if game.get('away_score') and game.get('home_score'):
            margin=float(game['away_score'])-float(game['home_score'])
            dog_margin=(margin if away_dog else -margin)+abs(spread)
            result='Win' if dog_margin>1e-8 else 'Loss' if dog_margin<-1e-8 else 'Push'
        records.append(dict(game_id=game['game_id'],matchup=f"{game['away_team']} @ {game['home_team']}",gameday=game['gameday'],pick=dog,pick_spread=abs(spread),result=result,season=game['season'],week=game['week'],game_type=game['game_type'],location='Away' if away_dog else 'Home',qb=game.get('away_qb_name' if away_dog else 'home_qb_name',''),roof=game.get('roof',''),primetime=bool(game.get('gametime') and game['gametime']>='19:00')))
    return records


def build_view(panel='money', now=None, games_path=GAMES, money_report=None, archive_week=None, archive_stage='REG', anomaly_category='world', anomaly_year=None):
    panel=panel if panel in PANELS else 'money'
    games=load_games(games_path)
    start,end=weekly_window(now)
    scheduled=[g for g in games.values() if start.isoformat()<=g.get('gameday','')<end.isoformat() and g.get('game_type') in {'REG','WC','DIV','CON','SB'}]
    scope=Counter((g['season'],g['game_type'],g['week']) for g in scheduled)
    season,game_type,week=scope.most_common(1)[0][0] if scope else (None,None,None)
    label=(f'{season} • Week {week}' if game_type=='REG' else f'{season} • {game_type}') if season else f'{start:%b %d} – {end-timedelta(days=1):%b %d}'
    all_handles=[]
    if panel=='money':
        report=money_report if money_report is not None else analyze(games_path=games_path)
        all_handles=[r for r in report.get('handle_records', []) if r['sportsbook'].casefold()=='draftkings']
        if archive_week == 'all':
            all_handles=[r for r in all_handles if r['season']==season]
        elif archive_week is not None:
            all_handles=[r for r in all_handles if r['season']==season and r['week']==str(archive_week) and r['game_type']==archive_stage]
        else:
            all_handles=[r for r in all_handles if start.isoformat()<=r['gameday']<end.isoformat()]
        records=[]
        for raw in report['records']:
            if raw['sportsbook'].casefold()!='draftkings': continue
            row=dict(raw);g=games[row['game_id']]
            row.update(season=g['season'],week=g['week'],game_type=g['game_type'],pick=row['fade_pick'],pick_spread=row['away_spread'] if row['fade_pick']==g['away_team'] else -row['away_spread'])
            records.append(row)
    elif panel=='primetime': records=[r for r in primetime_records(games) if r['season']==season]
    else: records=[]
    weekly=[r for r in records if start.isoformat()<=r['gameday']<end.isoformat()]
    if archive_week == 'all':
        visible=records
        label=f'{season} • All weeks'
    elif archive_week is not None:
        visible=[r for r in records if r['week']==str(archive_week) and r['game_type']==archive_stage]
        label=f'{season} • Week {archive_week}' if archive_stage=='REG' else f'{season} • {archive_stage}'
    elif panel=='primetime':
        instant=(now or datetime.now(ZoneInfo('America/New_York'))).astimezone(ZoneInfo('America/New_York'))
        visible=[r for r in weekly if r['result']=='Pending' and datetime.fromisoformat(r['gameday']+'T'+games[r['game_id']]['gametime']).replace(tzinfo=ZoneInfo('America/New_York'))>instant]
    else:
        visible=weekly
    current=sorted(visible,key=lambda r:(r['gameday'],r['game_id']))
    if panel=='primetime':
        historical=primetime_records(games, only_primetime=False)
        for row in current: row.update(profile=dog_profile(row,historical))
    running=summarize([r for r in records if r['season']==season and (r['game_type']!='REG' or int(r['week'])>=6)])
    # Weekly archives use recorded data, including still-pending outcomes; no invented history.
    past=[r for r in records if r['gameday']<start.isoformat() and (panel=='money' or r['season']==season)]
    grouped=defaultdict(list)
    for r in past: grouped[(r['season'],r['game_type'],r['week'])].append(r)
    history=[]
    for (s,t,w),rows in sorted(grouped.items(),key=lambda item:max(r['gameday'] for r in item[1]),reverse=True):
        history.append(dict(week=w,stage=t,label=f'{s} • Week {w}' if t=='REG' else f'{s} • {t}',summary=summarize(rows)))
    public_markets=None
    if panel=='money':
        from public_money import build_market_view
        public_markets=build_market_view(games_path.parent,games,start,end,season,archive_week,archive_stage)
    movement=None
    if panel=='movement':
        from reverse_line_analysis import build_movement_view
        movement=build_movement_view(games_path.parent,games,start,end,season,archive_week,archive_stage)
        history=movement['history']
        past=[]
    anomalies=None
    if panel=='anomalies':
        from anomaly_analysis import build_anomalies
        anomalies=build_anomalies(games_path.parent,games,season,anomaly_category,anomaly_year)
    return dict(anomalies=anomalies,movement=movement,public_markets=public_markets,all_handles=all_handles,panel=panel,title=PANELS[panel],week_label='All recorded weeks • Editing preview' if EDITING_PREVIEW else label,scheduled_week_label=label,running=running,games=current,summary=movement['summary'] if movement is not None else summarize(records) if panel=='primetime' and archive_week is None else summarize(current),season=season,archive_week=archive_week,current_week=week,current_stage=game_type,history=history,previous=movement['previous'] if movement is not None else summarize(past),ready=panel in {'money','primetime','movement','anomalies'})


def dog_profile(target, historical):
    # Historical comparisons stop before the matchup; final scores never select filters.
    prior=[r for r in historical if r['gameday']<target['gameday'] and r['result']!='Pending' and r['pick']==target['pick'] and (not target['qb'] or r['qb']==target['qb'])]
    same=[r for r in prior if r['location']==target['location']]
    base=summarize(same)
    comparisons=[]
    def add(label, rows, comparison=False):
        summary=summarize(rows)
        if summary['wins']+summary['losses']<5 or base['ats_pct'] is None: return
        delta=round(summary['ats_pct']-base['ats_pct'],1)
        comparisons.append(dict(label=label,summary=summary,delta=delta,comparison=comparison))
    add('Primetime', [r for r in same if r['primetime']])
    spread=target['pick_spread']
    low,high=(0,3) if spread<3 else (3,7) if spread<7 else (7,float('inf'))
    add('Spread under +3' if high==3 else 'Spread +3 to +6.5' if high==7 else 'Spread +7 or more',[r for r in same if low<=r['pick_spread']<high])
    roof=target['roof']
    if roof:
        indoor=roof in {'dome','closed'}
        add('Indoors' if indoor else 'Outdoors',[r for r in same if r['roof'] and (r['roof'] in {'dome','closed'})==indoor])
    add('Home dogs comparison' if target['location']=='Away' else 'Away dogs comparison',[r for r in prior if r['location']!=target['location']],True)
    add('Last five seasons',[r for r in same if int(r['season'])>=int(target['season'])-5])
    comparisons.sort(key=lambda r:(-abs(r['delta']),-r['summary']['graded'],r['label']))
    return dict(description=f"{target['qb'] or target['pick']} / {target['pick']} — {target['location'].lower()} underdog",baseline=base,comparisons=comparisons[:3])
