"""Scheduler tests: temporary files and mocked actions only."""
import fcntl
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import hosted_updates as hosted


class SchedulerTests(unittest.TestCase):
    def test_real_lock_contention_is_visible_and_does_not_run_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'logs').mkdir()
            with (root/'logs/auto_update.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(hosted, 'update_once') as update:
                    self.assertEqual(hosted.locked_update(root), 75)
                    update.assert_not_called()
            self.assertIn('lock_busy', (root/'logs/scout-worker_scheduler.jsonl').read_text())

    def test_uncaught_worker_exception_is_reported_and_lock_released(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(hosted, 'update_once', side_effect=ImportError('broken import')):
                self.assertEqual(hosted.locked_update(directory), 1)
            with patch.object(hosted, 'update_once', return_value={'state':'ok'}) as update:
                self.assertEqual(hosted.locked_update(directory), 0)
                update.assert_called_once()
            events = [json.loads(line) for line in (Path(directory)/'logs/scout-worker_scheduler.jsonl').read_text().splitlines()]
            self.assertEqual([e['state'] for e in events], ['attempt', 'failure', 'attempt', 'success'])

    def test_thread_recovers_from_calendar_or_status_exception_and_retries_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = Mock()
            stop.is_set.side_effect = [False, False, False, True]
            action = Mock(side_effect=[ValueError('calendar/status'), 75, 0])
            hosted.scheduler_loop('test', action, 21600, directory, stop)
            self.assertEqual(action.call_count, 3)
            self.assertEqual([c.args[0] for c in stop.wait.call_args_list], [21600, 60, 21600])
            states = [json.loads(line)['state'] for line in (Path(directory)/'logs/test_scheduler.jsonl').read_text().splitlines()]
            self.assertEqual(states, ['attempt','failure','attempt','lock_busy','attempt','success'])

    def test_logging_failure_does_not_kill_timer(self):
        with patch.object(Path, 'mkdir', side_effect=OSError('read only')):
            hosted.scheduler_event('/unused', 'test', 'attempt')

    def test_poll_is_not_logged_as_a_prediction_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = Mock()
            stop.is_set.side_effect = [False, True]
            with patch.object(hosted, 'scheduler_event') as event:
                hosted.scheduler_loop('automatic-data-updates', Mock(return_value='not_due'),
                                      30, directory, stop, False)
            event.assert_not_called()

    def test_interrupted_stage_retains_timestamped_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(hosted, 'backup_database', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    hosted.update_once(root)
            status = json.loads((root/'logs/auto_update_status.json').read_text())
            self.assertEqual(status['stages'], {'account backup':'running'})
            self.assertIn('checked_at', status)
            self.assertIn('pid', status)
            hosted.scout_status(root, 'needs attention', 'supervisor interrupted')
            status = json.loads((root/'logs/auto_update_status.json').read_text())
            self.assertEqual(status['stages']['account backup'], 'running')
            self.assertEqual(status['state'], 'needs attention')

    def test_leader_recovery_updates_status_without_starting_worker(self):
        from scheduler_runtime import atomic_json
        import time
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'logs/automatic-data-updates.schedule.json'
            atomic_json(path, {'state':'running', 'next_due':time.time()+1560})
            with patch.object(hosted.threading, 'Thread') as thread, patch.object(hosted, 'run_worker') as worker:
                hosted.run_leader(root, Mock())
                action = next(c.kwargs['args'][1] for c in thread.call_args_list
                              if c.kwargs['name'] == 'automatic-data-updates')
                self.assertEqual(action(), 'not_due')
                worker.assert_not_called()
            self.assertEqual(json.loads((root/'logs/auto_update_status.json').read_text())['state'], 'needs attention')

    def test_worker_exit_timeout_and_failure_are_not_silent(self):
        import subprocess
        with patch.object(hosted.subprocess, 'run', return_value=subprocess.CompletedProcess(['worker'], 75)):
            self.assertEqual(hosted.run_worker('unused'), 75)
        for failure in [subprocess.TimeoutExpired('worker', 600), OSError('missing')]:
            with patch.object(hosted.subprocess, 'run', side_effect=failure):
                with self.assertRaises(type(failure)): hosted.run_worker('unused')
        with patch.object(hosted.subprocess, 'run', return_value=subprocess.CompletedProcess(['worker'], 1)):
            with self.assertRaises(subprocess.CalledProcessError): hosted.run_worker('unused')

    def test_gunicorn_starts_scheduler_without_blocking_on_warmup(self):
        import sys
        from types import SimpleNamespace
        config = runpy.run_path('gunicorn.conf.py')
        calls = []
        with patch.object(hosted, 'start_scheduler', side_effect=lambda: calls.append('scheduler')), patch.dict(sys.modules, {'trend_finder_2': SimpleNamespace(scan_basic_trends=lambda **kw: calls.append('warmup'))}):
            config['post_worker_init'](None)
        self.assertEqual(calls, ['scheduler'])


if __name__ == '__main__': unittest.main()
