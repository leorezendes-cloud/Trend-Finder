import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from expert_official_injury_batch import upcoming_games, collect
from expert_matchup_evidence import _observed_injury_context


class InjuryBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schedule = self.root / "nfl_games.csv"
        self.schedule.write_text(
            "game_id,season,week,game_type,gameday,gametime,away_team,home_team\n"
            "2026_12_GB_LA,2026,12,REG,2026-11-26,20:00,GB,LA\n"
            "2026_12_CHI_DET,2026,12,REG,2026-11-26,13:00,CHI,DET\n"
        )
        self.now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)

    def test_schedule_exact_and_one_weekly_fetch(self):
        games = upcoming_games(self.schedule, self.now)
        self.assertEqual(len(games), 2)
        calls = []
        def fetch(season, week):
            calls.append((season, week))
            return {"season": season, "week": week,
                    "source_url": "https://www.nfl.com/injuries/league/2026/REG12",
                    "retrieved_at": "2026-11-25T12:00:00+00:00",
                    "unverified_table_candidates": [
                        {"team": team, "team_label_confidence": "exact_unique_heading",
                         "verified": False, "players": [{"name": "Test Player", "game_status": "Out"}]}
                        for team in ("GB", "LA", "CHI", "DET")]}
        with patch("expert_official_injury_batch.preflight_game", side_effect=lambda page, game, cutoff: {
            "structural_preflight_passed": True, "issues": [],
            "game_id": game["game_id"], "teams": [game["away_team"], game["home_team"]]}):
            result = collect(self.schedule, self.root / "data" / "expert_official_observations",
                             self.now, fetch)
        self.assertEqual(calls, [(2026, 12)])
        self.assertEqual(len([r for r in result if "saved" in r]), 2)
        scout = {"game": games[1]}
        found, sources = _observed_injury_context(
            scout, self.root, datetime(2026, 11, 25, 13, tzinfo=timezone.utc))
        self.assertEqual(set(found), {"GB", "LA"})
        self.assertIsNone(found["GB"]["source_published_at"])
        self.assertEqual(found["GB"]["verification_status"], "observed_official_page_unverified")
        self.assertEqual(len(sources), 2)
        hidden, _ = _observed_injury_context(
            scout, self.root, datetime(2026, 11, 25, 11, tzinfo=timezone.utc))
        self.assertFalse(hidden)
        hidden, _ = _observed_injury_context(
            scout, self.root, datetime(2026, 11, 27, tzinfo=timezone.utc))
        self.assertFalse(hidden)

    def test_duplicate_schedule_rejected(self):
        with self.schedule.open("a") as stream:
            stream.write("2026_12_GB_LA,2026,12,REG,2026-11-26,20:00,GB,LA\n")
        with self.assertRaises(ValueError):
            upcoming_games(self.schedule, self.now)


if __name__ == "__main__":
    unittest.main()
