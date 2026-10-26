"""Focused tests for saved game-market grades and five-game disclosure."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scout4.stats import betting_result

ROOT = Path(__file__).resolve().parent

class MarketAndLastFiveTests(unittest.TestCase):
    def test_grade_saved_spread_and_total(self):
        market = betting_result({'home_score':'30','away_score':'24',
            'spread_line':'3.5','total_line':'50.5'})
        self.assertEqual(market['spread'], 3.5)
        self.assertEqual(market['home_ats'], 'W')
        self.assertEqual(market['ou'], 'O')

    def test_home_cards_show_lines_and_only_confirmed_results(self):
        template = (ROOT/'templates/_home_games_board.html').read_text()
        js = (ROOT/'static/games_board.js').read_text()
        css = (ROOT/'static/games_board.css').read_text()
        self.assertIn('tf-board-market-line', template)
        self.assertIn('tf-board-market-result', template)
        self.assertIn("live.state === 'post' && live.completed === true", js)
        self.assertIn('showMarket(card, live);', js)
        self.assertIn('tf-market-hit', css)
        self.assertIn('tf-board-marks', template)
        self.assertIn('left:50%', css)

    def test_last_five_are_only_pregame_confirmed_results(self):
        from game_center import _recent_team_context
        target = {'game_id':'2026_08_CIN_BAL','season':'2026','week':'8',
          'away_team':'CIN','home_team':'BAL','gameday':'2026-10-26','gametime':'20:15'}
        prior = [
          {'game_id':'2026_05_CIN_BAL','season':'2026','week':'5',
           'away_team':'CIN','home_team':'BAL','gameday':'2026-10-10','gametime':'13:00',
           'away_score':'35','home_score':'13','result':'-22'},
          {'game_id':'2026_06_BAL_CIN','season':'2026','week':'6',
           'away_team':'BAL','home_team':'CIN','gameday':'2026-10-18','gametime':'13:00',
           'away_score':'20','home_score':'24','result':'4'},
          {'game_id':'2026_08_CIN_BAL','season':'2026','week':'8',
           'away_team':'CIN','home_team':'BAL','gameday':'2026-10-26','gametime':'20:15',
           'away_score':'','home_score':'','result':''},
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'nfl_games.csv'
            with path.open('w', newline='') as f:
                writer = csv.DictWriter(f,fieldnames=prior[0].keys())
                writer.writeheader();writer.writerows(prior)
            with patch('fan_views.ROOT',Path(temp)):
                d = _recent_team_context(target)
        self.assertEqual(d['CIN']['wins'],2)
        self.assertEqual(d['CIN']['games'],2)
        self.assertEqual(d['CIN']['history'][0]['opponent'],'BAL')
        self.assertEqual(d['CIN']['history'][0]['venue'],'vs')
        self.assertEqual(d['CIN']['history'][0]['outcome'],'W')
        self.assertEqual(d['BAL']['history'][0]['outcome'],'L')
        self.assertEqual(d['CIN']['points_for'],29.5)
        self.assertNotIn(target['game_id'], [r.get('game_id') for r in d['CIN']['history']])

    def test_team_cards_start_closed_and_preserve_member_picks(self):
        page=(ROOT/'templates/game_center.html').read_text()
        self.assertIn('class="tf-gc-form-history"',page)
        self.assertIn('View last {{ form.history|length }} games',page)
        self.assertIn('tf-gc-my-picks',page)

if __name__=='__main__':unittest.main()
