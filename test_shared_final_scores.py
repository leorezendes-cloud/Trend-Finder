import unittest
from pathlib import Path
from unittest.mock import patch
from app import app
from pregame_lines import effective_rows
from score_finals import final_signature

class SharedFinalTests(unittest.TestCase):
 def setUp(self):
  self.path=Path(__file__).resolve().parent/'nfl_games.csv'
  self.row=dict(game_id='2026_06_SEA_DEN',season='2026',week='6',game_type='REG',away_team='SEA',home_team='DEN',gameday='2026-10-15',gametime='20:15',away_score='',home_score='',spread_line='-3')
  self.final=dict(away='SEA',home='DEN',date='2026-10-16T00:15Z',away_score='14',home_score='17',state='post',completed=True,status='Final/OT')
 def test_shared_hosted_final_is_cached_per_request_and_offline_stays_raw(self):
  with patch.dict(app.config,HOSTED_READ_ONLY_DATA=True):
   with app.test_request_context('/trend-finder'):
    response=app.json.response({'games':[self.final]})
    with patch('fan_views.scores',return_value=response) as fetch:
     for _ in range(2):
      result=effective_rows([self.row],self.path)[0]
      self.assertEqual(result['home_score'],'17');self.assertEqual(result['result'],'3');self.assertEqual(result['overtime'],'1')
     self.assertTrue(final_signature(self.path));self.assertEqual(fetch.call_count,1)
     self.assertEqual(effective_rows([self.row],self.path,include_scores=False)[0]['home_score'],'')
   with patch('fan_views.scores') as fetch:
    self.assertEqual(effective_rows([self.row],self.path)[0]['home_score'],'');fetch.assert_not_called()
  self.assertEqual(self.row['home_score'],'')
 def test_trend_cache_signature_changes_when_a_new_final_arrives(self):
  from trend_finder_2 import _trend_data_signature
  signatures=[]
  with patch.dict(app.config,HOSTED_READ_ONLY_DATA=True):
   for finals in ([],[self.final]):
    with app.test_request_context('/trends'):
     with patch('fan_views.scores',return_value=app.json.response({'games':finals})):
      signatures.append(_trend_data_signature())
  self.assertNotEqual(*signatures)

if __name__=='__main__':unittest.main()
