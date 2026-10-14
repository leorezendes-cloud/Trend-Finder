import unittest
from unittest.mock import patch
from flask import Flask

from wsgi import configure_hosted_app


class HostingTests(unittest.TestCase):
    def make_app(self, hops='0'):
        application = Flask('hosting-test')
        from flask import Blueprint
        members = Blueprint('membership', __name__)
        members.add_url_rule('/members/login', 'login', lambda: 'login', methods=['POST'])
        application.register_blueprint(members)
        newsletters = Blueprint('newsletter', __name__)
        newsletters.add_url_rule('/newsletter/manage','manage',lambda:'owner checks live in the newsletter module',methods=['POST'])
        application.register_blueprint(newsletters)
        picks = Blueprint('member_picks', __name__)
        picks.add_url_rule('/picks/games/1','save_pick',lambda:'member and kickoff checks live in the picks module',methods=['POST'])
        application.register_blueprint(picks)
        application.add_url_rule('/', 'home', lambda: 'analysis', methods=['GET','POST'])
        application.add_url_rule('/trend-finder', 'trend_finder', lambda: 'analysis', methods=['GET','POST'])
        application.add_url_rule('/refresh', 'refresh', lambda: self.fail('Collector was executed'), methods=['POST'])
        application.add_url_rule('/peer', 'peer', lambda: __import__('flask').request.remote_addr)
        with patch.dict('os.environ', {'TREND_FINDAH_PROXY_HOPS':hops}):
            configure_hosted_app(application)
        return application

    def test_hosting_blocks_data_mutation_but_allows_membership_and_analysis(self):
        client = self.make_app().test_client()
        self.assertEqual(client.post('/refresh').status_code, 403)
        self.assertEqual(client.post('/members/login').status_code, 200)
        self.assertEqual(client.post('/').status_code, 200)
        self.assertEqual(client.post('/trend-finder').status_code, 200)
        self.assertEqual(client.post('/newsletter/manage').status_code, 200)
        self.assertEqual(client.post('/picks/games/1').status_code, 200)

    def test_static_files_bypass_application_work_and_are_cacheable(self):
        from flask import request
        application = self.make_app()
        application.config['TESTING'] = True
        @application.before_request
        def reject_static_application_work():
            if request.path in ('/static/navigation.css', '/static/Images/Branding/gravy-train-branding/gravy-train/gravy-train-nav.png'):
                self.fail('Static request ran page/session logic')
        client = application.test_client()
        with client.get('/static/navigation.css') as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn('.home-section-card img', response.text)
            self.assertIn('public', response.headers['Cache-Control'])
            self.assertIn('max-age=3600', response.headers['Cache-Control'])
            self.assertNotIn('Cookie', response.headers.get('Vary', ''))
        path = '/static/Images/Branding/gravy-train-branding/gravy-train/gravy-train-nav.png'
        with client.get(path) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/png')
        with client.get('/static/../membership.py') as response:
            self.assertEqual(response.status_code, 404)
        self.assertEqual(client.post('/refresh').status_code, 403)

    def test_server_has_parallel_request_capacity(self):
        import runpy
        from pathlib import Path
        config = runpy.run_path(str(Path(__file__).with_name('gunicorn.conf.py')))
        self.assertEqual(config['worker_class'], 'gthread')
        self.assertGreaterEqual(config['threads'], 4)
        self.assertEqual(config['workers'], 1)

    def test_forwarded_address_is_ignored_by_default(self):
        response = self.make_app().test_client().get('/peer', headers={'X-Forwarded-For':'203.0.113.9'})
        self.assertEqual(response.text, '127.0.0.1')

    def test_explicit_trusted_proxy_count(self):
        response = self.make_app('1').test_client().get('/peer', headers={'X-Forwarded-For':'198.51.100.1, 203.0.113.9'})
        self.assertEqual(response.text, '203.0.113.9')
        with self.assertRaises(RuntimeError):
            self.make_app('4')


if __name__ == '__main__':
    unittest.main()
