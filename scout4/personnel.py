"""Versioned personnel evidence. No automatic injury point penalties or starter claims."""
import argparse
import csv
import gzip
import os
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .stats import number, team_code

ROOT = Path(__file__).resolve().parents[1]


def timestamp(value):
    value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Personnel timestamps must include a timezone')
    return value.astimezone(timezone.utc)


def evidence(depth, injuries, manifest, game, cutoff, kickoff):
    """Select a pregame QB depth snapshot and exact-week injury evidence."""
    cutoff, kickoff = timestamp(cutoff), timestamp(kickoff)
    observed = timestamp(manifest['retrieved_at'])
    if not observed <= cutoff < kickoff:
        raise ValueError('Personnel must be observed before the pre-kickoff cutoff')
    if (cutoff-observed).total_seconds() > 86400:
        raise ValueError('Personnel retrieval is stale')
    result = {}
    for side in ('away', 'home'):
        team = team_code(game[side+'_team'])
        rows = [r for r in depth if team_code(r['team']) == team and r.get('pos_abb') == 'QB'
                and timestamp(r['dt']) <= cutoff]
        latest = max((timestamp(r['dt']) for r in rows), default=None)
        rows = [r for r in rows if timestamp(r['dt']) == latest]
        rows.sort(key=lambda r: (int(r['pos_rank']), str(r.get('gsis_id'))))
        current = [r for r in injuries if team_code(r['team']) == team
                   and str(r['season']) == str(game['season'])
                   and str(r['week']) == str(game['week'])
                   and r.get('season_type') == game.get('game_type', 'REG')]
        result[team] = {'qb_depth_order': rows, 'confirmed_starter': None,
                        'injury_rows': current, 'injury_coverage': 'reported rows only' if current else 'unknown',
                        'depth_updated_at': latest.isoformat() if latest else None,
                        'depth_stale': latest is None or (cutoff-latest).total_seconds() > 86400,
                        'observed_at': observed.isoformat()}
    return result


def qb_profile(rows, player_id, season, before_week, prior=100):
    """Descriptive passing EPA/attempt, shrunk toward prior-window league QB mean.

    Not per-dropback EPA: current player feed does not include QB sacks. No
    target-game rows enter the estimate. Identity uses GSIS IDs, never names.
    """
    eligible = [r for r in rows if str(r['season']) == str(season)
                and r.get('season_type') == 'REG' and int(r['week']) < before_week
                and r.get('position') == 'QB' and number(r.get('attempts')) is not None
                and number(r.get('passing_epa')) is not None and float(r['attempts']) > 0]
    attempts = sum(float(r['attempts']) for r in eligible)
    league = sum(float(r['passing_epa']) for r in eligible)/attempts if attempts else None
    own = [r for r in eligible if r['player_id'] == player_id]
    n = sum(float(r['attempts']) for r in own)
    epa = sum(float(r['passing_epa']) for r in own)
    return {'player_id': player_id, 'prior_attempts': n, 'games': len(own),
            'raw_epa_per_attempt': epa/n if n else None,
            'shrunk_epa_per_attempt': (epa+prior*league)/(n+prior) if league is not None else None,
            'league_epa_per_attempt': league, 'prior_weight': prior,
            'coverage': 'observed' if n else 'no prior attempts; league fallback only',
            'point_adjustment': None}


def _release_cache(stream):
    """Release our own newly written raw evidence pages on memory-limited Linux."""
    stream.flush()
    if hasattr(os, 'posix_fadvise'):
        os.fsync(stream.fileno())
        try: os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError: pass  # Cache advice is optional; evidence bytes are unchanged.


def _json_rows(path):
    """Read our raw JSON array incrementally instead of materializing its text/list."""
    decoder=json.JSONDecoder()
    opener = gzip.open if path.suffix=='.gz' else open
    with opener(path,'rt') as stream:
        buffer=''; first=True; opened=False; since_advice=0
        def block_read():
            nonlocal since_advice
            block=stream.read(65536); since_advice+=len(block)
            if since_advice>=4*1024*1024 and hasattr(os,'posix_fadvise'):
                try: os.posix_fadvise(stream.fileno(),0,0,os.POSIX_FADV_DONTNEED)
                except OSError: pass
                since_advice=0
            return block
        while True:
            buffer=buffer.lstrip()
            if not buffer:
                block=block_read()
                if not block: raise ValueError('Incomplete personnel evidence')
                buffer=block.lstrip()
            if not opened:
                if not buffer.startswith('['): raise ValueError('Expected personnel array')
                buffer=buffer[1:]; opened=True; continue
            if buffer.startswith(']'):
                if buffer[1:].strip() or stream.read().strip(): raise ValueError('Trailing personnel data')
                return
            if not first:
                if not buffer.startswith(','): raise ValueError('Missing personnel row separator')
                buffer=buffer[1:].lstrip()
            while True:
                buffer=buffer.lstrip()
                try: value,end=decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    block=block_read()
                    if not block: raise ValueError('Incomplete personnel row')
                    buffer+=block
                else: break
            if not isinstance(value,dict): raise ValueError('Invalid personnel row')
            yield value
            buffer=buffer[end:]; first=False


