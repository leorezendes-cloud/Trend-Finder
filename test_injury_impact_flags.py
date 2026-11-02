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

    def test_shared_completed_game_flag_is_used_by_score_surfaces(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent
        partial = (root / "templates/_game_injury_impact_flag.html").read_text()
        self.assertIn("injury_impact_for_game(game.game_id)", partial)
        for name in ("sunday_results.html", "matchup.html", "_general_games.html",
                     "_home_games_board.html", "games_board.html", "game_center.html"):
            self.assertIn("_game_injury_impact_flag.html",
                          (root / "templates" / name).read_text(), name)

    def test_unrelated_games_are_not_flagged(self):
        self.assertIsNone(for_game("2026_08_BUF_BAL"))
        self.assertIsNone(for_game("2026_08_NE_CHI"))
        self.assertIsNone(for_game(None))


if __name__ == "__main__":
    unittest.main()
