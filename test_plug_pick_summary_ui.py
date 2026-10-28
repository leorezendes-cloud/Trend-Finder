"""Render the standalone Plug status section for every ATS/O-U combination."""
import re
import unittest
from pathlib import Path
from jinja2 import Environment, StrictUndefined

TEMPLATE=Path(__file__).resolve().parent/'templates/expert_dashboard.html'

def render_status(*,ats='stay_away',ou='stay_away',ats_side='CIN',ats_line=-2,ou_pick='Over 49'):
    text=TEMPLATE.read_text()
    start=text.index('{% set ats_decision =')
    end=text.index('</div>',start)+len('</div>')
    fragment=text[start:end]
    game=dict(away_team='CIN',home_team='BAL')
    ats_decision=dict(side=ats_side,away_line=ats_line) if ats=='selected' else None
    item=dict(plug_ats_status=ats,plug_ats_decision=ats_decision,
              plug_ou_status=ou,plug_ou_pick=ou_pick if ou=='selected' else None,
              plug_ou_review=False,upcoming=True)
    return Environment(autoescape=True,undefined=StrictUndefined).from_string(fragment).render(item=item,g=game)

class PlugTopPicksPresentationTests(unittest.TestCase):
    def test_both_selected_share_one_heading_and_exact_lines(self):
        html=render_status(ats='selected',ou='selected')
        self.assertEqual(html.count("The Plug\'s Top Picks:"),1)
        self.assertIn('ATS</strong> – (CIN -2)',html)
        self.assertIn('O/U</strong> – (Over 49)',html)
        self.assertNotIn('Stay Away',html)

    def test_selected_spread_from_home_team_uses_opposite_quote(self):
        html=render_status(ats='selected',ou='stay_away',ats_side='BAL',ats_line=-2)
        self.assertIn('ATS</strong> – (BAL +2)',html)
        self.assertIn('Plug O/U: Stay Away',html)
        self.assertEqual(html.count("The Plug\'s Top Picks:"),1)

    def test_only_total_selected(self):
        html=render_status(ats='stay_away',ou='selected')
        self.assertIn('O/U</strong> – (Over 49)',html)
        self.assertIn('Plug ATS: Stay Away',html)
        self.assertNotIn('ATS</strong> –',html)

    def test_both_stay_away_no_heading(self):
        html=render_status()
        self.assertNotIn('Top Picks:',html)
        self.assertEqual(html.count('Stay Away'),2)
        self.assertEqual(html.count('plug-market-muted'),2)

    def test_pending_does_not_claim_stay_away(self):
        html=render_status(ats='pending',ou='awaiting_weekly_selection')
        self.assertIn('Plug ATS: Awaiting weekly picks',html)
        self.assertIn('Plug O/U: Awaiting weekly shortlist',html)
        self.assertNotIn('Stay Away',html)
        self.assertNotIn('Top Picks:',html)

if __name__=='__main__':
    unittest.main()
