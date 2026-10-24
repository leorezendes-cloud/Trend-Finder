"""Focused checks for the Weekly Plug editorial-only newsletter changes."""
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from newsletter_draft import _trend_copy, _weekly_featured_pick, _matchups

class WeeklyEditorialTests(unittest.TestCase):
    def test_minnesota_natural_language(self):
        t = {'title':'MIN — SU','scope':'team','kind':'su','outcome':'Win','streak':10,'wins':7,'sample':7}
        title, desc = _trend_copy(t)
        self.assertEqual(title, 'MIN — SU: 10 Straight Wins')
        self.assertIn('Minnesota Vikings have won 10 consecutive games outright', desc)
        self.assertNotIn('7/7', desc)

    def test_primetime_underdogs(self):
        t = {'title':'Primetime underdogs — ATS','scope':'situational','kind':'ats','outcome':'Cover','streak':12,'wins':7,'sample':7}
        title, desc = _trend_copy(t)
        self.assertIn('12 Straight Covers', title)
        self.assertIn('have covered the spread', desc)

    def test_recent_5_of_7_not_called_streak(self):
        t = {'title':'MIN — SU','scope':'team','kind':'su','outcome':'Win','streak':2,'wins':5,'sample':7}
        title, desc = _trend_copy(t)
        self.assertIn('5 of Last 7', title)
        self.assertIn('5 of its last 7', desc)

    def test_featured_requires_public_expert_match(self):
        p=['MIN @ GB · Sunday\nATS: MIN +3 · Total: Under 47\nhttps://t.com/game']
        e=['MIN @ GB · Sunday\nATS: MIN · Total: Under\nA strong run defense.\nhttps://t.com/game']
        block, versions = _weekly_featured_pick(p,e,['abc'],[])
        self.assertIn("Expert's take:",block)
        self.assertEqual(versions,['abc'])
        pending, versions = _weekly_featured_pick(p,[],['abc'],[])
        self.assertIn('being prepared',pending)
        self.assertEqual(versions,[])

    def test_marquee_roundup_selects_across_windows(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            fields = ['game_id','gameday','gametime','away_team','home_team',
                      'away_score','home_score','season','week']
            import csv
            fixtures = [
                ('thursday','2030-10-17','20:20','BAL','PIT'),
                ('early_a','2030-10-20','13:00','CAR','SEA'),
                ('early_rivalry','2030-10-20','13:00','MIN','GB'),
                ('late','2030-10-20','16:25','SF','LA'),
                ('sunday_night','2030-10-20','20:20','DAL','PHI'),
                ('monday','2030-10-21','20:15','KC','DEN'),
            ]
            with (root/'nfl_games.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields)
                w.writeheader()
                for gid,date,time,away,home in fixtures:
                    w.writerow(dict(game_id=gid,gameday=date,gametime=time,
                        away_team=away,home_team=home,away_score='',home_score='',
                        season=2030,week=7))
            now = datetime(2030,10,16,16,tzinfo=timezone.utc)
            result = _matchups(root,now,'https://trendfindah.com',{},[],
                              active_only=False,max_games=5,editorial=True)
            self.assertEqual(len(result),5)
            self.assertIn('MIN at GB', '\n'.join(result))
            self.assertNotIn('CAR at SEA', '\n'.join(result))
            self.assertIn('NFC North matchup', '\n'.join(result))
            self.assertTrue(all('/matchup/' in item for item in result))
            self.assertEqual(len({item.split(' · ',1)[0] for item in result}),5)
            self.assertTrue(any('MONDAY NIGHT' in x for x in result))
            self.assertNotIn('most watched', '\n'.join(result).lower())
            monthly = _matchups(root,now,'https://trendfindah.com',{},[],
                               active_only=False,max_games=8,editorial=False)
            self.assertEqual(len(monthly),6)
            self.assertTrue(all('NFC North matchup' not in x for x in monthly))

    def test_marquee_records_are_only_from_completed_past_games(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            fields=['game_id','gameday','gametime','away_team','home_team',
                    'away_score','home_score','season','week']
            import csv
            rows=[
                dict(game_id='old',gameday='2030-10-10',gametime='20:20',
                     away_team='MIN',home_team='GB',away_score='30',home_score='10',season=2030,week=6),
                dict(game_id='future_data',gameday='2030-10-22',gametime='20:20',
                     away_team='GB',home_team='MIN',away_score='50',home_score='0',season=2030,week=8),
                dict(game_id='upcoming',gameday='2030-10-20',gametime='13:00',
                     away_team='MIN',home_team='GB',away_score='',home_score='',season=2030,week=7)
            ]
            with (root/'nfl_games.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            now=datetime(2030,10,16,16,tzinfo=timezone.utc)
            result=_matchups(root,now,'https://trendfindah.com',{},[],active_only=False,editorial=True)
            self.assertEqual(len(result),1)
            self.assertIn('Minnesota Vikings (1–0)', result[0])
            self.assertIn('Green Bay Packers (0–1)', result[0])
            self.assertNotIn('1–1',result[0])

if __name__=='__main__': unittest.main()
