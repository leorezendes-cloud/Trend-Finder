"""Read-only regression checks for lightweight page rendering under load."""
import csv
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint, Flask

from hosted_memory import install_memory_gate
from market_views import read
from site_week import current_site_week, _cached_current_site_week


class SitePerformanceAuditTests(unittest.TestCase):
    def test_week_label_reuses_parse_and_invalidates_on_week_and_file_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nfl_games.csv'
            with path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=('game_type', 'season', 'week', 'gameday', 'gametime'))
                writer.writeheader()
                writer.writerows([
                    {'game_type': 'REG', 'season': 2030, 'week': 6, 'gameday': '2030-10-20', 'gametime': '13:00'},
                    {'game_type': 'REG', 'season': 2030, 'week': 7, 'gameday': '2030-10-27', 'gametime': '13:00'},
                ])
            week6 = datetime(2030, 10, 16, 12, 1, tzinfo=timezone.utc)
            week7 = datetime(2030, 10, 23, 12, 1, tzinfo=timezone.utc)
            _cached_current_site_week.cache_clear()
            with patch('market_views.read', wraps=read) as loader:
                self.assertEqual(current_site_week(path, week6), (2030, 6))
                self.assertEqual(current_site_week(path, week6), (2030, 6))
                self.assertEqual(loader.call_count, 1)
                self.assertEqual(current_site_week(path, week7), (2030, 7))
                self.assertEqual(loader.call_count, 2)
                stat = path.stat()
                # Replace with a new same-size value to simulate an in-place update.
                data = path.read_text().replace('2030-10-27', '2030-10-28')
                path.write_text(data)
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
                self.assertEqual(current_site_week(path, week7), (2030, 7))
                self.assertEqual(loader.call_count, 3)
            self.assertLessEqual(_cached_current_site_week.cache_info().currsize, 2)

    def test_missing_schedule_has_no_week(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(current_site_week(Path(directory) / 'missing.csv'))

    def test_leaderboard_remains_accessible_during_heavy_analytics(self):
        app = Flask(__name__)
        entered, release = threading.Event(), threading.Event()

        @app.get('/expensive')
        def expensive():
            entered.set()
            release.wait(3)
            return 'complete'

        huddle = Blueprint('huddle_leaderboard', __name__, url_prefix='/community/leaderboard')

        @huddle.get('/')
        def board():
            return 'standings'

        app.register_blueprint(huddle)
        install_memory_gate(app)

        def slow_request():
            with app.test_client() as client:
                return client.get('/expensive').status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(slow_request)
            try:
                self.assertTrue(entered.wait(2))
                start = time.monotonic()
                with app.test_client() as client:
                    response = client.get('/community/leaderboard/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, b'standings')
                self.assertLess(time.monotonic() - start, 0.8)
            finally:
                release.set()
            self.assertEqual(running.result(timeout=3), 200)


if __name__ == '__main__':
    unittest.main()
