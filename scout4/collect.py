"""Explicit, versioned nflverse weekly statistics import; never runs on page load.

Run: .venv/bin/python -m scout4.collect --seasons 2025 2026
"""
import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .stats import TEAM_METRICS, PLAYER_METRICS

ROOT = Path(__file__).resolve().parents[1]


def collect(season, outdir):
    import nflreadpy as nfl
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = outdir / str(season) / stamp
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {'schema_version': 1, 'season': season,
                'retrieval_started_at': datetime.now(timezone.utc).isoformat(),
                'source': 'nflverse via nflreadpy weekly stats',
                'availability': 'Retrieved now; historical publication times are unverified.', 'files': {}}
    for kind, metrics in (('team', TEAM_METRICS), ('player', PLAYER_METRICS)):
        frame = getattr(nfl, f'load_{kind}_stats')(season, summary_level='week')
        identity = ['season', 'week', 'season_type', 'game_id', 'team', 'opponent_team']
        if kind == 'player':
            identity += ['player_id', 'player_name', 'player_display_name', 'position']
        missing = set(identity) - set(frame.columns)
        if missing:
            raise ValueError(f'{kind} feed missing identity fields: {sorted(missing)}')
        fields = identity + list(metrics)
        count = frame.height
        if not count:
            raise ValueError(f'No {kind} statistics for {season}; existing cache retained')
        path = folder / f'{kind}.csv'
        with path.open('x', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            # Keep CSV values/order unchanged without duplicating the entire wide
            # feed as Python objects. Missing metrics still serialize as blanks.
            selected = frame.select([k for k in fields if k in frame.columns])
            writer.writerows({k: row.get(k) for k in fields}
                             for row in selected.iter_rows(named=True))
            del selected
        manifest['files'][kind] = {'path': str(path.relative_to(outdir)), 'rows': count,
                                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                   'missing_metrics': sorted(set(metrics) - set(frame.columns))}
        del frame
    manifest['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    pointer = outdir / str(season) / 'latest.json'
    temp = pointer.with_suffix('.tmp')
    temp.write_text(json.dumps(manifest, indent=2))
    temp.replace(pointer)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seasons', nargs='+', type=int, required=True)
    parser.add_argument('--outdir', type=Path, default=ROOT / 'data' / 'scout4')
    args = parser.parse_args()
    for season in args.seasons:
        result = collect(season, args.outdir)
        print(f'{season}: ' + ', '.join(f'{k} {v["rows"]} rows' for k,v in result['files'].items()))


if __name__ == '__main__':
    main()
