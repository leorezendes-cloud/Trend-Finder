"""Publish already sealed, approved production forecasts. No models, AI or network."""
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path
from expert_beta import Store, canonical, instant, validate_scout, clock

APPROVED_VERSION = 'plug-points-only-4'


def immutable(path, data):
    """Publish complete bytes atomically and exclusively, including across readers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.pending-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        try:
            os.link(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
        except FileExistsError:
            if path.read_bytes() != data: raise ValueError('Immutable archive conflict')
    finally:
        temporary.unlink(missing_ok=True)


def convert(record, configuration_sha256):
    if record['version'] != APPROVED_VERSION or record['configuration_sha256'] != configuration_sha256:
        raise ValueError('Not the approved production configuration')
    if record['weights'] != {'scout_scoring': 0.0, 'plug_points_only': 1.0}:
        raise ValueError('Experimental forecast weights')
    cutoff, sealed, kickoff = (instant(record[k]) for k in ('decision_cutoff_utc','sealed_at_utc','kickoff_utc'))
    if not cutoff <= sealed < kickoff or sealed > clock() or record.get('status') != 'SEALED_PREKICKOFF_RESEARCH':
        raise ValueError('Invalid original pregame seal')
    game = {k: record[k] for k in ('game_id','season','week','away_team','home_team','kickoff_utc')}
    away, home = game['away_team'], game['home_team']
    if game['game_id'] != f"{int(game['season'])}_{int(game['week']):02}_{away}_{home}":
        raise ValueError('Game identity mismatch')
    points = record['plug_points_only']
    ats = record['components']['Blend']['pick']
    if ats not in (None, away, home): raise ValueError('Invalid published ATS side')
    quotes, sources = {}, []
    def quote(raw, market):
        if raw['market'] != market or instant(raw['kickoff_utc']) != kickoff:
            raise ValueError('Quote identity mismatch')
        a,b = (away,home) if market == 'Spread' else ('Over','Under')
        oa,ob = ('away','home') if market == 'Spread' else ('Over','Under')
        quotes[market] = dict(game_id=game['game_id'],side_a=a,side_b=b,line_a=raw['line'],
            line_b=-raw['line'] if market=='Spread' else raw['line'],
            odds_a=raw['odds'][oa],odds_b=raw['odds'][ob],sportsbook=raw['sportsbook'],
            captured_at_utc=raw['captured_at_utc'])
        sources.append(dict(name=market+' market',url=raw['source_url'],observed_at=raw['captured_at_utc']))
    quote(record['quote'], 'Spread')
    total = record.get('totals')
    side = None
    if total:
        side = total['prediction']['lean']
        if side not in (None,'Over','Under'): raise ValueError('Invalid published total side')
        quote(total['quote'], 'Total')
    scout = dict(game=game,cutoff_utc=record['decision_cutoff_utc'],model_version=record['version'],
        scores={away:points['away_points'],home:points['home_points']},
        spread={'label':'Pick' if ats else 'No pick','side':ats},
        total={'label':'Pick' if side else 'No pick','side':side},
        quotes=quotes,sources=sources,conditions=list(record.get('limitations',[])),evidence_issues=[],
        production_source=dict(configuration_sha256=configuration_sha256,sealed_at_utc=record['sealed_at_utc']))
    validate_scout(scout)
    return scout


def publish(root, destination, configuration):
    """Idempotent recovery after restarts; original seals never become import times."""
    root, destination, configuration = Path(root), Path(destination), Path(configuration)
    raw_config = configuration.read_bytes()
    config = json.loads(raw_config)
    if config['version'] != APPROVED_VERSION or config['weights'] != {'scout_scoring':0.0,'plug_points_only':1.0}:
        raise ValueError('Automatic publication requires approved points-only production model')
    config_hash = hashlib.sha256(raw_config).hexdigest()
    destination.mkdir(parents=True,exist_ok=True)
    status = {'published':0,'preserved':0,'excluded':[]}
    with (destination/'publication.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        archive = Store(destination)
        # Fail closed on a damaged existing archive; never repair by overwriting it.
        archive.records()
        for path in sorted((root/'data/scout4/blend/predictions').glob('*.json')):
            try:
                raw = path.read_bytes(); record = json.loads(raw)
                if path.stem != record['game_id']: raise ValueError('Source filename mismatch')
                scout = convert(record,config_hash)
            except (ValueError,KeyError,TypeError) as error:
                status['excluded'].append({'file':path.name,'reason':type(error).__name__})
                continue
            digest = hashlib.sha256(raw).hexdigest()
            # A previously published game can never silently change or be downgraded.
            receipt = destination/'publication_receipts'/(record['game_id']+'.json')
            evidence = canonical({'source_sha256':digest,'configuration_sha256':config_hash})
            if receipt.exists() and receipt.read_bytes() != evidence:
                raise ValueError('Sealed production forecast changed after publication')
            immutable(destination/'production_sources'/(digest+'.json'),raw)
            scout['production_source']['source_sha256'] = digest
            version = archive.append(scout,kind='production_import',generated_at=record['sealed_at_utc'])
            immutable(receipt,evidence)
            status['published' if not (destination/'publication_versions'/(version+'.json')).exists() else 'preserved'] += 1
            immutable(destination/'publication_versions'/(version+'.json'),canonical({'version':version}))
    status['checked_at'] = clock().isoformat()
    status['state'] = 'published' if status['published'] or status['preserved'] else 'awaiting approved production seals'
    with tempfile.NamedTemporaryFile(dir=destination, prefix='.status-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(canonical(status)); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, destination/'last_publication.json')
        finally: temporary.unlink(missing_ok=True)
    return status
