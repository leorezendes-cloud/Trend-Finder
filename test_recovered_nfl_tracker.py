import csv,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from flask import Flask,g
from jinja2 import ChoiceLoader,DictLoader
from recovered_nfl_tracker import capture,view,bp,ROOT,kickoff


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=datetime(2026,10,2,16,tzinfo=timezone.utc)
        self.games=[]
        for i,day in enumerate(('2026-09-13','2026-09-20','2026-09-27','2026-10-04'),1):
            self.games.append(dict(game_id=f'2026_{i:02d}_A_H',season='2026',week=str(i),game_type='REG',gameday=day,gametime='13:00',away_team='A',home_team='H',away_score='24' if i<4 else '',home_score='21' if i<4 else '',result='-3' if i<4 else '',location='Home',away_qb_name='Away Starter' if i<4 else '',home_qb_name='Home Starter' if i<4 else '',away_qb_id='00-0000001' if i<4 else '',home_qb_id='00-0000002' if i<4 else ''))
        self.target=self.games[-1]
        self.write_games()
        self.write_quote('40')

    def write_games(self):
        with (self.root/'nfl_games.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(self.games[0]));w.writeheader();w.writerows(self.games)

    def write_quote(self,line,now=None):
        now=now or self.now
        q=dict(game_id=self.target['game_id'],away_team='A',home_team='H',market='Total',side_a='Over',side_b='Under',line_a=line,line_b=line,captured_at_utc=now.isoformat(),kickoff_utc=kickoff(self.target).isoformat(),sportsbook='Fixture',source_url='https://example.com/line')
        with (self.root/'public_money_snapshots.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(q));w.writeheader();w.writerow(q)

    def report(self,side,name_id,now=None):
        folder=self.root/'data/scout4/starter_reports';folder.mkdir(parents=True,exist_ok=True)
        record=dict(game_id=self.target['game_id'],team=side,expected_qb_id=name_id,observed_at=(now or self.now).isoformat(),published_at=(now or self.now).isoformat(),kickoff_utc=kickoff(self.target).isoformat(),source_url='https://example.com/starter')
        (folder/(side+'.json')).write_text(json.dumps(record))

    def test_first_line_freezes_no_retroactive_qb_pick_and_final_grades(self):
        self.assertEqual(capture(self.root,self.now),1)
        self.write_quote('50')
        self.assertEqual(capture(self.root,self.now),0)
        row=view(self.root,self.now)['rows'][0]
        self.assertEqual(row['result']['market_total'],'40')
        self.assertEqual(row['result']['selection']['rule'],'D')
        self.assertIsNone(row['qb_record'])
        self.target.update(away_score='24',home_score='21',result='-3',away_qb_name='New QB')
        self.write_games()
        after=kickoff(self.target)+timedelta(hours=4)
        self.report('A','00-0000002',after)
        self.assertEqual(capture(self.root,after),0)
        row=view(self.root,after)['rows'][0]
        self.assertEqual(row['original_grade'],'Loss')
        self.assertEqual(row['qb_grade'],'No pregame QB pick')

    def test_pregame_qb_change_seals_flip_and_preserves_evidence(self):
        self.report('A','00-0000002')
        capture(self.root,self.now)
        row=view(self.root,self.now)['rows'][0]
        self.assertEqual(row['qb_record']['pick'],'Over')
        self.report('A','00-0000001')
        capture(self.root,self.now)
        self.assertEqual(view(self.root,self.now)['rows'][0]['qb_record']['pick'],'Over')
        self.target.update(away_score='24',home_score='21',result='-3');self.write_games()
        row=view(self.root,kickoff(self.target)+timedelta(hours=4))['rows'][0]
        self.assertEqual(row['qb_grade'],'Win')

    def test_non_sensitive_category_needs_no_qb_report(self):
        self.write_quote('50');capture(self.root,self.now)
        row=view(self.root,self.now)['rows'][0]
        self.assertEqual(row['result']['selection']['rule'],'F')
        self.assertEqual(row['qb_record']['pick'],'Under')

    def test_stale_and_future_lines_cannot_save(self):
        self.write_quote('40',self.now-timedelta(hours=7));self.assertEqual(capture(self.root,self.now),0)
        self.write_quote('40',self.now+timedelta(minutes=1));self.assertEqual(capture(self.root,self.now),0)

    def test_missing_qb_reports_and_stale_reports_stay_pending(self):
        self.report('A','00-0000002',self.now-timedelta(hours=25));capture(self.root,self.now)
        self.assertIsNone(view(self.root,self.now)['rows'][0]['qb_record'])

    def test_owner_access_and_read_only_page(self):
        app=Flask(__name__,template_folder=str(ROOT/'templates'),static_folder=str(ROOT/'static'))
        app.config.update(TESTING=True,PICKS_SOURCE_ROOT=str(self.root))
        app.register_blueprint(bp)
        app.jinja_loader=ChoiceLoader([DictLoader({'_site_navigation.html':'','_branding_head.html':''}),app.jinja_loader])
        app.jinja_env.filters['eastern_time']=lambda value:value or 'Unknown'
        @app.before_request
        def identity():
            from flask import request
            g.is_owner=request.headers.get('Test-Owner')=='yes'
        client=app.test_client()
        self.assertEqual(client.get('/research/recovered-totals').status_code,403)
        response=client.get('/research/recovered-totals',headers={'Test-Owner':'yes'})
        self.assertEqual(response.status_code,200)
        self.assertIn(b'40',response.data)
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertFalse((self.root/'data/recovered_totals/tracker.sqlite3').exists())


if __name__=='__main__':unittest.main()
