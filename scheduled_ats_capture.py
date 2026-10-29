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

def refresh_dynamic(root, status):
    from hosted_updates import dynamic_enabled
    if not dynamic_enabled():
        return
    from plug_dynamic_batch import refresh
    from plug_dynamic_finalize_batch import finalize_due
    # Closing is independent of quote availability and refresh errors. A
    # provider outage must never prevent saved pregame decisions from locking.
    errors = []
    try:
        status['dynamic'] = refresh(root, now=datetime.now(timezone.utc))
    except Exception as error:
        errors.append(type(error).__name__+': '+str(error))
    try:
        status['dynamic_closing'] = finalize_due(
            root, as_of_utc=datetime.now(timezone.utc).isoformat())
        if status['dynamic_closing']['errors']:
            raise RuntimeError('Invalid dynamic closing receipt')
    except Exception as error:
        errors.append(type(error).__name__+': '+str(error))
    status['dynamic_finished_utc'] = datetime.now(timezone.utc).isoformat()
    if errors:
        status['dynamic_error'] = '; '.join(errors)
        raise RuntimeError(status['dynamic_error'])


def _finish_cycle(root, status, code):
    try:
        # The adapter independently rejects stale or invalid per-game quotes.
        # One unavailable market must not starve other freshly captured games.
        refresh_dynamic(root, status)
    except Exception as error:
        status.update(state='error', message=str(error))
        code = 1
    save_status(root, status)
    return code


def run(root=ROOT, now=None):
    now=now or datetime.now(timezone.utc)
    logs=root/'logs';logs.mkdir(parents=True,exist_ok=True)
    with (logs/'ats_capture.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Collection already running; skipped overlapping run.');return 0
        from plug_dynamic_official import PIPELINE
        status=dict(checked_at_utc=now.isoformat(),source='DraftKings',saved=0,pipeline=PIPELINE)
        code = 0
        try:
            upcoming=upcoming_games(root,now)
            if not upcoming:
                status.update(state='idle',message='No upcoming games in the next eight days.')
                print(status['message'])
                return _finish_cycle(root, status, code)
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
                print(status['message'])
                return _finish_cycle(root, status, code)
            report=analyze(root/'ats_handle_snapshots.csv',root/'nfl_games.csv')
            status.update(state='ok',splits_available=True,saved=len(rows),qualifying=report['all']['qualifying'],pending=report['all']['pending'],latest_capture_utc=max(r['captured_at_utc'] for r in rows))
            print(f"Capture complete: {len(rows)} observations saved; {report['all']['qualifying']} latest qualifying games, {report['all']['pending']} pending.")
        except Exception as exc:
            status.update(state='error',message=str(exc))
            print(f'Collection failed: {exc}',file=sys.stderr)
            code = 1
        return _finish_cycle(root, status, code)

if __name__=='__main__':sys.exit(run())
