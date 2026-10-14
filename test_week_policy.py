"""Clock boundaries, latest quotes, and isolated daily forecast revisions."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from site_week import active_week, week_window
from market_views import market_games
from daily_forecasts import update_daily


def write_csv(path, rows):
    with path.open('w', newline='') as source:
        writer=csv.DictWriter(source,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


class WeekPolicyTests(unittest.TestCase):
    def test_eastern_boundary_and_daylight_saving(self):
        for month,day,hour in ((10,16,12),(11,6,13)):
            before=datetime(2030,month,day,hour-1,59,tzinfo=timezone.utc)
            after=datetime(2030,month,day,hour,tzinfo=timezone.utc)
            self.assertNotEqual(week_window(before)[0],week_window(after)[0])
            self.assertEqual(week_window(after)[0].hour,8)
        games=[dict(game_type='REG',season='2030',week='6',gameday='2030-10-20',gametime='13:00')]
        self.assertIsNone(active_week(games,datetime(2030,10,16,11,59,tzinfo=timezone.utc)))
        self.assertEqual(active_week(games,datetime(2030,10,16,12,tzinfo=timezone.utc)),(2030,6))

    def test_both_markets_and_missing_game_remain_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            game=dict(game_id='g',game_type='REG',season='2030',week='6',gameday='2030-10-20',gametime='13:00',away_team='A',home_team='B',away_score='',home_score='',spread_line='',total_line='')
            write_csv(root/'nfl_games.csv',[game,dict(game,game_id='missing',away_team='C')])
            quote=dict(game_id='g',away_team='A',home_team='B',kickoff_utc='2030-10-20T17:00:00Z',captured_at_utc='2030-10-19T12:00:00Z',market='Spread',side_a='A',side_b='B',line_a='3',line_b='-3')
            write_csv(root/'public_money_snapshots.csv',[quote,dict(quote,market='Total',side_a='Over',side_b='Under',line_a='44.5',line_b='44.5'),dict(quote,captured_at_utc='2030-10-19T14:00:00Z',line_a='99',line_b='-99')])
            games=market_games(root,datetime(2030,10,19,13,tzinfo=timezone.utc))
            self.assertEqual(len(games),2)
            self.assertEqual((games[0]['spread'],games[0]['total']),(3,44.5))
            self.assertIsNone(games[1]['spread']);self.assertIsNone(games[1]['total'])

    def test_daily_revision_preserves_original_and_retains_change(self):
        from scout4.blend import CORE
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('nfl_games.csv','public_money_snapshots.csv',*CORE):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('unchanged')
            folder=root/'data/scout4/blend/predictions';folder.mkdir(parents=True)
            original=dict(game_id='g',components={'Blend':{'pick':'A','away_margin':1}},quote={'line':3},totals=None)
            path=folder/'g.json';path.write_text(json.dumps(original));before=path.read_bytes()
            calls=[]
            def runner(work,now):
                calls.append(now)
                base=work/'data/scout4/blend';(base/'predictions').mkdir(parents=True)
                (base/'predictions/g.json').write_text(json.dumps(dict(original,components={'Blend':{'pick':'B','away_margin':-5}})))
                (base/'status.json').write_text(json.dumps({'pending':[]}))
            now=datetime(2030,10,19,13,tzinfo=timezone.utc)
            report=update_daily(root,now,runner)
            self.assertEqual(report['records']['g']['components']['Blend']['pick'],'B')
            self.assertEqual(report['changes']['g']['previous'],original)
            update_daily(root,now,runner);self.assertEqual(len(calls),1)
            report=update_daily(root,datetime(2030,10,20,13,tzinfo=timezone.utc),runner)
            self.assertIn('g',report['changes']);self.assertEqual(path.read_bytes(),before)
            self.assertTrue((root/'data/scout4/daily/2030-10-19/blend/predictions/g.json').exists())

    def test_saved_manual_analysis_reopens_results(self):
        from app import app
        response=app.test_client().get('/trend-finder?run=analyze&season=2026&location=Away')
        self.assertEqual(response.status_code,200)
        self.assertIn('<h2>Results</h2>',response.text)
        self.assertIn('Sign in to save this trend',response.text)

    def test_pending_daily_review_can_retry(self):
        from scout4.blend import CORE
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('nfl_games.csv','public_money_snapshots.csv',*CORE):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('unchanged')
            (root/'data/scout4').mkdir(parents=True)
            calls=[]
            def runner(work,now):
                calls.append(now);base=work/'data/scout4/blend';base.mkdir(parents=True)
                (base/'status.json').write_text(json.dumps({'pending':[{'game_id':'g','reason':'Missing quotes'}]}))
            now=datetime(2030,10,19,13,tzinfo=timezone.utc)
            update_daily(root,now,runner);update_daily(root,now,runner)
            self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
