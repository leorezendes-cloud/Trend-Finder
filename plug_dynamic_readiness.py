"""Bounded, no-network production audit and prospective activation gate."""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from plug_dynamic_journal import read, _time
from plug_dynamic_closing import read_closing
from plug_dynamic_official import PIPELINE, POLICY, activation, validated_revision


def check(root, *, now=None, require_hosted=True):
    root = Path(root).resolve()
    now = now or datetime.now(timezone.utc)
    errors, warnings = [], []
    next_week_games = {}
    if require_hosted:
        if root != Path('/var/data/site-data') or not Path('/var/data').is_mount():
            errors.append('Expected Render persistent disk mounted at /var/data')
        from hosted_updates import SOURCE
        for name in ('plug_dynamic_research','plug_dynamic_closing','plug_dynamic_official'):
            if (SOURCE/name).resolve() != root/name:
                errors.append('Source directory is not linked to persistent disk: '+name)
    for name, max_age in (('auto_update_status.json',25200),('ats_capture_status.json',1800)):
        try:
            status = json.loads((root/'logs'/name).read_text())
            stamp = status.get('finished') or status.get('dynamic_finished_utc') or status.get('checked_at_utc')
            if status.get('pipeline') != PIPELINE or status.get('state') != 'ok':
                errors.append(name+': current pipeline has not completed successfully')
            age = (now-_time(stamp)).total_seconds()
            if not 0 <= age <= max_age:
                errors.append(name+': successful status is stale')
            if name.startswith('ats_'):
                dynamic = status.get('dynamic', {})
                if dynamic.get('state') not in ('ok','partial','idle','waiting_next_week'):
                    errors.append('No verified dynamic market refresh')
                next_week_games = dynamic.get('next_week_games', {})
                if dynamic.get('unavailable'):
                    warnings.append({'unavailable_games':dynamic.get('games', {})})
                if status.get('dynamic_closing',{}).get('errors'):
                    errors.append('Dynamic closing validation errors')
                if status.get('dynamic_error'):
                    errors.append(status['dynamic_error'])
            warnings.extend(status.get('warnings',{}).values())
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
            errors.append(name+': '+str(error))
    # A manual capture cannot prove unattended scheduling. Require an actual
    # successful market timer tick from this deployment's pipeline.
    timer = root/'logs/game-day-market_scheduler.jsonl'
    try:
        with timer.open() as stream:
            successful = any(json.loads(line).get('state')=='success'
                             and json.loads(line).get('pipeline')==PIPELINE
                             and 0 <= (now-_time(json.loads(line)['at'])).total_seconds() <= 1800
                             for line in stream)
        if not successful:
            errors.append('Awaiting successful unattended market scheduler tick')
    except (OSError,ValueError,KeyError,TypeError):
        errors.append('Awaiting successful unattended market scheduler tick')
    if require_hosted:
        try:
            boot=json.loads((root/'logs/dynamic_boot.json').read_text())
            verified=json.loads((root/'logs/dynamic_restart_verified.json').read_text())
            if (boot['pipeline'] != PIPELINE or verified['pipeline'] != PIPELINE
                    or boot['boot_id'] != verified['boot_id']):
                raise ValueError('Restart checkpoint belongs to a different boot')
            checkpoint(root,verified['checkpoint'],verify=True)
        except (OSError,ValueError,KeyError,TypeError) as error:
            errors.append('Persistent restart verification required: '+str(error))
    journals = closed = 0
    for path in sorted((root/'plug_dynamic_research').glob('*.jsonl')):
        try:
            rows = read(root,path.stem)
            if not rows:
                raise ValueError('Empty journal')
            validated_revision(root,path.stem,now.isoformat())
            journals += 1
            if _time(rows[-1]['kickoff_utc']) <= now:
                if read_closing(root,path.stem) is None:
                    raise ValueError('Missing due closing receipt')
                closed += 1
        except (OSError,ValueError,KeyError,TypeError) as error:
            errors.append(path.stem+': '+str(error))
    for path in (root/'plug_dynamic_closing').glob('*.json'):
        try:
            read_closing(root,path.stem)
        except (OSError,ValueError,KeyError,TypeError) as error:
            errors.append(path.stem+': '+str(error))
    if not journals:
        errors.append('No verified dynamic journals')
    return dict(ready=not errors, pipeline=PIPELINE, journals=journals, closed=closed,
                errors=errors, warnings=warnings, awaiting_next_week=next_week_games)


