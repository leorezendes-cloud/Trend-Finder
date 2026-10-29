"""Newsletter must use published archive identity, not versionless dashboard replacements."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from newsletter_draft import _plug_content

class Archive:
    def __init__(self, record):
        self.record = record
    def records(self):
        return [self.record]
    def featured(self, season, week):
        return []

class NewsletterIdentityTest(unittest.TestCase):
    def test_published_snapshot_survives_versionless_dashboard_card(self):
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        game = dict(game_id="2026_09_BAL_PIT", season=2026, week=9,
                    away_team="BAL", home_team="PIT",
                    kickoff_utc=(now + timedelta(days=2)).isoformat())
        record = dict(version="sealed-v1", kind="production_import",
                      scout=dict(game=game, spread=dict(side="BAL"),
                                 total=dict(side="Over"), quotes={}))
        with patch("expert_beta.store", return_value=Archive(record)), patch(
            "plug_dashboard.combined_cards", side_effect=AssertionError(
                "Newsletter must not depend on dashboard cards"
            )):
            picks, expert, versions = _plug_content(
                now, "https://trendfindah.com", [], max_picks=None
            )
        self.assertEqual(len(picks), 1)
        self.assertIn("ATS: BAL", picks[0])
        self.assertIn("Total: Over", picks[0])
        self.assertEqual(expert, [])
        self.assertEqual(versions, ["sealed-v1"])

if __name__ == "__main__":
    unittest.main()
