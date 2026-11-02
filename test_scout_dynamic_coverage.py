import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scout_dynamic_public import records


class ScoutDynamicCoverageTests(unittest.TestCase):
    def test_week_with_no_verified_receipts_is_reported_as_missing_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with (root/'nfl_games.csv').open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=[
                    'game_id','season','week','game_type','away_team','home_team'])
                writer.writeheader()
                writer.writerow(dict(game_id='2026_06_A_B',season=2026,week=6,
                                     game_type='REG',away_team='A',home_team='B'))
                writer.writerow(dict(game_id='2026_07_C_D',season=2026,week=7,
                                     game_type='REG',away_team='C',home_team='D'))
                writer.writerow(dict(game_id='2026_08_E_F',season=2026,week=8,
                                     game_type='REG',away_team='E',home_team='F'))
            with patch.dict(os.environ,{'TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC':'1'}):
                result=records(root,{},2026,7)
            self.assertEqual(result['scout_dynamic_counts']['ou']['Win'],0)
            self.assertEqual(result['scout_dynamic_coverage'],
                             {'expected':1,'available':0,'missing':1})
            self.assertEqual(result['scout_dynamic_records'],[])

    def test_all_weeks_coverage_counts_only_eligible_regular_season_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with (root/'nfl_games.csv').open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=[
                    'game_id','season','week','game_type','away_team','home_team'])
                writer.writeheader()
                for week in (5,6,7,8):
                    writer.writerow(dict(game_id=f'2026_{week:02d}_A_B',season=2026,
                        week=week,game_type='REG',away_team='A',home_team='B'))
                writer.writerow(dict(game_id='2026_07_CFB_A_B',season=2026,week=7,
                    game_type='POST',away_team='A',home_team='B'))
            with patch.dict(os.environ,{'TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC':'1'}):
                result=records(root,{},2026,None)
            self.assertEqual(result['scout_dynamic_coverage']['expected'],3)
            self.assertEqual(result['scout_dynamic_coverage']['available'],0)
            self.assertEqual(result['scout_dynamic_coverage']['missing'],3)


if __name__=='__main__':
    unittest.main()
