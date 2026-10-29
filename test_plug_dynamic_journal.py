"""Research journal regression cases (no production data)."""
import tempfile
import unittest
from plug_dynamic_journal import append, read

BASE=dict(ats_selected=True,ats_side="BAL",ats_away_line=-7.5,
          ou_selected=True,ou_side="Under",ou_market_total=48.5,
          ou_source="fade_v14",
          quote_observed_utc="2026-10-28T12:00:00+00:00",
          evaluated_utc="2026-10-28T12:01:00+00:00",
          kickoff_utc="2026-10-29T00:00:00+00:00")

class JournalTest(unittest.TestCase):
    def test_revisions_are_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            one=append(root,"2026_08_BAL_PIT",BASE)
            self.assertEqual(one["revision"],1)
            self.assertEqual(append(root,"2026_08_BAL_PIT",BASE),one)
            two=append(root,"2026_08_BAL_PIT",
                {**BASE,"ats_side":None,"ats_selected":False,
                 "ats_away_line":-6.5,
                 "quote_observed_utc":"2026-10-28T13:00:00+00:00",
                 "evaluated_utc":"2026-10-28T13:01:00+00:00"})
            self.assertEqual(two["revision"],2)
            self.assertEqual(len(read(root,"2026_08_BAL_PIT")),2)

    def test_reject_future_out_of_order_and_postkickoff(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,"2026_08_BAL_PIT",BASE)
            for change in (
                {"evaluated_utc":"2026-10-29T00:00:00+00:00"},
                {"quote_observed_utc":"2026-10-28T14:00:00+00:00"},
                {"kickoff_utc":"2026-10-30T00:00:00+00:00"},
            ):
                with self.subTest(change=change),self.assertRaises(ValueError):
                    append(root,"2026_08_BAL_PIT",{**BASE,**change,
                        "ats_away_line":-8.5})

    def test_tamper_detection(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,"2026_08_BAL_PIT",BASE)
            from pathlib import Path
            file=Path(root)/"plug_dynamic_research"/"2026_08_BAL_PIT.jsonl"
            file.write_text(file.read_text().replace("BAL","PIT"),encoding="utf-8")
            with self.assertRaises(ValueError):
                read(root,"2026_08_BAL_PIT")

if __name__=="__main__":
    unittest.main()
