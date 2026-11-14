"""Reproduce offline audit using existing cache; never download or alter inputs."""
import argparse,json,resource,time,sys
from pathlib import Path
from .store import connect,ingest,sha
from .pbp import ingest_pbp
from .evaluate import evaluate

def main():
    p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);dbpath=a.output/'features.sqlite';db=connect(dbpath)
    cache=a.repository/'research/checklist_runs/20261014T191622Z'
    pbp=a.repository/'research/scout41_prediction_experiment/market_baseline_development/sources'
    inventory=[];start=time.monotonic()
    for year in range(2022,2027):
        for kind,path in [('schedule',cache/'schedule_input.csv'),('team',cache/f'team_{year}.csv'),('player',cache/f'player_{year}.csv')]:
            # These are cached research snapshots, not original-time publication receipts.
            result=ingest(db,path,kind,season=year,captured_at='2026-10-14T19:16:22+00:00',url='https://github.com/nflverse/nflverse-data')
            inventory.append(dict(kind=kind,season=year,file=path.name,**result));print(kind,year,result,flush=True)
        path=pbp/f'play_by_play_{year}.parquet'
        if path.exists():
            meta=json.loads(path.with_suffix('.parquet.source.json').read_text())
            assert sha(path)==meta['sha256'],'Cached PBP checksum mismatch'
            result=ingest_pbp(db,path,season=year,captured_at=meta['retrieved_at'],url=meta['requested_url'])
            inventory.append(dict(kind='pbp',season=year,file=path.name,**result));print('pbp',year,result,flush=True)
    report=evaluate(db,train_season=2022,mode='retrospective')
    report['inputs']=inventory
    report['resources']={'database_bytes':dbpath.stat().st_size,'elapsed_seconds':round(time.monotonic()-start,3),
                         'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)}
    (a.output/'evaluation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['resources']),flush=True);db.close()

if __name__=='__main__':main()
