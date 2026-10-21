"""Atomic first-write installation around the unchanged approved forecast engine.

No network, grading, Expert operations, or automatic repair of existing records.
Caller must hold auto_update.lock; this wrapper also serializes its own journal.
"""
import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scheduler_runtime import atomic_json, exclusive


class StagingError(RuntimeError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def invalid(value):
        raise ValueError('Nonfinite JSON value')
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Nonfinite JSON number')
        return number
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, parse_constant=invalid, parse_float=finite, object_pairs_hook=unique)


def safe_relative(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise StagingError('Unsafe relative path')
    return path


def no_links(base):
    if base.is_symlink() or any(p.is_symlink() for p in base.rglob('*')):
        raise StagingError('Symlink in isolated staging tree')


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_tree(base):
    for directory in sorted((p for p in base.rglob('*') if p.is_dir()), key=lambda p:len(p.parts), reverse=True):
        sync_directory(directory)
    sync_directory(base)


def checked_existing(path):
    if path.is_symlink() or not path.is_file():
        raise StagingError('Existing forecast requires manual review: '+path.name)
    try:
        record = strict_json(path.read_bytes())
        if not isinstance(record, dict) or record.get('status') != 'SEALED_PREKICKOFF_RESEARCH':
            raise ValueError('Not a sealed record')
        from scout4.shadow import aware
        for key in ('game_id','kickoff_utc','decision_cutoff_utc','sealed_at_utc','version','configuration_sha256'):
            if key not in record:
                raise ValueError('Incomplete sealed record')
        if path.name != record['game_id']+'.json':
            raise ValueError('Forecast identity mismatch')
        if not aware(record['decision_cutoff_utc']) <= aware(record['sealed_at_utc']) < aware(record['kickoff_utc']):
            raise ValueError('Invalid pregame timestamps')
        return record
    except (ValueError, TypeError) as error:
        raise StagingError('Existing partial/invalid forecast requires manual review: '+path.name) from error


def validate(candidate, stage, journal, config, clock):
    from scout4.shadow import aware, kickoff, quote
    from scout4.stats import read_csv
    from plug_publication import convert
    raw = candidate.read_bytes()
    record = strict_json(raw)
    if candidate.name != record['game_id']+'.json' or not re.fullmatch(r'\d{4}_\d{2}_[A-Z0-9]+_[A-Z0-9]+', record['game_id']):
        raise StagingError('Forecast filename/identity mismatch')
    if (record['configuration_sha256'] != journal['configuration_sha256']
            or record['version'] != config['version'] or record['weights'] != config['weights']):
        raise StagingError('Forecast configuration mismatch')
    cutoff = aware(record['decision_cutoff_utc'])
    if cutoff != aware(journal['cutoff']):
        raise StagingError('Forecast cutoff changed')
    if not cutoff <= aware(record['sealed_at_utc']) <= clock():
        raise StagingError('Invalid original seal time')
    games = {g['game_id']:g for g in read_csv(stage/'nfl_games.csv')}
    game = games[record['game_id']]
    if (record['kickoff_utc'] != kickoff(game).isoformat()
            or any(str(record[k]) != str(game[k]) for k in ('season','week','away_team','home_team'))):
        raise StagingError('Forecast schedule mismatch')
    expected = {name:journal['snapshots'][name] for name in ('nfl_games.csv','public_money_snapshots.csv')}
    if record['input_hashes'] != expected:
        raise StagingError('Forecast input fingerprints changed')
    manifest = strict_json((stage/f'data/scout4/{record["season"]}/latest.json').read_bytes())
    if record['stats_manifest'] != manifest:
        raise StagingError('Forecast statistics provenance mismatch')
    quotes = read_csv(stage/'public_money_snapshots.csv')
    if record['quote'] != quote(quotes, game, 'Spread', cutoff):
        raise StagingError('Forecast spread provenance mismatch')
    if record.get('totals') and record['totals']['quote'] != quote(quotes, game, 'Total', cutoff):
        raise StagingError('Forecast total provenance mismatch')
    # Existing production validator checks original pregame seal and public schema.
    convert(record, journal['configuration_sha256'])
    return record, digest(raw)


def install(candidate, target, record, clock, expected_digest=None):
    """Copy to a private final-filesystem inode, then atomically link exclusively."""
    if candidate.stat().st_dev != target.parent.stat().st_dev:
        raise StagingError('Staging and destination must share a filesystem')
    raw = candidate.read_bytes()
    if expected_digest is not None and digest(raw) != expected_digest:
        raise StagingError('Candidate changed after validation')
    if target.parent.is_symlink():
        raise StagingError('Prediction destination became a symlink')
    if target.exists() or target.is_symlink():
        checked_existing(target)
        if target.read_bytes() != raw:
            raise StagingError('Existing conflicting forecast requires manual review: '+target.name)
        return 'preserved'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.forecast-install-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        # Check after flushing, immediately before the only publication operation.
        if clock() >= datetime.fromisoformat(record['kickoff_utc']):
            raise StagingError('Kickoff reached; new forecast installation rejected')
        try:
            os.link(temporary, target)
        except FileExistsError:
            checked_existing(target)
            if target.read_bytes() != raw:
                raise StagingError('Concurrent forecast conflict requires manual review: '+target.name)
            return 'preserved'
        sync_directory(target.parent)
        return 'installed'
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def snapshot(root, source, stage, config_path, cutoff):
    from scout4.blend import CORE
    from scout4.shadow import kickoff
    from scout4.stats import read_csv
    fingerprints = {}
    def copy(path, relative, expected=None):
        relative = safe_relative(relative)
        raw = path.read_bytes()
        if expected is not None and digest(raw) != expected:
            raise StagingError('Snapshot fingerprint mismatch: '+str(relative))
        target = stage/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        sync_directory(target.parent)
        fingerprints[str(relative)] = digest(raw)
    copy(config_path, 'automatic_model.json')
    config = strict_json((stage/'automatic_model.json').read_bytes())
    for name in CORE:
        copy(source/name, name, config['code_sha256'][name])
    # Configuration identity is unchanged; no model fitting or config creation.
    for name in ('nfl_games.csv','public_money_snapshots.csv'):
        copy(root/name, name)
    years = {g['season'] for g in read_csv(stage/'nfl_games.csv')
             if g['game_type']=='REG' and g.get('gameday') and g.get('gametime')
             and 0 < (kickoff(g)-cutoff).total_seconds() <= 7*86400}
    cache = (root/'data/scout4').resolve()
    for year in years:
        if not str(year).isdigit():
            raise StagingError('Invalid season')
        relative = Path('data/scout4')/year/'latest.json'
        copy(root/relative, relative)
        manifest = strict_json((stage/relative).read_bytes())
        info = manifest['files']['team']
        team_relative = safe_relative(info['path'])
        original = (cache/team_relative).resolve()
        if not original.is_relative_to(cache):
            raise StagingError('Statistics path escapes cache')
        destination = Path('data/scout4')/team_relative
        if str(destination) not in fingerprints:
            copy(original, destination, info['sha256'])
    predictions = stage/'data/scout4/blend/predictions'
    predictions.mkdir(parents=True, exist_ok=True)
    for existing in sorted((root/'data/scout4/blend/predictions').glob('*.json')):
        checked_existing(existing)
        copy(existing, Path('data/scout4/blend/predictions')/existing.name)
    no_links(stage)
    sync_tree(stage)
    return fingerprints, config


def verify_snapshot(stage, journal):
    no_links(stage)
    for name, fingerprint in journal['snapshots'].items():
        path = stage/safe_relative(name)
        if digest(path.read_bytes()) != fingerprint:
            raise StagingError('Staged snapshot changed: '+name)


def recover(stage, final, config_path, clock):
    path = stage/'journal.json'
    no_links(stage)
    journal = strict_json(path.read_bytes())
    if journal['state'] == 'snapshot_failed':
        raise StagingError(journal.get('error', 'Snapshot failed; manual review required'))
    if journal['state'] == 'complete':
        return journal
    if journal['state'] == 'snapshotting':
        # Model was never entered: retain the incomplete snapshot for inspection.
        journal['state'] = 'abandoned_snapshot'
        atomic_json(path, journal)
        return journal
    if journal['state'] in ('abandoned_snapshot', 'abandoned_generation'):
        return journal
    try:
        if digest(config_path.read_bytes()) != journal['configuration_sha256']:
            raise StagingError('Recovery configuration differs from approved configuration')
        verify_snapshot(stage, journal)
        config = strict_json((stage/'automatic_model.json').read_bytes())
        candidates = sorted((stage/'data/scout4/blend/predictions').glob('*.json'))
        fresh = [p for p in candidates if str(p.relative_to(stage)) not in journal['snapshots']]
        if 'candidates' in journal and {p.name for p in fresh} != set(journal['candidates']):
            raise StagingError('Completed candidate set changed')
        if journal['state'] == 'generating' and not fresh:
            journal.update(state='abandoned_generation', finished_at=clock().isoformat())
            atomic_json(path, journal)
            return journal
        for candidate in candidates:
            relative = str(candidate.relative_to(stage))
            if relative in journal['snapshots']:
                continue  # Existing forecasts are never reinstalled or rewritten.
            expected = journal.get('candidates', {}).get(candidate.name)
            if expected is not None and digest(candidate.read_bytes()) != expected:
                raise StagingError('Completed candidate fingerprint changed')
            record, fingerprint = validate(candidate, stage, journal, config, clock)
            result = install(candidate, final/candidate.name, record, clock, fingerprint)
            journal.setdefault('records', {})[candidate.name] = {
                'sha256':digest(candidate.read_bytes()), 'result':result}
            atomic_json(path, journal)
        journal.update(state='complete', finished_at=clock().isoformat())
        atomic_json(path, journal)
        return journal
    except Exception as error:
        journal.update(state='needs_review', error_type=type(error).__name__, error=str(error),
                       checked_at=clock().isoformat())
        atomic_json(path, journal)
        raise


def run_staged(root, source=None, configuration=None, *, clock=None):
    """Run only beneath scheduler's shared update lock; never call on requests."""
    from scout4.blend import run
    root = Path(root).resolve()
    source = Path(source or Path(__file__).parent).resolve()
    configuration = Path(configuration or source/'automatic_model.json').resolve()
    clock = clock or (lambda:datetime.now(timezone.utc))
    base = (root/'data/scout4/blend').resolve()
    base.mkdir(parents=True, exist_ok=True)
    final = base/'predictions'
    if final.is_symlink():
        raise StagingError('Prediction destination must not be a symlink')
    final.mkdir(exist_ok=True)
    staging = base/'atomic_staging'
    if staging.is_symlink():
        raise StagingError('Staging directory must not be a symlink')
    staging.mkdir(exist_ok=True)
    if staging.stat().st_dev != final.stat().st_dev:
        raise StagingError('Staging and destination must share a filesystem')
    if (staging/'pipeline.lock').is_symlink():
        raise StagingError('Staging lock must not be a symlink')
    with exclusive(staging/'pipeline.lock') as acquired:
        if not acquired:
            raise StagingError('Prediction staging already active; retry later')
        # Complete earlier attempts before any new generation.
        recovered = False
        for stage in sorted(staging.glob('run-*')):
            no_links(stage)
            journal_path = stage/'journal.json'
            if not journal_path.exists():
                # Allocation stopped before a journal was durable; model never ran.
                atomic_json(journal_path, {'state':'abandoned_snapshot'})
            before = strict_json(journal_path.read_bytes())['state']
            result = recover(stage, final, configuration, clock)
            recovered |= (result['state'] == 'complete' and before != 'complete')
        if recovered:
            return {'state':'ok', 'recovered':True}
        stage = staging/('run-'+uuid.uuid4().hex)
        stage.mkdir()
        sync_directory(staging)
        journal = {'schema_version':1, 'state':'snapshotting', 'cutoff':clock().isoformat(), 'records':{}}
        atomic_json(stage/'journal.json', journal)
        try:
            fingerprints, config = snapshot(root, source, stage, configuration,
                                            datetime.fromisoformat(journal['cutoff']))
        except Exception as error:
            journal.update(state='snapshot_failed', error_type=type(error).__name__, error=str(error))
            atomic_json(stage/'journal.json', journal)
            raise
        journal.update(state='generating', snapshots=fingerprints,
                       configuration_sha256=fingerprints['automatic_model.json'])
        atomic_json(stage/'journal.json', journal)
        # Serialized worker process: temporarily change only orchestration configuration.
        previous = os.environ.get('TREND_FINDAH_AUTO_MODEL_CONFIG')
        try:
            os.environ['TREND_FINDAH_AUTO_MODEL_CONFIG'] = str(stage/'automatic_model.json')
            run(stage, now=datetime.fromisoformat(journal['cutoff']))
        finally:
            if previous is None:
                os.environ.pop('TREND_FINDAH_AUTO_MODEL_CONFIG', None)
            else:
                os.environ['TREND_FINDAH_AUTO_MODEL_CONFIG'] = previous
        no_links(stage)
        candidates = {}
        for path in (stage/'data/scout4/blend/predictions').glob('*.json'):
            if str(path.relative_to(stage)) not in fingerprints:
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
                candidates[path.name] = digest(path.read_bytes())
        sync_tree(stage)
        journal.update(state='generated', candidates=candidates)
        atomic_json(stage/'journal.json', journal)
        result = recover(stage, final, configuration, clock)
        # Keep status visible at the original location without exposing partial files.
        status = stage/'data/scout4/blend/status.json'
        if status.exists():
            atomic_json(base/'status.json', strict_json(status.read_bytes()))
        return {'state':'ok', 'records':result['records']}
