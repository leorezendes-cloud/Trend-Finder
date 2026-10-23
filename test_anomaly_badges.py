import csv
import tempfile
import unittest
from pathlib import Path
from flask import Flask, render_template
from anomaly_badges import saved_anomaly_links, _index

class AnomalyBadgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.app=Flask(__name__)
        self.app.add_url_rule('/conspiracy-dungeon', 'conspiracy_dungeon_page', lambda: '')
        self.event=dict(event_id='abc',category='team',event_date='2026-10-22',title='<Saved event>',game_id='2026_07_NE_CHI',status='Confirmed',source_url='https://example.org/event')
        self.write([self.event])
    def tearDown(self):
        self.tmp.cleanup()
        _index.cache_clear()
    def write(self,rows):
        with (self.root/'anomaly_events.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=self.event.keys());writer.writeheader();writer.writerows(rows)
    def links(self,game='2026_07_NE_CHI'):
        with self.app.test_request_context(): return saved_anomaly_links(game,self.root)
    def test_exact_game_only(self):
        self.assertEqual([],self.links('2026_08_NE_CHI'))
        self.assertEqual([],self.links(''))
        self.assertEqual(1,len(self.links()))
    def test_link_targets_saved_event_category_year_anchor(self):
        link=self.links()[0]
        self.assertIn('category=team',link['url']);self.assertIn('anomaly_year=2026',link['url'])
        self.assertTrue(link['url'].endswith('#anomaly-abc'))
    def test_source_change_invalidates_index(self):
        self.links();self.write([dict(self.event,title='Updated saved event')])
        self.assertEqual('Updated saved event',self.links()[0]['title'])
    def test_bad_events_are_ignored(self):
        for change in ({'status':'Pending'},{'category':'invalid'},{'event_date':'bad'},{'source_url':'javascript:alert(1)'},{'event_id':''}):
            self.write([dict(self.event,**change)]);self.assertEqual([],self.links())
    def test_multiple_events_and_reported(self):
        self.write([self.event,dict(self.event,event_id='other',status='Reported')])
        self.assertEqual(2,len(self.links()))
    def test_template_escapes_titles(self):
        with self.app.test_request_context():
            html=render_template('_game_anomaly_flag.html',anomalies=self.links())
        self.assertIn('&lt;Saved event&gt;',html);self.assertNotIn('<Saved event>',html)
        self.assertNotIn(' open',html)
    def test_research_games_link_exact_event_without_nested_summary(self):
        self.app.jinja_env.globals['saved_anomaly_links'] = lambda game: saved_anomaly_links(game,self.root)
        game=dict(game_id='2026_07_NE_CHI',away_team='NE',home_team='CHI',away_score=24,home_score=30,spread=None,total=None,dog_side='',location='',game_type='REG')
        self.app.add_url_rule('/matchup/<game_id>', 'fans.matchup', lambda game_id: '')
        with self.app.test_request_context():
            html=render_template('_general_games.html',games=[game],total=1,preview=True)
            self.assertIn('#anomaly-abc',html)
            self.assertGreater(html.index('class="game-anomaly-flag"'),html.index('</details>'))
            game['game_id']='2026_08_NE_CHI'
            html=render_template('_general_games.html',games=[game],total=1,preview=True)
            self.assertNotIn('class="game-anomaly-flag"',html)

    def test_missing_file_safe(self):
        (self.root/'anomaly_events.csv').unlink();self.assertEqual([],self.links())
    def test_completed_guards_and_safe_dom(self):
        source=Path('fan_views.py').read_text()
        self.assertIn("row['state'] == 'post' and row.get('completed') is True",source)
        self.assertIn("ROOT/'anomaly_events.csv'",source)
        js=Path('static/anomaly_flags.js').read_text()
        self.assertNotIn('innerHTML',js);self.assertIn('link.textContent = event.title',js)
        plug=Path('templates/expert_dashboard.html').read_text()
        self.assertIn('{% if item.final_score %}{% set anomalies=',plug)

if __name__=='__main__': unittest.main()
