import csv
import fcntl
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import gameday_stats as stats

class GameDayStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'logs').mkdir()
        with (self.root/'nfl_games.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['gameday','season','game_type']);w.writeheader();w.writerow(dict(gameday='2027-01-10',season='2026',game_type='WC'))
        self.now=datetime(2027,1,11,2,tzinfo=timezone.utc)
    def tearDown(self):self.tmp.cleanup()
    def test_eastern_date_and_postseason_season(self):
        self.assertEqual(2026,stats.game_day_season(self.root,self.now))
        self.assertIsNone(stats.game_day_season(self.root,datetime(2027,1,11,15,tzinfo=timezone.utc)))
    def test_offday_never_spawns(self):
        with patch.object(stats.subprocess,'run') as run:
            self.assertEqual(0,stats.run(self.root,datetime(2027,1,12,tzinfo=timezone.utc)));run.assert_not_called()
    def test_shared_lock_blocks_feed(self):
        with (self.root/'logs/auto_update.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(stats.subprocess,'run') as run:
                self.assertEqual(75,stats.run(self.root,self.now));run.assert_not_called()
    def test_only_feed_workers_and_inherited_lock(self):
        with patch.object(stats.subprocess,'run') as run,patch.object(stats.shutil,'disk_usage',return_value=SimpleNamespace(free=1024**3)):
            self.assertEqual(0,stats.run(self.root,self.now))
            self.assertEqual(['finals','stats'],[c.args[0][2] for c in run.call_args_list])
            for call in run.call_args_list:self.assertTrue(call.kwargs['pass_fds']);self.assertEqual(180,call.kwargs['timeout'])
    def test_recent_full_refresh_skips_duplicate(self):
        p=self.root/'data/scout4/2026/latest.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'retrieved_at':self.now.isoformat()}))
        with patch.object(stats.subprocess,'run') as run,patch.object(stats.shutil,'disk_usage',return_value=SimpleNamespace(free=1024**3)):
            self.assertEqual(0,stats.run(self.root,self.now));run.assert_not_called()
    def test_low_disk_does_not_spawn(self):
        with patch.object(stats.subprocess,'run') as run,patch.object(stats.shutil,'disk_usage',return_value=SimpleNamespace(free=1)):
            with self.assertRaises(RuntimeError):stats.run(self.root,self.now)
            run.assert_not_called()
    def test_identical_feeds_retain_pointer_and_no_extra_snapshot(self):
        import polars as pl
        import nflreadpy as nfl
        from scout4.collect import collect
        team=pl.DataFrame(dict(season=[2026],week=[7],season_type=['REG'],game_id=['g'],team=['NE'],opponent_team=['CHI']))
        player=team.with_columns(pl.lit('p').alias('player_id'),pl.lit('Name').alias('player_name'),pl.lit('Name').alias('player_display_name'),pl.lit('QB').alias('position'))
        out=self.root/'data/scout4'
        with patch.object(nfl,'load_team_stats',return_value=team),patch.object(nfl,'load_player_stats',return_value=player):
            first=collect(2026,out);pointer=out/'2026/latest.json';before=pointer.read_bytes()
            self.assertEqual(first,collect(2026,out,reuse_unchanged=True));self.assertEqual(before,pointer.read_bytes())
            self.assertEqual(1,len([p for p in pointer.parent.iterdir() if p.is_dir()]))
            with patch.object(nfl,'load_team_stats',return_value=team.with_columns(pl.lit(100).alias('passing_yards'))):
                self.assertNotEqual(first,collect(2026,out,reuse_unchanged=True))
            self.assertEqual(2,len([p for p in pointer.parent.iterdir() if p.is_dir()]))
