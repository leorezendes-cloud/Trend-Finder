"""End-to-end isolated market -> revision -> card -> kickoff grade regression.

Uses mocked validated market snapshots and a temporary research directory.
Official immutable receipts and production routes are never modified.
"""
import tempfile
import unittest
from unittest.mock import patch

from plug_dynamic_research import observe
from plug_dynamic_cards import card_state
from plug_dynamic_grading import closing_grade

GID="2026_08_BAL_PIT"
KICK="2026-10-29T00:00:00+00:00"
def market(spread, total, observed):
    return {"markets":[
        {"key":"Spread","captured":observed,"stale":False,
         "sides":[{"name":"BAL","line":spread},{"name":"PIT","line":-spread}]},
        {"key":"Total","captured":observed,"stale":False,
         "sides":[{"name":"Over","line":total},{"name":"Under","line":total}]}]}
def call(root,now):
    return observe(root,game_id=GID,away_team="BAL",home_team="PIT",
        kickoff_utc=KICK,model_away_spread=-8.0,v14_total=49.5,
        original_total_side="Over",evaluation_utc=now)

class EndToEndTest(unittest.TestCase):
    def test_line_moves_out_of_ats_range_and_final_grades_only_ou(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("plug_dynamic_market.matchup_public_market",
                       return_value=market(-8.5,49.0,"2026-10-28T12:00:00+00:00")):
                call(root,"2026-10-28T12:01:00+00:00")
            with patch("plug_dynamic_market.matchup_public_market",
                       return_value=market(-6.5,48.0,"2026-10-28T13:00:00+00:00")):
                call(root,"2026-10-28T13:01:00+00:00")
            card=card_state(root,GID,as_of_utc="2026-10-28T14:00:00+00:00",
                            away_team="BAL",home_team="PIT")
            self.assertTrue(card["changed"])
            self.assertEqual(card["ats"],"Stay Away")
            self.assertEqual(card["ou"],"Under 48")
            result=closing_grade(root,GID,as_of_utc=KICK,away_score=28,home_score=20)
            self.assertIsNone(result["ats"])
            self.assertEqual(result["ou"],"Push")
            self.assertEqual(result["revision"],2)

    def test_kickoff_rejects_late_update_without_writing(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("plug_dynamic_market.matchup_public_market",
                       return_value=market(-8.5,49.0,"2026-10-28T12:00:00+00:00")):
                call(root,"2026-10-28T12:01:00+00:00")
            with patch("plug_dynamic_market.matchup_public_market",
                       return_value=market(-7.5,48.0,"2026-10-29T00:00:00+00:00")):
                with self.assertRaises(ValueError): call(root,KICK)
            result=closing_grade(root,GID,as_of_utc=KICK,away_score=28,home_score=20)
            self.assertEqual(result["revision"],1)

if __name__=="__main__":
    unittest.main()
