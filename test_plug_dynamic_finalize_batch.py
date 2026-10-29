"""Batch closing research finalization tests."""
import tempfile
import unittest
from plug_dynamic_journal import append
from plug_dynamic_finalize_batch import finalize_due
from plug_dynamic_closing import read_closing

GID="2026_08_BAL_PIT"
ROW=dict(ats_selected=True,ats_side="BAL",ats_away_line=-7.5,
         ou_selected=True,ou_side="Under",ou_market_total=48.5,
         ou_source="fade_v14",quote_observed_utc="2026-10-28T12:00:00+00:00",
         evaluated_utc="2026-10-28T12:01:00+00:00",
         kickoff_utc="2026-10-29T00:00:00+00:00")

class FinalizeBatchTest(unittest.TestCase):
    def test_only_finalizes_after_kickoff(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,GID,ROW)
            early=finalize_due(root,as_of_utc="2026-10-28T23:59:00+00:00")
            self.assertEqual(early["due"],0)
            self.assertIsNone(read_closing(root,GID))
            late=finalize_due(root,as_of_utc=ROW["kickoff_utc"])
            self.assertEqual((late["due"],late["locked"]),(1,1))
            self.assertIsNotNone(read_closing(root,GID))
            self.assertEqual(finalize_due(root,as_of_utc=ROW["kickoff_utc"])["locked"],1)
if __name__=="__main__":
    unittest.main()
