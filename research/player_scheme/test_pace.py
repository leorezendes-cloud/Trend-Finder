import json,unittest
from . import test_engine
from .pace import summarize,estimate
from .pace_experiment import scores

class PaceTests(unittest.TestCase):
    def test_neutral_clock_pairs_exclude_stoppages_and_possession_changes(self):
        import polars as pl
        rows=[]
        for i,(clock,play,desc) in enumerate([(2500,'run','in bounds'),(2470,'run','in bounds'),(2460,'no_play','Timeout'),(2440,'pass','incomplete'),(2400,'run','out of bounds'),(2370,'run','in bounds'),(2320,'run','in bounds'),(2280,'run','in bounds')]):
            rows.append(dict(game_id='2024_01_NE_BUF',season=2024,play_id=float(i),posteam='BUF' if i==7 else 'NE',defteam='NE' if i==7 else 'BUF',play_type=play,fixed_drive=2. if i==7 else 1.,qtr=2.,game_seconds_remaining=float(clock),half_seconds_remaining=float(clock-1800),wp=.5,timeout=float(i==2),incomplete_pass=float(i==3),qb_kneel=0.,qb_spike=0.,desc=desc))
        result=summarize(pl.DataFrame(rows).lazy(),2024).to_dicts();ne=next(r for r in result if r['posteam']=='NE')
        self.assertEqual(ne['neutral_pairs'],2);self.assertEqual(ne['neutral_clock_seconds'],80)
        with self.assertRaises(ValueError):summarize(pl.DataFrame(rows+[rows[0]]).lazy(),2024)
        for r in rows:r.update(wp=.95,half_seconds_remaining=80.)
        self.assertEqual(sum(r['neutral_pairs'] for r in summarize(pl.DataFrame(rows).lazy(),2024).to_dicts()),0)
    def test_score_scaling_does_not_double_count_embedded_pace(self):
        s=scores([24.,21.],[1.,-1.],[1.,1.])
        self.assertEqual(s['pace_direct'],[24.,21.]);self.assertEqual(s['pace_plus_matchup'],[25.,20.])
        s=scores([24.,21.],[1.,-1.],[1.1,.9])
        self.assertAlmostEqual(s['pace_direct'][0],26.4)
        self.assertAlmostEqual(s['pace_plus_matchup'][0],27.5)
        self.assertAlmostEqual(s['conservative_plus_matchup'][0],26.25)
    def fixture(self):
        f=test_engine.EngineTests();f.setUp();self.addCleanup(f.doCleanups)
        for r in f.teams:
            payload=dict(drives=10,snaps=60,neutral_pairs=20,neutral_clock_seconds=600)
            f.db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)',('pace',r['game_id'],r['team'],r['opponent_team'],'','','',test_engine.CAP,json.dumps(payload)))
        return f
    def test_future_pace_cannot_change_projection(self):
        f=self.fixture();cutoff='2024-09-22T17:00:00+00:00';before=estimate(f.db,'NE','BUF',cutoff)
        self.assertIsNotNone(before)
        f.db.execute("UPDATE observations SET payload=? WHERE kind='pace' AND gid>='2024_04_NE_BUF'",(json.dumps(dict(drives=100,snaps=500,neutral_pairs=50,neutral_clock_seconds=500)),))
        self.assertEqual(before,estimate(f.db,'NE','BUF',cutoff))
        for t in before['teams']:self.assertAlmostEqual(t['ratio'],1.)
    def test_small_samples_and_missing_neutral_pairs_are_unavailable(self):
        f=self.fixture();self.assertIsNone(estimate(f.db,'NE','BUF','2024-09-02T00:00:00+00:00'))
        f.db.execute("UPDATE observations SET payload=? WHERE kind='pace'",(json.dumps(dict(drives=10,snaps=60,neutral_pairs=0,neutral_clock_seconds=0)),))
        self.assertIsNone(estimate(f.db,'NE','BUF','2024-10-25T00:00:00+00:00'))

if __name__=='__main__':unittest.main()
