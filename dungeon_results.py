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
    from site_week import week_window
    start,end=week_window(now)
    return start.date(),end.date()


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



def team_season_ats_before(games, team, season, cutoff_date):
    """Team ATS W-L-P in completed regular-season games before the target date.

    spread_line is the away-team spread in the saved game dataset.
    Exclude ungraded games and games on/after the target date to avoid
    leaking the upcoming game's result into the preview or archive.
    """
    wins = losses = pushes = 0
    for game in games.values():
        if (str(game.get('season')) != str(season)
                or game.get('game_type') != 'REG'
                or game.get('gameday', '') >= cutoff_date
                or team not in (game.get('away_team'), game.get('home_team'))):
            continue
        try:
            spread = float(game['spread_line'])
            away = float(game['away_score'])
            home = float(game['home_score'])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (spread, away, home)):
            continue
        away_ats_margin = away - home + spread
        team_ats_margin = (away_ats_margin if team == game['away_team']
                           else -away_ats_margin)
        if team_ats_margin > 1e-8:
            wins += 1
        elif team_ats_margin < -1e-8:
            losses += 1
        else:
            pushes += 1
    return dict(wins=wins, losses=losses, pushes=pushes,
                graded=wins + losses + pushes)



def build_view(panel='money', now=None, games_path=GAMES, money_report=None, archive_week=None, archive_stage='REG', anomaly_category='world', anomaly_year=None):
    panel = panel if panel in PANELS else 'money'

    # Keep old Reverse Line Movement links working.
    # Both features now live under Mike's section.
    if panel == 'movement':
        panel = 'money'
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
        for row in current:
            row.update(profile=dog_profile(row,historical),
                       team_season_ats=team_season_ats_before(
                           games, row['pick'], row['season'], row['gameday']))
    running=summarize([r for r in records if r['season']==season and (r['game_type']!='REG' or int(r['week'])>=6)])
    # Weekly archives use recorded data, including still-pending outcomes; no invented history.
    past=[r for r in records if r['gameday']<start.isoformat() and (panel=='money' or r['season']==season)]
    grouped=defaultdict(list)
    for r in past: grouped[(r['season'],r['game_type'],r['week'])].append(r)
    history=[]
    for (s,t,w),rows in sorted(grouped.items(),key=lambda item:max(r['gameday'] for r in item[1]),reverse=True):
        history.append(dict(week=w,stage=t,label=f'{s} • Week {w}' if t=='REG' else f'{s} • {t}',summary=summarize(rows)))
    primetime_tracker = (build_primetime_tracker(games, season, now)
                         if panel == 'primetime' else None)
    primetime_totals_view = (primetime_totals(games, season, now)
                            if panel == 'primetime' else None)
    public_markets = None
    movement = None
    anomalies = None

    if panel == 'money':
        from public_money import build_market_view
        from reverse_line_analysis import build_movement_view

        public_markets = build_market_view(
            games_path.parent, games, start, end,
            season, archive_week, archive_stage
        )

        movement = build_movement_view(
            games_path.parent, games, start, end,
            season, archive_week, archive_stage
        )

        # Match each market's movement data to Mike's existing game cards.
        movement_lookup = {
            (card['matchup'], card['gameday']): {
                market['market']: market
                for market in card['markets']
            }
            for card in movement['markets']['cards']
        }

        for card in public_markets['cards']:
            by_market = movement_lookup.get(
                (card['matchup'], card['gameday']), {}
            )
            for market in card['markets']:
                market['movement'] = by_market.get(market['market'])
        anomalies=None
    if panel=='anomalies':
        from anomaly_analysis import build_anomalies
        anomalies=build_anomalies(games_path.parent,games,season,anomaly_category,anomaly_year)
    return dict(primetime_totals=primetime_totals_view,primetime_tracker=primetime_tracker,anomalies=anomalies,movement=movement,public_markets=public_markets,all_handles=all_handles,panel=panel,title=PANELS[panel],week_label='All recorded weeks • Editing preview' if EDITING_PREVIEW else label,scheduled_week_label=label,running=running,games=current,summary=movement['summary'] if movement is not None else summarize(records) if panel=='primetime' and archive_week is None else summarize(current),season=season,archive_week=archive_week,current_week=week,current_stage=game_type,history=history,previous=movement['previous'] if movement is not None else summarize(past),ready=panel in {'money','primetime','movement','anomalies'})



