import csv,tempfile,unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from emerging_alerts import home_dog_alert

class EmergingAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.rows=[dict(game_id='past'+str(i),season='2026',game_type='REG',gameday=f'2026-10-0{i+1}',gametime='20:15',away_team='SEA',home_team='DEN',away_score='20',home_score='24',spread_line='-2.5',total_line='44',location='Home') for i in range(5)]
        self.upcoming=dict(self.rows[0],game_id='tonight',gameday='2026-10-15',away_score='',home_score='')
        self.now=datetime(2026,10,15,19,38,tzinfo=ZoneInfo('America/New_York'))
        self.write()
    def write(self):
        with (self.root/'nfl_games.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=self.rows[0].keys());writer.writeheader();writer.writerows(self.rows)
    def alert(self,game=None,now=None):
        with patch('emerging_alerts.upcoming_rows',return_value=[self.upcoming if game is None else game]):return home_dog_alert(self.root,now or self.now)
    def test_record_and_matching_tonight_game(self):
        alert=self.alert();self.assertEqual(alert['record']['wins'],5);self.assertEqual(alert['record']['losses'],0)
        self.assertTrue(alert['tonight']);self.assertEqual(alert['game']['game_id'],'tonight');self.assertEqual(alert['spread'],2.5)
    def test_no_alert_for_wrong_context_or_started_game(self):
        for change in ({'spread_line':'2.5'},{'spread_line':'nan'},{'spread_line':'-inf'},{'location':'Neutral'},{'gametime':'13:00'},{'game_type':'SB'},{'home_score':'0'}):
            self.assertIsNone(self.alert(dict(self.upcoming,**change)))
        self.assertIsNone(self.alert(now=self.now.replace(hour=20,minute=15)))
    def test_record_updates_and_future_finals_do_not_count(self):
        self.rows.append(dict(self.rows[0],game_id='future',gameday='2026-10-20',home_score='0'));self.write()
        self.assertEqual(self.alert()['record']['games'],5)
        self.rows[0]['home_score']='10';self.write();self.assertIsNone(self.alert())

if __name__=='__main__':unittest.main()
