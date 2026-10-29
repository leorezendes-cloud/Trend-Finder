"""Regression: newsletter reads published Scout picks even when card masks them."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from newsletter_draft import _plug_content

class FakeArchive:
    def records(self):
        return [self.record]
    def featured(self, season, week):
        return []

class NewsletterSnapshotTest(unittest.TestCase):
    def test_masked_card_does_not_hide_published_scout_pick(self):
        now=datetime(2026,10,29,tzinfo=timezone.utc)
        game={"game_id":"2026_08_BAL_PIT","season":2026,"week":8,
              "away_team":"BAL","home_team":"PIT",
              "kickoff_utc":(now+timedelta(days=2)).isoformat()}
        archive=FakeArchive()
        archive.record={"version":"published-v1","kind":"production_import",
                        "scout":{"game":game,"spread":{"side":"BAL"},
                                 "total":{"side":"Under"},"quotes":{}}}
        masked={"upcoming":True,"version":"published-v1",
                "saved_picks":{"spread":{"side":None},"total":{"side":None}}}
        with patch("expert_beta.store",return_value=archive),patch(
            "plug_dashboard.combined_cards",return_value=([masked],[])):
            picks,experts,versions=_plug_content(now,"https://trendfindah.com",[],max_picks=None)
        self.assertEqual(len(picks),1)
        self.assertIn("ATS: BAL",picks[0])
        self.assertIn("Total: Under",picks[0])
        self.assertEqual(experts,[])
        self.assertEqual(versions,["published-v1"])

if __name__=="__main__":
    unittest.main()
