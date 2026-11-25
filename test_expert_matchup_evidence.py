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

    def test_five_recent_games_and_season_scoring_observations_are_pregame_only(self):
        dates = ["2026-09-01", "2026-09-08", "2026-09-15",
                 "2026-09-22", "2026-10-06", "2026-10-20"]
        rows = [
            dict(game_id=str(i), season=2026, game_type="REG",
                 gameday=date, away_team="PHI", home_team="NYG",
                 away_score=str(10 + i), home_score="10")
            for i, date in enumerate(dates)
        ]
        rows.append(dict(game_id="future", season=2026, game_type="REG",
                         gameday="2026-11-03", away_team="PHI", home_team="NYG",
                         away_score="99", home_score="0"))
        self._schedule(rows)
        result = snapshot(self.scout, self.root)
        team = result["team_form"][0]
        self.assertEqual(len(team["recent"]), 5)
        self.assertEqual(team["recent"][0]["score"], "15-10")
        self.assertEqual(team["recent_five_scores"]["games"], 5)
        self.assertEqual(team["season_to_date_scores"]["games"], 6)
        self.assertEqual(team["away_scores"]["games"], 6)
        self.assertIsNone(team["home_scores"])
        self.assertEqual(team["season_to_date_scores"]["points_for_per_game"], 12.5)
        self.assertNotIn("99-0", str(result))

    def test_expected_qb_uses_next_available_depth_chart_option_and_current_injuries(self):
        self.scout["game"].update(game_id="2026_09_JAX_BAL", away_team="JAX", home_team="BAL",
                                  kickoff_utc="2026-11-08T18:00:00+00:00")
        self._schedule([
            dict(game_id="prior", season=2026, game_type="REG", gameday="2026-10-25",
                 away_team="PHI", home_team="NYG", away_score="24", home_score="17"),
        ])
        folder = self.root / "data" / "scout4" / "personnel" / "2026" / "20261104T120000Z"
        folder.mkdir(parents=True)
        observed = "2026-11-04T12:00:00+00:00"
        game = {
            "game_id": "2026_09_JAX_BAL",
            "kickoff_utc": "2026-11-08T18:00:00+00:00",
            "observed_at": observed,
            "personnel": {
                "BAL": {
                    "qb_depth_order": [
                        {"player_name": "Lamar Jackson", "gsis_id": "qb1", "pos_rank": 1},
                        {"player_name": "Tyler Huntley", "gsis_id": "qb2", "pos_rank": 2},
                        {"player_name": "Joe Fagnano", "gsis_id": "qb3", "pos_rank": 3},
                    ],
                    "injury_rows": [
                        {"player_name": "Lamar Jackson", "position": "QB",
                         "report_status": "Out", "report_primary_injury": "Thumb"},
                        {"player_name": "Tyler Huntley", "position": "QB",
                         "report_status": "Out", "report_primary_injury": "Turf Toe"},
                    ],
                    "injury_coverage": "reported rows only",
                    "depth_updated_at": observed,
                    "depth_stale": False,
                },
                "JAX": {
                    "qb_depth_order": [
                        {"player_name": "Trevor Lawrence", "gsis_id": "qb4", "pos_rank": 1},
                    ],
                    "injury_rows": [],
                    "injury_coverage": "unknown",
                    "depth_updated_at": observed,
                    "depth_stale": False,
                },
            },
        }
        (folder / "pregame_evidence.json").write_text(json.dumps({
            "manifest": {"retrieved_at": observed, "source": "NFLverse via nflreadpy"},
            "games": [game],
        }))
        weather_folder = self.root / "data" / "scout4" / "weather" / "20261104T121000Z"
        weather_folder.mkdir(parents=True)
        weather_row = {
            "game_id": "2026_09_JAX_BAL",
            "kickoff_utc": "2026-11-08T18:00:00+00:00",
            "observed_at": "2026-11-04T12:10:00+00:00",
            "source": "Open-Meteo live forecast",
            "stadium": "M&T Bank Stadium",
            "roof_context": "Open-air metadata",
            "request_url": "https://api.open-meteo.com/v1/forecast?fixture=1",
            "hours": [
                {"valid_at_utc": f"2026-11-08T{hour:02d}:00:00+00:00",
                 "temperature_2m": 48, "wind_speed_10m": 12,
                 "wind_gusts_10m": 21, "precipitation": 0.01,
                 "precipitation_probability": 35}
                for hour in range(18, 22)
            ],
            "limitations": ["Outside grid forecast; not measured on-field conditions."],
        }
        (weather_folder / "evidence.json").write_text(json.dumps({"records": [weather_row]}))
        result = snapshot(self.scout, self.root, as_of="2026-11-04T13:00:00+00:00")
        bal = result["personnel"]["teams"]["BAL"]
        self.assertEqual(bal["expected_quarterback"]["name"], "Joe Fagnano")
        self.assertEqual(bal["expected_quarterback"]["depth_rank"], 3)
        self.assertIn("Lamar Jackson", [r["player"] for r in bal["key_injuries"]])
        self.assertIn("Tyler Huntley", [r["player"] for r in bal["key_injuries"]])
        self.assertEqual(bal["snapshot_freshness"], "current")
        self.assertEqual(result["sources"][0]["name"], "nflverse_personnel")
        self.assertEqual(result["weather"]["stadium"], "M&T Bank Stadium")
        self.assertEqual(result["weather"]["hours"][0]["wind_gusts_mph"], 21)
        self.assertEqual(result["weather"]["freshness"], "current")
        self.assertIn("open_meteo_weather", [source["name"] for source in result["sources"]])
        # Expert research observed after Scout's cutoff is valid when still pre-kickoff.
        self.assertGreater(result["personnel"]["observed_at"], self.scout["cutoff_utc"])

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


    def test_large_unrelated_feeds_do_not_accumulate_in_memory(self):
        import gc
        import tracemalloc
        self.test_player_metrics_are_limited_to_historical_games()
        expected = snapshot(self.scout, self.root)
        player_path = self.root / 'data/scout4/players.csv'
        with player_path.open() as stream:
            fields = next(csv.reader(stream))
        with player_path.open('a', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            for i in range(15000):
                writer.writerow(dict(game_id='irrelevant', season=2026, season_type='REG',
                    team='NYG', player_id=str(i % 500), player_display_name='Other '+str(i % 500),
                    passing_yards='1234567890'*20))
        with (self.root/'nfl_games.csv').open('a', newline='') as stream:
            writer = csv.writer(stream)
            for i in range(15000):
                writer.writerow([str(i), 2019, 'REG', '2019-10-01', 'NYG', 'DAL', 21, 17])
        gc.collect()
        tracemalloc.start()
        try:
            actual = snapshot(self.scout, self.root)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(actual, expected)
        self.assertLess(peak, 3*1024*1024, 'Unrelated CSV rows must not accumulate')


if __name__ == "__main__":
    unittest.main()
