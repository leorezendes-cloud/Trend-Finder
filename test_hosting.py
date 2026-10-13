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
