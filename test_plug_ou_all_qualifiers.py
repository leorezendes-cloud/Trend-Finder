"""Offline acceptance tests for separate prospective Plug O/U shortlist issuance."""
import csv
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plug_ou_receipts import issue_pending, read as read_v1, grade
from plug_ou_all_qualifiers import shortlist
from plug_ou_weekly_v3 import issue_weekly, read_effective, read_week

FIELDS=['game_id','season','week','game_type','gameday','gametime',
        'away_team','home_team','away_score','home_score']
GAPS=(4.0,0.0,0.5,-1.5,3.0,-2.5,1.0,0.75)

class PlugOuWeeklyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.now=datetime(2026,10,28,18,0,tzinfo=timezone.utc)
        self.kick=datetime(2026,10,30,0,0,tzinfo=timezone.utc)
        self.folder=self.root/'data/scout4/blend/predictions'
        self.folder.mkdir(parents=True)
        self.rows=[]
        self.projections={}
        for i,gap in enumerate(GAPS):
            game_id=f'2026_08_T{2*i:02d}_T{2*i+1:02d}'
            line=47.5 if i==0 else 48.0+0.5*i
            self.projections[game_id]=line+gap
            self.rows.append(dict(game_id=game_id,season='2026',week='8',
                game_type='REG',gameday='2026-10-29',gametime='20:00',
                away_team=f'T{2*i:02d}',home_team=f'T{2*i+1:02d}',
                away_score='',home_score=''))
        with (self.root/'nfl_games.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS)
            writer.writeheader();writer.writerows(self.rows)

    def _forecast(self,i):
        row=self.rows[i]
        gid=row['game_id']
        cutoff=self.now-timedelta(minutes=4)
        quote_time=(cutoff-timedelta(minutes=1)).isoformat()
        spread={'market':'Spread','line':3.5,'kickoff_utc':self.kick.isoformat(),
                'captured_at_utc':quote_time}
        total={**spread,'market':'Total',
               'line':47.5 if i==0 else 48.0+0.5*i}
        record={**{k:row[k] for k in ('game_id','away_team','home_team')},
                'season':2026,'week':8,'status':'SEALED_PREKICKOFF_RESEARCH',
                'kickoff_utc':self.kick.isoformat(),
                'decision_cutoff_utc':cutoff.isoformat(),
                'sealed_at_utc':(cutoff+timedelta(minutes=1)).isoformat(),
                'quote':spread,'totals':{'quote':total,'prediction':{'lean':'Under'}}}
        (self.folder/(gid+'.json')).write_text(json.dumps(record))

    def _issue_v1(self):
        return issue_pending(self.root,now=self.now,
                             projection_fn=lambda *a,**k:self.projections)

    def test_all_qualifiers_and_restarts_are_immutable(self):
        for i in range(8):self._forecast(i)
        issued=self._issue_v1()
        self.assertEqual(issued['issued'],8)
        originals={r['game_id']:read_v1(self.root,r['game_id']) for r in self.rows}
        weekly=issue_weekly(self.root,now=self.now+timedelta(minutes=1))
        self.assertEqual(weekly['published'],1)
        self.assertEqual(weekly['selected'],6)
        saved=read_week(self.root,2026,8)
        self.assertEqual(saved['candidate_count'],6)
        self.assertEqual(saved['total_games'],8)
        self.assertEqual(set(saved['selected_ids']),{
            self.rows[i]['game_id'] for i in range(1,8) if i!=1})
        self.assertTrue(all(read_effective(self.root,gid)['selected']
                            ==(gid in saved['selected_ids']) for gid in originals))
        for row in self.rows:
            gid=row['game_id']
            self.assertEqual(read_v1(self.root,gid),originals[gid])
            effective=read_effective(self.root,gid)
            self.assertIn(effective['selection_status'],('selected','stay_away'))
            self.assertEqual(effective['shortlist_policy'],saved['policy_version'])
        before=(self.root/'data/scout4/blend/plug_ou/weekly_v3/2026_08.json').read_bytes()
        replay=issue_weekly(self.root,now=self.kick+timedelta(hours=1))
        self.assertEqual(replay['preserved'],1)
        self.assertEqual(replay['published'],0)
        self.assertEqual((self.root/'data/scout4/blend/plug_ou/weekly_v3/2026_08.json').read_bytes(),before)

    def test_partial_slate_and_missing_projection_never_issue_shortlist(self):
        for i in range(7):self._forecast(i)
        self.assertEqual(self._issue_v1()['issued'],7)
        result=issue_weekly(self.root,now=self.now)
        self.assertEqual(result['published'],0)
        self.assertEqual(result['pending_slate'],1)
        self.assertIsNone(read_week(self.root,2026,8))
        self._forecast(7)
        self.assertEqual(self._issue_v1()['issued'],1)
        self.assertEqual(issue_weekly(self.root,now=self.now)['published'],1)

    def test_no_hindsight_after_first_game_kickoff(self):
        for i in range(8):self._forecast(i)
        self._issue_v1()
        result=issue_weekly(self.root,now=self.kick+timedelta(seconds=1))
        self.assertEqual(result['started'],1)
        self.assertIsNone(read_week(self.root,2026,8))
        # V1 remains labeled as its original all-game publication.
        old=read_effective(self.root,self.rows[2]['game_id'])
        self.assertFalse(old['selected'])
        self.assertEqual(old['selection_status'],'awaiting_weekly_selection')

    def test_corrupt_weekly_selection_fails_closed_without_rewriting(self):
        for i in range(8):self._forecast(i)
        self._issue_v1();issue_weekly(self.root,now=self.now)
        path=self.root/'data/scout4/blend/plug_ou/weekly_v3/2026_08.json'
        corrupted=json.loads(path.read_text())
        corrupted['selected_ids']=[]
        path.write_text(json.dumps(corrupted))
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):
            read_effective(self.root,self.rows[4]['game_id'])
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):
            issue_weekly(self.root,now=self.now+timedelta(minutes=1))

    def test_no_quota_one_or_multiple_qualifiers(self):
        rows=[dict(game_id=str(i),season=2026,week=8,gap=gap,eligible=eligible)
              for i,(gap,eligible) in enumerate(((0.,True),(0.2,True),(-0.3,True),(2.,False)))]
        self.assertEqual(shortlist(rows),{'1','2'})
        self.assertEqual(shortlist(rows[:1]),set())

    def test_selection_rule_deterministic_and_rejects_duplicate(self):
        rows=[dict(game_id=str(i),season=2026,week=8,gap=g)
              for i,g in enumerate((0,2.,-2.,1.,0.1,3.,-0.5))]
        self.assertEqual(shortlist(rows),{'1','2','3','4','5','6'})
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            shortlist(rows+[rows[0]])
        with self.assertRaisesRegex(ValueError,'Nonfinite'):
            shortlist([dict(game_id='n',season=2026,week=8,gap=float('nan'))])

if __name__=='__main__':
    unittest.main()
