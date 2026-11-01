"""Focused owner consensus checks; no production data or network needed."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from owner_consensus import compare

NOW = datetime(2026, 10, 31, 20, tzinfo=timezone.utc)
KICK = "2026-11-01T18:00:00+00:00"


def example(locked=True):
    return dict(game_id="2026_9_NE_BUF", season="2026", away="NE", home="BUF",
                kickoff_utc=KICK, locked=locked, state="ready",
                result={"selection": {"pick": "Over"}, "market_total": 45.5},
                qb_record=None, actual_total=None)


class ConsensusTests(unittest.TestCase):
    @patch("owner_consensus._safe_plug")
    @patch("owner_consensus._safe_scout")
    def test_three_way_agreement(self, scout, plug):
        scout.return_value = (dict(ou_side="Over", ats_side="NE",
            total_quote={"line": 45.5}), "pregame")
        plug.return_value = (dict(ou_selected=True, ou_side="Over",
            ou_market_total=45.5, ats_selected=True, ats_side="NE"), "pregame")
        data = compare([example()], ".", now=NOW)
        self.assertEqual(data["rows"][0]["ou_agreement"], "3/3 agree")
        self.assertEqual(data["rows"][0]["ats_agreement"], "Scout + Plug agree")
        self.assertEqual(data["record"]["Win"], 0)

    @patch("owner_consensus._safe_plug")
    @patch("owner_consensus._safe_scout")
    def test_missing_plug_is_not_unanimous(self, scout, plug):
        scout.return_value = ({"ou_side": "Over", "ats_side": "NE"}, "pregame")
        plug.return_value = (None, None)
        data = compare([example()], ".", now=NOW)
        self.assertEqual(data["rows"][0]["ou_agreement"], "Partial")

    @patch("owner_consensus._safe_plug")
    @patch("owner_consensus._safe_scout")
    def test_preview_not_graded(self, scout, plug):
        scout.return_value = ({"ou_side": "Over"}, "pregame")
        plug.return_value = ({"ou_selected": True, "ou_side": "Over"}, "pregame")
        row = example(locked=False)
        data = compare([row], ".", now=NOW)
        self.assertEqual(data["rows"][0]["ou_agreement"], "3/3 agree (preview)")
        self.assertEqual(sum(data["record"].values()), 0)

    @patch("owner_consensus._safe_plug")
    @patch("owner_consensus._safe_scout")
    def test_split(self, scout, plug):
        scout.return_value = ({"ou_side": "Under"}, "pregame")
        plug.return_value = ({"ou_selected": True, "ou_side": "Over"}, "pregame")
        self.assertEqual(compare([example()], ".", now=NOW)["rows"][0]["ou_agreement"], "Split")


if __name__ == "__main__":
    unittest.main()
