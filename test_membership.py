import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from flask import Flask
from membership import init_membership, migrate, issue_reset, db
from unittest.mock import patch
from contextlib import closing


class MembershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'members.sqlite3')
        with patch.dict('os.environ', {'TREND_FINDAH_DATABASE': self.database, 'TREND_FINDAH_SECRET_KEY': 'test-secret'}):
            self.app = Flask(__name__, instance_path=self.temp.name)
            self.app.add_url_rule('/', 'home', lambda: 'public')
            # Shared navigation references public endpoints.
            for endpoint in ['trend_finder','plug_page','trends_page','sunday_page','sunday_results_page','conspiracy_dungeon_page','scout4.teams_page','scout4.players_page','scout4.ratings_page','sunday_scout.sunday_scout_page','fans.fantasy']:
                self.app.add_url_rule('/' + endpoint, endpoint, lambda: 'public')
            init_membership(self.app)
        self.app.config['TESTING'] = True
        self.app.config['RESEND_API_KEY'] = ''
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def token(self, path='/members/register'):
        response = self.client.get(path)
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def register(self, **changes):
        data = dict(email='Person@example.com', password='long secure password', password_confirm='long secure password', csrf_token=self.token())
        data.update(changes)
        return self.client.post('/members/register', data=data)

    def row(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute('SELECT * FROM members').fetchone()

    def test_registration_hash_default_consent_and_logout(self):
        self.assertEqual(self.register().status_code, 302)
        row = self.row()
        self.assertEqual(row['email'], 'person@example.com')
        self.assertNotEqual(row['password_hash'], 'long secure password')
        self.assertEqual(row['newsletter_opt_in'], 0)
        self.assertIsNotNone(row['consent_updated_at'])
        self.assertEqual(self.client.get('/members/preferences').status_code, 200)
        self.assertEqual(self.client.get('/members/logout').status_code, 405)
        self.assertEqual(self.client.post('/members/logout', data={'csrf_token': self.token('/members/preferences')}).status_code, 302)
        self.assertEqual(self.client.get('/members/preferences').location, '/members/login')

    def test_csrf_and_session_rotation(self):
        self.assertEqual(self.client.post('/members/register', data={}).status_code, 400)
        old_token = self.token()
        self.register()
        self.assertEqual(self.client.post('/members/preferences', data={'csrf_token': old_token}).status_code, 400)
        self.assertEqual(self.client.post('/members/logout', data={}).status_code, 400)

    def test_validation_and_duplicate(self):
        for changes in [dict(email='bad'), dict(password='short'), dict(password_confirm='different'), dict(newsletter_opt_in='bogus')]:
            self.assertEqual(self.register(**changes).status_code, 400)
            self.assertIsNone(self.row())
        self.register()
        self.assertEqual(self.register(email='PERSON@example.com').status_code, 400)

    def test_password_minimum_boundary(self):
        self.assertEqual(self.register(password='123456789', password_confirm='123456789').status_code, 400)
        self.assertIsNone(self.row())
        self.assertEqual(self.register(password='1234567890', password_confirm='1234567890').status_code, 302)

    def test_login_and_generic_failure(self):
        self.register()
        self.client.post('/members/logout', data={'csrf_token': self.token('/members/preferences')})
        for email in ['person@example.com', 'missing@example.com']:
            response = self.client.post('/members/login', data={'email': email, 'password':'wrong', 'csrf_token': self.token('/members/login')})
            self.assertEqual(response.status_code, 400)
            self.assertIn('Email or password is incorrect.', response.text)
        self.assertEqual(self.client.post('/members/login', data={'email':'PERSON@example.com','password':'long secure password','csrf_token':self.token('/members/login')}).status_code, 302)

    def test_login_returns_home_and_profile_indicates_session(self):
        self.assertEqual(self.register().location, '/')
        self.assertIn('Signed in', self.client.get('/members/preferences').text)
        self.client.post('/members/logout', data={'csrf_token': self.token('/members/preferences')})
        bad = self.client.post('/members/login', data={'email':'wrong@example.com',
            'password':'wrong', 'csrf_token':self.token('/members/login')})
        self.assertEqual(bad.status_code, 400)
        self.assertNotIn('Welcome Back', bad.text)
        self.assertNotIn('Signed in', bad.text)
        good = self.client.post('/members/login', data={'email':'person@example.com',
            'password':'long secure password', 'csrf_token':self.token('/members/login')})
        self.assertEqual(good.location, '/')
        self.assertIn('Signed in', self.client.get('/members/preferences').text)

    def test_operator_signup_count_does_not_print_addresses(self):
        self.register()
        result = self.app.test_cli_runner().invoke(args=['membership-count'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Total members: 1', result.output)
        self.assertIn('Signed up in the last 7 days: 1', result.output)
        self.assertNotIn('person@example.com', result.output)

    def test_preferences_persistence_opt_out_and_migration(self):
        self.register(newsletter_opt_in='yes')
        self.assertEqual(self.row()['newsletter_opt_in'], 1)
        response = self.client.post('/members/preferences', data={'csrf_token':self.token('/members/preferences'),'newsletter_frequency':'monthly'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.row()['newsletter_opt_in'], 0)
        self.assertEqual(self.row()['newsletter_frequency'], 'monthly')
        self.assertEqual(self.client.post('/members/preferences', data={'csrf_token':self.token('/members/preferences'),'newsletter_frequency':'daily'}).status_code, 400)
        with self.app.app_context():
            migrate()
        self.assertEqual(self.row()['email'], 'person@example.com')
        result = self.app.test_cli_runner().invoke(args=['init-membership-db'])
        self.assertEqual(result.exit_code, 0)

    def reset_token(self):
        with self.app.app_context():
            return issue_reset(self.row()['id'])

    def test_reset_single_use_and_old_password_rejected(self):
        self.register()
        token = self.reset_token()
        path = '/members/reset-password/' + token
        self.assertEqual(self.client.post(path, data={}).status_code, 400)
        response = self.client.get(path)
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        data = {'password':'new password phrase', 'password_confirm':'new password phrase', 'csrf_token':self.token(path)}
        self.assertEqual(self.client.post(path, data=data).status_code, 302)
        self.assertEqual(self.client.get(path).status_code, 400)
        self.assertEqual(self.client.post('/members/login', data={'email':'person@example.com','password':'long secure password','csrf_token':self.token('/members/login')}).status_code, 400)
        self.assertEqual(self.client.post('/members/login', data={'email':'person@example.com','password':'new password phrase','csrf_token':self.token('/members/login')}).status_code, 302)

    def test_reset_expiration_validation_and_replacement(self):
        self.register()
        first = self.reset_token()
        token = self.reset_token()
        self.assertEqual(self.client.get('/members/reset-password/' + first).status_code, 400)
        path = '/members/reset-password/' + token
        self.assertEqual(self.client.post(path, data={'csrf_token':self.token(path),'password':'short','password_confirm':'short'}).status_code, 400)
        self.assertEqual(self.client.post(path, data={'csrf_token':self.token(path),'password':'long new password','password_confirm':'different'}).status_code, 400)
        with self.app.app_context():
            with db():
                db().execute('UPDATE password_resets SET expires_at=0')
        self.assertEqual(self.client.get(path).status_code, 400)

    def test_password_reset_invalidates_other_browser_session(self):
        self.register()
        other = self.app.test_client()
        response = other.get('/members/login')
        csrf = re.search(r'name="csrf_token" value="([^\"]+)"', response.text).group(1)
        other.post('/members/login', data={'email':'person@example.com','password':'long secure password','csrf_token':csrf})
        path = '/members/reset-password/' + self.reset_token()
        self.client.post(path, data={'csrf_token':self.token(path),'password':'new password phrase','password_confirm':'new password phrase'})
        self.assertEqual(other.get('/members/preferences').location, '/members/login')

    def test_rate_limit_and_window_expiry(self):
        csrf = self.token('/members/login')
        data = {'csrf_token':csrf,'email':'missing@example.com','password':'wrong'}
        for _ in range(5):
            self.assertEqual(self.client.post('/members/login', data=data).status_code, 400)
        self.assertEqual(self.client.post('/members/login', data=data).status_code, 429)
        with self.app.app_context():
            with db():
                db().execute('UPDATE auth_limits SET started_at=0')
        self.assertEqual(self.client.post('/members/login', data=data).status_code, 400)
        # The IP-wide ceiling also limits attempts spread across addresses.
        for number in range(29):
            self.assertEqual(self.client.post('/members/login', data=dict(data,email=f'user{number}@example.com')).status_code, 400)
        self.assertEqual(self.client.post('/members/login', data=dict(data,email='another@example.com')).status_code, 429)

    def test_recovery_does_not_disclose_accounts_or_send_email(self):
        self.register()
        path = '/members/forgot-password'
        results = []
        for email in ['person@example.com','unknown@example.com']:
            response = self.client.post(path, data={'csrf_token':self.token(path),'email':email})
            self.assertEqual(response.status_code, 200)
            self.assertIn('No email has been sent', response.text)
            results.append(response.text)
        self.assertEqual(results[0], results[1])
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM password_resets').fetchone()[0], 0)

    def test_email_recovery_round_trip_and_trusted_origin(self):
        import json
        from unittest.mock import MagicMock
        self.register()
        self.app.config.update(RESEND_API_KEY='test-key', PUBLIC_ORIGIN='https://trendfindah.com')
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id":"email-id"}'
        path = '/members/forgot-password'
        with patch('membership.urlopen', return_value=response) as sender:
            pages = []
            for email in ['person@example.com', 'unknown@example.com']:
                reply = self.client.post(path, data={'csrf_token':self.token(path), 'email':email},
                                         headers={'X-Forwarded-Host':'untrusted.example'})
                self.assertEqual(reply.status_code, 200)
                pages.append(reply.text)
            self.assertEqual(pages[0], pages[1])
            self.assertEqual(sender.call_count, 1)
            request = sender.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(payload['to'], ['person@example.com'])
            self.assertEqual(request.full_url, 'https://api.resend.com/emails')
            self.assertEqual(sender.call_args.kwargs['timeout'], 8)
            link = re.search(r'https://trendfindah.com/members/reset-password/[^\s]+', payload['text']).group()
        reset_path = link.removeprefix('https://trendfindah.com')
        reply = self.client.post(reset_path, data={'csrf_token':self.token(reset_path),
            'password':'recovered password phrase', 'password_confirm':'recovered password phrase'})
        self.assertEqual(reply.status_code, 302)
        self.assertEqual(self.client.get(reset_path).status_code, 400)
        self.assertEqual(self.client.post('/members/login', data={'csrf_token':self.token('/members/login'),
            'email':'person@example.com', 'password':'recovered password phrase'}).status_code, 302)

    def test_delivery_failure_revokes_token_and_does_not_expose_details(self):
        from urllib.error import URLError
        self.register()
        self.app.config['RESEND_API_KEY'] = 'test-key'
        path = '/members/forgot-password'
        with patch('membership.urlopen', side_effect=URLError('private provider detail')):
            with self.assertLogs(self.app.logger, level='ERROR') as logs:
                reply = self.client.post(path, data={'csrf_token':self.token(path), 'email':'person@example.com'})
        self.assertEqual(reply.status_code, 200)
        self.assertNotIn('private provider detail', reply.text + ''.join(logs.output))
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM password_resets').fetchone()[0], 0)

    def test_version_one_database_migrates_without_losing_accounts(self):
        legacy = str(Path(self.temp.name) / 'legacy.sqlite3')
        with closing(sqlite3.connect(legacy)) as connection:
            connection.execute('CREATE TABLE members (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, newsletter_opt_in INTEGER NOT NULL DEFAULT 0, newsletter_frequency TEXT NOT NULL DEFAULT "weekly", consent_updated_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            connection.execute('INSERT INTO members(email,password_hash) VALUES("legacy@example.com","existing-hash")')
            connection.execute('PRAGMA user_version=1')
            connection.commit()
        self.app.config['MEMBERSHIP_DATABASE'] = legacy
        with self.app.app_context():
            migrate()
            migrate()
            row = db().execute('SELECT * FROM members').fetchone()
            self.assertEqual(row['email'], 'legacy@example.com')
            self.assertEqual(row['password_hash'], 'existing-hash')
            self.assertEqual(row['session_version'], 0)
            self.assertEqual(db().execute('PRAGMA user_version').fetchone()[0], 2)

    def test_backup_and_local_reset_cli(self):
        self.register()
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['membership-reset-link','person@example.com'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('http://localhost:5002/members/reset-password/', result.output)
        with patch.dict('os.environ', {'TREND_FINDAH_ENV':'production'}):
            self.assertNotEqual(runner.invoke(args=['membership-reset-link','person@example.com']).exit_code, 0)
        destination = str(Path(self.temp.name) / 'backup.sqlite3')
        result = runner.invoke(args=['backup-membership-db',destination])
        self.assertEqual(result.exit_code, 0)
        with closing(sqlite3.connect(destination)) as connection:
            self.assertEqual(connection.execute('SELECT email FROM members').fetchone()[0], 'person@example.com')
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertNotEqual(runner.invoke(args=['backup-membership-db',destination]).exit_code, 0)

    def test_public_access_and_secure_settings(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertTrue(self.app.config['SESSION_COOKIE_HTTPONLY'])
        self.assertEqual(self.app.config['SESSION_COOKIE_SAMESITE'], 'Lax')
        with patch.dict('os.environ', {'TREND_FINDAH_ENV':'production','TREND_FINDAH_SECRET_KEY':''}):
            with self.assertRaises(RuntimeError):
                init_membership(Flask('production', instance_path=self.temp.name))


if __name__ == '__main__':
    unittest.main()
