"""Compact dynamic card view model tests."""
import tempfile
import unittest
from plug_dynamic_journal import append
from plug_dynamic_cards import card_state

BASE=dict(ats_selected=True,ats_side="PIT",ats_away_line=-8.5,
          ou_selected=True,ou_side="Over",ou_market_total=49.,
          ou_source="follow_v14",
          quote_observed_utc="2026-10-28T12:00:00+00:00",
          evaluated_utc="2026-10-28T12:01:00+00:00",
          kickoff_utc="2026-10-29T00:00:00+00:00")
def card(root,as_of):
    return card_state(root,"2026_08_BAL_PIT",as_of_utc=as_of,
                      away_team="BAL",home_team="PIT")
class CardTest(unittest.TestCase):
    def test_unavailable_pregame_and_locked(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(card(root,"2026-10-28T13:00:00+00:00")["status"],"unavailable")
            append(root,"2026_08_BAL_PIT",BASE)
            pre=card(root,"2026-10-28T13:00:00+00:00")
            self.assertEqual((pre["ats"],pre["ou"]),("PIT +8.5","Over 49"))
            self.assertFalse(pre["changed"])
            self.assertEqual(card(root,"2026-10-29T00:00:00+00:00")["status"],"locked")
    def test_changed_and_stay_away(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,"2026_08_BAL_PIT",BASE)
            append(root,"2026_08_BAL_PIT",{**BASE,"ats_selected":False,"ats_side":None,
                "ats_away_line":-6.5,"quote_observed_utc":"2026-10-28T13:00:00+00:00",
                "evaluated_utc":"2026-10-28T13:01:00+00:00"})
            state=card(root,"2026-10-28T14:00:00+00:00")
            self.assertEqual(state["ats"],"Stay Away")
            self.assertTrue(state["changed"])
if __name__=="__main__":
    unittest.main()
