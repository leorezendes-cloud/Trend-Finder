"""Research orchestration tests; no production filesystem or odds API."""
import tempfile
import unittest
from unittest.mock import patch
from plug_dynamic_research import observe,snapshot

ARGS=dict(game_id="2026_08_BAL_PIT",away_team="BAL",home_team="PIT",
          kickoff_utc="2026-10-29T00:00:00+00:00",model_away_spread=-8.,
          v14_total=49.5,original_total_side="Over",
          evaluation_utc="2026-10-28T15:00:00+00:00")
STATE=dict(ats_selected=True,ats_side="PIT",ats_away_line=-8.5,
           ou_selected=True,ou_side="Over",ou_market_total=49.,
           ou_source="follow_v14",
           quote_observed_utc="2026-10-28T14:00:00+00:00",
           evaluated_utc=ARGS["evaluation_utc"],
           kickoff_utc=ARGS["kickoff_utc"])

class ResearchOrchestrationTest(unittest.TestCase):
    def test_writes_only_validated_decision_and_locks_read_at_kickoff(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(snapshot(root,ARGS["game_id"],as_of_utc=ARGS["evaluation_utc"])["status"],"unavailable")
            with patch("plug_dynamic_research.verified_decision",return_value=STATE):
                a=observe(root,**ARGS)
                b=observe(root,**ARGS)
            self.assertEqual(a,b)
            self.assertEqual(snapshot(root,ARGS["game_id"],as_of_utc=ARGS["evaluation_utc"])["status"],"pregame")
            self.assertEqual(snapshot(root,ARGS["game_id"],as_of_utc=ARGS["kickoff_utc"])["status"],"locked")
            self.assertEqual(snapshot(root,ARGS["game_id"],as_of_utc=ARGS["kickoff_utc"])["revisions"],1)

    def test_failure_cannot_mutate_research_history(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("plug_dynamic_research.verified_decision",side_effect=ValueError("stale")):
                with self.assertRaises(ValueError): observe(root,**ARGS)
            self.assertEqual(snapshot(root,ARGS["game_id"],as_of_utc=ARGS["kickoff_utc"])["status"],"unavailable")

if __name__=="__main__":
    unittest.main()
