import unittest
from datetime import datetime,timezone
from weekly_results import confirmed_score_rows

class WeeklyFinalFallbackTests(unittest.TestCase):
 def setUp(self):
  self.game=dict(game_id='2026_06_SEA_DEN',away_team='SEA',home_team='DEN',gameday='2026-10-15',gametime='20:15',away_score='',home_score='',spread_line='-3')
  self.final=dict(away='SEA',home='DEN',date='2026-10-16T00:15Z',away_score='14',home_score='17',state='post',completed=True)
  self.now=datetime(2026,10,16,5,tzinfo=timezone.utc)
 def apply(self,updates):return confirmed_score_rows([self.game],updates,self.now)[0]
 def test_correct_final_is_read_only_and_keeps_line(self):
  row=self.apply([self.final]);self.assertEqual(row['away_score'],'14');self.assertEqual(row['home_score'],'17');self.assertEqual(row['spread_line'],'-3');self.assertEqual(row['result'],'3');self.assertEqual(self.game['away_score'],'')
 def test_requires_final_status_identity_time_and_valid_scores(self):
  for change in ({'completed':False},{'state':'in'},{'away':'SF'},{'date':'2026-10-17T00:15Z'},{'home_score':'nan'},{'away_score':'-1'},{'home_score':'17.5'},{'date':'2026-10-16T00:30Z'}):
   self.assertEqual(self.apply([dict(self.final,**change)])['away_score'],'')
 def test_conflicts_are_rejected_and_saved_finals_preserved(self):
  self.assertEqual(self.apply([self.final,dict(self.final,home_score='20'),self.final])['away_score'],'')
  self.game.update(away_score='10',home_score='13');self.assertEqual(self.apply([self.final])['away_score'],'10')

if __name__=='__main__':unittest.main()
