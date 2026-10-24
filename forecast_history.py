"""Read-only settlement guards for historical views; never changes model sources."""
import hashlib
import math
from datetime import datetime


def record_digest(record):
    # Used for supplied in-memory records in tests/exports. Public links use the
    # exact source-file digest, including original formatting, supplied by caller.
    import json
    return hashlib.sha256(json.dumps(record,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def pregame_record(record):
    def instant(value):
        if not isinstance(value,str):raise ValueError('Timestamp required')
        t=datetime.fromisoformat(value.replace('Z','+00:00'))
        if t.tzinfo is None:raise ValueError('Timezone required')
        return t
    kickoff=instant(record['kickoff_utc'])
    cutoff=instant(record['decision_cutoff_utc'])
    sealed=instant(record['sealed_at_utc'])
    if not cutoff<=sealed<kickoff:raise ValueError('Invalid forecast seal ordering')
    quotes=[record['quote']]
    if record.get('totals'):quotes.append(record['totals']['quote'])
    for q in quotes:
        if instant(q['captured_at_utc'])>cutoff:raise ValueError('Quote captured after forecast cutoff')
        if q.get('kickoff_utc') and instant(q['kickoff_utc'])!=kickoff:raise ValueError('Quote kickoff mismatch')
        if not math.isfinite(float(q['line'])):raise ValueError('Invalid frozen line')
    return record


def grade_components(record,game):
    from scout4.blend import grade_components as original
    allowed=(None,record['away_team'],record['home_team'])
    if any(c.get('pick') not in allowed for c in record['components'].values()):raise ValueError('Unknown ATS selection')
    result=original(record,game)
    # A game-level push cannot settle a wager that was never selected.
    for name,c in record['components'].items():
        if c.get('pick') is None:result[name]='No Call'
    return result


def total_result(record,game):
    from scout4.blend_results import total_result as original
    if record.get('totals'):
        lean=record['totals']['prediction']['lean']
        if lean not in (None,'No Call','Over','Under'):raise ValueError('Unknown total selection')
        if lean in (None,'No Call'):
            if not game or any(record[k]!=game.get(k) for k in ('game_id','away_team','home_team')):raise ValueError('Outcome identity mismatch')
            return 'No Call'
    return original(record,game)


def archive_root(root):
    from flask import current_app, has_app_context
    from pathlib import Path
    import os
    configured = current_app.config.get('EXPERT_BETA_STORE') if has_app_context() else None
    return Path(configured or os.getenv('TREND_FINDAH_EXPERT_STORE') or
                ('/var/data/expert_beta' if Path('/var/data').exists() else root/'instance/expert_beta'))


def official_sources(root, *, destination=None, now=None):
    """One read-only cohort: latest evidenced pre-kickoff publication, else legacy seal.

    Development records and late imports cannot replace the historical cohort.
    Publication events are local observed times, never inferred from model seals.
    """
    import json
    from pathlib import Path
    from expert_beta import Store, clock, instant, canonical
    from plug_publication import convert
    root=Path(root); destination=Path(destination) if destination else archive_root(root)
    now=now or clock()
    selected={}
    for path in (root/'data/scout4/blend/predictions').glob('*.json'):
        raw=path.read_bytes(); record=json.loads(raw)
        if path.stem!=record.get('game_id'):raise ValueError('Forecast filename mismatch')
        pregame_record(record)
        if instant(record['sealed_at_utc'])>now:continue
        record['_history_digest']=hashlib.sha256(raw).hexdigest()
        selected[record['game_id']]=record
    ranked={}
    for archived in Store(destination).records():
        if archived.get('kind')!='production_import':continue
        version=archived['version']
        event_path=destination/'publication_events'/(version+'.json')
        if not event_path.exists():continue
        try:
            event=json.loads(event_path.read_text())
            published=instant(event['observed_published_at'])
            scout=archived['scout']; source=scout['production_source']
            if event['version']!=version:raise ValueError('Publication identity mismatch')
            if not instant(source['sealed_at_utc'])<=published<instant(scout['game']['kickoff_utc']) or published>now:continue
            digest=source['source_sha256']; config=source['configuration_sha256']
            import re
            if not all(re.fullmatch('[a-f0-9]{64}',x) for x in (digest,config)):raise ValueError('Invalid source fingerprint')
            if event['source_sha256']!=digest or event['configuration_sha256']!=config:raise ValueError('Publication source mismatch')
            marker=json.loads((destination/'publication_versions'/(version+'.json')).read_text())
            if marker!={'version':version}:raise ValueError('Publication marker mismatch')
            raw=(destination/'production_sources'/(digest+'.json')).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Publication source damaged')
            record=json.loads(raw);pregame_record(record)
            expected=convert(record,config);expected['production_source']['source_sha256']=digest
            if canonical(expected)!=canonical(scout):raise ValueError('Published forecast differs from approved source')
            if event['original_sealed_at']!=record['sealed_at_utc']:raise ValueError('Publication seal mismatch')
            record['_history_digest']=digest;record['_archive_version']=version
            game_id=record['game_id'];rank=(published,instant(record['sealed_at_utc']),version)
            if game_id not in ranked or rank>ranked[game_id][0]:ranked[game_id]=(rank,record)
        except (OSError,KeyError,TypeError,ValueError) as error:
            raise ValueError('Approved publication requires operator review') from error
    selected.update({game_id:value[1] for game_id,value in ranked.items()})
    return selected
