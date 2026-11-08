"""Read-only retention preview regression checks (no production data)."""
import csv
import tempfile
import unittest
from pathlib import Path

from public_money_retention import preview
from public_money import FIELDS

class PublicMoneyRetentionTests(unittest.TestCase):
    def test_preserves_market_and_split_transitions_in_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "public_money_snapshots.csv"
            base = dict.fromkeys(FIELDS, "")
            base.update(game_id="game", kickoff_utc="2026-11-08T18:00:00+00:00",
                        away_team="ARI", home_team="SEA", sportsbook="DraftKings",
                        market="Spread", side_a="ARI", side_b="SEA", line_a="7",
                        line_b="-7", odds_a="-110", odds_b="-110",
                        handle_a="64", handle_b="36", bets_a="60", bets_b="40")
            rows = []
            for time, changes in (
                ("2026-11-06T10:00:00+00:00", {}),
                ("2026-11-06T10:05:00+00:00", {}),
                ("2026-11-06T10:10:00+00:00", {"handle_a": "65", "handle_b": "35"}),
                ("2026-11-06T10:15:00+00:00", {"handle_a": "65", "handle_b": "35"}),
                ("2026-11-07T10:00:00+00:00", {"handle_a": "65", "handle_b": "35"}),
                ("2026-11-07T10:05:00+00:00", {"line_a": "6.5", "line_b": "-6.5",
                                                 "handle_a": "65", "handle_b": "35"}),
            ):
                rows.append(dict(base, captured_at_utc=time, **changes))
            with p.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            original = p.read_bytes()
            result = preview(p)
            self.assertEqual(result["rows"], 6)
            self.assertEqual(result["groups"], 1)
            self.assertEqual(result["changed_observations"], 2)
            self.assertEqual(result["illustrative_retained_rows"], 4)
            self.assertEqual(result["illustrative_redundant_rows"], 2)
            self.assertEqual(p.read_bytes(), original)

if __name__ == "__main__":
    unittest.main()
