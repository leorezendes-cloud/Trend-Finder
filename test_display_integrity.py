"""Regression checks for absent data, corrected identities, and saved totals."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from name_aliases import corrected_row
from pregame_lines import effective_rows
from app import app
import trend_finder_2 as finder

class DisplayIntegrityTests(unittest.TestCase):
    def test_empty_analysis_renders_unavailable_rates(self):
        with patch('app.run_analysis', return_value=finder.Check_Games([])):
            response = app.test_client().post('/trend-finder', data={'action':'analyze'})
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for label in ('Straight Up Win Rate', 'Dog Cover Rate', 'ATS Edge'):
            fragment = html.split(label, 1)[1].split('</div>', 1)[0]
            self.assertIn('N/A', fragment)
            self.assertNotIn('0.00%', fragment)

    def test_aliases_preserve_identity_and_source(self):
        original = {'away_qb_name':'Justin Herbery', 'away_qb_id':'00-0036355', 'referee':'Bill Vinocich'}
        corrected = corrected_row(original)
        self.assertEqual(corrected['away_qb_name'], 'Justin Herbert')
        self.assertEqual(corrected['referee'], 'Bill Vinovich')
        self.assertEqual(corrected['away_qb_id'], original['away_qb_id'])
        self.assertEqual(original['away_qb_name'], 'Justin Herbery')
        self.assertTrue(finder.matches_csv_filters(original, {'qb_name':'Justin Herbert'}))

    def test_total_ignores_late_and_invalid_quotes(self):
        game = dict(game_id='example', gameday='2026-10-01', gametime='20:00', away_team='A', home_team='B', spread_line='3', total_line='')
        quote = dict(game_id='example', sportsbook='DraftKings', market='Total', side_a='Over', side_b='Under', line_a='45.5', line_b='45.5', source_url='https://example.com', kickoff_utc='2026-10-02T00:00:00+00:00', captured_at_utc='2026-10-01T23:00:00+00:00')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root/'public_money_snapshots.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=quote)
                writer.writeheader()
                writer.writerows([quote, dict(quote, line_a='99', line_b='99', captured_at_utc='2026-10-02T00:01:00+00:00'), dict(quote, line_b='44', captured_at_utc='2026-10-01T23:30:00+00:00')])
            result = effective_rows([game], root/'nfl_games.csv')[0]
        self.assertEqual(result['total_line'], '45.5')
        self.assertEqual(result['total_source'], 'DraftKings pregame capture')
        self.assertEqual(game['total_line'], '')

if __name__ == '__main__':
    unittest.main()
