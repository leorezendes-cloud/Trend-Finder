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

class WeeklyWindowTests(unittest.TestCase):
    def run_batch(self, gids, failures, *, when='2026-10-29T16:00:00+00:00'):
        import csv
        from datetime import datetime
        from pathlib import Path
        rows=[dict(game_id='2026_08_BAL_PIT',season=2026,week=8,game_type='REG',
                   gameday='2026-11-01',gametime='13:00'),
              dict(game_id='2026_09_JAX_BAL',season=2026,week=9,game_type='REG',
                   gameday='2026-11-05',gametime='20:15')]
        with tempfile.TemporaryDirectory() as root:
            with (Path(root)/'nfl_games.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            with patch('plug_dynamic_batch.upcoming_games',return_value=gids),\
                 patch('plug_dynamic_batch.observe_from_receipts',side_effect=failures) as observe:
                result=refresh(root,now=datetime.fromisoformat(when))
                self.assertEqual(observe.call_count,len(gids))
                # Reporting a future wait never fabricates a journal or receipt.
                self.assertFalse((Path(root)/'plug_dynamic_research').exists())
                return result

    def test_current_week_coverage_is_ok_when_only_next_week_receipt_is_waiting(self):
        from plug_dynamic_errors import WeeklyReceiptPending
        result=self.run_batch(['2026_08_BAL_PIT','2026_09_JAX_BAL'],
                              [{'revision':1},WeeklyReceiptPending('not issued yet')])
        self.assertEqual(result['state'],'ok')
        self.assertEqual(result['refreshed'],1)
        self.assertEqual(result['unavailable'],0)
        self.assertEqual(result['awaiting_next_week'],1)
        self.assertIn('2026_09_JAX_BAL',result['next_week_games'])
        self.assertEqual(result['games'],{})

    def test_future_only_window_is_an_explicit_wait_not_a_fake_refresh(self):
        from plug_dynamic_errors import WeeklyReceiptPending
        result=self.run_batch(['2026_09_JAX_BAL'],[WeeklyReceiptPending('not issued yet')])
        self.assertEqual(result['state'],'waiting_next_week')
        self.assertEqual(result['refreshed'],0)

    def test_missing_current_week_receipt_remains_visible(self):
        from plug_dynamic_errors import WeeklyReceiptPending
        result=self.run_batch(['2026_08_BAL_PIT'],[WeeklyReceiptPending('missing')])
        self.assertEqual(result['state'],'unavailable')
        self.assertEqual(result['unavailable'],1)
        self.assertEqual(result['awaiting_next_week'],0)

    def test_rollover_promotes_missing_receipt_to_active_week_unavailable(self):
        from plug_dynamic_errors import WeeklyReceiptPending
        result=self.run_batch(['2026_09_JAX_BAL'],[WeeklyReceiptPending('missing')],
                              when='2026-11-04T14:00:00+00:00')
        self.assertEqual(result['state'],'unavailable')
        self.assertEqual(result['unavailable'],1)

    def test_other_missing_future_evidence_and_corruption_are_not_hidden(self):
        from plug_dynamic_errors import Unavailable
        result=self.run_batch(['2026_09_JAX_BAL'],[Unavailable('stale market')])
        self.assertEqual(result['unavailable'],1)
        self.assertEqual(result['awaiting_next_week'],0)
        with self.assertRaisesRegex(ValueError,'checksum'):
            self.run_batch(['2026_09_JAX_BAL'],[ValueError('receipt checksum mismatch')])

    def test_next_capture_retries_and_resolves_without_a_manual_repair(self):
        from plug_dynamic_errors import WeeklyReceiptPending
        before=self.run_batch(['2026_09_JAX_BAL'],[WeeklyReceiptPending('not yet')])
        after=self.run_batch(['2026_09_JAX_BAL'],[{'revision':1}])
        self.assertEqual(before['awaiting_next_week'],1)
        self.assertEqual(after['refreshed'],1)
        self.assertEqual(after['awaiting_next_week'],0)
        self.assertEqual(after['state'],'ok')

if __name__=="__main__":
    unittest.main()
