"""Offline 14-game frozen-model Scout benchmark. Writes only a temporary fixture."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import csv
import hashlib
import json
import os
import resource
import shutil
import tempfile
from unittest.mock import patch
from test_prediction_staging import fixture, NOW, FixedClock, csv_file
from scout4 import blend, shadow
from scout_dynamic import cycle
from scout_dynamic_store import journal


def run():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)/'fixture';fixture(root)
        original=list(csv.DictReader((root/'nfl_games.csv').read_text().splitlines()))
        feed=list(csv.DictReader((root/'data/scout4/fixture/team.csv').read_text().splitlines()))
        quotes=list(csv.DictReader((root/'public_money_snapshots.csv').read_text().splitlines()))
        teams='NE BUF ARI ATL BAL CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LA LAC LV MIA MIN NO NYG NYJ PHI PIT SEA'.split()
        schedule=[];stats=[];prices=[]
        for away,home in zip(teams[::2],teams[1::2]):
            def mapped(row):
                d=dict(row)
                for key in ('away_team','home_team','team','opponent_team','side_a','side_b'):
                    if key in d:d[key]=away if d[key]=='NE' else home if d[key]=='BUF' else d[key]
                d['game_id']=row['game_id'].replace('_NE_BUF','_'+away+'_'+home)
                return d
            schedule += [mapped(r) for r in original]
            stats += [mapped(r) for r in feed]
            prices += [dict(mapped(r),sportsbook='DraftKings',handle_a='',handle_b='',bets_a='',bets_b='',source_url=
                'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard') for r in quotes]
        csv_file(root/'nfl_games.csv',schedule);csv_file(root/'data/scout4/fixture/team.csv',stats)
        csv_file(root/'public_money_snapshots.csv',prices)
        p=root/'data/scout4/2030/latest.json';m=json.loads(p.read_text())
        m['files']['team']['sha256']=hashlib.sha256((root/'data/scout4/fixture/team.csv').read_bytes()).hexdigest()
        p.write_text(json.dumps(m))
        with patch.dict(os.environ,{'TREND_FINDAH_AUTO_MODEL_CONFIG':str(root/'automatic_model.json'),
             'TREND_FINDAH_SCOUT_DYNAMIC_RESEARCH':'1','TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC':'0'}), \
             patch.object(shadow,'datetime',FixedClock):
            generated=blend.run(root,now=NOW)
            assert generated['saved']==14,generated
            for _ in range(3):
                report=cycle(root,now=NOW,clock=lambda:NOW)
                assert report['refreshed']==14 and not report['errors'],report
        files=[p for p in (root/'scout_dynamic').rglob('*') if p.is_file()]
        assert all(len(journal(root,g['game_id']))==1 for g in schedule if not g['away_score'])
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        mib=peak/(1048576 if sys.platform=='darwin' else 1024)
        print(json.dumps(dict(fixture_games=14,cycles=3,peak_rss_mib=round(mib,2),
            fixture_store_bytes=sum(p.stat().st_size for p in files),
            free_disk_bytes=shutil.disk_usage(root).free,
            largest_single_revision_file_bytes=max(p.stat().st_size for p in files),
            measured_environment=sys.platform,production_measurement=False),sort_keys=True))

if __name__=='__main__':run()
