"""UI-only navigation cleanup: keep established research and backtest routes."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

class NavigationConsolidationTests(unittest.TestCase):
    def test_discovery_only_displays_trend_discovery(self):
        html=(ROOT/'templates/trends.html').read_text()
        self.assertNotIn('discovery-upcoming', html)
        self.assertNotIn('matchup-finder', html)
        self.assertIn('Recent hot performance', html)
        self.assertIn('Active ATS streaks', html)
        self.assertIn("url_for('sunday_page')", html)

    def test_removed_finder_does_not_run_its_unused_previews(self):
        source=(ROOT/'app.py').read_text()
        section=source.split('@app.route("/trends")',1)[1].split('@app.route("/trend-details")',1)[0]
        self.assertNotIn('upcoming_previews',section)
        self.assertNotIn('matchup_matches',section)
        self.assertIn('scan_hot_performance',section)
        self.assertIn('scan_active_streaks',section)

    def test_backtests_link_on_historical_page_and_routes_retained(self):
        historical=(ROOT/'templates/sunday.html').read_text()
        nav=(ROOT/'templates/_site_navigation.html').read_text()
        app=(ROOT/'app.py').read_text()
        self.assertIn("url_for('backtest_page')", historical)
        self.assertNotIn('>Backtests</a>',nav)
        self.assertIn('Historical Matchup Trends', historical)
        self.assertIn('@app.route("/backtests")',app)
        self.assertIn('@app.route("/sunday")',app)

if __name__ == '__main__': unittest.main()
