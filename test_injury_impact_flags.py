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
        self.assertNotIn("Research context only. The official score, selections, and grades remain unchanged.", partial)
        for name in ("sunday_results.html", "matchup.html", "_general_games.html",
                     "_home_games_board.html", "games_board.html", "game_center.html"):
            self.assertIn("_game_injury_impact_flag.html",
                          (root / "templates" / name).read_text(), name)

    def test_plug_flag_precedes_completed_game_disclosure(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent
        template = (root / "templates/expert_dashboard.html").read_text()
        flag = template.index("{% include '_game_injury_impact_flag.html' %}")
        disclosure = template.index('<details class="plug-completed-details">')
        self.assertLess(flag, disclosure)
        css = (root / "static/expert_beta.css").read_text()
        self.assertIn(".plug-completed-body * { text-align:left;", css)
        self.assertIn("padding: 16px 20px 20px !important", css)
        injury_css = (root / "static/injury_impact.css").read_text()
        self.assertIn(".weekly-injury-impact .weekly-injury-impact-body", injury_css)
        self.assertIn("padding:20px 24px !important", injury_css)
        self.assertIn("background-color:#111827 !important", injury_css)
        self.assertIn(".plug-completed-body p,", css)
        self.assertNotIn("plug-completed-details > summary {\n  padding:", css)

    def test_home_injury_flag_is_outside_live_refreshed_badge_container(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent
        template = (root / "templates/_home_games_board.html").read_text()
        marks_end = template.index('</div>', template.index('class="tf-board-marks"'))
        injury = template.index('class="tf-board-injury"')
        self.assertGreater(injury, marks_end)
        css = (root / "static/games_board.css").read_text()
        self.assertIn(".tf-board-item > .tf-board-injury", css)
        self.assertIn("right:10px", css)
        self.assertIn("bottom:9px", css)
        self.assertIn(".tf-board-home .tf-board-item > .tf-board-injury .game-injury-impact-body {", css)
        self.assertIn("background:#111827 !important", css)
        self.assertIn(".weekly-injury-impact .weekly-injury-impact-body", (root / "static/injury_impact.css").read_text())
        self.assertIn("right:0 !important", css)
        self.assertNotIn(".tf-board-home .tf-board-item > .tf-board-injury details.game-injury-impact > summary", css)
        self.assertIn("@media(max-width:720px)", css)
        self.assertIn("position:relative", css[css.rfind("@media(max-width:720px)"):])
        self.assertIn("margin:8px 0 0", css[css.rfind("@media(max-width:720px)"):])

    def test_unrelated_games_are_not_flagged(self):
        self.assertIsNone(for_game("2026_08_BUF_BAL"))
        self.assertIsNone(for_game("2026_08_NE_CHI"))
        self.assertIsNone(for_game(None))


if __name__ == "__main__":
    unittest.main()
