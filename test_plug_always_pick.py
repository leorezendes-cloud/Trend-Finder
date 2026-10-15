import hashlib,json,unittest
from pathlib import Path
from scout4.blend import combine,plug_ats_pick,plug_total_pick,configuration
from unittest.mock import patch

class PlugPickPolicyTests(unittest.TestCase):
    def test_close_edges_always_have_direction_and_exact_ties_use_dog(self):
        game={'away_team':'A','home_team':'B'}
        self.assertEqual(plug_ats_pick(combine(-2.99,-2.99,3),game,3,True),'A')
        self.assertEqual(plug_ats_pick(combine(-3.01,-3.01,3),game,3,True),'B')
        self.assertEqual(plug_ats_pick(combine(-3,-3,3),game,3,True),'A')
        self.assertEqual(plug_ats_pick(combine(3,3,-3),game,-3,True),'B')
        self.assertEqual(plug_ats_pick(combine(0,0,0),game,0,True),'B')
        self.assertIsNone(plug_ats_pick(combine(-3,-3,3),game,3,False))

    def test_totals_tie_does_not_modify_original_prediction(self):
        prediction={'lean':'No Call','total':44,'prob_over':.5}
        result=plug_total_pick(prediction,True)
        self.assertEqual(result['lean'],'Under')
        self.assertIn('tie_break',result)
        self.assertEqual(prediction['lean'],'No Call')
        for lean in ('Over','Under'):
            self.assertEqual(plug_total_pick({'lean':lean},True),{'lean':lean})

    def test_production_configuration_is_versioned_and_hash_valid(self):
        root=Path(__file__).resolve().parent
        with patch.dict('os.environ',{'TREND_FINDAH_AUTO_MODEL_CONFIG':str(root/'automatic_model.json')}):
            config,_=configuration(root)
        self.assertTrue(config['always_pick'])
        self.assertEqual(config['version'],'plug-points-only-4')
        for name,digest in config['code_sha256'].items():self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),digest)

    def test_new_capture_uses_policy_and_existing_pick_stays_locked(self):
        import csv,tempfile
        from datetime import datetime,timezone,timedelta
        from scout4 import blend
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);now=datetime(2030,10,16,12,tzinfo=timezone.utc)
            game={'game_id':'g','season':'2030','week':'6','game_type':'REG','gameday':'2030-10-20','gametime':'13:00','away_team':'A','home_team':'B'}
            with (root/'nfl_games.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=game);writer.writeheader();writer.writerow(game)
            (root/'public_money_snapshots.csv').write_text('game_id,market\n')
            config={'always_pick':True,'score_model':{},'totals_candidate':{'model':{}},'version':'always-pick-test','weights':{'scout_scoring':.5,'plug_points_only':.5}}
            def seal(path,record):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(record));return True
            estimate={'margin_first':-3,'first_estimate':{'plausible':True},'second_estimate':{'plausible':True}}
            with patch.object(blend,'configuration',return_value=(config,'config-hash')),patch.object(blend,'load_stats',return_value=({},{})),patch.object(blend,'statistics_gate',return_value=None),patch.object(blend,'quote',side_effect=lambda quotes,g,market,now:{'line':3 if market=='Spread' else 40}),patch.object(blend,'build_ratings',return_value=({},{})),patch.object(blend,'matchup',return_value=estimate),patch.object(blend,'plug_prediction',return_value={'away_margin':-3}),patch.object(blend,'profiles',return_value=({},{})),patch.object(blend,'features',return_value={'ready':True}),patch.object(blend,'predict',return_value={'lean':'No Call','total':40}),patch.object(blend,'seal',side_effect=seal):
                self.assertEqual(blend.run(root,now)['saved'],1)
                path=root/'data/scout4/blend/predictions/g.json';before=path.read_bytes();record=json.loads(before)
                self.assertEqual(record['components']['Blend']['pick'],'A')
                self.assertEqual(record['totals']['prediction']['lean'],'Under')
                self.assertEqual(blend.run(root,now+timedelta(seconds=1))['preserved'],1)
                self.assertEqual(path.read_bytes(),before)
