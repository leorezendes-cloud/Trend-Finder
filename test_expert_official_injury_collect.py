import io
from datetime import datetime, timedelta, timezone
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock, MagicMock
from expert_official_injury_collect import fetch_official_injury_page, injury_table_candidates, label_team_candidates, preflight_game


class CollectorTests(unittest.TestCase):
    def test_bounded_read_only_week_preview(self):
        response = MagicMock()
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.geturl.return_value = "https://www.nfl.com/injuries/league/2026/REG12"
        response.read.return_value = b"<html><h1>Injuries - WEEK 12</h1><p>Packers</p></html>"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        result = fetch_official_injury_page(2026, 12, opener=opener)
        self.assertFalse(result["verified_player_records"])
        self.assertEqual(result["week"], 12)
        self.assertIsNone(result["publication_provenance"]["published_at"])
        self.assertEqual(result["publication_provenance"]["status"], "not_established_from_week_page")
        self.assertTrue(result["publication_provenance"]["retrieved_at_is_not_publication_time"])

    def test_reject_wrong_week(self):
        response = MagicMock()
        response.headers = {"Content-Type": "text/html"}
        response.geturl.return_value = "https://www.nfl.com/injuries/league/2026/REG12"
        response.read.return_value = b"<h1>Injuries - WEEK 11</h1>"
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with self.assertRaises(ValueError):
            fetch_official_injury_page(2026, 12, opener=opener)

    def test_extract_table_without_fabricating_team_or_status(self):
        html = """<table><tr><th>Player</th><th>Position</th><th>Injuries</th>
        <th>Practice Status</th><th>Game Status</th></tr>
        <tr><td>Example Player</td><td>QB</td><td>Ankle</td>
        <td>Limited Participation in Practice</td><td>Questionable</td></tr>
        <tr><td>Another Player</td><td>WR</td><td></td>
        <td>Full Participation in Practice</td><td></td></tr></table>"""
        candidates = injury_table_candidates(html)
        self.assertEqual(len(candidates), 1)
        self.assertIsNone(candidates[0]["team"])
        self.assertFalse(candidates[0]["verified"])
        self.assertEqual(candidates[0]["players"][0]["game_status"], "Questionable")
        self.assertEqual(candidates[0]["players"][1]["game_status"], "Not Reported")

    def test_source_heading_is_preserved_without_team_guessing(self):
        html = """<h3>Packers</h3><table><tr><th>Player</th><th>Position</th>
        <th>Injuries</th><th>Practice Status</th><th>Game Status</th></tr>
        <tr><td>Example Player</td><td>RB</td><td>Finger</td>
        <td>Limited Participation in Practice</td><td>Questionable</td></tr></table>"""
        rows = injury_table_candidates(html)
        self.assertEqual(rows[0]["source_heading"], "Packers")
        self.assertIsNone(rows[0]["team"])
        self.assertFalse(rows[0]["verified"])

    def test_only_unique_exact_headings_receive_candidate_team(self):
        rows = [
            {"source_team_label": "Packers", "team": None, "verified": False},
            {"source_team_label": "Rams", "team": None, "verified": False},
            {"source_team_label": "Packers injury news", "team": None, "verified": False},
        ]
        result = label_team_candidates(rows)
        self.assertEqual([row["team"] for row in result], ["GB", "LA", None])
        self.assertTrue(all(not row["verified"] for row in result))
        duplicate = label_team_candidates([rows[0], rows[0]])
        self.assertEqual([row["team"] for row in duplicate], [None, None])

    def test_date_heading_with_adjacent_team_labels(self):
        header = ("<tr><th>Player</th><th>Position</th><th>Injuries</th>"
                  "<th>Practice Status</th><th>Game Status</th></tr>")
        player = ("<tr><td>Example Player</td><td>RB</td><td>Finger</td>"
                  "<td>Limited Participation in Practice</td><td>Questionable</td></tr>")
        html = ("<h3>WEDNESDAY, NOVEMBER 25TH</h3>"
                "<div>GB Packers</div><span>Packers</span><table>" + header + player + "</table>"
                "<span>Rams</span><table>" + header + player + "</table>")
        rows = label_team_candidates(injury_table_candidates(html))
        self.assertEqual([r["source_heading"] for r in rows],
                         ["WEDNESDAY, NOVEMBER 25TH"] * 2)
        self.assertEqual([r["source_team_label"] for r in rows], ["Packers", "Rams"])
        self.assertEqual([r["team"] for r in rows], ["GB", "LA"])
        self.assertTrue(all(not r["verified"] for r in rows))

    def test_ignore_unrecognized_tables(self):
        self.assertEqual(injury_table_candidates(
            "<table><tr><th>Player</th></tr><tr><td>Unknown</td></tr></table>"), [])

    def test_exact_game_preflight_is_never_auto_importable(self):
        now = datetime.now(timezone.utc)
        observed = now - timedelta(minutes=5)
        game = {"season": 2026, "week": 12, "game_id": "2026_12_GB_LA",
                "away_team": "GB", "home_team": "LA",
                "kickoff_utc": (now + timedelta(hours=3)).isoformat()}
        snapshot = {"season": 2026, "week": 12,
                    "source_url": "https://www.nfl.com/injuries/league/2026/REG12",
                    "retrieved_at": observed.isoformat(), "verified_player_records": False,
                    "unverified_table_candidates": [
                        {"team": team, "team_label_confidence": "exact_unique_heading",
                         "verified": False, "players": [{"name": "Example"}]}
                        for team in ("GB", "LA")]}
        result = preflight_game(snapshot, game, now.isoformat())
        self.assertTrue(result["structural_preflight_passed"])
        self.assertFalse(result["eligible_for_automatic_import"])
        self.assertFalse(result["publication_time_verified"])
        snapshot["retrieved_at"] = (now + timedelta(hours=4)).isoformat()
        late = preflight_game(snapshot, game, now.isoformat())
        self.assertFalse(late["structural_preflight_passed"])
        self.assertIn("observed_at_or_after_kickoff", late["issues"])
        snapshot["retrieved_at"] = observed.isoformat()
        snapshot["unverified_table_candidates"][1]["team"] = "CHI"
        missing = preflight_game(snapshot, game, now.isoformat())
        self.assertIn("missing_or_ambiguous_team_LA", missing["issues"])

    def test_compact_cli_exact_game_audit(self):
        from expert_official_injury_collect import main
        now = datetime.now(timezone.utc)
        game = {"game": {"season": 2026, "week": 12, "game_id": "2026_12_GB_LA",
                         "away_team": "GB", "home_team": "LA",
                         "kickoff_utc": (now + timedelta(hours=3)).isoformat()}}
        snapshot = {"season": 2026, "week": 12,
                    "source_url": "https://www.nfl.com/injuries/league/2026/REG12",
                    "retrieved_at": (now - timedelta(minutes=2)).isoformat(),
                    "verified_player_records": False,
                    "preview": ["large preview"],
                    "unverified_table_candidates": [
                        {"team": team, "source_team_label": label,
                         "team_label_confidence": "exact_unique_heading",
                         "verified": False, "players": [{"name": "Example"}]}
                        for team, label in (("GB", "Packers"), ("LA", "Rams"))]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.json"
            path.write_text(json.dumps(game))
            import io
            with patch("sys.argv", ["collector", "--season", "2026", "--week", "12",
                                    "--game-json", str(path), "--as-of", now.isoformat(),
                                    "--compact"]), patch("expert_official_injury_collect.fetch_official_injury_page",
                                                        return_value=snapshot), patch("sys.stdout", new_callable=io.StringIO) as output:
                main()
            result = json.loads(output.getvalue())
        self.assertTrue(result["game_preflight"]["structural_preflight_passed"])
        self.assertFalse(result["game_preflight"]["eligible_for_automatic_import"])
        self.assertEqual(len(result["candidate_summary"]), 2)
        self.assertNotIn("unverified_table_candidates", result)
        self.assertNotIn("preview", result)

    def test_reject_invalid_week(self):
        with self.assertRaises(ValueError):
            fetch_official_injury_page(2026, 0)
