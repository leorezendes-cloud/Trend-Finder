"""Measure marginal reader RAM separately from optional offline Polars processing."""
import argparse,json,resource,sys,time
from pathlib import Path

def rss_bytes():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform=='darwin' else value*1024

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);a=p.parse_args()
    baseline=rss_bytes();start=time.monotonic()
    import sqlite3
    from .features import build
    db=sqlite3.connect('file:'+str(a.db.resolve())+'?mode=ro',uri=True)
    db.execute('PRAGMA cache_size=-2048')
    for _ in range(4):
        for cutoff,mode in [('2026-10-29T12:00:00+00:00','observed'),('2026-02-15T12:00:00+00:00','retrospective'),('2023-02-15T12:00:00+00:00','retrospective')]:
            result=build(db,'NE','BUF',cutoff,mode=mode)
            json.dumps(result,allow_nan=False)
    peak=rss_bytes();db.close()
    report={'baseline_rss_bytes':baseline,'peak_rss_bytes':peak,'additional_peak_bytes':peak-baseline,
            'additional_target_bytes':25*1024*1024,'database_bytes':a.db.stat().st_size,
            'reads':12,'cases':['current observed','full prior regular season retrospective','full charted historical season retrospective'],'elapsed_seconds':round(time.monotonic()-start,3)}
    report['within_memory_target']=report['additional_peak_bytes']<report['additional_target_bytes']
    print(json.dumps(report,indent=2))
    if not report['within_memory_target']:raise SystemExit(1)

if __name__=='__main__':main()
