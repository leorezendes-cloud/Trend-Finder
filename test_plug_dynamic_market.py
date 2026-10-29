"""Saved-market adapter validation (mocked provider; no network)."""
import unittest
from unittest.mock import patch
from plug_dynamic_market import verified_decision

NOW="2026-10-28T15:00:00+00:00"
KICK="2026-10-29T00:00:00+00:00"
MARKET={"markets":[
    {"key":"Spread","captured":"2026-10-28T14:00:00+00:00","stale":False,
     "sides":[{"name":"BAL","line":-8.5},{"name":"PIT","line":8.5}]},
    {"key":"Total","captured":"2026-10-28T14:01:00+00:00","stale":False,
     "sides":[{"name":"Over","line":49.0},{"name":"Under","line":49.0}]}]}
ARGS=dict(game_id="2026_08_BAL_PIT",away_team="BAL",home_team="PIT",
          kickoff_utc=KICK,model_away_spread=-8.0,v14_total=49.5,
          original_total_side="Over",evaluation_utc=NOW)

class SavedMarketAdapterTest(unittest.TestCase):
    def test_valid_market_creates_decision(self):
        with patch("plug_dynamic_market.matchup_public_market",return_value=MARKET):
            d=verified_decision("/tmp/not-used",**ARGS)
        self.assertTrue(d["ats_selected"])
        self.assertEqual(d["ats_side"],"PIT")
        self.assertEqual(d["ou_side"],"Over")

    def test_reject_missing_stale_or_invalid_market(self):
        variants=[
            {"markets":MARKET["markets"][:1]},
            {"markets":[*MARKET["markets"],MARKET["markets"][0]]},
            {"markets":[{**MARKET["markets"][0],"sides":[{"name":"BAL","line":True},{"name":"PIT","line":-1}]},MARKET["markets"][1]]},
            {"markets":[{**MARKET["markets"][0],"stale":True},MARKET["markets"][1]]},
            {"markets":[{**MARKET["markets"][0],"sides":[{"name":"BAL","line":-8.5},{"name":"PIT","line":7.5}]},MARKET["markets"][1]]},
            {"markets":[MARKET["markets"][0],{**MARKET["markets"][1],"captured":"2026-10-29T01:00:00+00:00"}]},
        ]
        for market in variants:
            with self.subTest(market=market),patch("plug_dynamic_market.matchup_public_market",return_value=market):
                with self.assertRaises(ValueError):
                    verified_decision("/tmp/not-used",**ARGS)

if __name__=="__main__":
    unittest.main()
