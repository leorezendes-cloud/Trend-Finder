import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scout_dynamic_public import records, _week_six_shadow_totals


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



    def test_week7_uses_saved_positive_scout_totals_and_frozen_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with (root/'nfl_games.csv').open('w',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=['game_id','season','week','game_type','away_team','home_team','away_score','home_score'])
                writer.writeheader()
                writer.writerow(dict(game_id='2026_07_A_B',season=2026,week=7,game_type='REG',away_team='A',home_team='B',away_score=24,home_score=20))
            saved={'2026_07_A_B':{'game_id':'2026_07_A_B','season':2026,'week':7,'away_team':'A','home_team':'B','kickoff_utc':'2026-10-25T17:00:00+00:00','totals':{'quote':{'line':43.5},'prediction':{'lean':'Over'}}}}
            with patch.dict(os.environ,{'TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC':'0'}):
                with patch('forecast_history.official_sources',return_value=saved):
                    with patch('forecast_history.total_result',return_value='Correct'):
                        result=records(root,{},2026,7)
            self.assertEqual(result['scout_dynamic_counts']['ou']['Win'],1)
            self.assertEqual(result['scout_dynamic_coverage'],{'expected':1,'available':1,'missing':0})
            row=result['scout_dynamic_records'][0]
            self.assertEqual(row['ou_side'],'Over')
            self.assertEqual(row['grades']['ou'],'Win')
            self.assertEqual(row['source'],'saved positive Scout totals')


    def test_week6_shadow_totals_use_frozen_candidate_schema_and_template_line_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config={'totals_model_file_sha256':'f'*64,'totals_candidate':{
                'name':'Market + statistics','target_season':2026,'first_eligible_week':6,
                'model':{'version':'scout4-totals-1'}}}
            (root/'automatic_model.json').write_text(json.dumps(config))
            shadow=[]
            for n in range(14):
                shadow.append({'game_id':f'2026_06_A{n}_B{n}','season':2026,'week':6,
                    'market':'Total','model_sha256':'f'*64,'model_name':'Market + statistics',
                    'away_team':f'A{n}','home_team':f'B{n}',
                    'kickoff_utc':'2026-10-18T17:00:00+00:00','selected_side':'Over',
                    'quote':{'line':44.5},'result':'Correct'})
            with patch('scout4.shadow.view',return_value={'records':shadow}):
                rows=_week_six_shadow_totals(root)
            self.assertEqual(len(rows),14)
            self.assertEqual(rows[0]['total_quote'],{'line':44.5})

if __name__=='__main__':
    unittest.main()
