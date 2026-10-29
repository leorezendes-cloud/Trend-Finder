"""Render the standalone Plug status section for every ATS/O-U combination."""
import re
import unittest
from pathlib import Path
from jinja2 import Environment, StrictUndefined, FileSystemLoader

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
    return Environment(autoescape=True,undefined=StrictUndefined,loader=FileSystemLoader(TEMPLATE.parent)).from_string(fragment).render(item=item,g=game)

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
        self.assertNotIn('Stay Away',html)
        self.assertNotIn('O/U</strong>',html)
        self.assertEqual(html.count("The Plug\'s Top Picks:"),1)

    def test_only_total_selected(self):
        html=render_status(ats='stay_away',ou='selected')
        self.assertIn('O/U</strong> – (Over 49)',html)
        self.assertNotIn('Stay Away',html)
        self.assertNotIn('ATS</strong> –',html)

    def test_both_stay_away_no_heading(self):
        html=render_status()
        self.assertNotIn('Top Picks:',html)
        self.assertNotIn('Stay Away',html)
        self.assertNotIn('plug-top-picks',html)

    def test_pending_does_not_claim_stay_away(self):
        html=render_status(ats='pending',ou='awaiting_weekly_selection')
        self.assertNotIn('Awaiting weekly',html)
        self.assertNotIn('Stay Away',html)
        self.assertNotIn('Top Picks:',html)

class DynamicSelectedPresentationTests(unittest.TestCase):
    def render(self,name,item):
        return Environment(autoescape=True,undefined=StrictUndefined,
                           loader=FileSystemLoader(TEMPLATE.parent)).get_template(name).render(item=item)

    def test_dynamic_only_selected_total_is_active_and_pending_result_is_hidden(self):
        item=dict(plug_dynamic_official=True,plug_ats_status='stay_away',plug_ou_status='selected',
                  plug_dynamic_card=dict(ats='Stay Away',ou='Under 48.5',note='Final selections lock at kickoff.'),
                  plug_ats_result=None,plug_ou_result='Pending')
        html=self.render('_plug_dynamic_official.html',item)
        self.assertIn('Under 48.5',html)
        self.assertIn('plug-selected-pick',html)
        self.assertNotIn('Stay Away',html)
        self.assertNotIn('ATS:</strong>',html)
        self.assertNotIn('Pending',html)
        self.assertNotIn('plug-settled-grade',html)

    def test_dynamic_no_selection_has_no_green_pick_section(self):
        item=dict(plug_dynamic_official=True,plug_ats_status='stay_away',plug_ou_status='stay_away')
        self.assertEqual(self.render('_plug_dynamic_official.html',item).strip(),'')

    def test_review_notice_stays_neutral_and_is_not_a_pick(self):
        item=dict(plug_dynamic_official=True,plug_dynamic_review=True,
                  plug_ats_status='review',plug_ou_status='review')
        html=self.render('_plug_dynamic_official.html',item)
        self.assertIn('awaiting verified evidence',html)
        self.assertNotIn('plug-selected-pick',html)

    def test_saved_pending_results_have_no_visible_section(self):
        for final in (None,dict(away=28,home=20)):
            item=dict(final_score=final,completed_grades=dict(scout_ats='Pending',plug_total='Pending'),
                      plug_ats_result='Pending')
            self.assertEqual(self.render('_plug_saved_results.html',item).strip(),'')

    def test_saved_confirmed_result_stays_visible_without_pending_or_green_wrapper(self):
        item=dict(final_score=dict(away=28,home=20),
                  completed_grades=dict(scout_ats='Loss',plug_total='Pending'),plug_ats_result='Win')
        html=self.render('_plug_saved_results.html',item)
        self.assertIn('Saved results',html)
        self.assertIn('plug-grade-loss',html)
        self.assertIn('plug-grade-win',html)
        self.assertNotIn('Pending',html)
        self.assertNotIn('plug-ou-selection',html)

if __name__=='__main__':
    unittest.main()
