"""Read-only newsletter summaries from published snapshots; no model execution."""
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


def timestamp(value):
    if not isinstance(value,str):raise ValueError('Missing timestamp')
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Timestamp has no timezone')
    return value.astimezone(timezone.utc)


def period_key(frequency, now):
    local=now.astimezone(ZoneInfo('America/New_York'))
    if frequency=='monthly':return local.strftime('%Y-%m')
    from site_week import week_window
    start,_=week_window(now)
    year,week,_=start.isocalendar()
    return f'{year}-W{week:02d}'


def build_draft(root, now):
    root=Path(root); sources={};warnings=[]
    def read(path):
        raw=path.read_bytes();sources[str(path.relative_to(root))]=hashlib.sha256(raw).hexdigest();return raw.decode('utf-8-sig')
    schedule=root/'nfl_games.csv'
    rows=list(csv.DictReader(read(schedule).splitlines())) if schedule.exists() else []
    if not rows:warnings.append('No saved schedule is available.')
    from site_week import active_week
    current=active_week(rows,now)
    has_week=any(row.get('season') and row.get('week') for row in rows)
    future={}
    for row in rows:
        if row.get('away_score') or row.get('home_score'):continue
        try:
            kickoff=datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        except (KeyError,ValueError):continue
        if has_week and (int(row.get('season',0)),int(row.get('week',0)))!=current:continue
        if not all(row.get(key) for key in ('game_id','away_team','home_team')):continue
        if now<kickoff<=now+timedelta(days=7):future[row['game_id']]=(row,kickoff)
    predictions=[];published_lines={}
    for path in sorted((root/'data/scout4/blend/predictions').glob('*.json')):
        try:
            record=json.loads(read(path))
            if record.get('game_id') not in future:continue
            row,kickoff=future[record['game_id']]
            if any(record.get(key)!=row.get(key) for key in ('away_team','home_team')):continue
            if timestamp(record['kickoff_utc'])!=kickoff:continue
            sealed=timestamp(record['sealed_at_utc']);quoted=timestamp(record['quote']['captured_at_utc'])
            if not quoted<=sealed<=now or sealed>=kickoff:continue
            blend=record['components']['Blend'];line=number(record['quote']['line']);edge=number(blend['ats_edge']);margin=number(blend['away_margin'])
            if None in (line,edge,margin):continue
            pick=blend.get('pick');away=row['away_team'];home=row['home_team']
            if pick not in (away,home,None):continue
            if pick is not None and (abs(edge)<1e-9 or pick != (away if edge>0 else home)):continue
            published_lines[record['game_id']]=line
            stamp=kickoff.astimezone(ZoneInfo('America/New_York')).strftime('%a %b %d, %I:%M %p ET')
            label='No ATS lean' if pick is None else f'{pick} {line if pick==away else -line:+g}'
            text=f'{away} at {home} — {stamp}: {label}. Saved blended away scoring margin {margin:+.1f}; ATS edge {edge:+.1f} points.'
            total=record.get('totals') or {};total_line=number(total.get('quote',{}).get('line'));estimate=number(total.get('prediction',{}).get('total'))
            if total_line is not None and estimate is not None:
                try:
                    total_quote=total['quote'];valid_total=timestamp(total_quote['captured_at_utc'])<=sealed and timestamp(total_quote['kickoff_utc'])==kickoff
                except (KeyError,ValueError,TypeError):valid_total=False
                if valid_total:text+=f' Saved projected total {estimate:.1f} vs. line {total_line:g}.'
            text+=' Quote saved '+quoted.astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %I:%M %p ET')+'.'
            if now-quoted>timedelta(hours=24):text+=' Saved quote is over 24 hours old; it is not live odds.'
            predictions.append((kickoff,-abs(edge),text))
        except (ValueError,KeyError,TypeError,AttributeError,OSError):
            warnings.append('A saved forecast was skipped because its evidence was incomplete or invalid.')
    predictions.sort(key=lambda item:(item[0],item[1]))
    prediction_text='\n\n'.join(item[2] for item in predictions[:8]) or 'No eligible published predictions are saved for upcoming games in the next seven days. Review The Plug before publishing this issue.'
    if not predictions:warnings.append('No eligible predictions: review before approving.')
    matchups=[]
    for row,kickoff in sorted(future.values(),key=lambda item:item[1])[:16]:
        line=published_lines.get(row['game_id'],number(row.get('spread_line')))
        text=f"{row['away_team']} at {row['home_team']} — {kickoff.astimezone(ZoneInfo('America/New_York')).strftime('%a %b %d, %I:%M %p ET')}."
        source='Saved public forecast line' if row['game_id'] in published_lines else 'Saved schedule line'
        text+=f' {source}: {row["away_team"]} {line:+g} (not live odds).' if line is not None else ' No eligible saved spread.'
        matchups.append(text)
    groups=defaultdict(lambda:[0,0,0])
    for row in rows:
        try:
            if row['gameday']>now.astimezone(ZoneInfo('America/New_York')).date().isoformat():continue
            home=number(row.get('home_score'));away=number(row.get('away_score'));line=number(row.get('spread_line'))
            if None in (home,away,line) or line==0 or not row.get('gametime') or row.get('location')=='Neutral':continue
            key=('Away' if line>0 else 'Home',row['gametime']>='19:00')
            result=(away-home+line)*(1 if line>0 else -1)
            groups[key][0 if result>1e-8 else 1 if result< -1e-8 else 2]+=1
        except KeyError:continue
    relevant=set()
    for row,_ in future.values():
        line=published_lines.get(row['game_id'],number(row.get('spread_line')))
        if line not in (None,0) and row.get('location')!='Neutral':
            relevant.add(('Away' if line>0 else 'Home',row.get('gametime','')>='19:00'))
    trends=[]
    for (side,prime),(wins,losses,pushes) in sorted(groups.items()):
        decisions=wins+losses
        if (side,prime) in relevant and decisions>=30:
            trends.append(f'{side} underdogs in {"night games (7 PM ET or later)" if prime else "games before 7 PM ET"}: {wins}-{losses}-{pushes} ATS, {100*wins/decisions:.1f}% covers across {decisions} decisions in completed saved history. Pushes excluded from the rate; this is a historical pattern, not a forecast.')
    return {'predictions':prediction_text,'matchups':'\n\n'.join(matchups) or 'No upcoming games are saved in the next seven days.',
            'trends':'\n\n'.join(trends) or 'No relevant historical groups have at least 30 completed ATS decisions.', 'updates':''}, {'generated_at':now.isoformat(),'sources':sources,'warnings':sorted(set(warnings))}
