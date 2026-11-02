import unittest

from injury_impact_flags import for_game


class InjuryImpactFlagTests(unittest.TestCase):
    def test_buffalo_baltimore_is_flagged_for_future_totals_research(self):
        flag = for_game("2026_08_BAL_BUF")
        self.assertIsNotNone(flag)
        self.assertEqual(flag["analysis_tag"], "injury_distorted")
        self.assertIn("first offensive snap", flag["details"])
        self.assertIn("Tyler Huntley", flag["details"])
        self.assertIn("Joe Fagnano", flag["details"])

    def test_unrelated_games_are_not_flagged(self):
        self.assertIsNone(for_game("2026_08_BUF_BAL"))
        self.assertIsNone(for_game("2026_08_NE_CHI"))
        self.assertIsNone(for_game(None))


if __name__ == "__main__":
    unittest.main()
