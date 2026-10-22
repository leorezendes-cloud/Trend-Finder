"""Synthetic, read-only presentation checks for saved predictions and gated reports."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import g, render_template, render_template_string
from app import app
from expert_beta import Store, matchup_prediction
from expert_beta_cli import feature
from test_expert_beta import fixture, report


class PredictionCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = patch.dict(app.config, EXPERT_BETA_ENABLED=True,
                                 EXPERT_BETA_STORE=self.tmp.name, EXPERT_BETA_ALL_FREE=False)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.scout = fixture()
        self.scout['total']['side'] = 'Under'  # Scores sum to 45; never infer this pick.
        expert = report(self.scout)
        expert.update(ats_side='JAX', total_side='Over', disagreement_reason='Fixture only')
        Store(Path(self.tmp.name)).append(self.scout, expert=expert)
        other = fixture('CHI', 'ATL')
        Store(Path(self.tmp.name)).append(other, expert=report(other))

    def card(self, featured=True):
        if featured:
            feature(Path(self.tmp.name), 2026, 1, ['HOU-JAX', 'CHI-ATL'])
        return matchup_prediction(self.scout['game']['game_id'])

    def panel(self, item):
        return render_template_string("{% from '_expert_panel.html' import expert_panel %}{{ expert_panel(item) }}", item=item)

    def test_shared_panel_saved_expert_lines_and_collapsed_report_link(self):
        with app.test_request_context('/'):
            g.member = None
            html = self.panel(self.card())
        self.assertIn('JAX -3', html)
        self.assertIn('Over 45', html)
        self.assertIn('PRIVATE_SUMMARY', html)
        self.assertNotIn(' open', html)
        self.assertLess(html.index('<details'), html.index('Read Full Expert Analysis'))
        self.assertLess(html.index('Read Full Expert Analysis'), html.index('</details>'))

    def test_restricted_report_does_not_expose_picks_or_summary(self):
        with app.test_request_context('/'):
            g.member = None
            html = self.panel(self.card(featured=False))
        self.assertNotIn('PRIVATE_SUMMARY', html)
        self.assertNotIn('JAX -3', html)
        self.assertNotIn('Read Full Expert Analysis', html)
        self.assertIn('Premium Expert report', html)

    def test_missing_report_pending(self):
        with app.test_request_context('/'):
            self.assertIn('Expert Analysis Coming Soon', self.panel(None))

    def test_comparison_uses_independent_total_and_separates_expert(self):
        with app.test_request_context('/'):
            g.member = None
            item = self.card()
            game = dict(self.scout['game'], away_score='', home_score='')
            html = render_template('matchup.html', game=game, prediction_item=item,
                forecast=None, teams=[], season=2026, week=1, manifest={},
                inline_picks=[], is_final=False, box_score=None)
        left, right = html.split('<section class="prediction-expert-panel">')
        self.assertIn('HOU +3', left)
        self.assertIn('HOU by 3.0 points', left)
        self.assertIn('Under 45', left)
        self.assertIn('JAX -3', right)
        self.assertIn('Over 45', right)
        self.assertNotIn('against the saved spread', html)
        self.assertNotIn('Experimental model estimate', html)

    def test_legacy_total_is_saved_not_inferred_and_missing_total_is_pending(self):
        game = dict(self.scout['game'], away_score='', home_score='')
        forecast = dict(components={'Blend': {'pick': 'JAX', 'away_margin': 8}},
            quote={'line': 3}, decision_cutoff_utc=self.scout['cutoff_utc'],
            totals={'prediction': {'lean': 'Under'}, 'quote': {'line': 51.5}})
        with app.test_request_context('/'):
            g.member = None
            def render():
                return render_template('matchup.html', game=game, prediction_item=None,
                    forecast=forecast, teams=[], season=2026, week=1, manifest={},
                    inline_picks=[], is_final=False, box_score=None)
            html = render()
            self.assertIn('JAX -3', html)
            self.assertIn('Under 51.5', html)
            forecast['totals'] = None
            self.assertIn('<strong>Over/Under:</strong> Forecast pending', render())

    def test_public_beta_preserves_approved_access_without_exposing_missing_reports(self):
        with app.test_request_context('/'):
            g.member = None
            with patch.dict(app.config, EXPERT_BETA_ALL_FREE=True):
                html = self.panel(self.card(featured=False))
                self.assertIn('PRIVATE_SUMMARY', html)
                self.assertIn('JAX -3', html)
                self.assertIn('Expert Analysis Coming Soon', self.panel(None))

    def test_pending_draft_is_not_rendered(self):
        from expert_beta import validate_expert
        draft = report(self.scout)
        draft['review_status'] = 'pending'
        with self.assertRaises(ValueError):
            validate_expert(draft, self.scout)


if __name__ == '__main__':
    unittest.main()
