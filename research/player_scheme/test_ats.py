import unittest
from .ats import grade,record,audit
from . import test_engine

class ATSTests(unittest.TestCase):
    def test_home_and_away_favorites_and_underdogs(self):
        self.assertEqual(grade(-2,3,-1),{'side':'away','result':'Win'})
        self.assertEqual(grade(-4,3,-1),{'side':'home','result':'Loss'})
        self.assertEqual(grade(4,-3,7),{'side':'away','result':'Win'})
        self.assertEqual(grade(2,-3,1),{'side':'home','result':'Win'})
    def test_push_pickem_no_call_and_nonfinite(self):
        self.assertEqual(grade(-2,3,-3)['result'],'Push')
        self.assertEqual(grade(1,0,0)['result'],'Push')
        self.assertEqual(grade(-3,3,20)['result'],'No Call')
        with self.assertRaises(ValueError):grade(float('nan'),3,1)
    def test_cover_rate_excludes_pushes_and_no_calls(self):
        rows=[{'baseline':{'result':r}} for r in ['Win','Win','Loss','Push','No Call']]
        self.assertAlmostEqual(record(rows,'baseline')['cover_pct'],200/3)
    def test_replay_predictions_exclude_future_outcomes_and_market_inputs(self):
        f=test_engine.EngineTests();f.setUp()
        try:
            rows=[dict(r,spread_line=3) for r in f.schedule];f.load('schedule',rows)
            path=f.root/'schedule.csv';before=audit(f.db,path,train_season=2023)
            self.assertTrue(before['games'])
            # Change only the final game's outcomes: its own pregame model cannot change.
            f.db.execute("UPDATE games SET away_score=99 WHERE gid='2024_08_NE_BUF'")
            rows[-1]['away_score']=99;f.load('schedule',rows)
            after=audit(f.db,path,train_season=2023)
            for k in ('baseline_away_margin','enhanced_away_margin'):
                self.assertEqual(before['games'][-1][k],after['games'][-1][k])
            for r in rows:r['spread_line']=-20
            f.load('schedule',rows);changed=audit(f.db,path,train_season=2023)
            self.assertEqual([r['enhanced_away_margin'] for r in after['games']],[r['enhanced_away_margin'] for r in changed['games']])
        finally:f.doCleanups()

if __name__=='__main__':unittest.main()
