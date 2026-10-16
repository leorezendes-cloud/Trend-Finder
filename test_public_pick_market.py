import csv,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from public_money import FIELDS
from public_pick_market import matchup_public_market

class PublicPickMarketTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.pick=dict(game_id='game',away='SEA',home='DEN',kickoff_at='2026-10-18T20:15:00+00:00',away_spread=3)
  self.now=datetime(2026,10,16,12,tzinfo=timezone.utc)
  self.row=dict(zip(FIELDS,['game','2026-10-18T20:15:00+00:00','2026-10-16T10:00:00+00:00','SEA','DEN','DraftKings','https://example.com/splits','Spread','SEA','DEN','-2.5','2.5','-110','-110','68','32','62','38']))
 def write(self,rows):
  with (self.root/'public_money_snapshots.csv').open('w',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
 def test_all_three_markets_and_separate_bets_money(self):
  ml=dict(self.row,market='Moneyline',line_a='',line_b='',odds_a='-145',odds_b='125')
  total=dict(self.row,market='Total',side_a='Over',side_b='Under',line_a='43.5',line_b='43.5')
  self.write([self.row,ml,total]);view=matchup_public_market(self.root,self.pick,self.now)
  self.assertEqual([len(m['sides']) for m in view['markets']],[2,2,2])
  side=view['markets'][1]['sides'][0];self.assertEqual(side['bets'],62);self.assertEqual(side['money'],68);self.assertEqual(side['line'],-2.5)
  self.assertEqual(self.pick['away_spread'],3)
 def test_rejects_future_wrong_identity_missing_and_postkickoff_observations(self):
  bad=[dict(self.row,captured_at_utc='2026-10-17T10:00:00+00:00'),dict(self.row,home_team='KC'),dict(self.row,bets_a=''),dict(self.row,kickoff_utc='2026-10-18T21:15:00+00:00'),dict(self.row,captured_at_utc=self.pick['kickoff_at']),dict(self.row,source_url='javascript:bad')]
  self.write(bad);self.assertTrue(all(not m['sides'] for m in matchup_public_market(self.root,self.pick,self.now)['markets']))
 def test_latest_per_market_and_explicit_missing(self):
  self.write([dict(self.row,captured_at_utc='2026-10-14T10:00:00+00:00'),self.row])
  view=matchup_public_market(self.root,self.pick,self.now)
  self.assertEqual(view['markets'][1]['captured'],self.row['captured_at_utc']);self.assertFalse(view['markets'][1]['stale'])
  self.assertEqual(view['markets'][0]['sides'],[])

if __name__=='__main__':unittest.main()
