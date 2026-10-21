"""Focused local smoke tests for the installed profile/Huddle refresh."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]

class ProfileHuddleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ROOT
        cls.templates = cls.root / 'templates'

    def test_profile_has_header_records_then_watchlists(self):
        template = (self.templates/'membership.html').read_text()
        self.assertLess(template.index('profile-huddle'), template.index('profile-records'))
        self.assertLess(template.index('profile-records'), template.index('id="my-watchlist"'))
        self.assertIn("records[key].get('Win',0)",template)
        self.assertNotIn('<h1>Gravy Train</h1>',template)

    def test_header_has_own_dropdown_and_safe_logout(self):
        nav = (self.templates/'_site_navigation.html').read_text()
        self.assertIn('<details class="site-profile-dropdown">',nav)
        self.assertIn("'Signed in' if g.member else 'Signed out'",nav)
        self.assertIn("url_for('membership.preferences')",nav)
        self.assertIn("url_for('member_picks.my_picks')",nav)
        self.assertIn("url_for('membership.logout')",nav)
        self.assertIn('name="csrf_token"',nav)

    def test_huddle_layout_and_hidden_leaderboard_preserved(self):
        huddle = (self.templates/'community.html').read_text()
        self.assertIn("filename='member_picks.css'",huddle)
        self.assertIn("filename='community.css'",huddle)
        self.assertIn('Leaderboard',huddle)
        self.assertIn('Coming soon',huddle)

    def test_membership_python_and_html_parse(self):
        ast.parse((self.root/'membership.py').read_text())
        env=Environment(loader=FileSystemLoader(str(self.templates)))
        for name in ('membership.html','community.html','_site_navigation.html'):
            env.parse((self.templates/name).read_text())

    def test_profile_renders_with_dummy_records(self):
        env=Environment(loader=FileSystemLoader(str(self.templates)))
        # The project has its own branding include; this isolates the rendering test.
        from jinja2 import ChoiceLoader,DictLoader
        env.loader=ChoiceLoader([DictLoader({'_branding_head.html':''}),env.loader])
        env.globals.update(url_for=lambda endpoint,**kw:'/mock/'+endpoint.replace('.','/'),csrf_token=lambda:'fake-token')
        g = SimpleNamespace(member={'id':1,'email':'test@example.com','newsletter_opt_in':1,'newsletter_frequency':'weekly'},is_owner=False)
        req = SimpleNamespace(endpoint='membership.preferences',blueprint='membership',script_root='',path='/members/preferences',args={},form={})
        results={'su':{'Win':3,'Loss':1},'ats':{'Win':2,'Loss':2},'ou':{}}
        html=env.get_template('membership.html').render(mode='preferences',g=g,request=req,config={},seo=None,current_site_week=None,watchlist=[],records=results,error=None,saved=False)
        self.assertIn('My Profile',html)
        self.assertIn('3–1',html)
        self.assertIn('My Watchlist',html)
        self.assertIn('Newsletter preferences',html)

if __name__=='__main__':unittest.main()
