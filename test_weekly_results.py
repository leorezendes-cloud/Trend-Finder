import unittest,tempfile,csv
from pathlib import Path
from unittest.mock import patch
from weekly_results import build_results
class WeeklyResultsChecks(unittest.TestCase):
 def test_combined_plug_record_includes_historical_and_prospective_weeks(self):
  from weekly_results import _combined_plug_record
  combined=_combined_plug_record(
   [dict(game_id='2026_06_A_B',season=2026,week=6,away_team='A',home_team='B',
         ats_side='B',ats_result='Win',ou_side='Under',ou_result='Loss')],
   [dict(game_id='2026_08_C_D',season=2026,week=8,away_team='C',home_team='D',
         ats_selected=True,ats_side='C',ats_result='Pending',ou_selected=True,
         ou_side='Over',ou_result='Win')])
  self.assertEqual([r['week'] for r in combined['rows']],[6,8])
  self.assertEqual(combined['counts']['ats']['Win'],1)
  self.assertEqual(combined['counts']['ats']['Pending'],1)
  self.assertEqual(combined['counts']['ou']['Loss'],1)
  self.assertEqual(combined['counts']['ou']['Win'],1)

 def test_full_week_does_not_publish_legacy_scout_csv_picks(self):
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
   self.assertEqual(b['scout_pick'],'No current pick');self.assertEqual(b['scout_result'],'—')
   self.assertEqual(v['games'][0]['scout_pick'],'No current pick')
