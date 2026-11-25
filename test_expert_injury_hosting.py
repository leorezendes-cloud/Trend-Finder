"""Regression checks for Render persistence and scheduler wiring."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hosted_updates


class InjuryHostingTests(unittest.TestCase):
    def test_observations_migrate_to_persistent_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            target = Path(tmp) / "persistent"
            (source / "data" / "expert_official_observations" / "2026" / "12").mkdir(parents=True)
            original = source / "data" / "expert_official_observations"
            (original / "2026" / "12" / "example.json").write_text('{"saved":true}')
            with patch.object(hosted_updates, "SOURCE", source):
                hosted_updates.initialize_data(source, target)
            self.assertTrue(original.is_symlink())
            self.assertEqual((original / "2026" / "12" / "example.json").read_text(), '{"saved":true}')
            self.assertEqual((target / "data" / "expert_official_observations" / "2026" / "12" / "example.json").read_text(), '{"saved":true}')
            hosted_updates.initialize_data(source, target)
            self.assertTrue(original.is_symlink())


if __name__ == "__main__":
    unittest.main()
