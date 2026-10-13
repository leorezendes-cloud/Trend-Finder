"""Upcoming previews must use historical matching rules, not model outputs."""
import unittest
from unittest.mock import patch
from app import app


class PageLayoutTests(unittest.TestCase):
    def test_upcoming_discovery_previews_lead_and_link_to_matching_trend(self):
        game = dict(matchup='BUF at LA', kickoff='Oct 12, 08:15 PM ET',
                    dog_team='BUF', dog_location='Away', is_primetime=True, dog_spread=2.5)
        with patch('app.upcoming_combination_contexts', return_value=[(None, set(), game)]):
            response = app.test_client().get('/trends')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('BUF at LA', html)
        self.assertIn('Historical underdog ATS:', html)
        self.assertLess(html.index('Coming up within 7 days'), html.index('Recent hot performance'))
        self.assertEqual(html.count('<details class="discovery-section">'), 4)
        self.assertNotIn('<details class="discovery-section" open', html)
        self.assertIn('/trend-details?', html)
        self.assertIn('prime=yes', html)
        self.assertIn('location=Away', html)

    def test_plug_keeps_baseline_and_historical_form_distinct(self):
        response = app.test_client().get('/sunday-scout')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Experimental points-only model', html)
        self.assertIn('Historical rankings and team form', html)
        self.assertIn('<details class="scout-analysis">', html)
        self.assertNotIn('<details class="scout-analysis" open', html)
        self.assertIn('not</em> a calibrated cover probability', html)


if __name__ == '__main__':
    unittest.main()
