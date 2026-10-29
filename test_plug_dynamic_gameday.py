"""Game-day dynamic research collection remains opt-in and follows capture."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from hosted_updates import refresh_game_day_market

NOW=datetime(2026,10,29,16,tzinfo=timezone.utc)
GID="2026_08_BAL_PIT"
CSV="game_id,gameday\n"+GID+",2026-10-29\n"

class GameDayRefreshTest(unittest.TestCase):
    def test_compatibility_wrapper_does_not_duplicate_collector_hook(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,"nfl_games.csv").write_text(CSV)
            with patch("scheduled_ats_capture.upcoming_games",return_value=[GID]),\
                 patch("scheduled_ats_capture.run",return_value=0) as capture,\
                 patch("plug_dynamic_batch.refresh") as dynamic,\
                 patch.dict("os.environ",{"TREND_FINDAH_DYNAMIC_RESEARCH":"1"}):
                refresh_game_day_market(root,now=NOW)
                capture.assert_called_once()
                dynamic.assert_not_called()
    def test_disabled_and_capture_failure(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,"nfl_games.csv").write_text(CSV)
            with patch("scheduled_ats_capture.upcoming_games",return_value=[GID]),\
                 patch("scheduled_ats_capture.run",return_value=0),\
                 patch("plug_dynamic_batch.refresh") as dynamic,\
                 patch.dict("os.environ",{"TREND_FINDAH_DYNAMIC_RESEARCH":"0"}):
                refresh_game_day_market(root,now=NOW)
                dynamic.assert_not_called()
            with patch("scheduled_ats_capture.upcoming_games",return_value=[GID]),\
                 patch("scheduled_ats_capture.run",return_value=1),\
                 patch("plug_dynamic_batch.refresh") as dynamic,\
                 patch.dict("os.environ",{"TREND_FINDAH_DYNAMIC_RESEARCH":"1"}):
                with self.assertRaises(RuntimeError):
                    refresh_game_day_market(root,now=NOW)
                dynamic.assert_not_called()
if __name__=="__main__":
    unittest.main()
