import copy,unittest
from . import test_engine
from .features import build
from .evaluate import Ridge
from .full_ats import CachedRidge,inputs,run

class FullATSTests(unittest.TestCase):
    def test_cached_ridge_matches_original_and_invalidates_after_update(self):
        old=Ridge(3);new=CachedRidge(3)
        for i in range(45):
            x=[1.,i/10,(i%3)/3];old.update(x,i/4);new.update(x,i/4)
        for x in ([1,2,3],[3,2,1]):self.assertAlmostEqual(old.predict(x),new.predict(x),places=12)
        old.update([1,1,1],99);new.update([1,1,1],99)
        self.assertAlmostEqual(old.predict([1,2,3]),new.predict([1,2,3]),places=12)
    def fixture(self):
        f=test_engine.EngineTests();f.setUp();self.addCleanup(f.doCleanups);return f
    def test_missing_scheme_is_gated_and_vector_sizes_fixed(self):
        f=self.fixture();obj=build(f.db,'NE','BUF','2024-10-25T00:00:00+00:00')
        xs,cov=inputs(obj)
        self.assertEqual({k:len(v) for k,v in xs.items()},{'limited':8,'players':28,'pbp':40,'full_available':46})
        self.assertEqual(xs['full_available'][-6:],[0.]*6)
        self.assertFalse(any(t['pressure_matchup_available'] for t in cov))
    def test_charted_interactions_use_verified_player_and_opponent_samples(self):
        f=self.fixture();obj=build(f.db,'NE','BUF','2024-10-25T00:00:00+00:00');p=obj['teams'][0]
        qb=copy.deepcopy(p['players'][0]);qb['position']='QB';qb['player_id']='00-0000999'
        for key,value in [('verified_pressure_response',2),('man_response',3),('zone_response',4)]:qb[key]={'value':value,'exposure':40}
        p['players'].append(qb)
        p['opponent_five_plus_rusher_rate']={'value':.4,'exposure':100};p['opponent_man_rate']={'value':.6,'exposure':100}
        xs,cov=inputs(obj)
        for actual,expected in zip(xs['full_available'][-6:-3],[.8,1.8,1.6]):self.assertAlmostEqual(actual,expected)
        self.assertTrue(cov[0]['pressure_matchup_available'])
        p['opponent_man_rate']['exposure']=0
        self.assertEqual(inputs(obj)[0]['full_available'][-5:-3],[0.,0.])
    def test_future_mutations_cannot_change_full_feature_vector(self):
        f=self.fixture();cutoff='2024-09-22T17:00:00+00:00';before=inputs(build(f.db,'NE','BUF',cutoff))
        f.db.execute("UPDATE observations SET payload='{}' WHERE gid>='2024_04_NE_BUF'")
        self.assertEqual(before,inputs(build(f.db,'NE','BUF',cutoff)))
    def test_kind_filter_keeps_cutoff_and_league_rows(self):
        from .store import history
        f=self.fixture();cutoff='2024-09-22T17:00:00+00:00'
        all_rows=list(history(f.db,cutoff))
        only=list(history(f.db,cutoff,kinds=('player',)))
        self.assertEqual(only,[r for r in all_rows if r['kind']=='player'])
        self.assertEqual(set(r['team'] for r in only),{'NE','BUF'})

    def test_full_replay_uses_one_shared_line_and_same_eligible_cohort(self):
        f=self.fixture();f.load('schedule',[dict(r,spread_line=3) for r in f.schedule])
        result=run(f.db,f.root/'schedule.csv',train_season=2023,last_season=2024)
        self.assertTrue(result['games'])
        self.assertEqual(result['seasons']['2024']['fully_charted_games'],0)
        self.assertEqual(set(result['games'][0]['margins']),{'baseline','limited','players','pbp','full_available'})

if __name__=='__main__':unittest.main()
