"""Focused checks for dynamic decision foundation; never touch production receipts."""
import unittest
from plug_dynamic_pregame import decide

BASE=dict(away_team="BAL",home_team="PIT",model_away_spread=-8.0,
          market_away_spread=-8.5,market_total=49.0,v14_total=49.5,
          original_total_side="Over",quote_observed_utc="2026-10-28T14:00:00+00:00",
          evaluation_utc="2026-10-28T14:01:00+00:00",
          kickoff_utc="2026-10-29T00:00:00+00:00")

class PregameDecisions(unittest.TestCase):
    def test_line_move_changes_ats_membership(self):
        self.assertEqual(decide(**BASE)["ats_side"],"PIT")
        moved=decide(**{**BASE,"market_away_spread":-6.5})
        self.assertFalse(moved["ats_selected"])

    def test_line_move_can_reverse_ats(self):
        moved=decide(**{**BASE,"market_away_spread":-7.5})
        self.assertEqual(moved["ats_side"],"BAL")

    def test_total_recalculates_independently(self):
        first=decide(**BASE)
        self.assertEqual(first["ou_side"],"Over")
        moved=decide(**{**BASE,"market_total":48.0})
        self.assertEqual(moved["ou_side"],"Under")

    def test_exact_agreement_has_no_ats_selection(self):
        self.assertFalse(decide(**{**BASE,"market_away_spread":-8.0})["ats_selected"])

    def test_refuse_after_kickoff_or_future_quote(self):
        for change in ({"evaluation_utc":"2026-10-29T00:00:00+00:00"},
                       {"quote_observed_utc":"2026-10-28T14:02:00+00:00"},
                       {"quote_observed_utc":"2026-10-29T00:00:00+00:00"}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                decide(**{**BASE,**change})

if __name__=="__main__":
    unittest.main()
