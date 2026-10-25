"""Read-only, mocked weekly scheduler regressions; never invoke live workers."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import hosted_updates as hosted
import weekly_pick_lines
from site_week import week_window


class WeeklyRetryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = [datetime(2030, 10, 17, 12, tzinfo=timezone.utc)]

    def setup_runner(self):
        """Capture the real scheduled wrapper; execute its lease action in memory."""
        from scheduler_runtime import due_job
        def instant(root, job, action, interval, timeout, on_recovery=None):
            return action()
        clock = patch.object(hosted, 'datetime')
        threads = patch.object(hosted.threading, 'Thread')
        lease = patch('scheduler_runtime.due_job', side_effect=instant)
        worker = patch.object(hosted, 'run_worker', return_value=0)
        mock_clock = clock.start()
        self.addCleanup(clock.stop)
        mock_clock.now.side_effect = lambda tz=None: self.now[0]
        mock_threads = threads.start()
        self.addCleanup(threads.stop)
        mock_lease = lease.start()
        self.addCleanup(lease.stop)
        mock_worker = worker.start()
        self.addCleanup(worker.stop)
        hosted.run_leader(self.root, Mock())
        matches = [call.kwargs['args'][1] for call in mock_threads.call_args_list
                   if call.kwargs.get('name') == 'automatic-weekly-lines']
        self.assertEqual(len(matches), 1)
        return matches[0], mock_worker, mock_lease

    def test_pending_week_retries_15_minutes_not_every_30_seconds(self):
        scheduled, worker, lease = self.setup_runner()
        self.assertEqual(scheduled(), 0)
        self.now[0] += timedelta(minutes=2)
        self.assertEqual(scheduled(), 'not_due')
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(lease.call_count, 1)  # Skip even the disk-backed lease.
        self.now[0] += timedelta(minutes=13)
        self.assertEqual(scheduled(), 0)
        self.assertEqual(worker.call_count, 2)

    def test_wednesday_capture_retains_30_second_attempts(self):
        self.now[0] = datetime(2030, 10, 16, 12, tzinfo=timezone.utc)
        scheduled, worker, _ = self.setup_runner()
        self.assertEqual(scheduled(), 0)
        self.now[0] += timedelta(seconds=30)
        self.assertEqual(scheduled(), 0)
        self.assertEqual(worker.call_count, 2)

    def test_ready_snapshot_prevents_workers_and_lease_writes(self):
        self.now[0] = datetime(2030, 10, 17, 12, tzinfo=timezone.utc)
        cutoff = week_window(self.now[0])[0].astimezone(timezone.utc)
        status = self.root/'logs/weekly_lines_status.json'
        status.parent.mkdir(parents=True)
        status.write_text(json.dumps({'state':'ready','published':True,'scheduled_cutoff':cutoff.isoformat()}))
        scheduled, worker, lease = self.setup_runner()
        self.assertEqual(scheduled(), 'not_due')
        self.assertEqual(scheduled(), 'not_due')
        worker.assert_not_called()
        lease.assert_not_called()
        self.now[0] = cutoff + timedelta(days=7)
        self.assertEqual(scheduled(), 0)  # New week's boundary runs immediately.
        self.assertEqual(worker.call_count, 1)

    def test_backoff_cannot_skip_next_wednesday_cutoff(self):
        self.now[0] = datetime(2030, 10, 23, 11, 55, tzinfo=timezone.utc)
        scheduled, worker, _ = self.setup_runner()
        self.assertEqual(scheduled(), 0)
        self.now[0] += timedelta(minutes=5)
        self.assertEqual(scheduled(), 0)
        self.assertEqual(worker.call_count, 2)

    def test_status_write_interruption_preserves_previous_status(self):
        status = self.root/'logs/weekly_lines_status.json'
        status.parent.mkdir(parents=True)
        status.write_text('{"state":"ready","scheduled_cutoff":"old"}')
        self.now[0] = datetime(2030, 10, 17, 12, tzinfo=timezone.utc)
        with patch.object(weekly_pick_lines, 'available_snapshot', return_value=None), \
             patch.object(weekly_pick_lines, 'freeze_snapshot', return_value={'state':'pending','reason':'missing'}), \
             patch.object(weekly_pick_lines, 'datetime') as clock, \
             patch('scheduler_runtime.os.replace', side_effect=OSError('interrupted')):
            clock.now.return_value = self.now[0]
            with self.assertRaises(OSError):
                weekly_pick_lines.scheduled_capture(self.root)
        self.assertEqual(json.loads(status.read_text())['state'], 'ready')


if __name__ == '__main__':
    unittest.main()
