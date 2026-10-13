"""Compare first/latest observed pregame spreads against latest >=65% public dollars."""
import csv
from collections import defaultdict
from ats_money_analysis import snapshot_from_row, summarize


def build_movement_view(root,games,start,end,season,archive_week=None,archive_stage='REG'):
    path=root/'ats_handle_snapshots.csv';groups=defaultdict(list);rejected=0
    if path.exists():
        with path.open(newline='',encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                try:
                    snap=snapshot_from_row(row);game=games[snap['game_id']]
                    if (snap['away_team'],snap['home_team'])!=(game['away_team'],game['home_team']):raise ValueError('Team mismatch')
                    if snap['sportsbook'].casefold()!='draftkings':continue
                    groups[snap['game_id']].append(snap)
                except (ValueError,TypeError,KeyError,OverflowError):rejected+=1
    records=[]
    for game_id,snaps in groups.items():
        # Count distinct observation times, never duplicates as independent games.
        by_time={s['captured']:s for s in snaps};snaps=sorted(by_time.values(),key=lambda s:s['captured'])
        first,last=snaps[0],snaps[-1];game=games[game_id]
        backed=last['away_team'] if last['away_handle_pct']>=65 else last['home_team'] if last['home_handle_pct']>=65 else None
        delta=last['away_spread']-first['away_spread']
        against=delta if backed==last['away_team'] else -delta if backed else None
        qualifies=len(snaps)>=2 and backed is not None and against>1e-8
        pick=(last['home_team'] if backed==last['away_team'] else last['away_team']) if qualifies else None
        pick_spread=(last['away_spread'] if pick==last['away_team'] else -last['away_spread']) if pick else None
        result='Pending'
        if qualifies and game.get('away_score') and game.get('home_score'):
            away_margin=float(game['away_score'])-float(game['home_score'])+last['away_spread']
            margin=away_margin if pick==last['away_team'] else -away_margin
            result='Win' if margin>1e-8 else 'Loss' if margin<-1e-8 else 'Push'
        status='Reverse movement' if qualifies else 'Need another snapshot' if len(snaps)<2 else 'Below 65% money' if not backed else 'Line unchanged' if abs(delta)<1e-8 else 'Moves with public money'
        records.append(dict(game_id=game_id,matchup=f"{last['away_team']} @ {last['home_team']}",away_team=last['away_team'],home_team=last['home_team'],gameday=game['gameday'],season=game['season'],week=game['week'],stage=game['game_type'],first_spread=first['away_spread'],latest_spread=last['away_spread'],away_handle=last['away_handle_pct'],home_handle=last['home_handle_pct'],snapshot_count=len(snaps),backed=backed,against=against,qualifies=qualifies,pick=pick,pick_spread=pick_spread,result=result,status=status,source_url=last['source_url']))
    def selected(row):
        if archive_week=='all':return row['season']==season
        if archive_week is not None:return row['season']==season and row['week']==str(archive_week) and row['stage']==archive_stage
        return start.isoformat()<=row['gameday']<end.isoformat()
    current=sorted([r for r in records if selected(r)],key=lambda r:(r['gameday'],r['matchup']))
    qualified=[r for r in current if r['qualifies']]
    past=[r for r in records if r['qualifies'] and r['season']==season and r['gameday']<start.isoformat()]
    history_groups=defaultdict(list)
    for r in past:history_groups[(r['stage'],r['week'])].append(r)
    history=[dict(stage=stage,week=week,label=f'{season} • Week {week}' if stage=='REG' else f'{season} • {stage}',summary=summarize(rows)) for (stage,week),rows in sorted(history_groups.items(),key=lambda item:int(item[0][1]),reverse=True)]
    from market_movement import build_market_movement
    markets=build_market_movement(root,games,start,end,season,archive_week,archive_stage)
    return dict(markets=markets,cards=current,summary=summarize(qualified),tracked=len(current),previous=summarize(past),history=history,rejected=rejected)
