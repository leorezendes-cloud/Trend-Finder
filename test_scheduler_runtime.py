"""Offline concurrency, restart and atomic-write regression tests."""
import json
import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from scheduler_runtime import exclusive, due_job, atomic_json
import hosted_updates as hosted


def contender(path, queue):
    with exclusive(path) as acquired:
        queue.put(acquired)


def hold_until_killed(path, queue):
    with exclusive(path) as acquired:
        queue.put(acquired)
        threading.Event().wait(30)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cross_process_lock_and_takeover_after_exit(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        path = self.root/'leader.lock'
        with exclusive(path) as acquired:
            self.assertTrue(acquired)
            child = context.Process(target=contender, args=(path, queue))
            child.start()
            self.assertFalse(queue.get(timeout=10))
            child.join(10)
            self.assertEqual(child.exitcode, 0)
        child = context.Process(target=contender, args=(path, queue))
        child.start()
        self.assertTrue(queue.get(timeout=10))
        child.join(10)
        self.assertEqual(child.exitcode, 0)

    def test_killed_process_releases_leadership_lock(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        path = self.root/'leader.lock'
        child = context.Process(target=hold_until_killed, args=(path, queue))
        child.start()
        try:
            self.assertTrue(queue.get(timeout=10))
            with exclusive(path) as acquired:
                self.assertFalse(acquired)
        finally:
            child.terminate(); child.join(10)
        with exclusive(path) as acquired:
            self.assertTrue(acquired)

    def test_weekly_cutoff_protection_survives_refactor(self):
        from datetime import datetime, timedelta, timezone
        cutoff = datetime(2030, 10, 16, 12, tzinfo=timezone.utc)
        for offset, delay in ((60, 120), (-300, 480)):
            now = cutoff+timedelta(seconds=offset)
            stop = Mock()
            stop.wait.return_value = True  # Simulate shutdown while deferred.
            with patch.object(hosted.threading, 'Thread') as thread, patch.object(hosted, 'run_worker') as worker, patch.object(hosted, 'datetime') as clock:
                hosted.run_leader(self.root, stop)
                scout = next(call.kwargs['args'][1] for call in thread.call_args_list if call.kwargs['name'] == 'automatic-data-updates')
                clock.now.return_value = now
                self.assertEqual(scout(), 'not_due')
                stop.wait.assert_called_once_with(delay)
                worker.assert_not_called()

    def test_startup_is_idempotent(self):
        with patch.dict('os.environ', {'TREND_FINDAH_AUTO_UPDATE':'1'}), patch.object(hosted, '_SCHEDULER_THREAD', None), patch.object(hosted.threading, 'Thread') as factory:
            factory.return_value.is_alive.return_value = True
            hosted.start_scheduler(); hosted.start_scheduler()
            self.assertEqual(factory.call_count, 1)
            factory.return_value.start.assert_called_once()

    def test_restart_deduplicates_then_recovers_missed_run(self):
        action = Mock(return_value=0)
        self.assertEqual(due_job(self.root, 'job', action, 600, 20, lambda:100), 0)
        self.assertEqual(due_job(self.root, 'job', action, 600, 20, lambda:101), 'not_due')
        self.assertEqual(due_job(self.root, 'job', action, 600, 20, lambda:900), 0)
        self.assertEqual(action.call_count, 2)

    def test_interrupted_job_recovers_after_lease(self):
        with self.assertRaises(KeyboardInterrupt):
            due_job(self.root, 'job', Mock(side_effect=KeyboardInterrupt), 600, 20, lambda:100)
        action = Mock(return_value=0)
        self.assertEqual(due_job(self.root, 'job', action, 600, 20, lambda:110), 'not_due')
        self.assertEqual(due_job(self.root, 'job', action, 600, 20, lambda:181), 0)
        action.assert_called_once()

    def test_contention_retries_in_sixty_seconds(self):
        action = Mock(side_effect=[75, 0])
        due_job(self.root, 'job', action, 21600, 600, lambda:100)
        self.assertEqual(due_job(self.root, 'job', action, 21600, 600, lambda:159), 'not_due')
        self.assertEqual(due_job(self.root, 'job', action, 21600, 600, lambda:160), 0)

    def test_overlapping_job_cannot_execute_action(self):
        with exclusive(self.root/'logs/job.job.lock'):
            action = Mock()
            self.assertEqual(due_job(self.root, 'job', action, 600, 20), 75)
            action.assert_not_called()

    def test_atomic_status_interruption_preserves_previous_file(self):
        path = self.root/'status.json'
        atomic_json(path, {'old':True})
        with patch('scheduler_runtime.os.replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): atomic_json(path, {'new':True})
        self.assertEqual(json.loads(path.read_text()), {'old':True})
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_existing_sealer_interruption_reproduces_separate_blocker(self):
        from datetime import datetime, timezone
        from scout4.shadow import seal
        path = self.root/'forecast.json'
        record = {'kickoff_utc':'2030-10-20T17:00:00Z',
                  'decision_cutoff_utc':'2030-10-19T12:00:00Z'}
        def interrupted_dump(record, stream, **kwargs):
            stream.write('{')
            raise OSError('interrupted write')
        with patch('scout4.shadow.json.dump', side_effect=interrupted_dump):
            with self.assertRaises(OSError):
                seal(path, record, lambda:datetime(2030,10,19,13,tzinfo=timezone.utc))
        self.assertEqual(path.read_bytes(), b'{')
        # A later attempt preserves that partial file, confirming the blocker.
        self.assertFalse(seal(path, record))

    def test_main_status_cannot_remain_healthy_after_scheduler_failure(self):
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        atomic_json(self.root/'logs/auto_update_status.json', {'state':'ok'})
        hosted.scheduler_loop('automatic-data-updates', Mock(side_effect=TimeoutError('timeout')), 30, self.root, stop)
        status = json.loads((self.root/'logs/auto_update_status.json').read_text())
        self.assertEqual(status['state'], 'needs attention')
        self.assertIn('checked_at', status)

    def test_legacy_success_migrates_without_immediate_duplicate(self):
        atomic_json(self.root/'logs/auto_update_status.json', {'state':'ok','finished':'1970-01-01T00:01:40+00:00'})
        action = Mock()
        self.assertEqual(due_job(self.root, 'automatic-data-updates', action, 600, 20, lambda:101), 'not_due')
        action.assert_not_called()

    def test_leadership_standby_takes_over_after_leader_stops(self):
        first_stop, second_stop = threading.Event(), threading.Event()
        entered = []
        elected = threading.Event()
        def leader(root, stop):
            entered.append(stop)
            elected.set()
            stop.wait(10)
        with patch.object(hosted, 'run_leader', side_effect=leader):
            first = threading.Thread(target=hosted.leadership_loop, args=(self.root, first_stop))
            second = threading.Thread(target=hosted.leadership_loop, args=(self.root, second_stop))
            first.start()
            self.assertTrue(elected.wait(2)); elected.clear()
            second.start()
            first_stop.set(); first.join(2)
            self.assertTrue(elected.wait(7))
            second_stop.set(); second.join(2)
        self.assertEqual(entered, [first_stop, second_stop])

    def test_expert_whole_job_lock_prevents_work_and_status_write(self):
        import expert_automation
        with exclusive(self.root/'logs/auto_update.lock'):
            with patch.object(expert_automation, '_execute_once') as execute:
                self.assertEqual(expert_automation.execute_once(root=self.root)['state'], 'lock_busy')
                execute.assert_not_called()
        self.assertFalse((self.root/'logs/expert_automation_status.json').exists())


if __name__ == '__main__': unittest.main()
