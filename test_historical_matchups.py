"""Isolated presentation checks; preserve the existing ranking and CSV pipeline."""
import copy
import csv
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from html.parser import HTMLParser
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader

ROOT = Path(__file__).resolve().parent


class Tiles(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.details = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'a' and attrs.get('class') == 'historical-matchup-tile':
            self.links.append(attrs['href'])
        if tag == 'details':
            self.details.append(attrs)


class HistoricalMatchupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {'TREND_FINDAH_DATABASE': str(Path(cls.temp.name)/'members.sqlite3'),
                                    'TREND_FINDAH_SECRET_KEY': 'isolated-matchup-tests'}):
            import app as module
        cls.module = module
        cls.app = Flask(__name__, template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))
        cls.app.config['TESTING'] = True
        cls.app.jinja_loader = ChoiceLoader([DictLoader({'_site_navigation.html': '', '_branding_head.html': ''}), cls.app.jinja_loader])
        cls.app.jinja_env.filters['eastern_time'] = lambda value: value
        cls.app.add_url_rule('/sunday', 'sunday_page', module.sunday_page)
        cls.app.add_url_rule('/market', 'market_page', module.market_page)
        cls.app.add_url_rule('/the-plug', 'plug_page', lambda: 'The Plug')
        cls.app.add_url_rule('/matchup/<game_id>', 'fans.matchup', lambda game_id: game_id)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.app.extensions.pop('historical_window_cache', None)
        self.client = self.app.test_client()
        self.history = [dict(location='Away',primetime=False,spread='0.5-3',sample=100,ci_low=51.2,ats_rate=61.0)]
        def game(gid, away, home, location='Away'):
            return dict(game_id=gid,away_team=away,home_team=home,dog_team=away,dog_spread=3.0,
                        dog_location=location,is_primetime=False,gameday='2026-10-25',gametime_et='13:00',
                        neutral=False,line_source='Saved fixture',line_time='2026-10-22T12:00:00+00:00',line_stale=False,
                        matches=[dict(spread='0.5-3',historical_sample=100,historical_ci_low=51.2,historical_ats_rate=61.0)])
        self.games = [game('2026_07_NE_CHI','NE','CHI'),game('2026_07_KC_SEA','KC','SEA'),game('2026_07_DAL_PHI','DAL','PHI','Home')]
        self.pending = [dict(game_id='2026_07_GB_DET',away_team='GB',home_team='DET',reason='Spread unavailable')]
        self.patches = [patch.object(self.module,'scan_basic_trends',return_value=self.history),
                        patch.object(self.module,'compare_trends',return_value=[]),
                        patch('site_views.public_matchups',side_effect=lambda *args: (copy.deepcopy(self.games),copy.deepcopy(self.pending)))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_compact_links_real_values_ties_pending_and_collapsed_evidence(self):
        response = self.client.get('/sunday?window=5')
        self.assertEqual(response.status_code,200)
        page = response.text
        self.assertIn('Historical Matchup Trends',page)
        self.assertIn('2026 Week 7',page)
        self.assertIn('Tied #1',page)
        self.assertIn('61.0<small>%</small>',page)
        self.assertIn('Insufficient history',page)
        self.assertIn('Awaiting eligible line',page)
        parsed = Tiles(); parsed.feed(page)
        self.assertEqual(parsed.links,[f'/matchup/{g["game_id"]}' for g in self.games+self.pending])
        self.assertTrue(parsed.details)
        self.assertTrue(all('open' not in item for item in parsed.details))
        self.assertIn('Exploratory matching spread ranges',page)
        self.assertIn('Captured 2026-10-22',page)
        self.assertNotIn('Illustrative design',page)
        self.assertNotIn('_home_sections.html',Path('templates/sunday.html').read_text())

    def test_export_keeps_existing_ranking_values_and_missing_data(self):
        response = self.client.get('/sunday?window=5&download=1')
        self.assertEqual(response.mimetype,'text/csv')
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['rank'],'1')
        self.assertEqual(rows[1]['rank'],'1')
        self.assertEqual(rows[0]['historical_ats'],'61.0')
        self.assertEqual(rows[0]['lower_bound'],'51.2')
        self.assertEqual(rows[0]['historical_games'],'100')
        self.assertEqual(rows[0]['window'],'5')
        self.assertEqual(rows[2]['rank'],'')
        self.assertEqual(rows[2]['historical_ats'],'')

    def test_archive_links_resolve_schedule_ids_and_preserve_window(self):
        archived = copy.deepcopy(self.games[:1])
        archived[0].pop('game_id')
        schedule = Path(self.temp.name)/'schedule.csv'
        schedule.write_text('gameday,away_team,home_team,game_id\n2026-10-25,NE,CHI,2026_07_NE_CHI\n')
        with patch.object(self.module,'scan_sunday_matchups',return_value=archived), patch.object(self.module,'game_file',schedule):
            page = self.client.get('/sunday?window=3&view=archive').text
        parsed = Tiles(); parsed.feed(page)
        self.assertEqual(parsed.links,['/matchup/2026_07_NE_CHI'])
        self.assertIn('Archived October 11, 2026 snapshot',page)
        self.assertIn('name="view" value="archive"',page)
        self.assertIn('value="3" selected',page)
        self.assertIn('download=1',page)

    def test_empty_view_and_invalid_window_still_render(self):
        with patch('site_views.public_matchups',return_value=([],[])):
            response = self.client.get('/sunday?window=invalid')
        self.assertEqual(response.status_code,200)
        self.assertIn('No scheduled matchups',response.text)
        self.assertIn('value="all" selected',response.text)

    def test_archive_without_schedule_id_links_to_evidence(self):
        archived = copy.deepcopy(self.games[:1]); archived[0].pop('game_id')
        schedule = Path(self.temp.name)/'empty.csv'
        schedule.write_text('gameday,away_team,home_team,game_id\n')
        with patch.object(self.module,'scan_sunday_matchups',return_value=archived), patch.object(self.module,'game_file',schedule):
            page = self.client.get('/sunday?view=archive').text
        parsed = Tiles(); parsed.feed(page)
        self.assertEqual(parsed.links,['#historical-evidence-1'])

    def test_retired_market_redirects_without_loading_market_data(self):
        with patch('market_views.market_games',side_effect=AssertionError('Retired page loaded data')):
            response = self.client.get('/market?week=7')
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.location,'/the-plug')
        self.assertEqual(self.client.get(response.location).data,b'The Plug')

    def test_plug_action_label_and_home_target(self):
        for name in ('_plug_actions.html', 'sunday_scout.html'):
            page = (ROOT/'templates'/name).read_text()
            self.assertIn("url_for('sunday_page')",page)
            self.assertIn('Historical Trends</a>',page)
            self.assertNotIn('← Upcoming Matchups',page)
        home = (ROOT/'templates/home.html').read_text()
        self.assertIn("url_for('plug_page')",home)
        self.assertIn('Upcoming spreads &amp; totals',home)
        self.assertNotIn("url_for('market_page')",home)

    def test_cached_html_and_csv_are_identical_without_recalculating(self):
        with patch('historical_window_cache.time',return_value=61):
            first=self.client.get('/sunday?window=5')
            export=self.client.get('/sunday?window=5&download=1')
            with patch.object(self.module,'scan_basic_trends',side_effect=AssertionError('Recomputed cached window')):
                second=self.client.get('/sunday?window=5')
                cached_export=self.client.get('/sunday?window=5&download=1')
        self.assertEqual(first.data,second.data)
        def records(response):
            return [{k:v for k,v in row.items() if k!='recorded_at'} for row in csv.DictReader(io.StringIO(response.text))]
        self.assertEqual(records(export),records(cached_export))


if __name__ == '__main__':
    unittest.main()