def protected_files(root):
    from plug_ats_select import storage_root
    root=Path(root)
    directories=[root/'data/scout4/blend/predictions',root/'data/scout4/blend/plug_ou',
                 root/'plug_dynamic_closing',root/'plug_dynamic_research',
                 root/'plug_dynamic_official',storage_root()]
    # Include every version of weekly O/U receipts and archived production data.
    directories += [p for p in (root/'data/scout4/blend').glob('plug_ou*') if p.is_dir()]
    store=Path(os.environ.get('TREND_FINDAH_EXPERT_STORE','/var/data/expert_beta'))
    directories += [store/'production_sources',store/'publication_receipts',store/'forecasts']
    return sorted({p.resolve() for d in directories for p in d.rglob('*')
                   if p.is_file() and p.suffix in ('.json','.jsonl')})


def checkpoint(root, path, verify=False, *, require_restart=False):
    if verify:
        saved=json.loads(Path(path).read_text())
        entries=saved['files']
        for entry in entries:
            p=Path(entry['path'])
            with p.open('rb') as stream:
                raw=stream.read(entry['size'])
            if len(raw)!=entry['size'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise ValueError('Protected historical bytes changed: '+str(p))
            if not entry['append_only'] and p.stat().st_size!=entry['size']:
                raise ValueError('Immutable historical record changed: '+str(p))
        if require_restart:
            boot=json.loads((Path(root)/'logs/dynamic_boot.json').read_text())
            if (not saved.get('boot_id') or saved['boot_id']==boot['boot_id']
                    or boot['pipeline'] != PIPELINE):
                raise ValueError('Restart the Render service after creating the checkpoint')
            from scheduler_runtime import atomic_json
            atomic_json(Path(root)/'logs/dynamic_restart_verified.json',dict(
                pipeline=PIPELINE,boot_id=boot['boot_id'],checkpoint=str(Path(path).resolve()),
                checked_at_utc=datetime.now(timezone.utc).isoformat()))
        return len(entries)
    entries=[]
    for p in protected_files(root):
        raw=p.read_bytes()
        entries.append(dict(path=str(p),size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                            append_only=p.parent.name=='plug_dynamic_research'))
    from plug_publication import immutable
    boot_path=Path(root)/'logs/dynamic_boot.json'
    boot=json.loads(boot_path.read_text()) if boot_path.exists() else {}
    immutable(path,json.dumps(dict(boot_id=boot.get('boot_id'),files=entries),sort_keys=True).encode())
    return len(entries)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('/var/data/site-data'))
    parser.add_argument('--activate',action='store_true')
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--verify-checkpoint',type=Path)
    args=parser.parse_args()
    if args.checkpoint:
        print(json.dumps({'protected_files':checkpoint(args.root,args.checkpoint)}));return
    if args.verify_checkpoint:
        print(json.dumps({'verified_files':checkpoint(args.root,args.verify_checkpoint,True,require_restart=True)}));return
    result=check(args.root)
    print(json.dumps(result,indent=2))
    if not result['ready']:
        raise SystemExit(1)
    if args.activate:
        from scheduler_runtime import exclusive
        from plug_publication import immutable
        from plug_dynamic_batch import refresh
        with exclusive(args.root/'logs/auto_update.lock') as acquired:
            if not acquired:
                raise SystemExit('Updater busy; retry activation after it finishes')
            if activation(args.root) is None:
                stamp=datetime.now(timezone.utc).isoformat()
                immutable(args.root/'plug_dynamic_official/activation.json',
                          json.dumps(dict(policy=POLICY,pipeline=PIPELINE,
                                          activated_at_utc=stamp),sort_keys=True).encode())
            # Newly observed revisions are mandatory after the prospective gate.
            # Unchanged decisions receive no duplicate journal entry; eligibility
            # uses durable per-game issuance receipts instead of timestamp edits.
            result=refresh(args.root)
            print(json.dumps({'activation_saved':True,'refresh':result,
                              'official_environment_unchanged':True}))

if __name__=='__main__':
    main()
