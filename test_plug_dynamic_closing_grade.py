"""Immutable dynamic closing grading checks."""
import tempfile
import unittest
from plug_dynamic_journal import append
from plug_dynamic_closing import finalize
from plug_dynamic_closing_grade import grade_closing

GID="2026_08_BAL_PIT"
ROW=dict(ats_selected=True,ats_side="BAL",ats_away_line=-7.5,
         ou_selected=True,ou_side="Under",ou_market_total=48.5,
         ou_source="fade_v14",quote_observed_utc="2026-10-28T12:00:00+00:00",
         evaluated_utc="2026-10-28T12:01:00+00:00",
         kickoff_utc="2026-10-29T00:00:00+00:00")

class ClosingGradeTest(unittest.TestCase):
    def test_receipt_is_sole_grading_source(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(grade_closing(root,GID,away_score=28,home_score=20)["status"],"unavailable")
            append(root,GID,ROW)
            finalize(root,GID,as_of_utc=ROW["kickoff_utc"])
            grade=grade_closing(root,GID,away_score=28,home_score=20)
            self.assertEqual((grade["ats"],grade["ou"]),("Win","Win"))
            self.assertEqual(grade["revision"],1)
    def test_invalid_final_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,GID,ROW)
            finalize(root,GID,as_of_utc=ROW["kickoff_utc"])
            for a,h in ((-1,20),(28.5,20),(float("nan"),20)):
                with self.subTest(scores=(a,h)),self.assertRaises(ValueError):
                    grade_closing(root,GID,away_score=a,home_score=h)
if __name__=="__main__":
    unittest.main()
