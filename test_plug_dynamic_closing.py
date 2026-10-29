"""Closing receipt contract tests; never touch official Plug publication."""
import tempfile
import unittest
from plug_dynamic_closing import finalize, read_closing
from plug_dynamic_journal import append

GID="2026_08_BAL_PIT"
ROW=dict(ats_selected=True,ats_side="BAL",ats_away_line=-7.5,
         ou_selected=True,ou_side="Under",ou_market_total=48.5,
         ou_source="fade_v14",quote_observed_utc="2026-10-28T12:00:00+00:00",
         evaluated_utc="2026-10-28T12:01:00+00:00",
         kickoff_utc="2026-10-29T00:00:00+00:00")

class ClosingReceiptTest(unittest.TestCase):
    def test_finalization_is_immutable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(finalize(root,GID,as_of_utc=ROW["kickoff_utc"]))
            append(root,GID,ROW)
            with self.assertRaises(ValueError):
                finalize(root,GID,as_of_utc="2026-10-28T23:59:00+00:00")
            first=finalize(root,GID,as_of_utc=ROW["kickoff_utc"])
            self.assertEqual(first,read_closing(root,GID))
            self.assertEqual(first,finalize(root,GID,as_of_utc="2026-10-30T00:00:00+00:00"))
            self.assertEqual(first["ats_away_line"],-7.5)
    def test_new_research_revision_cannot_rewrite_closing_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,GID,ROW)
            finalize(root,GID,as_of_utc=ROW["kickoff_utc"])
            before=read_closing(root,GID)
            with self.assertRaises(ValueError):
                append(root,GID,{**ROW,"ats_away_line":-8.5,
                    "quote_observed_utc":"2026-10-28T13:00:00+00:00",
                    "evaluated_utc":"2026-10-28T13:01:00+00:00"})
            self.assertEqual(before,read_closing(root,GID))
if __name__=="__main__":
    unittest.main()
