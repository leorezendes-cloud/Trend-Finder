import unittest,tempfile,csv
from pathlib import Path
from unittest.mock import patch
from weekly_results import build_results
class WeeklyResultsChecks(unittest.TestCase):
 def test_full_week_and_original_pick_line(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   games={'x':dict(game_id='x',season='2026',week='5',game_type='REG',gameday='2026-10-12',gametime='20:15',away_team='BUF',home_team='LA',away_score='37',home_score='34',spread_line='3.5',line_source='Capture'), 'y':dict(game_id='y',season='2026',week='5',game_type='REG',gameday='2026-10-08',gametime='20:15',away_team='TB',home_team='DAL',away_score='7',home_score='10',spread_line='1.5',line_source='CSV')}
   row=dict(away='BUF',home='LA',underdog='LA',favorite='BUF',spread='4',form_cover_cushion='2',form_lean='Form leans underdog')
   with (root/'sunday_scout_pregame_2026-10-11.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=row);w.writeheader();w.writerow(row)
   with patch('weekly_results.load_games',return_value=games):v=build_results(root,5)
   self.assertEqual(len(v['games']),2)
   b=next(g for g in v['games'] if g['away_team']=='BUF')
   self.assertEqual(b['underdog'],'BUF');self.assertEqual(b['ats_result'],'Cover')
   self.assertEqual(b['scout_pick'],'LA +4');self.assertEqual(b['scout_result'],'Correct')
   self.assertEqual(v['games'][0]['scout_pick'],'No saved pick')
