import argparse
import json
from pathlib import Path
from .store import connect,ingest,maintain
from .features import build
from .evaluate import evaluate

def main():
    p=argparse.ArgumentParser(description='Offline player/scheme research; no production integration')
    p.add_argument('--db',type=Path,required=True)
    sub=p.add_subparsers(dest='command',required=True)
    i=sub.add_parser('ingest');i.add_argument('kind',choices=['schedule','team','player','pbp','charting']);i.add_argument('path',type=Path);i.add_argument('--season',type=int,required=True);i.add_argument('--captured-at',required=True);i.add_argument('--url',required=True);i.add_argument('--pbp-path',type=Path)
    f=sub.add_parser('matchup');f.add_argument('away');f.add_argument('home');f.add_argument('--cutoff',required=True);f.add_argument('--mode',choices=['observed','retrospective'],default='observed')
    e=sub.add_parser('evaluate');e.add_argument('--train-season',type=int,default=2022);e.add_argument('--mode',choices=['observed','retrospective'],default='observed')
    m=sub.add_parser('maintain');m.add_argument('--keep-seasons',type=int,default=8)
    a=p.parse_args();db=connect(a.db)
    try:
        if a.command=='ingest':
            if a.kind=='charting':
                if a.pbp_path is None:p.error('--pbp-path required for charting')
                from .pbp import ingest_charting
                result=ingest_charting(db,a.path,a.pbp_path,season=a.season,captured_at=a.captured_at,url=a.url)
            elif a.kind=='pbp':
                from .pbp import ingest_pbp
                result=ingest_pbp(db,a.path,season=a.season,captured_at=a.captured_at,url=a.url)
            else:result=ingest(db,a.path,a.kind,season=a.season,captured_at=a.captured_at,url=a.url)
        elif a.command=='matchup':result=build(db,a.away,a.home,a.cutoff,mode=a.mode)
        elif a.command=='evaluate':result=evaluate(db,train_season=a.train_season,mode=a.mode)
        else:result=maintain(db,keep_seasons=a.keep_seasons)
        print(json.dumps(result,indent=2,allow_nan=False))
    finally:db.close()

if __name__=='__main__':main()