def build_primetime_tracker(games, season, now=None):
    """Current-season primetime ATS, home/away and chronological cover streak."""
    instant = now or datetime.now(ZoneInfo('America/New_York'))
    if instant.tzinfo is None:
        raise ValueError('Timezone-aware time required')
    instant = instant.astimezone(ZoneInfo('America/New_York'))
    # The site's existing grading excludes pick'ems and uses the saved spread.
    rows = primetime_records(games)
    if season is None:
        eligible = [int(r['season']) for r in rows if int(r['season']) <= instant.year]
        season = str(max(eligible)) if eligible else str(instant.year)
    rows = [r for r in rows if str(r['season']) == str(season)
            and r['game_type'] == 'REG' and r['result'] in ('Win', 'Loss', 'Push')]

    def played(row):
        source = games[row['game_id']]
        clock = source.get('gametime') or '00:00'
        kickoff = datetime.fromisoformat(row['gameday'] + 'T' + clock).replace(
            tzinfo=ZoneInfo('America/New_York'))
        return kickoff <= instant

    rows = [r for r in rows if played(r)]
    rows.sort(key=lambda r: (
        r['gameday'], games[r['game_id']].get('gametime') or '', r['game_id']))
    streak = []
    for row in reversed(rows):
        if row['result'] == 'Push':
            continue  # Same convention as find_active_streak in Trend Finder.
        if row['result'] != 'Win':
            break
        streak.append(row)
    streak.reverse()

    recent = []
    for row in reversed(rows[-10:]):
        source = games[row['game_id']]
        recent.append(dict(date=row['gameday'], matchup=row['matchup'],
                           dog=row['pick'], spread=row['pick_spread'],
                           location=row['location'], result=row['result'],
                           away_score=source.get('away_score'),
                           home_score=source.get('home_score')))
    return dict(season=season, overall=summarize(rows),
                home=summarize([r for r in rows if r['location'] == 'Home']),
                away=summarize([r for r in rows if r['location'] == 'Away']),
                streak=len(streak),
                streak_start=streak[0]['gameday'] if streak else None,
                streak_end=streak[-1]['gameday'] if streak else None,
                recent=recent)


def primetime_totals(games, season, now=None):
    """Score recorded totals for finished regular-season primetime dog games."""
    instant = now or datetime.now(ZoneInfo('America/New_York'))
    if instant.tzinfo is None:
        raise ValueError('Timezone-aware time required')
    instant = instant.astimezone(ZoneInfo('America/New_York'))
    over = under = pushes = 0
    for record in primetime_records(games):
        if str(record['season']) != str(season) or record['game_type'] != 'REG':
            continue
        game = games[record['game_id']]
        if record['result'] == 'Pending':
            continue
        try:
            total_line = float(game['total_line'])
            home_score = float(game['home_score'])
            away_score = float(game['away_score'])
        except (ValueError, TypeError, KeyError):
            continue
        if not all(math.isfinite(x) for x in (total_line, home_score, away_score)):
            continue
        kickoff = datetime.fromisoformat(
            record['gameday'] + 'T' + (game.get('gametime') or '00:00')
        ).replace(tzinfo=ZoneInfo('America/New_York'))
        if kickoff > instant:
            continue
        points = home_score + away_score
        if points > total_line:
            over += 1
        elif points < total_line:
            under += 1
        else:
            pushes += 1
    decided = over + under
    return dict(over=over, under=under, pushes=pushes,
                over_pct=round(100 * over / decided, 1) if decided else None,
                under_pct=round(100 * under / decided, 1) if decided else None)

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
