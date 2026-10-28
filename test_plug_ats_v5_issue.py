"""Issue of v5 ATS weekly receipts must never happen post-kickoff or on partial slates."""
import csv
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import plug_ats_v5_weekly as v5

class ATSv5Publication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.folder=self.root/'data/scout4/blend/predictions'
        self.folder.mkdir(parents=True)
        self.now=datetime.now(timezone.utc)
        self.kick=(self.now+timedelta(days=2)).astimezone(ZoneInfo('America/New_York')).replace(second=0,microsecond=0)
        self.games=[]
        for i in range(4):
            a,h=f'A{i}',f'H{i}'
            self.games.append(dict(game_id=f'{self.kick.year}_08_{a}_{h}',
                 season=str(self.kick.year),week='8',game_type='REG',
                 gameday=self.kick.strftime('%Y-%m-%d'),gametime=self.kick.strftime('%H:%M'),
                 away_team=a,home_team=h))
        self.path=self.root/'nfl_games.csv'
        self._save_schedule()

    def _save_schedule(self):
        with self.path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=self.games[0])
            w.writeheader();w.writerows(self.games)

    def _save_forecasts(self,n=4):
        for i,g in enumerate(self.games[:n]):
            record=dict(game_id=g['game_id'],season=int(g['season']),week=8,
               away_team=g['away_team'],home_team=g['home_team'],
               kickoff_utc=self.kick.astimezone(timezone.utc).isoformat(),
               version='plug-points-only-4',sealed_at_utc=(self.now-timedelta(minutes=15)).isoformat(),
               quote=dict(market='Spread',line=[8.,-8.5,7.,-9.][i],
                  captured_at_utc=(self.now-timedelta(minutes=20)).isoformat()))
            (self.folder/(g['game_id']+'.json')).write_text(json.dumps(record))

    def _run(self):
        forecast=[8.5,-9.,7.5,-8.]
        values={g['game_id']:forecast[i] for i,g in enumerate(self.games)}
        with patch.object(v5,'storage_root',return_value=self.root/'ats_store'),\
             patch.object(v5,'pregame_record',return_value=None),\
             patch.object(v5,'projections',return_value=values):
            return v5.issue_pending(self.root,now=self.now),v5.read_week(self.kick.year,8)

    def test_complete_slate_issues_all_qualifiers_only_and_preserves(self):
        self._save_forecasts()
        report,receipt=self._run()
        self.assertEqual(report['published'],1)
        self.assertEqual(report['selected'],2)
        self.assertEqual(len(receipt['games']),4)
        self.assertEqual(receipt['selected_ids'],sorted([self.games[0]['game_id'],self.games[1]['game_id']]))
        self.assertEqual([g['side'] for g in receipt['games']],['H0','A1',None,None])
        path=self.root/'ats_store'/f'{self.kick.year}_08_{v5.POLICY}.json'
        saved=path.read_bytes()
        after,_=self._run()
        self.assertEqual(after['preserved'],1)
        self.assertEqual(saved,path.read_bytes())

    def test_partial_slate_does_not_publish(self):
        self._save_forecasts(3)
        report,receipt=self._run()
        self.assertEqual(report['published'],0)
        self.assertEqual(report['pending'],1)
        self.assertIsNone(receipt)

    def test_prior_kickoff_blocks_entire_week(self):
        self._save_forecasts()
        earlier=self.kick-timedelta(days=3)
        self.games[0]['gameday']=earlier.strftime('%Y-%m-%d')
        self.games[0]['gametime']=earlier.strftime('%H:%M')
        self._save_schedule()
        report,receipt=self._run()
        self.assertEqual(report['published'],0)
        self.assertEqual(report['started'],1)
        self.assertIsNone(receipt)

    def test_missing_kickoff_blocks_entire_week(self):
        self._save_forecasts()
        self.games[0]['gametime']=''
        self._save_schedule()
        report,receipt=self._run()
        self.assertEqual(report['published'],0)
        self.assertEqual(report['started'],1)
        self.assertIsNone(receipt)

if __name__=='__main__':
    unittest.main()
