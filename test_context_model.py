import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from scout4.context_model import features, fit, capture

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.pred = {'game_id':'g', 'decision_cutoff_utc':'2026-10-14T12:00:00Z',
                     'kickoff_utc':'2026-10-15T12:00:00Z','away_team':'BUF','home_team':'NYJ'}
        self.weather = {'game_id':'g','kickoff_utc':self.pred['kickoff_utc'],
                        'observed_at':'2026-10-14T11:00:00Z','roof_context':'Open-air metadata',
                        'hours':[{'wind_speed_10m':10,'wind_gusts_10m':20,'temperature_2m':40,'precipitation':0.1} for _ in range(4)]}
        self.people = {'game_id':'g','kickoff_utc':self.pred['kickoff_utc'],
                       'observed_at':'2026-10-14T11:00:00Z','personnel':{}}
        for team in ('BUF','NYJ'):
            self.people['personnel'][team] = {'observed_at':self.people['observed_at'],
               'injury_coverage':'reported rows only', 'injury_rows':[{'report_status':'Out'},{'report_status':'Questionable'}]}
    def test_observations_are_not_assumed_penalties(self):
        self.assertEqual(features(self.pred,self.weather,self.people),[10,20,10,0.1,1,1])
    def test_late_stale_and_wrong_game_rejected(self):
        for field,value in [('observed_at','2026-10-14T13:00:00Z'),('observed_at','2026-10-12T11:00:00Z'),('game_id','other')]:
            weather=copy.deepcopy(self.weather);weather[field]=value
            with self.assertRaises(ValueError):features(self.pred,weather,self.people)
    def test_unknown_is_not_healthy(self):
        self.people['personnel']['BUF']['injury_coverage']='unknown'
        with self.assertRaises(ValueError):features(self.pred,self.weather,self.people)
    def test_unknown_roof_is_not_outdoor(self):
        self.weather['roof_context']='Retractable roof; game setting unconfirmed'
        with self.assertRaises(ValueError):features(self.pred,self.weather,self.people)
    def test_fitted_adjustment_uses_observed_training_residuals(self):
        model=fit([([i,0,0,0,0,0],2*i+3) for i in range(100)])
        self.assertLess(abs(model([50,0,0,0,0,0])-103),0.2)

    def test_capture_is_immutable_and_does_not_write_official_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.pred['components']={'Blend':{'away_margin':3}}
            self.pred['totals']={'prediction':{'total':42}}
            inputs=[('data/scout4/blend/predictions/g.json',self.pred),
                    ('data/scout4/weather/snapshot/evidence.json',{'records':[self.weather]}),
                    ('data/scout4/personnel/2026/snapshot/pregame_evidence.json',{'games':[self.people]})]
            for name,data in inputs:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data))
            (root/'nfl_games.csv').write_text('game_id,away_score,home_score\n')
            official=root/inputs[0][0]; before=official.read_bytes()
            with patch('scout4.context_model.evaluate',return_value={}):
                self.assertEqual(capture(root)['eligible_records'],1)
                saved=root/'data/scout4/context/records/g.json'; first=saved.read_bytes()
                self.assertIsNone(json.loads(first)['candidate'])
                capture(root)
            self.assertEqual(first,saved.read_bytes())
            self.assertEqual(before,official.read_bytes())

    def test_research_collection_failure_does_not_prevent_official_predictions(self):
        from hosted_updates import update_once
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'logs').mkdir()
            (root/'nfl_games.csv').write_text('game_id,away_team,home_team\n')
            (root/'data/scout4/blend/predictions').mkdir(parents=True)
            with patch.dict('os.environ',{'TREND_FINDAH_CONTEXT_RESEARCH':'1'}), \
                 patch('hosted_updates.backup_database'), patch('update_nfl_games.main'), \
                 patch('scout4.collect.collect'), patch('scheduled_ats_capture.run',return_value=0), \
                 patch('scout4.context_model.refresh_sources',side_effect=ValueError('unavailable')), \
                 patch('scout4.context_model.capture'), patch('scout4.blend.run') as official:
                status=update_once(root)
            official.assert_called_once()
            self.assertEqual(status['stages']['injury/weather collection'],'failed: ValueError')

if __name__=='__main__':unittest.main()
