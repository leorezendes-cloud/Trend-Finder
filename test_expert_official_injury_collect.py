import io
import unittest
from unittest.mock import Mock, MagicMock
from expert_official_injury_collect import fetch_official_injury_page, injury_table_candidates


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

    def test_ignore_unrecognized_tables(self):
        self.assertEqual(injury_table_candidates(
            "<table><tr><th>Player</th></tr><tr><td>Unknown</td></tr></table>"), [])

    def test_reject_invalid_week(self):
        with self.assertRaises(ValueError):
            fetch_official_injury_page(2026, 0)
