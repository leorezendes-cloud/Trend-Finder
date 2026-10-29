"""Authoritative dynamic overlay handles pregame revisions and immutable grades."""
import tempfile
import unittest
from plug_dynamic_authoritative import attach
from plug_dynamic_closing import finalize
from plug_dynamic_journal import append

GID="2026_08_BAL_PIT"
KICK="2026-10-29T00:00:00+00:00"
ROW=dict(ats_selected=True,ats_side="BAL",ats_away_line=-7.5,
         ou_selected=True,ou_side="Under",ou_market_total=48.5,
         ou_source="fade_v14",quote_observed_utc="2026-10-28T12:00:00+00:00",
         evaluated_utc="2026-10-28T12:01:00+00:00",kickoff_utc=KICK)
def card(final=None):
    result={"scout":{"game":{"game_id":GID,"away_team":"BAL","home_team":"PIT",
                              "kickoff_utc":KICK}},"plug_ats_status":"selected"}
    if final is not None:
        result["final_score"]={"away":final[0],"home":final[1]}
    return result

class DynamicOfficialTest(unittest.TestCase):
    def test_pregame_and_closing_require_real_records(self):
        with tempfile.TemporaryDirectory() as root:
            item=card()
            self.assertFalse(attach(root,item,as_of_utc="2026-10-28T13:00:00+00:00"))
            self.assertNotIn("plug_dynamic_official",item)
            append(root,GID,ROW)
            self.assertTrue(attach(root,item,as_of_utc="2026-10-28T13:00:00+00:00"))
            self.assertEqual(item["plug_dynamic_card"]["ats"],"BAL -7.5")
            completed=card((28,20))
            self.assertFalse(attach(root,completed,as_of_utc=KICK))
            finalize(root,GID,as_of_utc=KICK)
            self.assertTrue(attach(root,completed,as_of_utc=KICK))
            self.assertEqual(completed["plug_dynamic_grades"]["ats"],"Win")
            self.assertEqual(completed["plug_dynamic_grades"]["ou"],"Win")
    def test_kickoff_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,GID,ROW)
            item=card()
            item["scout"]["game"]["kickoff_utc"]="2026-10-30T00:00:00+00:00"
            with self.assertRaises(ValueError):
                attach(root,item,as_of_utc="2026-10-28T13:00:00+00:00")
if __name__=="__main__":
    unittest.main()
