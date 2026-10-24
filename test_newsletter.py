import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from membership import init_membership, db
from newsletter import send_issue, signer


class NewsletterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch.dict('os.environ', {'TREND_FINDAH_DATABASE':str(Path(self.temp.name)/'members.sqlite3'),
            'TREND_FINDAH_SECRET_KEY':'test-secret', 'TREND_FINDAH_NEWSLETTER_ENABLED':'false'}):
            self.app=Flask(__name__,instance_path=self.temp.name)
            self.app.add_url_rule('/', 'home',lambda:'public')
            self.app.add_url_rule('/_test/community', endpoint='community.discussion', view_func=lambda: 'public')
            for endpoint in ['trend_finder','plug_page','trends_page','sunday_page','sunday_results_page','conspiracy_dungeon_page','scout4.teams_page','scout4.players_page','scout4.ratings_page','sunday_scout.sunday_scout_page','fans.fantasy']:
                self.app.add_url_rule('/'+endpoint,endpoint,lambda:'public')
            self.app.add_url_rule('/matchup/<game_id>','fans.matchup',lambda game_id:'public')
            init_membership(self.app)
        self.app.config.update(NEWSLETTER_AUTO_DRAFT_ENABLED=False,TESTING=True,RESEND_API_KEY='fake-test-key',NEWSLETTER_ADDRESS='Test address only',NEWSLETTER_ENABLED=False)
        with self.app.app_context():
            with db():
                for email,opt,frequency in [('owner@example.com',1,'weekly'),('weekly@example.com',1,'weekly'),('monthly@example.com',1,'monthly'),('out@example.com',0,'weekly')]:
                    db().execute('INSERT INTO members(email,password_hash,newsletter_opt_in,newsletter_frequency) VALUES(?,?,?,?)',(email,'unused',opt,frequency))
                db().execute('INSERT INTO site_owners VALUES(1)')
        self.client=self.app.test_client()
        self.login_owner()

    def tearDown(self):
        self.temp.cleanup()

    def login_owner(self):
        with self.client.session_transaction() as session:
            session['member_id']=1
            session['member_version']=0

    def csrf(self,path='/newsletter/manage'):
        response=self.client.get(path)
        return re.search('name="csrf_token" value="([^"]+)"',response.text).group(1)

    def draft(self,**changes):
        data={'subject':'Weekly prediction highlights','frequency':'weekly','predictions':'Published prediction highlights with saved evidence.','matchups':'Upcoming games','trends':'Notable trends','csrf_token':self.csrf()}
        data.update(changes)
        return self.client.post('/newsletter/manage',data=data)

    def approved_issue(self):
        response=self.draft();issue_id=int(response.location.rsplit('/',1)[1])
        token=self.csrf('/newsletter/issues/'+str(issue_id))
        self.assertEqual(self.client.post(f'/newsletter/issues/{issue_id}/approve',data={'csrf_token':token}).status_code,302)
        return issue_id

    def provider(self):
        from io import BytesIO
        return BytesIO(b'{"id":"provider-123"}')

    def test_owner_only_and_csrf(self):
        self.assertEqual(self.client.post('/newsletter/manage',data={}).status_code,400)
        self.client=self.app.test_client()
        self.assertEqual(self.client.get('/newsletter/manage').status_code,403)
        with self.client.session_transaction() as session:session['member_id']=2
        self.assertEqual(self.client.get('/newsletter/manage').status_code,403)

    def test_draft_validation_preview_order_and_escape(self):
        self.assertEqual(self.draft(frequency='daily').status_code,400)
        self.assertEqual(self.draft(predictions='short').status_code,400)
        response=self.draft(predictions='<script>alert(1)</script> Prediction evidence.')
        preview=self.client.get(response.location+'/preview')
        self.assertEqual(preview.status_code,200)
        self.assertIn('&lt;script&gt;',preview.text)
        self.assertNotIn('<script>',preview.text)
        self.assertLess(preview.text.index('&lt;script&gt;'), preview.text.index('Upcoming games'))
        self.assertEqual(preview.headers['Cache-Control'],'no-store')

    def test_opt_in_frequency_and_duplicate_protection(self):
        issue_id=self.approved_issue()
        with self.app.app_context(),patch('newsletter.urlopen',side_effect=lambda *a,**k:self.provider()) as provider,patch('newsletter.time.sleep'):
            self.app.config['NEWSLETTER_ENABLED']=True
            self.assertEqual(send_issue(issue_id),(2,0,0))
            self.assertEqual(send_issue(issue_id),(0,0,0))
            self.assertEqual(provider.call_count,2)
            emails=[json.loads(call.args[0].data)['to'][0] for call in provider.call_args_list]
            self.assertEqual(set(emails),{'owner@example.com','weekly@example.com'})
            payload=json.loads(provider.call_args.args[0].data)
            self.assertIn('List-Unsubscribe-Post',payload['headers'])
            self.assertIn('Test address only',payload['text'])

    def test_drafts_edit_until_approved(self):
        response=self.draft();path=response.location
        csrf=self.csrf(path+'/edit')
        updated=self.client.post(path+'/edit',data={'subject':'Updated prediction highlights','frequency':'monthly','predictions':'Updated published prediction evidence.','csrf_token':csrf})
        self.assertEqual(updated.status_code,302)
        self.assertIn('Updated prediction highlights',self.client.get(path).text)
        self.client.post(path+'/approve',data={'csrf_token':self.csrf(path)})
        self.assertEqual(self.client.get(path+'/edit').status_code,409)

    def test_manual_unsubscribe_requires_csrf(self):
        with self.app.app_context():token=signer().dumps(2)
        path='/newsletter/unsubscribe/'+token
        response=self.client.get(path)
        csrf=re.search('name="csrf_token" value="([^\"]+)"',response.text).group(1)
        self.assertEqual(self.client.post(path,data={'csrf_token':csrf}).status_code,200)
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT newsletter_opt_in FROM members WHERE id=2').fetchone()[0],0)

    def test_disabled_sending_dry_run_and_no_email_on_approval(self):
        with patch('newsletter.urlopen') as provider:
            issue_id=self.approved_issue()
            with self.app.app_context():
                with self.assertRaises(ValueError):send_issue(issue_id)
            result=self.app.test_cli_runner().invoke(args=['newsletter-send',str(issue_id)])
            self.assertEqual(result.exit_code,0)
            self.assertIn('No email sent',result.output)
            self.assertEqual(provider.call_count,0)
        self.app.config.update(NEWSLETTER_ENABLED=True,NEWSLETTER_ADDRESS='')
        result=self.app.test_cli_runner().invoke(args=['newsletter-send',str(issue_id),'--send'])
        self.assertNotEqual(result.exit_code,0)

    def test_unsubscribe_get_is_safe_and_post_suppresses_without_login(self):
        with self.app.app_context():token=signer().dumps(2)
        client=self.app.test_client();path='/newsletter/unsubscribe/'+token
        self.assertEqual(client.get(path).status_code,200)
        with self.app.app_context():self.assertEqual(db().execute('SELECT newsletter_opt_in FROM members WHERE id=2').fetchone()[0],1)
        self.assertEqual(client.post(path,data={}).status_code,400)
        self.assertEqual(client.post(path,data={'List-Unsubscribe':'One-Click'}).status_code,200)
        self.assertEqual(client.post(path,data={'List-Unsubscribe':'One-Click'}).status_code,200)
        with self.app.app_context():self.assertEqual(db().execute('SELECT newsletter_opt_in FROM members WHERE id=2').fetchone()[0],0)
        self.assertEqual(client.get('/newsletter/unsubscribe/bad-token').status_code,400)

    def test_uncertain_retry_uses_identical_key_and_payload(self):
        from urllib.error import URLError
        issue_id=self.approved_issue();self.app.config['NEWSLETTER_ENABLED']=True
        with self.app.app_context(),patch('newsletter.time.sleep'):
            with patch('newsletter.urlopen',side_effect=URLError('test outage')) as failed:
                self.assertEqual(send_issue(issue_id),(0,0,2))
                request_before=failed.call_args_list[0].args[0]
            with patch('newsletter.urlopen',side_effect=lambda *a,**k:self.provider()) as retried:
                self.assertEqual(send_issue(issue_id),(2,0,0))
                request_after=retried.call_args_list[0].args[0]
            self.assertEqual(request_before.data,request_after.data)
            self.assertEqual(request_before.get_header('Idempotency-key'),request_after.get_header('Idempotency-key'))

    def test_opt_out_rechecked_before_retry_and_audience_is_frozen(self):
        from urllib.error import URLError
        issue_id=self.approved_issue();self.app.config['NEWSLETTER_ENABLED']=True
        with self.app.app_context(),patch('newsletter.time.sleep'):
            with patch('newsletter.urlopen',side_effect=URLError('test outage')):send_issue(issue_id)
            with db():
                db().execute('UPDATE members SET newsletter_opt_in=0 WHERE id=2')
                db().execute('INSERT INTO members(email,password_hash,newsletter_opt_in) VALUES("late@example.com","unused",1)')
            with patch('newsletter.urlopen',side_effect=lambda *a,**k:self.provider()) as provider:
                self.assertEqual(send_issue(issue_id),(1,1,0))
                self.assertEqual(provider.call_count,1)

    def test_cancellation_and_expired_idempotency_window(self):
        from urllib.error import URLError
        issue_id=self.approved_issue();self.app.config['NEWSLETTER_ENABLED']=True
        with self.app.app_context(),patch('newsletter.time.sleep'):
            with patch('newsletter.urlopen',side_effect=URLError('test outage')):send_issue(issue_id)
            with db():db().execute('UPDATE newsletter_deliveries SET attempted_at=0')
            with patch('newsletter.urlopen') as provider:
                self.assertEqual(send_issue(issue_id),(0,0,2));self.assertEqual(provider.call_count,0)
        token=self.csrf('/newsletter/issues/'+str(issue_id))
        self.client.post(f'/newsletter/issues/{issue_id}/cancel',data={'csrf_token':token})
        with self.app.app_context():
            with self.assertRaises(ValueError):send_issue(issue_id)

    def test_live_cli_works_without_request_context(self):
        issue_id=self.approved_issue();self.app.config['NEWSLETTER_ENABLED']=True
        with patch('newsletter.urlopen',side_effect=lambda *a,**k:self.provider()),patch('newsletter.time.sleep'):
            result=self.app.test_cli_runner().invoke(args=['newsletter-send',str(issue_id),'--send'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertIn('Provider accepted: 2',result.output)


if __name__=='__main__':unittest.main()
