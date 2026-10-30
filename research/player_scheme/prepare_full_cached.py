"""Offline, checksum-verified extension of the existing audit DB; no downloads."""
import argparse,json,shutil
from pathlib import Path
from .store import connect,ingest,sha
from .pbp import ingest_pbp,ingest_charting

def prepare(repository,source_db,output):
    if output.exists():raise ValueError('Choose a new output DB; never overwrite an audit')
    shutil.copyfile(source_db,output);db=connect(output);inventory=[]
    cache=repository/'research/checklist_runs/20261014T191622Z';base=repository/'research/scout41_prediction_experiment/pregame_intelligence_sources'
    try:
        for year in range(2019,2023):
            if year<2022:
                meta=json.loads((repository/f'data/scout4/{year}/latest.json').read_text())
                inventory.append(dict(kind='schedule',season=year,**ingest(db,cache/'schedule_input.csv','schedule',season=year,captured_at='2026-10-14T19:16:22Z',url='existing nflverse cached schedule')))
                for kind in ('team','player'):
                    record=meta['files'][kind];path=repository/'data/scout4'/record['path']
                    if sha(path)!=record['sha256']:raise ValueError('Weekly source hash mismatch')
                    inventory.append(dict(kind=kind,season=year,**ingest(db,path,kind,season=year,captured_at=meta['retrieved_at'],url=meta['source'])))
            pbp=base/f'play_by_play_{year}.parquet';chart=base/f'pbp_participation_{year}.parquet'
            pm=json.loads(pbp.with_suffix('.parquet.source.json').read_text());cm=json.loads(chart.with_suffix('.parquet.source.json').read_text())
            if sha(pbp)!=pm['sha256'] or sha(chart)!=cm['sha256']:raise ValueError('Parquet source hash mismatch')
            inventory.append(dict(kind='pbp',season=year,**ingest_pbp(db,pbp,season=year,captured_at=pm['retrieved_at'],url=pm['requested_url'])))
            inventory.append(dict(kind='charting',season=year,**ingest_charting(db,chart,pbp,season=year,captured_at=max(pm['retrieved_at'],cm['retrieved_at']),url=cm['requested_url'])))
            print('validated',year,flush=True)
    finally:db.close()
    output.with_suffix('.sources.json').write_text(json.dumps({'base_database_sha256':sha(source_db),'sources':inventory,'database_bytes':output.stat().st_size},indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--source-db',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.repository,a.source_db,a.output)
