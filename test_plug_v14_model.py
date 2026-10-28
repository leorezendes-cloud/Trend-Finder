"""Regression fixtures for the frozen 2026 independent v14 reconstruction."""
import csv
import tempfile
import unittest
from pathlib import Path
from plug_v14_model import projections

FIELDS=('game_id','season','game_type','week','gameday','away_team','home_team',
        'away_score','home_score','total_line','away_rest','home_rest',
        'location','div_game','away_qb_id','home_qb_id')

def fixture(path,*,mutate_target=False):
    with path.open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=FIELDS)
        w.writeheader()
        for year in range(2014,2027):
            for week in range(1,19):
                for i in range(8):
                    target=year==2026 and week==8
                    future=year==2026 and week>=8
                    w.writerow(dict(
                        game_id=f'{year}_{week:02d}_T{2*i:02d}_T{2*i+1:02d}',
                        season=year,game_type='REG',week=week,gameday=f'{year}-10-01',
                        away_team=f'T{2*i:02d}',home_team=f'T{2*i+1:02d}',
                        away_score=(999 if target and mutate_target else '' if future else 15+((year+2*week+3*i)%28)),
                        home_score=(999 if target and mutate_target else '' if future else 16+((3*year+week+5*i)%27)),
                        total_line=(75.5 if target and mutate_target else 38+((year+week+i)%16)*0.5),
                        away_rest=7,home_rest=7,location='Home',div_game=int(i%3==0),
                        away_qb_id=('FUTURE_QB' if target and mutate_target else f'QB{2*i:02d}'),
                        home_qb_id=('FUTURE_QB2' if target and mutate_target else f'QB{2*i+1:02d}')))

class IndependentV14Tests(unittest.TestCase):
    def test_frozen_synthetic_golden_and_no_target_leakage(self):
        expected=[42.85316336356338,43.42366712447876,41.60649398495435,
                  41.23918839170456,40.15065880429099,41.07375030977338,
                  41.531479990579875,42.12323450022536]
        game_ids=[f'2026_08_T{2*i:02d}_T{2*i+1:02d}' for i in range(8)]
        with tempfile.TemporaryDirectory() as folder:
            a=Path(folder)/'original.csv';b=Path(folder)/'mutated.csv'
            fixture(a);fixture(b,mutate_target=True)
            original=projections(a,eligible_ids=set(game_ids))
            tampered=projections(b,eligible_ids=set(game_ids))
            self.assertEqual(set(original),set(game_ids))
            for i,key in enumerate(game_ids):
                self.assertAlmostEqual(original[key],expected[i],places=7)
                self.assertAlmostEqual(original[key],tampered[key],places=7)

    def test_other_seasons_require_new_frozen_release(self):
        with self.assertRaises(ValueError):
            projections(Path('unused.csv'),season=2027)

if __name__=='__main__':
    unittest.main()
