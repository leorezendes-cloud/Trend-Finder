"""Focused all-games board tests. Never hit ESPN or modify production."""
import unittest
from unittest.mock import patch

from app import app

class WeeklyGameBoardTests(unittest.TestCase):
    def test_renders_entire_saved_week_without_provider_network(self):
        season_rows = [
            {'game_id':'2026_08_PHI_DAL','season':'2026','week':'8',
             'game_type':'REG','away_team':'PHI','home_team':'DAL',
             'gameday':'2026-10-26','gametime':'20:15',
             'away_score':'','home_score':'','result':''},
            {'game_id':'2026_08_BUF_NE','season':'2026','week':'8',
             'game_type':'REG','away_team':'BUF','home_team':'NE',
             'gameday':'2026-10-25','gametime':'13:00',
             'away_score':'30','home_score':'23','result':'-7'},
        ]
        with patch('scout4.stats.read_csv',return_value=season_rows), \
                patch('site_week.active_slate',return_value=((2026,'REG',8), season_rows)), \
                patch('game_center.urlopen') as external:
            page = app.test_client().get('/games')
            self.assertEqual(page.status_code,200)
            body=page.get_data(as_text=True)
            self.assertIn('/game/2026_08_PHI_DAL/data',body)
            self.assertIn('/game/2026_08_BUF_NE/data',body)
            self.assertIn('NFL Scores',body)
            self.assertIn('Final scores',body)
            external.assert_not_called()

    def test_home_scoreboard_links_to_full_slate(self):
        from pathlib import Path
        page = (Path(__file__).resolve().parent / 'templates/home.html').read_text()
        self.assertIn('View All Games',page)
        self.assertIn("url_for('fans.all_games_board')",page)

    def test_preserves_single_game_center(self):
        rules=[r.rule for r in app.url_map.iter_rules()]
        self.assertIn('/games',rules)
        self.assertIn('/game/<game_id>',rules)
        self.assertIn('/matchup/<game_id>',rules)

if __name__=='__main__':
    unittest.main()
