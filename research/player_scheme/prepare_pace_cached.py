"""Copy an existing compact audit and add verified cached pace aggregates, offline."""
import argparse,json,shutil
from pathlib import Path
from .store import connect,sha
from .pace import ingest_pace

def prepare(repository,source_db,output):
    if output.exists():raise ValueError('Refusing to overwrite an audit DB')
    shutil.copyfile(source_db,output);db=connect(output);sources=[]
    try:
        for year in range(2022,2027):
            folder='pregame_intelligence_sources' if year==2022 else 'market_baseline_development/sources'
            path=repository/'research/scout41_prediction_experiment'/folder/f'play_by_play_{year}.parquet'
            meta=json.loads(path.with_suffix('.parquet.source.json').read_text())
            if sha(path)!=meta['sha256']:raise ValueError('Source checksum mismatch')
            sources.append(dict(season=year,**ingest_pace(db,path,season=year,captured_at=meta['retrieved_at'],url=meta['requested_url'])))
            print('pace validated',year,flush=True)
    finally:db.close()
    output.with_suffix('.sources.json').write_text(json.dumps({'base_database_sha256':sha(source_db),'sources':sources,'database_bytes':output.stat().st_size},indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--source-db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.repository,a.source_db,a.output)
