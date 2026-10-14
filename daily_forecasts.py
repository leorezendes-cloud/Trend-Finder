"""Daily revisions use the existing blend unchanged, in a separate workspace."""
import json,shutil,tempfile
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def signature(record):
    blend=record.get('components',{}).get('Blend',{});total=record.get('totals') or {}
    def rounded(value):return round(float(value),1) if value is not None else None
    return (blend.get('pick'),rounded(blend.get('away_margin')),record.get('quote',{}).get('line'),total.get('prediction',{}).get('lean'),rounded(total.get('prediction',{}).get('total')),total.get('quote',{}).get('line'))


def daily_view(root):
    path=Path(root)/'data/scout4/daily/latest.json'
    if not path.exists():return {'generated_at':None,'records':{},'changes':{}}
    return json.loads(path.read_text())


def update_daily(root,now=None,runner=None):
    from scout4.blend import run,CORE
    root=Path(root);now=now or datetime.now(timezone.utc);folder=root/'data/scout4/daily';folder.mkdir(parents=True,exist_ok=True)
    day=now.astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m-%d');target=folder/day
    if (target/'complete.json').exists():
        completed=json.loads((target/'complete.json').read_text())
        if not completed.get('pending'):return daily_view(root)
    previous=daily_view(root)
    with tempfile.TemporaryDirectory(prefix='forecast-review-',dir=folder) as temporary:
        work=Path(temporary)
        for name in ('nfl_games.csv','public_money_snapshots.csv',*CORE):
            destination=work/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,destination)
        cache=root/'data/scout4'
        for source in cache.iterdir():
            if source.is_dir() and source.name.isdigit():shutil.copytree(source,work/'data/scout4'/source.name)
        config=cache/'blend/config.json'
        if config.exists():
            destination=work/'data/scout4/blend/config.json';destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(config,destination)
        (runner or run)(work,now=now)
        source=work/'data/scout4/blend'
        status=json.loads((source/'status.json').read_text())
        records={p.stem:json.loads(p.read_text()) for p in (source/'predictions').glob('*.json')}
        originals={p.stem:json.loads(p.read_text()) for p in (cache/'blend/predictions').glob('*.json')}
        changes={key:value for key,value in previous.get('changes',{}).items() if key in records}
        for key,record in records.items():
            old=previous.get('records',{}).get(key) or originals.get(key)
            if old and signature(old)!=signature(record):changes[key]={'previous':old,'current':record,'observed_at':now.isoformat()}
        report={'generated_at':now.isoformat(),'records':records,'changes':changes,'pending':status.get('pending',[])}
        if target.exists():shutil.rmtree(target)
        shutil.copytree(source,target/'blend')
        (target/'complete.json').write_text(json.dumps(report,indent=2))
    latest=folder/'latest.json';temp=latest.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2));temp.replace(latest)
    # Original graded predictions are never touched. Keep fourteen daily evidence sets.
    days=sorted(p for p in folder.iterdir() if p.is_dir() and (p/'complete.json').exists())
    for old in days[:-14]:shutil.rmtree(old)
    return report
