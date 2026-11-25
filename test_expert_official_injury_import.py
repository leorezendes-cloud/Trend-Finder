import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from expert_official_injury_import import import_verified, validate


class VerifiedImportTests(unittest.TestCase):
    def report(self):
        now = datetime.now(timezone.utc)
        return dict(season=2026, week=12, game_id="2026_12_GB_LA",
                    team="GB", source_url="https://www.nfl.com/injuries/league/2026/REG12",
                    published_at=(now-timedelta(hours=2)).isoformat(),
                    observed_at=(now-timedelta(hours=1)).isoformat(),
                    kickoff_utc=(now+timedelta(days=2)).isoformat(),
                    players=[dict(name="Example Player", position="QB",
                                  game_status="Questionable", injury="Ankle")])

    def test_atomic_compact_import_and_no_older_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            record = self.report()
            destination = import_verified(record, folder)
            self.assertTrue(destination.is_file())
            self.assertLess(destination.stat().st_size, 32768)
            with self.assertRaises(ValueError):
                import_verified(record, folder)

    def test_reject_post_kickoff(self):
        record = self.report()
        record["kickoff_utc"] = record["published_at"]
        with self.assertRaises(ValueError):
            validate(record)

    def test_reject_unverified_status_and_domain(self):
        record = self.report()
        record["players"][0]["game_status"] = "Healthy"
        with self.assertRaises(ValueError):
            validate(record)
        record = self.report()
        record["source_url"] = "https://example.com/injuries"
        with self.assertRaises(ValueError):
            validate(record)

    def test_reject_unsafe_game_id(self):
        record = self.report()
        record["game_id"] = "../unsafe"
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                import_verified(record, folder)
