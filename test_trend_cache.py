import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import trend_finder_2 as trends


class TrendCacheTests(unittest.TestCase):
    def test_reuse_independent_records_and_invalidate_all_data_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            games = Path(directory) / 'nfl_games.csv'
            games.write_text('initial')
            trends._cached_basic_trends.cache_clear()
            with patch.object(trends, 'game_file', games), patch.object(
                    trends, '_scan_basic_trends', return_value=[{'sample': 10}]) as scan:
                first = trends.scan_basic_trends(season='2026')
                first[0]['sample'] = 0
                self.assertEqual(trends.scan_basic_trends(season='2026')[0]['sample'], 10)
                self.assertEqual(scan.call_count, 1)
                for filename in ('nfl_games.csv', 'manual_spread_overrides.csv',
                                 'public_money_snapshots.csv'):
                    (Path(directory) / filename).write_text('updated contents')
                    trends.scan_basic_trends(season='2026')
                self.assertEqual(scan.call_count, 4)
                trends.scan_basic_trends(season=(1999, 2025))
                self.assertEqual(scan.call_count, 5)
        trends._cached_basic_trends.cache_clear()
