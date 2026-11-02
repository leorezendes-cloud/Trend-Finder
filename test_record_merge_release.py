"""Merged records presentation and independent weekly Plug tally checks."""
import unittest
from pathlib import Path
from unittest.mock import patch
from collections import Counter
from jinja2 import Environment
from fan_views import plug_week_record

ROOT=Path(__file__).resolve().parent

class MergedRecordsTests(unittest.TestCase):
    def test_week_filter_is_independent_and_pushes_are_kept(self):
        rows=[dict(season=2026,week=8,result=r,game_id=str(i))
              for i,r in enumerate(['Win','Loss','Push','Pending'])]
        rows += [dict(season=2026,week=9,result='Loss'),dict(season=2025,week=8,result='Win')]
        picks,total=plug_week_record(rows,2026,8)
        self.assertEqual(len(picks),4)
        self.assertEqual(total,dict(Win=1,Loss=1,Push=1,Pending=1))
        self.assertEqual(plug_week_record([],2026,8),( [], {'Win':0,'Loss':0,'Push':0,'Pending':0}))

    def test_all_weeks_is_union_of_normalized_weekly_receipts(self):
        rows = [
            dict(season="2026", week="6", result="Win", game_id="w6-a"),
            dict(season=2026, week=7, result="Loss", game_id="w7-a"),
            dict(season="2026", week="8", result="Push", game_id="w8-a"),
            dict(season=2026, week=8, result="Pending", game_id="w8-b"),
            dict(season=2025, week=8, result="Win", game_id="old-season"),
            dict(season=2026, week=9, result="Loss", game_id="other-week"),
        ]
        all_picks, all_total = plug_week_record(rows, 2026, None)
        week_picks = [
            plug_week_record(rows, 2026, week)[0]
            for week in (6, 7, 8)
        ]
        self.assertEqual(
            {row["game_id"] for row in all_picks},
            {row["game_id"] for group in week_picks for row in group},
        )
        self.assertEqual(len(all_picks), sum(map(len, week_picks)))
        self.assertEqual(
            all_total,
            dict(Win=1, Loss=1, Push=1, Pending=1),
        )
        self.assertEqual(
            plug_week_record(rows, "2026", "8")[1],
            dict(Win=0, Loss=0, Push=1, Pending=1),
        )

    def test_one_unified_page_and_legacy_url_remain(self):
        nav=(ROOT/'templates/_record_navigation.html').read_text()
        self.assertIn('Scout &amp; The Plug',nav)
        self.assertNotIn('Scout Record</a>',nav)
        self.assertNotIn('Plug Record</a>',nav)
        page=(ROOT/'templates/prediction_results.html').read_text()
        for piece in ('Scout Picks','The Plug Picks','The Expert adds matchup analysis', 'tf-record-board'):
            self.assertIn(piece,page)
        self.assertNotIn('experimental',page.lower())
        route=(ROOT/'expert_beta.py').read_text()
        self.assertIn("url_for('fans.prediction_results', _anchor='plug-record')",route)
        self.assertIn("@bp.route('/the-plug/ats-record')",route)

    def test_shared_navigation_and_no_bad_plug_only_button(self):
        self.assertIn("'_record_navigation.html'",(ROOT/'templates/sunday_results.html').read_text())
        self.assertIn('Scout &amp; The Plug',(ROOT/'templates/_plug_actions.html').read_text())
        self.assertNotIn('The Plug’s Record',(ROOT/'templates/_plug_actions.html').read_text())
        self.assertIn('Scout &amp; The Plug Records',(ROOT/'templates/expert_dashboard.html').read_text())

    def test_jinja_syntax(self):
        env=Environment()
        for p in ('templates/prediction_results.html','templates/_record_navigation.html','templates/sunday_results.html'):
            env.parse((ROOT/p).read_text())

if __name__=='__main__': unittest.main()
