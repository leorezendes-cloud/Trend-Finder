"""Market capture must not disguise saved public splits as a primary failure."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import scheduled_ats_capture as capture

NOW=datetime(2026, 11, 8, 14, 0, tzinfo=timezone.utc)
ROW={"captured_at_utc": NOW.isoformat()}
REPORT={"all": {"qualifying": 1, "pending": 1}}


class MarketCaptureStatusTests(unittest.TestCase):
    def test_valid_splits_survive_missing_backup_market(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(capture, "upcoming_games", return_value=["2026_10_SEA_LV"]), \
                 patch.object(capture, "collect", return_value=[ROW]), \
                 patch.object(capture, "missing_markets", return_value={("2026_10_SEA_LV", "Total")}), \
                 patch.object(capture, "missing_prices", return_value=["2026_10_SEA_LV"]), \
                 patch("odds_backup.collect", side_effect=ValueError("Backup returned no verified upcoming spread or total prices")), \
                 patch.object(capture, "analyze", return_value=REPORT), \
                 patch.object(capture, "refresh_dynamic"):
                result=capture.run(root, now=NOW)
            self.assertEqual(result, 0)
            status=json.loads((root/"logs"/"ats_capture_status.json").read_text())
            self.assertTrue(status["splits_available"])
            self.assertEqual(status["primary_state"], "ok")
            self.assertEqual(status["state"], "ok")
            self.assertEqual(status["saved"], 1)
            self.assertEqual(status["missing_games"], ["2026_10_SEA_LV"])
            self.assertIn("backup_warning", status)
            self.assertNotIn("primary_error", status)

    def test_archive_disabled_by_default(self):
        # Both sources must require explicit opt-in, in addition to disk guard.
        from collect_ats_handle import archive_evidence
        import os
        self.assertNotEqual(os.environ.get("TREND_FINDAH_ARCHIVE_MARKET_EVIDENCE"), "1")


if __name__ == "__main__":
    unittest.main()
