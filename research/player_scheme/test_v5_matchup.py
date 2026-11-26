import csv,json,os,tempfile,unittest
from pathlib import Path
from .v5_matchup import load_model,comparison,qualifies

ROOT=Path(__file__).resolve().parents[2]
MODEL=Path(os.environ.get('V5_MODEL_PATH',ROOT/'plug_ats_v5_model.py'))
SCHEDULE=Path(os.environ.get('V5_SCHEDULE_PATH',ROOT/'nfl_games.csv'))

class V5MatchupTests(unittest.TestCase):
    def test_unchanged_model_golden_predictions(self):
        m=load_model(MODEL)
        for year,week,expected in [(2024,4,{'2024_04_BUF_BAL':-2.840}),(2025,4,{'2025_04_BAL_KC':-1.363}),(2026,6,{'2026_06_HOU_JAX':6.294,'2026_06_CAR_PHI':-.293})]:
            actual=m.projections(SCHEDULE,year,week)
            for gid,value in expected.items():self.assertAlmostEqual(actual[gid],value,delta=.004)
    def test_zero_bonus_and_signs_preserve_v5_and_freeze_original_shortlist(self):
        r=comparison(8.5,8.,-10.,0.,0.)
        self.assertEqual(r['baseline'],r['adjusted']);self.assertTrue(r['baseline_selected'])
        r=comparison(8.5,8.,-10.,1.,0.)
        self.assertEqual(r['baseline'],{'side':'home','result':'Win'})
        self.assertEqual(r['adjusted'],{'side':'away','result':'Loss'})
        self.assertEqual(r['adjusted_away_margin'],-7.5)
        self.assertTrue(r['baseline_selected']);self.assertTrue(r['adjusted_selected'])
        self.assertFalse(qualifies(7.5,7));self.assertFalse(qualifies(8,8));self.assertFalse(qualifies(9,8))
    def test_push_no_call_nonfinite_and_model_hash_gate(self):
        self.assertEqual(comparison(8.5,8,-8,0,0)['baseline']['result'],'Push')
        self.assertEqual(comparison(8,8,-8,0,0)['baseline']['result'],'No Call')
        with self.assertRaises(ValueError):comparison(8,8,0,float('inf'),0)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'different.py';p.write_text('raise RuntimeError("must never execute")\n')
            with self.assertRaises(ValueError):load_model(p)
    def test_target_week_scores_qbs_and_market_line_do_not_change_v5_prediction(self):
        m=load_model(MODEL);before=m.projections(SCHEDULE,2026,6)
        with SCHEDULE.open(newline='',encoding='utf-8-sig') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
        for r in rows:
            if r['season']=='2026' and int(r['week'])>=6:r.update(away_score='999',home_score='0',away_qb_id='FUTURE-QB',home_qb_id='FUTURE-QB-2',spread_line='999')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'altered.csv'
            with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            self.assertEqual(before,m.projections(p,2026,6))

if __name__=='__main__':unittest.main()
