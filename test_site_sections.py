"""Check navigation hierarchy and preserve the moved analysis workflow."""
import unittest
from html.parser import HTMLParser
from app import app


class NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active_nav = None
        self.links = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'nav':
            self.active_nav = attrs.get('aria-label')
            self.links.setdefault(self.active_nav, [])
        if tag == 'a' and self.active_nav:
            self.links[self.active_nav].append(attrs.get('href'))

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.active_nav = None


class SiteSectionsTests(unittest.TestCase):
    def test_navigation_stylesheet_is_versioned_and_available(self):
        import hashlib
        from pathlib import Path
        from flask import url_for
        with app.test_request_context():
            url = url_for('static', filename='navigation.css')
        expected = hashlib.sha256((Path(app.static_folder) / 'navigation.css').read_bytes()).hexdigest()[:12]
        self.assertTrue(url.endswith('v=' + expected))
        with app.test_client().get(url) as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn('.home-section-card img', response.text)
        self.assertIn(url, app.test_client().get('/').text)

    def test_home_head_probe_does_not_build_matchup_page(self):
        from unittest.mock import patch
        with patch('app.sunday_page', side_effect=AssertionError('Probe ran trend analysis')):
            response = app.test_client().head('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'')

    def setUp(self):
        self.client = app.test_client()

    def test_home_is_landing_with_three_section_destinations(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('Find your next angle.', html)
        self.assertIn('Discover NFL trends with custom ATS filters.', html)
        self.assertIn('Picks going left?? Get right with the plug.', html)
        self.assertIn('Find the fix in the Conspiracy Dungeon.', html)
        self.assertIn('Sign in', html)
        self.assertIn('Images/Branding/trend-findah-background.png', html)
        self.assertNotIn('class="home-filter-form"', html)
        parser = NavigationParser()
        parser.feed(html)
        self.assertEqual(parser.links['Main navigation'][:4], ['/', '/trend-finder', '/the-plug', '/conspiracy-dungeon'])
        self.assertNotIn('/trends', parser.links['Main navigation'])
        self.assertIn('/sunday-results', parser.links['Home navigation'])

    def test_trend_finder_owns_discovery_and_form_destination(self):
        response = self.client.get('/trend-finder')
        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/trend-finder" class="home-filter-form"', response.text)
        self.assertIn('Images/Branding/trend-findah-nav.png', response.text)
        parser = NavigationParser()
        parser.feed(response.text)
        self.assertIn('/trends', parser.links['Trend Finder navigation'])
        self.assertEqual(self.client.get('/trends').status_code, 200)
        response = self.client.post('/', data={'season':'2026'})
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.location, '/trend-finder')

    def test_plug_groups_existing_stats_and_preserves_old_url(self):
        response = self.client.get('/the-plug')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Images/Branding/gravy-train-branding/the-plug/the-plug-full.png', response.text)
        parser = NavigationParser()
        parser.feed(response.text)
        for path in ['/scout4/teams', '/scout4/players', '/scout4/ratings', '/scout4/shadow']:
            self.assertIn(path, parser.links['The Plug navigation'])
        self.assertEqual(self.client.get('/sunday-scout').status_code, 200)
        self.assertEqual(self.client.get('/sunday').status_code, 200)

    def test_collapsed_menu_and_page_specific_backdrops(self):
        for path, art in [('/', 'trend-findah-background.png'), ('/trend-finder', 'trend-findah-background.png'), ('/the-plug', 'the-plug-full.png'), ('/conspiracy-dungeon', 'conspiracy-dungeon-full.png')]:
            html = self.client.get(path).text
            self.assertIn('<details class="site-menu" id="site-menu">', html)
            self.assertNotIn('id="site-menu" open', html)
            self.assertIn(art, html)
            self.assertIn('gravy-train-branding/favicon.ico', html)
            self.assertIn('navigation.js', html)
        with self.client.get('/static/Images/Branding/gravy-train-branding/favicon.ico') as response:
            self.assertEqual(response.status_code, 200)

    def test_brands_and_member_navigation_remain_available(self):
        self.assertEqual(self.client.get('/conspiracy-dungeon').status_code, 200)
        with self.client.session_transaction() as session:
            session['member_id'] = 999
        # Avoid relying on an actual local user account.
        with app.app_context():
            for name in ['gravy-train','trend-findah-nav','the-plug','conspiracy-dungeon']:
                with self.client.get('/static/Images/Branding/' + name + '.png') as response:
                    self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/members/login').status_code, 200)


if __name__ == '__main__':
    unittest.main()
