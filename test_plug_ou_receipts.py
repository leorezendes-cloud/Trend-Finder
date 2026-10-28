"""No-network issuance, immutability, cutoff, and grading tests for Plug O/U."""
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from plug_ou_receipts import issue_pending,read,grade

class PlugOuReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.folder=self.root/'data/scout4/blend/predictions'
        self.folder.mkdir(parents=True)
        self.now=datetime(2026,10,28,18,tzinfo=timezone.utc)
        self.game_id='2026_08_NE_CHI'
        (self.root/'nfl_games.csv').write_text('synthetic training snapshot')
        self.record=self.make_record()

    def make_record(self,line=49.,side='Under'):
        ko=self.now+timedelta(days=1)
        cutoff=self.now-timedelta(minutes=4)
        quote={'market':'Total','line':line,'captured_at_utc':(cutoff-timedelta(minutes=1)).isoformat(),
               'kickoff_utc':ko.isoformat()}
        source={'game_id':self.game_id,'season':2026,'week':8,
                'away_team':'NE','home_team':'CHI','status':'SEALED_PREKICKOFF_RESEARCH',
                'decision_cutoff_utc':cutoff.isoformat(),
                'sealed_at_utc':(self.now-timedelta(minutes=3)).isoformat(),
                'kickoff_utc':ko.isoformat(),
                'quote':{**quote,'market':'Spread','line':3.},
                'totals':{'quote':quote,'prediction':{'lean':side}}}
        (self.folder/(self.game_id+'.json')).write_text(json.dumps(source))
        return source

    def test_issues_independent_over_and_grades_it(self):
        status=issue_pending(self.root,now=self.now,projection_fn=lambda *a,**k:{self.game_id:47.})
        self.assertEqual(status['issued'],1)
        receipt=read(self.root,self.game_id)
        self.assertEqual(receipt['original_scout_side'],'Under')
        self.assertEqual(receipt['side'],'Over')
        self.assertEqual(receipt['market_total'],49.)
        self.assertEqual(grade(receipt,27,30),'Win')
        self.assertEqual(grade(receipt,12,13),'Loss')
        self.assertEqual(grade(receipt,24,25),'Push')
        self.assertEqual(grade(receipt,None,None),'Pending')
        original=(self.folder/(self.game_id+'.json')).read_bytes()
        self.assertEqual(issue_pending(self.root,now=self.now+timedelta(minutes=1),
                                      projection_fn=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Model reran')))['issued'],0)
        self.assertEqual((self.folder/(self.game_id+'.json')).read_bytes(),original)

    def test_below_48_retains_original(self):
        self.make_record(line=45.,side='Under')
        issue_pending(self.root,now=self.now,projection_fn=lambda *a,**k:{self.game_id:50.})
        receipt=read(self.root,self.game_id)
        self.assertEqual(receipt['side'],'Under')
        self.assertEqual(receipt['decision_source'],'original_plug')

    def test_postkickoff_cannot_backdate(self):
        result=issue_pending(self.root,now=self.now+timedelta(days=2),
                             projection_fn=lambda *a,**k:{self.game_id:47.})
        self.assertEqual(result['issued'],0)
        self.assertIsNone(read(self.root,self.game_id))

    def test_missing_model_never_invents_pick(self):
        result=issue_pending(self.root,now=self.now,projection_fn=lambda *a,**k:{})
        self.assertEqual(result['missing_model'],1)
        self.assertIsNone(read(self.root,self.game_id))

    def test_tamper_rejected(self):
        issue_pending(self.root,now=self.now,projection_fn=lambda *a,**k:{self.game_id:47.})
        original=self.folder/(self.game_id+'.json')
        original.write_bytes(original.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'source mismatch'):
            read(self.root,self.game_id)

if __name__=='__main__':
    unittest.main()
