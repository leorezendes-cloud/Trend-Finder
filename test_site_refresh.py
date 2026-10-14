import csv,json,tempfile,unittest,hashlib
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from site_views import upcoming_rows
from weekly_results import build_results

class PublicScheduleTests(unittest.TestCase):
    def test_saved_line_same_game_future_quotes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=[{'game_id':'g','gameday':'2030-10-20','gametime':'13:00','away_team':'A','home_team':'B','away_score':'','home_score':'','spread_line':'','season':'2030','game_type':'REG','week':'6'}]
            with (root/'nfl_games.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            quote={'game_id':'g','market':'Spread','away_team':'A','home_team':'B','side_a':'A','side_b':'B','line_a':'3','line_b':'-3','captured_at_utc':'2030-10-19T12:00:00Z','kickoff_utc':'2030-10-20T17:00:00Z'}
            with (root/'public_money_snapshots.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(quote));w.writeheader();w.writerows([quote,dict(quote,line_a='99',line_b='-99',captured_at_utc='2030-10-20T16:00:00Z'),dict(quote,away_team='C',line_a='88',line_b='-88')])
            before=(root/'nfl_games.csv').read_bytes();now=datetime(2030,10,19,13,tzinfo=timezone.utc)
            view=upcoming_rows(root,now);self.assertEqual(view[0]['spread_line'],'3.0')
            folder=root/'data/scout4/blend/predictions';folder.mkdir(parents=True)
            (folder/'g.json').write_text(json.dumps({'game_id':'g','away_team':'A','home_team':'B','kickoff_utc':quote['kickoff_utc'],'quote':{'line':2,'captured_at_utc':quote['captured_at_utc']}}))
            self.assertEqual(upcoming_rows(root,now)[0]['spread_line'],'3.0')
            self.assertEqual((root/'nfl_games.csv').read_bytes(),before)

class BlendResultsTests(unittest.TestCase):
    def test_original_quote_controls_ats_and_total_grading(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'data/scout4/blend/predictions';folder.mkdir(parents=True)
            g={'game_id':'g','season':'2026','week':'6','game_type':'REG','gameday':'2026-10-18','gametime':'13:00','away_team':'A','home_team':'B','away_score':'20','home_score':'22','spread_line':'-100','line_source':'Changed schedule'}
            r={'game_id':'g','season':2026,'week':6,'away_team':'A','home_team':'B','kickoff_utc':'2026-10-18T17:00:00Z','quote':{'line':3,'captured_at_utc':'2026-10-13T12:00:00Z'},'components':{'Blend':{'pick':'A','ats_edge':1}},'totals':{'quote':{'line':40},'prediction':{'lean':'Over'}}}
            p=folder/'g.json';p.write_text(json.dumps(r));before=p.read_bytes()
            with patch('weekly_results.load_games',return_value={'g':g}):v=build_results(root,6)
            self.assertEqual(v['model_label'],'Blended ATS');self.assertEqual(v['games'][0]['scout_pick'],'A +3')
            self.assertEqual(v['games'][0]['scout_result'],'Correct');self.assertEqual(v['games'][0]['total_result'],'Correct')
            self.assertEqual(v['tally']['total_correct'],1);self.assertEqual(p.read_bytes(),before)
            g['away_score']=g['home_score']=''
            with patch('weekly_results.load_games',return_value={'g':g}):v=build_results(root)
            self.assertEqual(v['selected_week'],6);self.assertEqual(v['games'][0]['scout_result'],'Pending')

if __name__=='__main__':unittest.main()
