import unittest
from unittest.mock import patch
from . import test_engine
from .score_bands import mismatch,band_vector,Points,total_grade,run

class ScoreBandTests(unittest.TestCase):
    def test_bands_require_both_units_and_preserve_sign(self):
        def p(a,d):return {'pass':{'opponent_adjusted_attack':a,'opponent_adjusted_allowed':d}}
        self.assertEqual(mismatch(p(.3,-.1),'pass'),0)
        self.assertEqual(mismatch(p(.3,.02),'pass'),0)
        self.assertEqual(mismatch(p(.3,.025),'pass'),1)
        self.assertEqual(mismatch(p(.3,.075),'pass'),2)
        self.assertEqual(mismatch(p(-.3,-.15),'pass'),-3)
        self.assertEqual(band_vector(-2,9),[0.,-1.5,0.])
    def test_warmup_direction_and_bounded_score_adjustments(self):
        m=Points(3);self.assertEqual(m.adjustment([1,0,0]),0)
        for _ in range(19):m.update([1,0,0],10)
        self.assertEqual(m.adjustment([1,0,0]),0)
        m.update([1,0,0],10)
        self.assertGreater(m.adjustment([1,0,0]),0)
        self.assertGreaterEqual(m.adjustment([-1.5,0,0]),-3)
        self.assertLessEqual(m.adjustment([1.5,0,0]),3)
        negative=Points(3)
        for _ in range(25):negative.update([1,0,0],-5)
        self.assertEqual(negative.adjustment([1,0,0]),0)
    def test_combined_fit_and_cap(self):
        m=Points(6)
        for _ in range(50):m.update([1,0,0,1,0,0],20)
        self.assertEqual(m.adjustment([1.5,0,0,1.5,0,0]),4)
    def test_total_push_no_call_and_direction(self):
        self.assertEqual(total_grade(48,47,50),{'side':'Over','result':'Win'})
        self.assertEqual(total_grade(46,47,47)['result'],'Push')
        self.assertEqual(total_grade(47,47,70)['result'],'No Call')
    def test_future_outcomes_and_lines_do_not_change_pregame_scores(self):
        f=test_engine.EngineTests();f.setUp()
        try:
            rows=[dict(r,spread_line=3,total_line=45) for r in f.schedule];f.load('schedule',rows)
            def prior(n):
                m=Points(n)
                for _ in range(30):m.update([1.]+[0.]*(n-1),3.)
                return m
            def replay():
                with patch('research.player_scheme.score_bands.Points',side_effect=prior), patch('research.player_scheme.score_bands.mismatch',return_value=1):
                    return run(f.db,f.root/'schedule.csv',train_season=2023,last_season=2024)
            before=replay()
            self.assertTrue(before['games'])
            self.assertTrue(any(abs(v)>0 for v in before['games'][-1]['bonuses']['combined']))
            f.db.execute("UPDATE games SET away_score=99 WHERE gid='2024_08_NE_BUF'")
            rows[-1]['away_score']=99;f.load('schedule',rows)
            after=replay()
            self.assertEqual(before['games'][-1]['scores'],after['games'][-1]['scores'])
            for r in rows:r.update(spread_line=-20,total_line=65)
            f.load('schedule',rows);changed=replay()
            self.assertEqual([r['scores'] for r in after['games']],[r['scores'] for r in changed['games']])
        finally:f.doCleanups()

if __name__=='__main__':unittest.main()
