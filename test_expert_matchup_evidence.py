"""No future-game leakage or unbounded evidence in Expert editorial context."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from expert_matchup_evidence import snapshot


class ExpertMatchupEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scout = dict(game=dict(season=2026, away_team="PHI", home_team="WAS"),
                          cutoff_utc="2026-10-31T18:00:00+00:00")

    def tearDown(self):
        self.tmp.cleanup()

    def _schedule(self, entries):
        with (self.root / "nfl_games.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "game_id", "season", "game_type", "gameday",
                "away_team", "home_team", "away_score", "home_score"])
            writer.writeheader()
            writer.writerows(entries)

    def test_missing_schedule_has_no_fabricated_stats(self):
        self.assertEqual(snapshot(self.scout, self.root), {})

    def test_only_prior_completed_games_appear(self):
        self._schedule([
            dict(game_id="prior", season=2026, game_type="REG", gameday="2026-10-20",
                 away_team="PHI", home_team="NYG", away_score="24", home_score="17"),
            dict(game_id="same-day", season=2026, game_type="REG", gameday="2026-10-31",
                 away_team="PHI", home_team="DAL", away_score="30", home_score="20"),
            dict(game_id="future", season=2026, game_type="REG", gameday="2026-11-02",
                 away_team="WAS", home_team="DAL", away_score="40", home_score="10"),
            dict(game_id="unfinished", season=2026, game_type="REG", gameday="2026-10-25",
                 away_team="WAS", home_team="NYG", away_score="", home_score=""),
        ])
        result = snapshot(self.scout, self.root)
        self.assertEqual(result["team_form"][0]["recent"][0]["score"], "24-17")
        self.assertEqual(len(result["team_form"]), 1)
        self.assertNotIn("player_performances", result)
        self.assertEqual(result["cutoff_date_exclusive"], "2026-10-31")

    def test_player_metrics_are_limited_to_historical_games(self):
        self._schedule([
            dict(game_id="prior", season=2026, game_type="REG", gameday="2026-10-20",
                 away_team="PHI", home_team="WAS", away_score="24", home_score="17"),
            dict(game_id="future", season=2026, game_type="REG", gameday="2026-11-02",
                 away_team="PHI", home_team="NYG", away_score="32", home_score="20"),
        ])
        folder = self.root / "data" / "scout4"
        (folder / "2026").mkdir(parents=True)
        with (folder / "players.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "game_id", "season", "season_type", "team", "player_id",
                "player_display_name", "passing_yards", "rushing_yards",
                "receiving_yards", "def_sacks"])
            writer.writeheader()
            writer.writerow(dict(game_id="prior", season=2026, season_type="REG",
                                 team="PHI", player_id="a", player_display_name="Sample Player",
                                 passing_yards="250"))
            writer.writerow(dict(game_id="future", season=2026, season_type="REG",
                                 team="PHI", player_id="b", player_display_name="Future Player",
                                 passing_yards="490"))
        (folder / "2026" / "latest.json").write_text(json.dumps(
            {"files": {"player": {"path": "players.csv"}}}))
        result = snapshot(self.scout, self.root)
        self.assertEqual(len(result["player_performances"]), 1)
        self.assertEqual(result["player_performances"][0]["player"], "Sample Player")


if __name__ == "__main__":
    unittest.main()