def collect(season, root=ROOT):
    import nflreadpy as nfl
    started = datetime.now(timezone.utc).isoformat()
    frames = {kind: getattr(nfl, 'load_'+kind)(season) for kind in ('depth_charts', 'injuries')}
    retrieved = datetime.now(timezone.utc)
    folder = root/'data'/'scout4'/'personnel'/str(season)/retrieved.strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {'season': season, 'retrieval_started_at': started, 'retrieved_at': retrieved.isoformat(),
                'source': 'nflverse via nflreadpy', 'files': {},
                'limitations': ['Depth order is not confirmed starter identity.',
                                'Injury publication times unavailable; retrieval time governs availability.',
                                'No record does not mean healthy. No fitted point adjustment.']}
    for kind, frame in frames.items():
        # Preserve the original JSON representation without a full dict-list copy.
        path = folder/(kind+'.json.gz'); count = 0
        content_hash = hashlib.sha256()
        with gzip.open(path,'wt',compresslevel=1) as stream:
            stream.write('['); content_hash.update(b'[')
            for row in frame.iter_rows(named=True):
                if kind == 'depth_charts' and timestamp(row['dt']) > retrieved:
                    continue
                text = (', ' if count else '')+json.dumps(row,default=str)
                stream.write(text); content_hash.update(text.encode()); count += 1
                if count % 8192 == 0: _release_cache(stream)
            stream.write(']'); content_hash.update(b']'); _release_cache(stream)
        fingerprint = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                fingerprint.update(block)
            if hasattr(os,'posix_fadvise'):
                try: os.posix_fadvise(stream.fileno(),0,0,os.POSIX_FADV_DONTNEED)
                except OSError: pass
        manifest['files'][kind] = {'path': str(path.relative_to(root)), 'rows': count,
                                  'sha256': fingerprint.hexdigest(), 'encoding':'gzip',
                                  'content_sha256':content_hash.hexdigest()}
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, default=2026)
    args = parser.parse_args()
    print(json.dumps(collect(args.season), indent=2))


def tracker_records(root=ROOT):
    """Read the latest saved evidence only; never refresh on a page view."""
    paths=sorted((root/'data/scout4/personnel').glob('*/*/pregame_evidence.json'))
    if not paths:return {}
    data=json.loads(paths[-1].read_text())
    return {g['game_id']:g for g in data['games']}


def refresh_tracker(season=2026,root=ROOT):
    from .shadow import kickoff
    from .stats import read_csv
    manifest=collect(season,root)
    folder=root/Path(manifest['files']['injuries']['path']).parent
    # evidence() only uses each team's latest pre-cutoff QB depth rows. Keep
    # those exact rows while retaining the complete raw feed on disk.
    latest={}; depth=[]
    for row in _json_rows(root/manifest['files']['depth_charts']['path']):
        if row.get('pos_abb')!='QB': continue
        team=team_code(row['team']); stamp=timestamp(row['dt'])
        if team not in latest or stamp > latest[team][0]: latest[team]=(stamp,[row])
        elif stamp == latest[team][0]: latest[team][1].append(row)
    for _,rows in latest.values(): depth.extend(rows)
    injuries=list(_json_rows(root/manifest['files']['injuries']['path']))
    cache=root/'data/scout4';pointer=json.loads((cache/str(season)/'latest.json').read_text())
    with (cache/pointer['files']['player']['path']).open(newline='') as stream:
        players=[row for row in csv.DictReader(stream) if row.get('position')=='QB']
    games=[];now=timestamp(manifest['retrieved_at'])
    for g in read_csv(root/'nfl_games.csv'):
        if str(g['season'])!=str(season) or g['game_type']!='REG':continue
        ko=kickoff(g)
        if not 0 < (ko-now).total_seconds() <= 7*86400:continue
        records=evidence(depth,injuries,manifest,g,now.isoformat(),ko.isoformat())
        for r in records.values():
            r['qb_profiles']=[qb_profile(players,q.get('gsis_id'),season,int(g['week'])) for q in r['qb_depth_order']]
        games.append({'game_id':g['game_id'],'kickoff_utc':ko.isoformat(),
                      'observed_at':now.isoformat(),'personnel':records})
    (folder/'pregame_evidence.json').write_text(json.dumps({'manifest':manifest,'player_statistics_manifest':pointer,'games':games},indent=2))
    return games
