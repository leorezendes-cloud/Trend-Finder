"""Isolated tests for member nicknames and avatar selections. No external requests.
Run from repo root: .venv/bin/python -m unittest discover -s tests -p 'test_huddle_identity.py' -v
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from flask import Flask, Blueprint, g, session, render_template
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
import membership
import community_comments as community


class HuddleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config.update(SECRET_KEY='temporary-test-secret', TESTING=True,
                          MEMBERSHIP_DATABASE=str(Path(self.temp.name)/'test.sqlite3'))
        root = Path(__file__).resolve().parents[1]
        app.jinja_loader=ChoiceLoader([
            DictLoader({'_site_navigation.html':'', '_branding_head.html':''}),
            FileSystemLoader(str(root/'templates'))])
        app.jinja_env.globals['csrf_token'] = lambda: session.setdefault('_csrf','test-csrf')
        member_bp=Blueprint('membership',__name__,url_prefix='/members')
        member_bp.add_url_rule('/preferences', 'preferences', self.preferences)
        member_bp.add_url_rule('/login','login',lambda:'login')
        member_bp.add_url_rule('/register','register',lambda:'register')
        member_bp.add_url_rule('/feedback/review','feedback_review',lambda:'review')
        member_bp.add_url_rule('/watchlist/<int:item_id>/remove','remove_watchlist',lambda item_id:'remove',methods=['POST'])
        app.register_blueprint(member_bp)
        picks_bp=Blueprint('member_picks',__name__,url_prefix='/picks')
        picks_bp.add_url_rule('/','my_picks',lambda:'picks')
        app.register_blueprint(picks_bp)
        fantasy_bp=Blueprint('fans',__name__)
        fantasy_bp.add_url_rule('/fantasy','fantasy',lambda:'fantasy')
        app.register_blueprint(fantasy_bp)
        app.add_url_rule('/','home',lambda:'home')
        @app.before_request
        def member_loader():
            g.member = membership.db().execute('SELECT id,email FROM members WHERE id=?',(session.get('member_id',-1),)).fetchone()
            g.is_owner = False
        @app.teardown_appcontext
        def close(error):
            con=g.pop('member_db',None)
            if con is not None:con.close()
        with app.app_context():
            con=membership.db()
            with con:
                con.execute('CREATE TABLE members (id INTEGER PRIMARY KEY,email TEXT)')
                con.executemany('INSERT INTO members VALUES(?,?)',[(1,'one@example.test'),(2,'two@example.test')])
        community.init_community(app)
        self.app=app
        self.client=app.test_client()

    def tearDown(self):self.temp.cleanup()

    def preferences(self):
        if g.member is None:return 'Sign in',403
        return render_template('membership.html',mode='preferences',g=g,error=None,saved=False,
                               watchlist=[],records={market:{} for market in ('su','ats','ou')},seo=None,
                               current_site_week=None)

    def login(self, member_id):
        with self.client.session_transaction() as data:
            data['member_id']=member_id
            data['_csrf']='test-csrf'

    def identity(self, nickname='', avatar='football', csrf='test-csrf'):
        return self.client.post('/community/identity',data={'csrf_token':csrf,
                                'display_name':nickname,'avatar':avatar})

    def post(self, body='Pats by ten'):
        return self.client.post('/community/post',data={'csrf_token':'test-csrf','body':body})

    def test_defaults_and_existing_comments_update_in_place(self):
        self.login(1)
        self.assertEqual(self.post().status_code,303)
        before=self.client.get('/community').get_data(as_text=True)
        self.assertIn('Fan #1',before)
        self.assertIn('Pats by ten',before)
        self.assertEqual(self.identity('FourthDown','trophy').status_code,303)
        after=self.client.get('/community').get_data(as_text=True)
        self.assertIn('FourthDown',after)
        self.assertIn('🏆',after)
        self.assertNotIn('one@example.test',after)
        with self.app.app_context():
            self.assertEqual(membership.db().execute('SELECT COUNT(*) FROM community_comments').fetchone()[0],1)

    def test_profile_form_and_saved_selections(self):
        self.login(1)
        self.identity('Pocket Passer','shield')
        page=self.client.get('/members/preferences').get_data(as_text=True)
        self.assertIn('Huddle identity',page)
        self.assertIn('Pocket Passer',page)
        self.assertIn('name="avatar" value="shield" checked',page)
        self.assertIn('My Watchlist',page)
        self.assertIn('Straight-up',page)

    def test_duplicates_are_case_insensitive_and_do_not_change_profile(self):
        self.login(1)
        self.assertEqual(self.identity('FourthDown','bolt').status_code,303)
        self.login(2)
        self.assertEqual(self.identity('fourthdown','fire').status_code,303)
        profile=self.client.get('/members/preferences').get_data(as_text=True)
        self.assertIn('nickname is already taken',profile)
        with self.app.app_context():
            con=membership.db()
            self.assertEqual(con.execute('SELECT COUNT(*) FROM community_profiles').fetchone()[0],1)

    def test_rejects_unsafe_fields_and_csrf(self):
        self.login(1)
        self.assertEqual(self.identity('Moderator').status_code,303)
        self.assertEqual(self.identity('<script>alert(1)</script>').status_code,303)
        self.assertEqual(self.identity('Valid Name','made-up').status_code,400)
        self.assertNotEqual(self.identity('Valid Name','football','wrong').status_code,303)
        with self.app.app_context():
            self.assertEqual(membership.db().execute('SELECT COUNT(*) FROM community_profiles').fetchone()[0],0)
        self.assertEqual(self.identity('Good Name','fire').status_code,303)
        self.assertEqual(self.identity('', 'football').status_code,303)
        with self.app.app_context():
            row=membership.db().execute('SELECT display_name,avatar_key FROM community_profiles WHERE member_id=1').fetchone()
            self.assertIsNone(row['display_name'])
            self.assertEqual(row['avatar_key'],'football')

    def test_signed_out_cannot_change_identity(self):
        with self.client.session_transaction() as data:data['_csrf']='test-csrf'
        self.assertEqual(self.identity('Guest Name').status_code,403)
        self.assertEqual(self.client.get('/community').status_code,200)


if __name__=='__main__':unittest.main()
