import csv,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from week12_kickoff_repair import repair,CORRECTIONS

class RepairTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.now=datetime(2026,11,25,tzinfo=timezone.utc)
  self.rows=[dict(game_id=gid,away_team=a,home_team=h,gameday='2026-11-29',gametime=old,away_score='',home_score='') for gid,(a,h,old,new) in CORRECTIONS.items()]
  self.write()
 def write(self):
  with (self.root/'nfl_games.csv').open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=self.rows[0]);w.writeheader();w.writerows(self.rows)
 def payload(self):
  times=['2026-11-30T01:20Z','2026-11-29T18:00Z','2026-11-29T21:05Z']
  return {'events':[dict(date=t,competitions=[dict(date=t,status={'type':{'state':'pre'}},competitors=[{'homeAway':'away','team':{'abbreviation':a}},{'homeAway':'home','team':{'abbreviation':h}}])]) for (a,h,_,_),t in zip(CORRECTIONS.values(),times)]}
 def test_exact_verified_changes_are_idempotent_and_backed_up(self):
  before=[dict(r) for r in self.rows]
  out=repair(self.root,apply=True,now=self.now,fetch=self.payload)
  self.assertEqual(len(out['changed']),3)
  with (self.root/'nfl_games.csv').open() as stream: rows=list(csv.DictReader(stream))
  for old,new in zip(before,rows):
   self.assertEqual({k:v for k,v in old.items() if k!='gametime'},{k:v for k,v in new.items() if k!='gametime'})
  self.assertEqual(json.loads((self.root/'logs/week12_kickoff_repair.json').read_text())['original_rows'],before)
  self.assertEqual(repair(self.root,apply=True,now=self.now,fetch=lambda:self.fail('must not fetch'))['changed'],[])
 def test_dry_run_does_not_write_or_fetch(self):
  before=(self.root/'nfl_games.csv').read_bytes()
  self.assertEqual(repair(self.root,now=self.now)['state'],'preview')
  self.assertEqual((self.root/'nfl_games.csv').read_bytes(),before)
 def test_mismatched_source_cannot_write(self):
  before=(self.root/'nfl_games.csv').read_bytes()
  with self.assertRaises(ValueError):repair(self.root,apply=True,now=self.now,fetch=lambda:{'events':[]})
  self.assertEqual((self.root/'nfl_games.csv').read_bytes(),before)
 def test_existing_seal_is_protected(self):
  p=self.root/'data/scout4/blend/predictions/2026_12_LV_CLE.json';p.parent.mkdir(parents=True);p.write_text('sealed')
  with self.assertRaises(ValueError):repair(self.root,apply=True,now=self.now,fetch=self.payload)
  self.assertEqual(p.read_text(),'sealed')
 def test_started_or_scored_games_are_protected(self):
  with self.assertRaises(ValueError):repair(self.root,apply=True,now=datetime(2026,11,30,tzinfo=timezone.utc),fetch=self.payload)
  self.rows[0]['away_score']='7';self.write()
  with self.assertRaises(ValueError):repair(self.root,apply=True,now=self.now,fetch=self.payload)
 def test_unexpected_original_time_is_protected(self):
  self.rows[0]['gametime']='14:00';self.write()
  with self.assertRaises(ValueError):repair(self.root,apply=True,now=self.now,fetch=self.payload)
