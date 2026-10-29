"""Locked dynamic research grading tests."""
import tempfile
import unittest
from plug_dynamic_journal import append
from plug_dynamic_grading import closing_grade

ROW=dict(ats_selected=True,ats_side="BAL",ats_away_line=-7.5,
         ou_selected=True,ou_side="Over",ou_market_total=48.5,
         ou_source="follow_v14",
         quote_observed_utc="2026-10-28T12:00:00+00:00",
         evaluated_utc="2026-10-28T12:01:00+00:00",
         kickoff_utc="2026-10-29T00:00:00+00:00")
GID="2026_08_BAL_PIT"

class ClosingGradeTest(unittest.TestCase):
    def test_only_lock_graded_and_uses_saved_line(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,GID,ROW)
            self.assertEqual(closing_grade(root,GID,as_of_utc="2026-10-28T13:00:00+00:00",away_score=28,home_score=20)["status"],"pregame")
            grade=closing_grade(root,GID,as_of_utc="2026-10-29T00:00:00+00:00",away_score=28,home_score=20)
            self.assertEqual((grade["ats"],grade["ou"]),("Win","Loss"))
    def test_stay_away_remains_ungraded(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,GID,{**ROW,"ats_selected":False,"ats_side":None,
                             "ou_selected":False,"ou_side":None})
            grade=closing_grade(root,GID,as_of_utc="2026-10-29T00:00:00+00:00",away_score=28,home_score=20)
            self.assertIsNone(grade["ats"])
            self.assertIsNone(grade["ou"])

if __name__=="__main__":
    unittest.main()
