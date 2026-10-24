"""Upcoming previews must use historical matching rules, not model outputs."""
import unittest
from unittest.mock import patch
from app import app


class PageLayoutTests(unittest.TestCase):
    def test_discovery_no_longer_renders_removed_upcoming_previews(self):
        # The duplicate upcoming-finder panel was deliberately removed.
        # This route must not invoke the old unused discovery preview builder.
        with patch('app.upcoming_combination_contexts', side_effect=AssertionError('obsolete preview called')):
            response = app.test_client().get('/trends')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Recent hot performance', html)
        self.assertIn('Active ATS streaks', html)
        self.assertIn('Explore Historical Matchup Trends', html)
        self.assertNotIn('Coming up within 7 days', html)
        self.assertNotIn('Upcoming Matchup Finder', html)
        self.assertNotIn('Coming up within 7 days', html)

    def test_expert_beta_redirects_legacy_sunday_scout_to_the_plug(self):
        # Scout reporting was folded into The Plug; old URLs still redirect.
        with patch.dict(app.config, {'EXPERT_BETA_ENABLED': True}):
            response = app.test_client().get('/sunday-scout')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/the-plug')


if __name__ == '__main__':
    unittest.main()
