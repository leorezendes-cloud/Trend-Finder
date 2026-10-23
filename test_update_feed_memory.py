"""Offline streaming-equivalence and subprocess-lock integration checks."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from scheduler_runtime import exclusive
import hosted_updates as hosted


class FeedMemoryTests(unittest.TestCase):
    def test_streamed_feed_bytes_match_legacy_null_missing_and_extra_columns(self):
        import polars as pl
        import nflreadpy as nfl
        from scout4.collect import collect
        from scout4.stats import TEAM_METRICS, PLAYER_METRICS
        fields = dict(season=[2026]*3, week=[1,2,3], season_type=['REG']*3,
                      game_id=['one','two','three'], team=['NE']*3, opponent_team=['BUF']*3,
                      passing_yards=[None, -0.0, 123.125], unused=['comma,text','é','x'])
        team = pl.DataFrame(fields)
        player = team.with_columns(pl.lit('p').alias('player_id'), pl.lit('Name').alias('player_name'),
                                  pl.lit(None).alias('player_display_name'), pl.lit('QB').alias('position'))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(nfl, 'load_team_stats', return_value=team), patch.object(nfl, 'load_player_stats', return_value=player):
                result = collect(2026, Path(directory))
            for kind, frame, metrics in [('team',team,TEAM_METRICS),('player',player,PLAYER_METRICS)]:
                identity = ['season','week','season_type','game_id','team','opponent_team']
                if kind == 'player': identity += ['player_id','player_name','player_display_name','position']
                columns = identity+list(metrics)
                expected = io.StringIO(newline='')
                writer = csv.DictWriter(expected, fieldnames=columns)
                writer.writeheader()
                writer.writerows({k:row.get(k) for k in columns} for row in frame.to_dicts())
                raw = (Path(directory)/result['files'][kind]['path']).read_bytes()
                self.assertEqual(raw, expected.getvalue().encode())
                self.assertEqual(result['files'][kind]['rows'], 3)
                self.assertEqual(result['files'][kind]['sha256'], hashlib.sha256(raw).hexdigest())

    def test_locked_pipeline_isolates_feeds_and_passes_the_live_shared_lock(self):
        from types import SimpleNamespace
        from test_prediction_staging import fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'root'; fixture(root)
            (root/'data/scout4/blend').mkdir(parents=True)
            def child(*args, **kwargs):
                fd, = kwargs['pass_fds']
                self.assertGreaterEqual(os.fstat(fd).st_ino, 1)
                with exclusive(root/'logs/auto_update.lock') as acquired:
                    self.assertFalse(acquired)
                self.assertEqual(kwargs['env']['POLARS_MAX_THREADS'], '1')
                self.assertEqual(kwargs['timeout'], 180)
            with patch.object(hosted.subprocess, 'run', side_effect=child) as execute, \
                 patch.object(hosted, 'backup_database'), \
                 patch('qb_verification.refresh_qbs'), patch('scheduled_ats_capture.run', return_value=0), \
                 patch('prediction_staging.run_staged'), patch('plug_publication.publish'), \
                 patch.dict(sys.modules, {'fan_views':SimpleNamespace(prediction_performance=lambda *a:({},[],[]))}), \
                 patch.dict(os.environ, {'TREND_FINDAH_CONTEXT_RESEARCH':'0','TREND_FINDAH_EXPERT_AUTO_DRAFT':'0'}):
                self.assertEqual(hosted.locked_update(root), 0)
            self.assertEqual([call.args[0][2] for call in execute.call_args_list], ['finals','stats'])
            self.assertNotIn('nflreadpy', subprocess.check_output([sys.executable,'-c',
                'import hosted_updates,sys; print("nflreadpy" if "nflreadpy" in sys.modules else "clean")'],text=True))

    def test_child_keeps_lock_after_supervisor_descriptor_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root/'shared.lock').open('a') as stream:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
                child = subprocess.Popen([sys.executable, '-c',
                    'import sys; print("ready",flush=True); sys.stdin.read()'],
                    pass_fds=(stream.fileno(),), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            try:
                with exclusive(root/'shared.lock') as acquired:
                    self.assertFalse(acquired)
            finally:
                child.communicate(timeout=5)
            with exclusive(root/'shared.lock') as acquired:
                self.assertTrue(acquired)

    def test_feed_worker_disables_memory_cache_without_changing_load_arguments(self):
        import update_feed_worker
        from nflreadpy.config import CacheMode
        with patch('nflreadpy.config.update_config') as config, patch('scout4.collect.collect') as collect:
            update_feed_worker.run('stats', Path('/offline'), 2026)
        config.assert_called_once_with(cache_mode=CacheMode.OFF)
        collect.assert_called_once_with(2026, Path('/offline/data/scout4'), reuse_unchanged=True)

    def test_orphan_stalled_feed_deadline_releases_inherited_lock(self):
        import fcntl
        import signal
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'shared.lock'
            with path.open('a') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
                child = subprocess.Popen([sys.executable, '-c',
                    'from update_feed_worker import arm_feed_deadline; '
                    'import sys; arm_feed_deadline(1); print("ready",flush=True); sys.stdin.read()'],
                    pass_fds=(stream.fileno(),), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            try:
                with exclusive(path) as acquired: self.assertFalse(acquired)
                self.assertEqual(child.wait(timeout=4), -signal.SIGALRM)
            finally:
                if child.poll() is None: child.kill(); child.wait()
                child.stdin.close(); child.stdout.close()
            with exclusive(path) as acquired: self.assertTrue(acquired)


if __name__ == '__main__':
    unittest.main()
