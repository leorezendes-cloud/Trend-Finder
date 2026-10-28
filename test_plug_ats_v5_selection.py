"""Prospective ATS-v5 policy and frozen historical parity checks (no network)."""
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

from plug_ats_v5_model import projections
from plug_ats_v5_weekly import classify,read_week,issue_pending,for_game,POLICY

class ATSv5Selection(unittest.TestCase):
    def test_favorite_threshold_is_strict(self):
        self.assertEqual(classify(8.5,8.,'AWY','HME'),'HME')
        self.assertEqual(classify(7.5,8.,'AWY','HME'),'AWY')
        self.assertIsNone(classify(8.0,8.,'AWY','HME'))
        self.assertIsNone(classify(9.0,8.,'AWY','HME'))
        self.assertIsNone(classify(7.01,7.,'AWY','HME'))
        self.assertIsNone(classify(-6.5,-7.,'AWY','HME'))
        self.assertEqual(classify(-8.5,-8.,'AWY','HME'),'HME')
        self.assertEqual(classify(-7.5,-8.,'AWY','HME'),'AWY')
        self.assertIsNone(classify(-8.,-8.,'AWY','HME'))
        self.assertIsNone(classify(-9.,-8.,'AWY','HME'))

    def test_golden_frozen_v5_predictions(self):
        root=Path(__file__).resolve().parent
        samples={
            2024:(4,{'2024_04_BUF_BAL':-2.840}),
            2025:(4,{'2025_04_BAL_KC':-1.363}),
            2026:(6,{'2026_06_HOU_JAX':6.294,
                     '2026_06_CAR_PHI':-0.293})
        }
        for year,(week,expected) in samples.items():
            with self.subTest(season=year):
                predicted=projections(root/'nfl_games.csv',year,week)
                for game,value in expected.items():
                    self.assertAlmostEqual(predicted[game],value,delta=0.004)

    def test_no_hindsight_when_data_for_target_week_changes(self):
        # Production Week 6 forecasts must not consume Week 6 actual scores
        # or the QB actually used in that same target game.
        from plug_ats_v5_model import read_games,features,fit
        source=Path(__file__).resolve().parent/'nfl_games.csv'
        records=read_games(source)
        baseline=features(records,2026,6)
        changed=[dict(r) for r in records]
        for g in changed:
            if g['season']==2026 and g['week']>=6:
                g.update(a_score=1000.,h_score=0.,a_qb='FUTURE-QB',
                         h_qb='ANOTHER-FUTURE-QB')
        altered=features(changed,2026,6)
        old={g['id']:x for g,x in baseline if g['season']==2026 and g['week']==6}
        new={g['id']:x for g,x in altered if g['season']==2026 and g['week']==6}
        self.assertEqual(old,new)

if __name__=='__main__':
    unittest.main()
