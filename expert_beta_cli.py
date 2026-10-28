"""Offline operator interface. Never starts servers, schedulers, AI calls or payments."""
import argparse
import hashlib
import json
from pathlib import Path
from expert_beta import Store, canonical, clock, grade, identity, validate_expert, validate_scout


def import_package(root, package):
    package = Path(package)
    raw = (package/'scout_public.json').read_bytes()
    manifest = json.loads((package/'manifest.json').read_text())
    # Release packaging has evolved: require an exact hash present in the manifest.
    digest = hashlib.sha256(raw).hexdigest()
    if manifest.get('files', {}).get('scout_public.json') != digest:
        raise ValueError('Package content hash missing or mismatched')
    payload = json.loads(raw)
    # Validate the entire incoming slate before exposing any new game versions.
    for scout in payload['games']:
        validate_scout(scout)
    versions = []
    for scout in payload['games']:
        versions.append(Store(root).append(scout, kind='development', generated_at=payload['generated_at_utc']))
    return versions


def feature(root, season, week, matchups):
    store = Store(root)
    ids = [f'{season}/{week}/{m}' for m in matchups]
    available = {identity(r['scout']) for r in store.records()}
    if len(ids) != 2 or len(set(ids)) != 2 or not set(ids) <= available:
        raise ValueError('Choose exactly two distinct imported games from the same week')
    path = Path(root)/'featured'/f'{season}-{week}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical(ids)
    try:
        with path.open('xb') as stream:
            stream.write(encoded)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise ValueError('Weekly free selections are already frozen')


def save_final(root, final):
    rows = [r for r in Store(root).records() if r['scout']['game']['game_id'] == final['game_id']]
    if not rows:
        raise ValueError('Final has no archived game')
    for r in rows:
        grade(r, final)
    path = Path(root)/'finals'/(hashlib.sha256(canonical(final)).hexdigest()+'.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as stream:
            stream.write(canonical(final))
    except FileExistsError:
        if path.read_bytes() != canonical(final):
            raise ValueError('Final integrity conflict')


def draft(root, version, approved=False, model=None, provider_name="openai"):
    from expert_beta import generate_draft, instant
    from expert_provider import OpenAIProvider, GeminiProvider
    if provider_name == "openai" and not approved:
        raise RuntimeError('Approval required for a paid API call')
    rows = [r for r in Store(root).records() if r['version'] == version]
    if len(rows) != 1:
        raise ValueError('Unknown forecast version')
    if provider_name not in ("gemini", "openai"):
        raise ValueError("Unknown provider")
    folder = Path(root)/'drafts';folder.mkdir(parents=True,exist_ok=True)
    saved = folder/(version+'.json')
    if provider_name == 'gemini' and saved.exists():
        # Reuse a complete response without loading credentials or spending quota.
        data=json.loads(saved.read_text())
        if data.get('scout_sha256') != hashlib.sha256(canonical(rows[0]['scout'])).hexdigest():
            raise ValueError('Saved draft references a different Scout snapshot')
        return str(saved)
    if provider_name == 'gemini' and clock() >= instant(rows[0]['scout']['game']['kickoff_utc']):
        raise ValueError('Gemini draft kickoff already reached')
    provider = GeminiProvider(model=model) if provider_name == "gemini" else OpenAIProvider(approved=True, model=model)
    if provider_name == "gemini" and not provider.free_tier_confirmed:
        raise RuntimeError("Confirm Gemini Free Tier and disabled billing before generation")
    if not provider.api_key or not provider.model:
        raise RuntimeError('Configure provider key and model locally first')
    folder = Path(root)/'drafts';folder.mkdir(parents=True,exist_ok=True)
    # Reservation persists even after a timeout: a server may have billed the call.
    # A retry therefore requires an operator to inspect the attempt first.
    reservation = folder/(version+'.attempt.json')
    if provider_name == 'gemini':
        # Separate lock: the scheduler already owns automation.lock. This protects
        # direct CLI requests too, without recursively locking the queue lock.
        import fcntl, os
        from datetime import timedelta
        from expert_auto_queue import recent_attempts
        with (Path(root)/'gemini_requests.lock').open('a') as budget_lock:
            fcntl.flock(budget_lock,fcntl.LOCK_EX)
            now=clock();attempts=recent_attempts(root,now)
            limit=int(os.environ.get('TREND_FINDAH_EXPERT_DAILY_LIMIT','16'))
            if not 1<=limit<=16:raise ValueError('Gemini daily limit must be 1..16')
            if len(attempts)>=limit:raise RuntimeError('Persistent Gemini 24-hour quota exhausted')
            if sum(t>now-timedelta(minutes=1) for t in attempts)>=4:
                raise RuntimeError('Persistent Gemini minute quota exhausted')
            with reservation.open('x') as stream:
                json.dump({'version':version,'started_at':now.isoformat(),'model':provider.model,'provider':provider_name},stream)
                stream.flush();os.fsync(stream.fileno())
    else:
        with reservation.open('x') as stream:
            json.dump({'version':version,'started_at':clock().isoformat(),'model':provider.model,'provider':provider_name},stream)
    # Keep Expert's analysis independent while showing the issued final Plug
    # O/U selection when it belongs to precisely this archived Scout source.
    from plug_ou_weekly import read_effective as read_plug_ou
    scout=rows[0]['scout']
    plug_ou=read_plug_ou(Path(__file__).resolve().parent,scout['game']['game_id'])
    if plug_ou and (not plug_ou['selected'] or plug_ou['source_sha256']!=scout.get('production_source',{}).get('source_sha256')):
        plug_ou=None
    result = generate_draft(scout,provider,plug_ou=plug_ou)
    path = folder/(version+'.json')
    with path.open('xb') as stream:
        stream.write(canonical(result))
    return str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('import-package');p.add_argument('package')
    p = commands.add_parser('feature');p.add_argument('season',type=int);p.add_argument('week',type=int);p.add_argument('matchups',nargs=2)
    p = commands.add_parser('final');p.add_argument('file')
    p = commands.add_parser('draft');p.add_argument('version');p.add_argument('--approve-paid-call', action='store_true');p.add_argument('--model');p.add_argument('--provider', choices=('gemini','openai'), default='gemini')
    p = commands.add_parser('publish-reviewed');p.add_argument('version');p.add_argument('file')
    args = parser.parse_args()
    if args.command == 'import-package':
        print(f'Imported {len(import_package(args.store,args.package))} development forecasts; original generation times retained.')
    elif args.command == 'feature':
        feature(args.store,args.season,args.week,args.matchups);print('Two weekly free games frozen.')
    elif args.command == 'final':
        save_final(args.store,json.loads(Path(args.file).read_text()));print('Sourced final archived. Grading is derived separately.')
    elif args.command == 'draft':
        print(draft(args.store, args.version, args.approve_paid_call, args.model, args.provider))
    else:
        rows = [r for r in Store(args.store).records() if r['version']==args.version]
        if len(rows)!=1:
            raise ValueError('Unknown forecast version')
        r = rows[0];report=json.loads(Path(args.file).read_text());validate_expert(report,r['scout'])
        # New AI analysis never inherits the old prospective classification.
        print(Store(args.store).append(r['scout'], expert=report, kind='historical_reconstruction' if r['kind']=='historical_reconstruction' else 'development'))


if __name__ == '__main__':
    main()
