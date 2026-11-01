import math,unittest
from . import test_full_ats
from .full_ats import run
from .v5_full import V5Baseline

class V5FullTests(unittest.TestCase):
    def fixture(self):
        helper=test_full_ats.FullATSTests();f=helper.fixture();self.addCleanup(helper.doCleanups)
        f.load('schedule',[dict(r,spread_line=3) for r in f.schedule]);return f
    def test_v5_sign_and_week_cache(self):
        class Model:
            calls=0
            def projections(self,path,year,week):self.calls+=1;return {'g':-7.5,'h':2}
        m=Model();b=V5Baseline(m,'unused')
        self.assertEqual(b(2024,4,'g'),7.5);self.assertEqual(b(2024,4,'h'),-2);self.assertEqual(m.calls,1)
        b(2024,5,'g');self.assertEqual(m.calls,2)
    def test_actual_v5_provider_replaces_pfpa_and_warmup_has_zero_bonus(self):
        f=self.fixture();calls=[]
        def provider(y,w,g):calls.append(g);return 9.25
        r=run(f.db,f.root/'schedule.csv',train_season=2023,last_season=2024,baseline_provider=provider)
        self.assertTrue(calls);self.assertTrue(r['games'])
        for g in r['games']:
            self.assertEqual(set(g['margins'].values()),{9.25})
    def test_future_outcomes_do_not_change_earlier_predictions(self):
        f=self.fixture();path=f.root/'schedule.csv'
        before=run(f.db,path,train_season=2023,last_season=2024,baseline_provider=lambda *a:7)
        f.db.execute('UPDATE games SET away_score=99 WHERE week>=4')
        rows=[dict(r,spread_line=3,away_score=99 if r['week']>=4 else r['away_score']) for r in f.schedule]
        f.load('schedule',rows)
        after=run(f.db,path,train_season=2023,last_season=2024,baseline_provider=lambda *a:7)
        self.assertEqual([(r['game_id'],r['margins']) for r in before['games']],[(r['game_id'],r['margins']) for r in after['games']])
    def test_trained_residual_uses_only_released_prior_targets(self):
        import csv,tempfile
        from datetime import datetime,timedelta,timezone
        from pathlib import Path
        from unittest.mock import patch
        from .full_ats import VARIANTS
        start=datetime(2024,1,1,tzinfo=timezone.utc)
        games=[]
        for i in range(45):
            kickoff=start+timedelta(days=7*i)
            games.append((f'g{i}',2024,i+1,kickoff.isoformat(),(kickoff+timedelta(hours=6)).isoformat(),'NE','BUF',30.,20.))
        class DB:
            def execute(self,*a):return self
            def fetchall(self):return games
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'schedule.csv'
            def replay():
                with p.open('w',newline='') as file:
                    w=csv.DictWriter(file,fieldnames=['game_id','game_type','spread_line','away_team','home_team','away_score','home_score']);w.writeheader()
                    w.writerows(dict(game_id=g[0],game_type='REG',spread_line=3,away_team='NE',home_team='BUF',away_score=g[7],home_score=g[8]) for g in games)
                return run(DB(),p,train_season=2023,last_season=2024,baseline_provider=lambda *a:0.)
            with patch('research.player_scheme.full_ats.build',return_value={'teams':[{'games':3},{'games':3}]}), patch('research.player_scheme.full_ats.inputs',return_value=({k:[1.] for k in VARIANTS if k!='baseline'},[{'neutral_dropbacks':0,'pressure_matchup_available':False,'man_matchup_available':False,'zone_matchup_available':False}]*2)):
                before=replay()
                self.assertEqual(before['games'][31]['margins']['players'],0.)
                self.assertGreater(before['games'][32]['margins']['players'],0.)
                games[35]=(*games[35][:7],999.,20.)
                after=replay()
                self.assertEqual([r['margins'] for r in before['games'][:36]],[r['margins'] for r in after['games'][:36]])
                self.assertNotEqual(before['games'][36]['margins'],after['games'][36]['margins'])

    def test_invalid_baseline_rejected(self):
        f=self.fixture()
        with self.assertRaises(ValueError):run(f.db,f.root/'schedule.csv',train_season=2023,last_season=2024,baseline_provider=lambda *a:math.nan)

if __name__=='__main__':unittest.main()
