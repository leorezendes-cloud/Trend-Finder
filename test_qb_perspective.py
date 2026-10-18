import unittest
from datetime import date
import tempfile
from pathlib import Path
from unittest.mock import patch
from flask import render_template
from app import app
from test_general_research import game
from general_research import research_games
from active_trends import active_highlights

class QBPerspectiveTests(unittest.TestCase):
    def test_qb_record_follows_both_sides(self):
        rows=[game('a',home_qb_name='Test QB',away_qb_name='Other'),
              game('b',away_qb_name='Test QB',home_qb_name='Other')]
        report=research_games(rows,filters={'qb_name':'Test QB'})
        qb=next(r for r in report['records'] if r['label']=='Test QB — All games')
        self.assertEqual((qb['wins'],qb['losses']),(1,1))
        for location,expected in [('home',0),('away',1)]:
            r=research_games(rows,filters={'qb_name':'Test QB'},location=location)
            q=next(q for q in r['records'] if q['label']=='Test QB — '+location.title())
            self.assertEqual((q['games'],q['wins']),(1,expected))

    def test_total_streak_crosses_seasons_and_push_breaks_it(self):
        rows=[game(str(i),season='2025' if i<2 else '2026',gameday=f'2025-12-{20+i:02}' if i<2 else f'2026-10-{10+i:02}',
                   home_qb_name='Test QB',away_qb_name='',total_line='40') for i in range(5)]
        highlights=active_highlights(rows,date(2026,10,18))
        qb=next(h for h in highlights if h.get('qb_name')=='Test QB')
        self.assertEqual((qb['streak'],qb['outcome']),(5,'Over'))
        rows[-1]['total_line']='44'
        self.assertFalse(any(h.get('qb_name')=='Test QB' for h in active_highlights(rows,date(2026,10,18))))

    def test_qb_ats_flips_with_team_side_and_preserves_missing_lines(self):
        rows=[game('away',away_qb_name='Test QB',home_qb_name='Other',spread_line='3'),
              game('home',home_qb_name='Test QB',away_qb_name='Other',spread_line='3'),
              game('missing',home_qb_name='Test QB',away_qb_name='Other',spread_line='')]
        report=research_games(rows,filters={'qb_name':'Test QB'})
        record=next(r for r in report['records'] if r['label'].startswith('Test QB — '))
        self.assertEqual((record['covers'],record['ats_losses'],record['ats_missing']),(1,1,1))
        with app.test_request_context('/'):
            html=render_template('_general_games.html',games=report['matches'],total=3,
                selected_qb='Test QB',evidence_metric='Test QB ATS',preview=True)
        self.assertIn('<th>Test QB team ATS</th>',html)
        self.assertIn('<td>Push</td><td>Cover</td>',html)
        self.assertIn('<td>Push</td><td>Loss</td>',html)

    def test_unknown_total_breaks_streak_and_future_results_do_not_extend_it(self):
        rows=[game(str(i),season='2026',gameday=f'2026-10-{10+i:02}',
                   home_qb_name='Test QB',total_line='40') for i in range(6)]
        rows[-1]['total_line']=''
        self.assertFalse(any(t.get('qb_name')=='Test QB' for t in active_highlights(rows,date(2026,10,18))))
        rows[-1]['total_line']='40';rows[-1]['gameday']='2026-10-19'
        qb=next(t for t in active_highlights(rows,date(2026,10,18)) if t.get('qb_name')=='Test QB')
        self.assertEqual(qb['streak'],5)

    def test_cache_signature_tracks_verified_qb_corrections(self):
        from active_trends import qb_source_signature
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'games.csv'
            before=qb_source_signature(path)
            (root/'research_qb_corrections.csv').write_text('game_id,side,qb_name\n')
            self.assertNotEqual(before,qb_source_signature(path))
            before=qb_source_signature(path)
            (root/'data/research_qbs').mkdir(parents=True)
            (root/'data/research_qbs/verified.json').write_text('{"games":{}}')
            self.assertNotEqual(before,qb_source_signature(path))

    def test_qb_search_displays_own_record_without_prominent_notice(self):
        rows=[game('a',home_qb_name='Josh Allen',away_qb_name='Other'),
              game('b',away_qb_name='Josh Allen',home_qb_name='Other')]
        with patch('general_research.research_rows',return_value=rows):
            response=app.test_client().get('/trend-finder?research_view=general&run=analyze&qb_name=Josh+Allen')
        self.assertEqual(response.status_code,200)
        self.assertIn('Josh Allen — All games',response.text)
        self.assertNotIn('QB data check:',response.text)

    def test_total_card_links_to_same_all_season_regular_game_scope(self):
        rows=[game(str(i),season='2026',gameday=f'2026-10-{10+i:02}',
                   home_qb_name='Test QB',total_line='40') for i in range(5)]
        highlights=active_highlights(rows,date(2026,10,18))
        with app.test_request_context('/'):
            html=render_template('_active_trends.html',active_highlights=highlights)
        self.assertIn('5 consecutive overs',html)
        self.assertIn('Game totals in Test QB starts, across seasons.',html)
        self.assertIn('qb_name=Test+QB',html)
        self.assertIn('game_type=REG',html)
