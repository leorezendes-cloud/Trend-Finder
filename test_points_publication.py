import copy,csv,json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from scout4 import blend
from scout4.research_benchmarks import recent_epa,grade_benchmarks

class PointsPublicationTests(unittest.TestCase):
    def test_weights_select_points_and_legacy_default_is_unchanged(self):
        self.assertEqual(blend.combine(-20,4,0)['away_margin'],-8)
        self.assertEqual(blend.combine(-20,4,0,{'scout_scoring':0,'plug_points_only':1})['away_margin'],4)
        for weights in ({},{'scout_scoring':-1,'plug_points_only':2},{'scout_scoring':.5,'plug_points_only':1}, {'scout_scoring':float('nan'),'plug_points_only':1}):
            with self.assertRaises(ValueError):blend.combine(1,2,0,weights)

    def test_new_policy_and_benchmarks_are_saved_once_on_same_line(self):
        config=json.loads((Path(__file__).parent/'automatic_model.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);now=datetime(2030,10,16,12,tzinfo=timezone.utc)
            game={'game_id':'g','season':'2030','week':'6','game_type':'REG','gameday':'2030-10-20','gametime':'13:00','away_team':'A','home_team':'B'}
            with (root/'nfl_games.csv').open('w',newline='') as output:
                writer=csv.DictWriter(output,fieldnames=game);writer.writeheader();writer.writerow(game)
            (root/'public_money_snapshots.csv').write_text('game_id,market\n')
            def seal(path,record):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(record));return True
            scout={'margin_first':-20,'first_estimate':{'plausible':True},'second_estimate':{'plausible':True}}
            with patch.object(blend,'configuration',return_value=(config,'hash')),patch.object(blend,'load_stats',return_value=({},{})),patch.object(blend,'statistics_gate',return_value=None),patch.object(blend,'quote',side_effect=lambda quotes,g,market,now:{'line':0 if market=='Spread' else 40}),patch.object(blend,'build_ratings',return_value=({},{})),patch.object(blend,'matchup',return_value=scout),patch.object(blend,'plug_prediction',return_value={'away_margin':4}),patch.object(blend,'profiles',return_value=({},{})),patch.object(blend,'features',return_value={}),patch.object(blend,'seal',side_effect=seal),patch('scout4.research_benchmarks.recent_epa',return_value={'away_margin':-1,'version':'fixture'}) as benchmark:
                self.assertEqual(blend.run(root,now)['saved'],1)
                path=root/'data/scout4/blend/predictions/g.json';before=path.read_bytes();record=json.loads(before)
                self.assertEqual(record['version'],'plug-points-only-4')
                self.assertEqual(record['components']['Blend']['pick'],'A')
                self.assertEqual(record['research_benchmarks']['Previous 50/50']['pick'],'B')
                self.assertEqual(record['research_benchmarks']['EPA Recent Form']['pick'],'B')
                self.assertEqual(blend.run(root,now+timedelta(minutes=1))['preserved'],1)
                self.assertEqual(path.read_bytes(),before)
                benchmark.side_effect=ValueError('Missing benchmark history')
                game['game_id']='g2'
                with (root/'nfl_games.csv').open('w',newline='') as output:
                    writer=csv.DictWriter(output,fieldnames=game);writer.writeheader();writer.writerow(game)
                self.assertEqual(blend.run(root,now+timedelta(minutes=2))['saved'],1)
                second=json.loads((root/'data/scout4/blend/predictions/g2.json').read_text())
                self.assertEqual(second['components']['Blend']['pick'],'A')
                self.assertIsNone(second['research_benchmarks']['EPA Recent Form']['pick'])
                self.assertEqual(path.read_bytes(),before)

    def test_epa_excludes_target_and_future_performance(self):
        schedule=[];feed=[]
        for week in range(1,5):
            schedule.append({'game_id':str(week),'season':'2030','week':str(week),'game_type':'REG','away_team':'A','home_team':'B','away_score':'20','home_score':'10'})
            feed.extend([{'game_id':str(week),'team':team,'season_type':'REG','passing_epa':value,'rushing_epa':0} for team,value in [('A',week),('B',0)]])
        target={**schedule[3],'week':'4'}
        result=recent_epa(schedule,feed,target)
        self.assertEqual(result['history']['away'],['1','2','3'])
        changed=copy.deepcopy(feed)
        for row in changed:
            if row['game_id']=='4':row['passing_epa']=100000
        self.assertEqual(result,recent_epa(schedule,changed,target))
        self.assertIsNone(recent_epa(schedule,feed,{**target,'week':'3'}))

    def test_grading_rejects_late_records_and_mismatched_identity(self):
        game={'game_id':'g','away_team':'A','home_team':'B','away_score':'20','home_score':'17'}
        record={**{k:game[k] for k in ('game_id','away_team','home_team')},'kickoff_utc':'2030-10-20T17:00:00+00:00',
                'decision_cutoff_utc':'2030-10-16T12:00:00+00:00','sealed_at_utc':'2030-10-16T12:01:00+00:00',
                'quote':{'line':-2.5,'captured_at_utc':'2030-10-16T11:00:00+00:00'},'research_benchmarks':{'comparison':{'pick':'A'}}}
        self.assertEqual(grade_benchmarks(record,game),{'comparison':'Win'})
        with self.assertRaises(ValueError):grade_benchmarks({**record,'sealed_at_utc':record['kickoff_utc']},game)
        with self.assertRaises(ValueError):grade_benchmarks(record,{**game,'game_id':'other'})

    def test_weekly_note_identifies_new_formula_without_changing_old_record(self):
        from weekly_results import build_results
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            game={'game_id':'g','season':'2026','week':'6','game_type':'REG','gameday':'2026-10-18','gametime':'13:00','away_team':'A','home_team':'B','away_score':'20','home_score':'17','spread_line':'3','total_line':'40'}
            folder=root/'data/scout4/blend/predictions';folder.mkdir(parents=True)
            record={'game_id':'g','season':2026,'week':6,'away_team':'A','home_team':'B','kickoff_utc':'2026-10-18T17:00:00Z',
                    'quote':{'line':3,'captured_at_utc':'2026-10-13T12:00:00Z'},
                    'components':{'Blend':{'pick':'A','ats_edge':1}},'weights':{'scout_scoring':0,'plug_points_only':1},
                    'totals':{'quote':{'line':40},'prediction':{'lean':'Over'}}}
            path=folder/'g.json';path.write_text(json.dumps(record));before=path.read_bytes()
            with patch('weekly_results.load_games',return_value={'g':game}):view=build_results(root,6)
            self.assertEqual(view['model_label'],'Original Plug ATS')
            self.assertIn('points-for/points-allowed',view['model_note'])
            self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
