"""Offline protection of the merged home scoreboard and member previews."""
import unittest
from pathlib import Path
from unittest.mock import patch
from app import app

class ScoreboardMergeTests(unittest.TestCase):
    def test_home_renders_weekly_board_without_live_network(self):
        from game_center import home_board_context
        game = {'game_id':'2026_08_DAL_PHI','season':'2026','week':'8',
                'game_type':'REG','away_team':'DAL','home_team':'PHI',
                'gameday':'2026-10-26','gametime':'20:15',
                'home_score':'','away_score':'','result':''}
        with patch('game_center.home_board_context',return_value={
            'slate':('2026','REG',8),'games':[game],
            'groups':{'in':[],'pre':[game],'post':[]}}), \
             patch('hosted_memory.home_context',return_value={
                'active_highlights':[],'emerging_alert':None,
                'freshness':{'stats':None,'predictions':None,'automatic':None}}):
            response = app.test_client().get('/')
            self.assertEqual(response.status_code,200)
            html=response.get_data(as_text=True)
            self.assertIn('tf-games-board',html)
            self.assertIn('/game/2026_08_DAL_PHI/data',html)
            self.assertNotIn('View All Games',html)
            self.assertIn('tf-board-marks',html)

    def test_legacy_games_url_returns_to_home_scoreboard(self):
        response=app.test_client().get('/games')
        self.assertEqual(response.status_code,302)
        self.assertTrue(response.headers['Location'].endswith('/#home-scores'))

    def test_single_game_center_previews_do_not_require_live_data(self):
        from game_center import _recent_team_context
        game={'game_id':'2026_08_DAL_PHI','season':'2026','week':'8',
              'away_team':'DAL','home_team':'PHI','gameday':'2026-10-26','gametime':'20:15'}
        old=dict(game,game_id='2026_07_DAL_PHI',week='7',gameday='2026-10-19',
                 home_score='21',away_score='24',result='-3')
        import csv, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'nfl_games.csv'
            with file.open('w', newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(game)+['home_score','away_score','result'])
                writer.writeheader()
                writer.writerows([old,game])
            with patch('fan_views.ROOT',Path(directory)):
                d=_recent_team_context(game)
        self.assertEqual(d['DAL']['wins'],1)
        self.assertEqual(d['DAL']['points_for'],24)
        self.assertEqual(d['PHI']['losses'],1)

    def test_game_center_keeps_picks_private(self):
        from game_center import _member_pick_preview
        from flask import g
        with app.test_request_context('/game/2026_08_DAL_PHI'):
            g.member=None
            self.assertIsNone(_member_pick_preview('2026_08_DAL_PHI'))

    def test_styles_reserve_space_for_badges(self):
        js=(Path(__file__).resolve().parent/'static/games_board.js').read_text()
        css=(Path(__file__).resolve().parent/'static/games_board.css').read_text()
        self.assertIn('hot_matches',js)
        self.assertIn('gameAnomalyFlag',js)
        self.assertIn('tf-board-marks',css)

if __name__=='__main__':unittest.main()
