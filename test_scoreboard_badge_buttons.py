"""Presentation-only release regression checks."""
import unittest
from pathlib import Path
from unittest.mock import patch
from app import app

ROOT = Path(__file__).resolve().parent

class BadgeButtonPolishTests(unittest.TestCase):
    def test_home_badges_centered_above_at_and_remain_independent(self):
        css = (ROOT / 'static/games_board.css').read_text()
        js = (ROOT / 'static/games_board.js').read_text()
        template = (ROOT / 'templates/_home_games_board.html').read_text()
        self.assertIn('left:50%;right:auto;top:42px;', css)
        self.assertIn('gap:8px;margin-top:26px', css)
        self.assertIn('class="tf-board-marks"', template)
        self.assertIn("card.parentElement.querySelector('.tf-board-marks')", js)
        self.assertIn('gameAnomalyFlag', js)
        self.assertIn('hot_matches', js)

    def test_matching_buttons_with_compact_mobile_labels(self):
        css = (ROOT / 'static/game_center.css').read_text()
        template = (ROOT / 'templates/game_center.html').read_text()
        self.assertIn('.tf-gc-actions .tf-gc-primary,', css)
        self.assertIn('.tf-gc-actions .tf-gc-secondary{', css)
        self.assertIn('font-size:.76rem;line-height:1.2', css)
        self.assertIn('Comparison &amp; Picks', template)
        self.assertIn('NFL Scores</span>', template)
        self.assertIn("url_for('fans.matchup', game_id=game.game_id)", template)
        self.assertIn("url_for('home', _anchor='home-scores')", template)

    def test_game_center_still_renders(self):
        game = {'game_id':'2026_07_CIN_BAL','away_team':'CIN',
                'home_team':'BAL','season':'2026','week':'7'}
        form = {'wins':1,'losses':0,'ties':0,'games':1, 'points_for':20,'points_against':10}
        with patch('game_center._game_context',return_value=(game,None)), \
             patch('game_center._recent_team_context',return_value={'CIN':form,'BAL':form}), \
             patch('game_center._member_pick_preview',return_value=None):
            response = app.test_client().get('/game/2026_07_CIN_BAL')
            self.assertEqual(response.status_code,200)
            self.assertIn('Comparison &amp; Picks',response.get_data(as_text=True))

if __name__ == '__main__':unittest.main()
