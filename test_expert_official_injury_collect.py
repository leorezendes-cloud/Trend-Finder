import io
import unittest
from unittest.mock import Mock, MagicMock
from expert_official_injury_collect import fetch_official_injury_page


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

    def test_reject_invalid_week(self):
        with self.assertRaises(ValueError):
            fetch_official_injury_page(2026, 0)
