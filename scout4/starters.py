"""Append-only sourced expected-QB reports, separate from model predictions."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from .personnel import ROOT, timestamp
from .shadow import kickoff
from .stats import read_csv


def save_report(game_id,team,player_id,source_url,source_text,published_at,root=ROOT,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Observation time requires timezone')
    games={g['game_id']:g for g in read_csv(root/'nfl_games.csv')}
    game=games.get(game_id)
    if not game or team not in (game['away_team'],game['home_team']):raise ValueError('Game/team mismatch')
    if now>=kickoff(game):raise ValueError('Cannot record starter evidence after kickoff')
    if not re.fullmatch(r'00-\d{7}',player_id or ''):raise ValueError('Select a player with a GSIS ID')
    parsed=urlparse(source_url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('A public source URL is required')
    if not source_text or not 10<=len(source_text.strip())<=3000:
        raise ValueError('Describe the source evidence in 10–3000 characters')
    published=timestamp(published_at)
    if published>now:raise ValueError('Source publication cannot be in the future')
    record={'game_id':game_id,'team':team,'expected_qb_id':player_id,'source_url':source_url,
            'source_evidence':source_text.strip(),'published_at':published.isoformat(),
            'observed_at':now.isoformat(),'kickoff_utc':kickoff(game).isoformat(),
            'status':'User-recorded expected starter report; source not independently verified',
            'applied_to_forecast':False}
    folder=root/'data/scout4/starter_reports';folder.mkdir(parents=True,exist_ok=True)
    from uuid import uuid4
    path=folder/(now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid4().hex+'.json')
    with path.open('x') as f:json.dump(record,f,indent=2)
    return record


def latest_reports(root=ROOT,now=None):
    now=now or datetime.now(timezone.utc);result={}
    for path in sorted((root/'data/scout4/starter_reports').glob('*.json')):
        r=json.loads(path.read_text())
        if timestamp(r['observed_at'])>now:continue
        r['stale']=(now-timestamp(r['observed_at'])).total_seconds()>86400
        key=(r['game_id'],r['team'])
        if key not in result or timestamp(r['observed_at'])>timestamp(result[key]['observed_at']):result[key]=r
    return result
