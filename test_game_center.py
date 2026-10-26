"""Offline smoke tests for the small NFL game-center parser and navigation."""
import unittest
from pathlib import Path
from unittest.mock import patch

from game_center import parse_summary, summary, _DETAIL_CACHE


class GameCenterTests(unittest.TestCase):
    def test_summary_parser_keeps_scoring_and_team_metrics(self):
        data = {
            'scoringPlays': [
                {'team': {'abbreviation':'HOU'}, 'period':{'number':2},
                 'clock':{'displayValue':'4:16'}, 'text':'Made 25-yard field goal',
                 'awayScore':10, 'homeScore':7},
                {'team': {'abbreviation':'BAD'}, 'period':{'number':2}, 'text':'Invalid'},
            ],
            'boxscore': {'teams': [
                {'team':{'abbreviation':'HOU'},
                 'statistics':[{'name':'totalYards','displayValue':'312'}]},
                {'team':{'abbreviation':'JAX'},
                 'statistics':[{'name':'totalYards','displayValue':'279'}]},
            ]},
        }
        x = parse_summary(data, 'HOU', 'JAX')
        self.assertEqual(len(x['plays']), 1)
        self.assertEqual(x['plays'][0]['time'], '4:16')
        self.assertEqual(x['metrics'][0], {'label':'Total yards','away':'312','home':'279'})

    def test_invalid_provider_id_does_not_hit_network(self):
        with patch('game_center.urlopen') as fetch:
            self.assertIsNone(summary('../../etc', 'HOU', 'JAX', 'in'))
            fetch.assert_not_called()

    def test_no_self_link_on_comparison_and_preserves_other_links(self):
        content = (Path(__file__).resolve().parent / 'templates/_pick_cards.html').read_text()
        self.assertIn("request.endpoint == 'fans.matchup'", content)
        self.assertIn("url_for('fans.matchup'", content)

    def test_game_center_links_to_comparison(self):
        html = (Path(__file__).resolve().parent / 'templates/game_center.html').read_text()
        self.assertIn("url_for('fans.matchup', game_id=game.game_id)", html)
        self.assertIn('tf-gc-plays', html)

    def test_game_center_http_routes(self):
        from app import app
        game = {'game_id':'2026_07_HOU_JAX', 'away_team':'HOU',
                'home_team':'JAX','season':'2026','week':'7'}
        with patch('game_center._game_context',return_value=(game,None)):
            page = app.test_client().get('/game/2026_07_HOU_JAX')
            self.assertEqual(page.status_code,200)
            self.assertIn('Team Comparison',page.get_data(as_text=True))
            data = app.test_client().get('/game/2026_07_HOU_JAX/data')
            self.assertEqual(data.status_code,200)
            self.assertEqual(data.json['state'],'pre')


if __name__ == '__main__':
    unittest.main()
