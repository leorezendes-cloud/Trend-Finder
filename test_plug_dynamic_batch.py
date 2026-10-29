"""Research refresh remains opt-in and never publishes official receipts."""
import tempfile
import unittest
from unittest.mock import patch
from plug_dynamic_batch import refresh

class BatchTest(unittest.TestCase):
    def test_refresh_and_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("plug_dynamic_batch.upcoming_games",return_value=["2026_08_BAL_PIT","2026_08_NE_NYJ"]),\
                 patch("plug_dynamic_batch.observe_from_receipts",side_effect=[{"revision":1},__import__("plug_dynamic_errors").Unavailable("missing quote")]) as obs:
                status=refresh(root)
        self.assertEqual(status["refreshed"],1)
        self.assertEqual(status["unavailable"],1)
        self.assertEqual(status["state"],"partial")
        self.assertEqual(obs.call_count,2)
    def test_programming_errors_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("plug_dynamic_batch.upcoming_games",return_value=["2026_08_BAL_PIT"]),\
                 patch("plug_dynamic_batch.observe_from_receipts",side_effect=RuntimeError("unexpected")):
                with self.assertRaises(RuntimeError):
                    refresh(root)
if __name__=="__main__":
    unittest.main()
