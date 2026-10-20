"""Focused Flask integration checks; uses a temporary SQLite database, no network."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint, Flask, g, session
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

import membership
import community_comments as community


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(__file__).resolve().parents[1]
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='local-tests-only',
                          MEMBERSHIP_DATABASE=str(Path(self.folder.name) / 'members.sqlite3'))
        app.jinja_loader = ChoiceLoader([DictLoader({'_site_navigation.html': ''}),
                                         FileSystemLoader(str(root / 'templates'))])
        app.jinja_env.globals['csrf_token'] = self.token
        members_bp = Blueprint('membership', __name__, url_prefix='/members')
        members_bp.add_url_rule('/login', 'login', lambda: 'login')
        members_bp.add_url_rule('/register', 'register', lambda: 'register')
        app.register_blueprint(members_bp)
        fantasy_bp = Blueprint('fans', __name__, url_prefix='/fans')
        fantasy_bp.add_url_rule('/fantasy', 'fantasy', lambda: 'fantasy')
        app.register_blueprint(fantasy_bp)
        picks_bp = Blueprint('member_picks', __name__, url_prefix='/picks')
        picks_bp.add_url_rule('/my-picks', 'my_picks', lambda: 'picks')
        app.register_blueprint(picks_bp)

        @app.before_request
        def load_member():
            g.member = None
            g.is_owner = False
            if session.get('member_id'):
                g.member = membership.db().execute('SELECT id,email FROM members WHERE id=?',
                                                   (session['member_id'],)).fetchone()
                g.is_owner = session.get('owner', False)

        @app.teardown_appcontext
        def close_db(error):
            connection = g.pop('member_db', None)
            if connection:
                connection.close()

        with app.app_context():
            con = membership.db()
            with con:
                con.execute('CREATE TABLE members (id INTEGER PRIMARY KEY, email TEXT)')
                con.executemany('INSERT INTO members VALUES(?,?)', [(1, 'a@example.com'), (2, 'b@example.com')])
        community.init_community(app)
        self.app = app
        self.client = app.test_client()

    def tearDown(self):
        self.folder.cleanup()

    @staticmethod
    def token():
        return session.setdefault('_csrf', 'test-token')

    def login(self, member=1, owner=False):
        with self.client.session_transaction() as sess:
            sess['member_id'] = member
            sess['_csrf'] = 'test-token'
            sess['owner'] = owner

    def post(self, text='What about these underdogs?', token='test-token'):
        return self.client.post('/community/post', data={'csrf_token': token, 'body': text})

    def test_anonymous_can_read_but_not_post(self):
        self.assertEqual(self.client.get('/community').status_code, 200)
        self.assertEqual(self.post().status_code, 303)  # Missing token; safely rejected with a message.
        with self.client.session_transaction() as sess:
            sess['_csrf'] = 'test-token'
        self.assertEqual(self.post().status_code, 403)

    def test_member_posts_and_html_is_escaped(self):
        self.login()
        self.assertEqual(self.post('<script>alert(1)</script>').status_code, 303)
        page = self.client.get('/community').get_data(as_text=True)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('Fan #1', page)
        self.assertNotIn('a@example.com', page)

    def test_csrf_and_rate_limit(self):
        self.login()
        self.assertEqual(self.post(token='wrong').status_code, 303)
        self.assertIn('session expired', self.client.get('/community').get_data(as_text=True))
        for _ in range(community.MAX_POSTS_IN_WINDOW):
            self.assertEqual(self.post().status_code, 303)
        response = self.post()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith('#composer'))
        self.assertIn('Post limit reached', self.client.get('/community').get_data(as_text=True))

    def test_member_report_and_owner_hide_restore(self):
        self.login(1)
        self.assertEqual(self.post().status_code, 303)
        self.login(2)
        self.assertEqual(self.client.post('/community/1/report',data={'csrf_token':'test-token'}).status_code, 303)
        self.login(1)
        self.assertEqual(self.client.post('/community/1/hide', data={'csrf_token':'test-token'}).status_code, 403)
        self.login(2, owner=True)
        self.assertEqual(self.client.get('/community?review=reported').status_code, 302)
        self.assertEqual(self.client.get('/community/reports').status_code, 200)
        self.assertEqual(self.client.post('/community/1/hide',data={'csrf_token':'test-token'}).status_code, 303)
        self.login(1)
        self.assertNotIn('What about these underdogs?', self.client.get('/community').get_data(as_text=True))
        self.login(2, owner=True)
        self.assertEqual(self.client.post('/community/1/restore',data={'csrf_token':'test-token'}).status_code, 303)
        self.login(1)
        self.assertIn('What about these underdogs?', self.client.get('/community').get_data(as_text=True))

    def test_actual_page_form_and_one_feed(self):
        import re
        self.login()
        html = self.client.get('/community').get_data(as_text=True)
        self.assertIn('The Huddle', html)
        self.assertIn('Fantasy Football', html)
        self.assertIn('Member Picks', html)
        self.assertIn('Leaderboard', html)
        self.assertNotIn('name="topic"', html)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(token)
        sent = self.client.post('/community/post', data={'csrf_token':token.group(1),'body':'Go Pats!'})
        self.assertEqual(sent.status_code, 303)
        refreshed = self.client.get('/community').get_data(as_text=True)
        self.assertIn('Go Pats!', refreshed)
        self.assertIn('Add to the conversation', refreshed)
        self.assertNotIn('Select a topic', refreshed)
        self.assertIn('Go Pats!', self.client.get('/community?topic=picks').get_data(as_text=True))
        self.assertIn('posted=1', sent.headers['Location'])
        self.assertIn('class="huddle-post-button"', refreshed)
        self.assertNotIn('↑', refreshed)
        self.assertIn('Comment Section', refreshed)
        self.assertNotIn('The conversation</h2>', refreshed)

    def test_report_queue_is_distinct_and_moderation_stays_there(self):
        self.login(1)
        self.post('One reported comment')
        self.post('One regular comment')
        self.login(2)
        self.assertEqual(self.client.get('/community/reports').status_code, 403)
        self.client.post('/community/1/report', data={'csrf_token': 'test-token'})
        self.login(2, owner=True)
        general = self.client.get('/community').get_data(as_text=True)
        self.assertIn('Review Reports', general)
        self.assertIn('/community/reports', general)
        review = self.client.get('/community/reports').get_data(as_text=True)
        self.assertIn('OWNER MODERATION', review)
        self.assertIn('Reported Comments', review)
        self.assertIn('One reported comment', review)
        self.assertNotIn('One regular comment', review)
        self.assertNotIn('id="composer"', review)
        self.assertIn('Back to Comments', review)
        response = self.client.post('/community/1/hide', data={'csrf_token': 'test-token', 'return_to': 'reports'})
        self.assertEqual(response.status_code, 303)
        self.assertIn('/community/reports', response.headers['Location'])
        self.assertIn('Hidden', self.client.get('/community/reports').get_data(as_text=True))
        self.assertEqual(self.client.get('/community/reports?page=2').status_code, 404)

    def test_invalid_fields_rejected(self):
        self.login()
        self.assertEqual(self.post('hi').status_code, 303)
        self.assertEqual(self.post('').status_code, 303)
        self.assertIn('up to 600 characters', self.client.get('/community').get_data(as_text=True))
        self.assertEqual(self.post('x'*601).status_code, 303)
        self.assertEqual(self.post('line\n'*13).status_code, 303)


if __name__ == '__main__':
    unittest.main()
