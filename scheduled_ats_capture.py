#!/usr/bin/env python3
"""One scheduled capture; safe to run alongside Flask or a manual capture."""
import csv
import fcntl
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from collect_ats_handle import collect
from ats_money_analysis import analyze

ROOT=Path(__file__).resolve().parent

def upcoming_games(root,now):
    with (root/'nfl_games.csv').open(newline='',encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    upcoming=[]
    for row in rows:
        if row.get('game_type') not in {'REG','WC','DIV','CON','SB'}: continue
        if row.get('away_score') or row.get('home_score') or not row.get('gametime'): continue
        kickoff=datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        if now<kickoff<now+timedelta(days=8): upcoming.append(row['game_id'])
    return upcoming

def save_status(root,status):
    target=root/'logs'/'ats_capture_status.json'
    temp=target.with_suffix(f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(status,indent=2));temp.replace(target)

def missing_markets(root, upcoming, now):
    from scout4.shadow import quote
    with (root/'nfl_games.csv').open(newline='',encoding='utf-8-sig') as stream:
        games={g['game_id']:g for g in csv.DictReader(stream)}
    path=root/'public_money_snapshots.csv'
    prices=[]
    if path.exists():
        with path.open(newline='',encoding='utf-8-sig') as stream:
            prices=list(csv.DictReader(stream))
    return {(gid,market) for gid in upcoming for market in ('Spread','Total')
            if quote(prices,games[gid],market,now) is None}

def missing_prices(root, upcoming, now):
    return sorted({gid for gid,market in missing_markets(root,upcoming,now)})

def run(root=ROOT, now=None):
    now=now or datetime.now(timezone.utc)
    logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/'ats_capture.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Collection already running; skipped overlapping run.');return 0
        status=dict(checked_at_utc=now.isoformat(),source='DraftKings',saved=0)
        try:
            upcoming=upcoming_games(root,now)
            if not upcoming:
                status.update(state='idle',message='No upcoming games in the next eight days.')
                save_status(root,status);print(status['message']);return 0
            required=None
            try:
                rows=collect(root)
                if not rows:
                    raise RuntimeError('No verified pregame handle observations were retrieved')
                if missing_prices(root,upcoming,datetime.now(timezone.utc)):
                    required=missing_markets(root,upcoming,datetime.now(timezone.utc))
                    raise RuntimeError('Primary feed is missing fresh spreads or totals')
            except Exception as primary_error:
                # Prices have an independent backup; missing splits are never
                # synthesized or sent through the public-money fade strategy.
                status.update(primary_state='unavailable', primary_error=type(primary_error).__name__,
                              splits_available=False)
                from odds_backup import collect as backup
                prices=backup(root,required=required)
                missing=missing_prices(root,upcoming,datetime.now(timezone.utc))
                if missing:
                    status['missing_games']=missing
                    raise RuntimeError('Backup is missing verified spreads or totals for upcoming games')
                status.update(state='ok', source='ESPN / DraftKings', saved=len(prices),
                              latest_capture_utc=max(r['captured_at_utc'] for r in prices),
                              message='Backup spreads and totals saved; public betting percentages unavailable.')
                save_status(root,status);print(status['message']);return 0
            report=analyze(root/'ats_handle_snapshots.csv',root/'nfl_games.csv')
            status.update(state='ok',splits_available=True,saved=len(rows),qualifying=report['all']['qualifying'],pending=report['all']['pending'],latest_capture_utc=max(r['captured_at_utc'] for r in rows))
            save_status(root,status)
            print(f"Capture complete: {len(rows)} observations saved; {report['all']['qualifying']} latest qualifying games, {report['all']['pending']} pending.")
            return 0
        except Exception as exc:
            status.update(state='error',message=str(exc))
            save_status(root,status);print(f'Collection failed: {exc}',file=sys.stderr);return 1

if __name__=='__main__':sys.exit(run())
