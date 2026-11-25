"""Guard shared Expert article layout against duplicated editorial conclusions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent / "templates"


class ExpertPresentationTests(unittest.TestCase):
    def test_both_views_use_same_sections(self):
        for name in ("expert_game.html", "expert_game_mobile.html"):
            body = (ROOT / name).read_text()
            self.assertIn("{% include '_expert_article_sections.html' %}", body)
            self.assertNotIn("Why the Expert differs from The Plug", body)
            self.assertNotIn("<h3>Final verdict</h3>", body)
            self.assertNotIn("Betting assessment:", body)
            self.assertNotIn("Uncertainty:", body)

    def test_scout_comparison_does_not_repeat_frozen_boilerplate(self):
        body = (ROOT / "_expert_article_sections.html").read_text()
        self.assertIn("Where Scout and The Expert Stand", body)
        self.assertIn("Current Scout", body)
        self.assertNotIn("disagreement_reason", body)
        self.assertNotIn("section.text|expert_prose(s.sources) %}{% endif %}", body)


if __name__ == "__main__":
    unittest.main()
