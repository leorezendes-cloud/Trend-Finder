"""Read-only Scout readiness audit; explicit prospective activation after approval."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

from scout_dynamic import configuration
from scout_dynamic_store import POLICY, canonical, closing, journal, signed, utc


def check(root, *, now=None, hosted=True):
    root=Path(root).resolve();now=now or datetime.now(timezone.utc)
    errors=[];count=0
    try:
        _,signature=configuration()
        if hosted and (root != Path('/var/data/site-data') or not Path('/var/data').is_mount()):
            raise ValueError('Expected mounted Render persistent disk')
        if hosted and (Path(__file__).resolve().parent/'scout_dynamic').resolve() != root/'scout_dynamic':
            raise ValueError('Scout store is not linked to persistent disk')
        status=json.loads((root/'scout_dynamic/status.json').read_bytes())
        if status['errors'] or not 0 <= (now-utc(status['checked_at'])).total_seconds() <= 1800:
            raise ValueError('Scout worker status is failed or stale')
        from scout4.stats import read_csv
        from scout4.shadow import kickoff
        from site_week import active_slate
        active,slate=active_slate(read_csv(root/'nfl_games.csv'),now)
        for g in slate:
            gid=g['game_id']
            if kickoff(g) <= now:
                continue
            rows=journal(root,gid)
            if not rows or rows[-1]['configuration_sha256'] != signature or gid in status['pending']:
                raise ValueError('Current Scout game unavailable: '+gid)
            count+=1
        for path in (root/'scout_dynamic').glob('*_*_*_*'):
            if not path.is_dir():continue
            rows=journal(root,path.name)
            if rows and utc(rows[-1]['kickoff_utc']) <= now and closing(root,path.name) is None:
                raise ValueError('Missing Scout closing snapshot: '+path.name)
        if not count:
            raise ValueError('No validated upcoming Scout predictions')
    except (ValueError,OSError,KeyError,TypeError) as error:
        errors.append(str(error))
    return dict(ready=not errors,errors=errors,current_games=count)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/var/data/site-data'))
    parser.add_argument('--activate',action='store_true')
    args=parser.parse_args();result=check(args.root)
    print(json.dumps(result,indent=2))
    if not result['ready']:raise SystemExit(1)
    if args.activate:
        from plug_publication import immutable
        _,signature=configuration()
        immutable(args.root/'scout_dynamic/activation.json',canonical(signed(dict(
            policy=POLICY,activated_at=datetime.now(timezone.utc).isoformat(),configuration_sha256=signature))))
        print('Prospective activation saved; publication still requires explicit public flag and a fresh worker cycle.')

if __name__=='__main__':main()
