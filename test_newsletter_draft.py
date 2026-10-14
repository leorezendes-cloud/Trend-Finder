import csv,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import test_newsletter
from membership import db
from newsletter import generate_draft
from newsletter_draft import build_draft, period_key


class DraftEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.now=datetime(2030,10,15,12,tzinfo=timezone.utc)
        row=dict(game_id='2030_06_A_B',gameday='2030-10-17',gametime='20:15',away_team='A',home_team='B',away_score='',home_score='',spread_line='99',location='Home')
        with (self.root/'nfl_games.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=row);writer.writeheader();writer.writerow(row)
        self.record={'game_id':row['game_id'],'away_team':'A','home_team':'B','kickoff_utc':'2030-10-18T00:15:00Z','sealed_at_utc':'2030-10-15T11:00:00Z',
            'quote':{'line':3,'captured_at_utc':'2030-10-15T10:00:00Z'},'components':{'Blend':{'pick':'A','ats_edge':1.5,'away_margin':-1.5}}}
        folder=self.root/'data/scout4/blend/predictions';folder.mkdir(parents=True);self.path=folder/'game.json';self.save()

    def save(self):self.path.write_text(json.dumps(self.record))
    def tearDown(self):self.temp.cleanup()

    def test_saved_forecast_not_recomputed_and_source_files_unchanged(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        sections,metadata=build_draft(self.root,self.now)
        self.assertIn('A +3',sections['predictions']);self.assertNotIn('A +99',sections['predictions'])
        self.assertIn('away scoring margin -1.5',sections['predictions'])
        self.assertIn('A +3',sections['matchups']);self.assertNotIn('A +99',sections['matchups'])
        self.assertEqual(len(metadata['sources']),2)
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_future_seal_team_mismatch_and_started_forecasts_are_excluded(self):
        self.record['sealed_at_utc']='2030-10-15T13:00:00Z';self.save()
        self.assertIn('No eligible',build_draft(self.root,self.now)[0]['predictions'])
        self.record['sealed_at_utc']='2030-10-15T11:00:00Z';self.record['away_team']='C';self.save()
        self.assertIn('No eligible',build_draft(self.root,self.now)[0]['predictions'])
        self.record['away_team']='A';self.save()
        self.assertIn('No eligible',build_draft(self.root,self.now+timedelta(days=5))[0]['predictions'])

    def test_malformed_file_missing_data_and_stale_quotes_are_honest(self):
        self.record['quote']['captured_at_utc']='2030-10-13T10:00:00Z';self.save()
        self.assertIn('over 24 hours old',build_draft(self.root,self.now)[0]['predictions'])
        self.path.write_text('{bad')
        sections,metadata=build_draft(self.root,self.now)
        self.assertIn('No eligible',sections['predictions']);self.assertTrue(metadata['warnings'])
        (self.root/'nfl_games.csv').unlink()
        self.assertIn('No upcoming',build_draft(self.root,self.now)[0]['matchups'])

    def test_historical_counts_exclude_pushes_from_rate(self):
        with (self.root/'nfl_games.csv').open() as stream:rows=list(csv.DictReader(stream))
        for index in range(34):
            row=dict(rows[0],game_id=f'history{index}',gameday='2030-10-10',home_score='20',away_score='20' if index<20 else '14' if index<30 else '17',spread_line='3')
            rows.append(row)
        with (self.root/'nfl_games.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        sections,_=build_draft(self.root,self.now)
        self.assertIn('20-10-4 ATS',sections['trends'])
        self.assertIn('66.7% covers across 30 decisions',sections['trends'])

    def test_eastern_week_period_boundary(self):
        self.assertEqual(period_key('weekly',datetime(2030,10,14,1,tzinfo=timezone.utc)),'2030-W41')
        self.assertEqual(period_key('weekly',datetime(2030,10,14,5,tzinfo=timezone.utc)),'2030-W42')


class DraftWorkflowTests(unittest.TestCase):
    setUp = test_newsletter.NewsletterTests.setUp
    tearDown = test_newsletter.NewsletterTests.tearDown
    login_owner = test_newsletter.NewsletterTests.login_owner
    def test_generate_once_preserves_edits_and_creates_next_week(self):
        sections={'predictions':'Published predictions with saved evidence.','matchups':'Games','trends':'Trends','updates':''}
        now=datetime(2030,10,15,12,tzinfo=timezone.utc)
        with self.app.app_context(),patch('newsletter_draft.build_draft',return_value=(sections,{'generated_at':now.isoformat(),'warnings':[],'sources':{}})),patch('newsletter.urlopen') as mail:
            first=generate_draft(1,now=now)
            with db():db().execute('UPDATE newsletter_issues SET sections=? WHERE id=?',(json.dumps(dict(sections,predictions='My edited highlights')),first))
            self.assertEqual(generate_draft(1,now=now),first)
            self.assertIn('My edited',db().execute('SELECT sections FROM newsletter_issues WHERE id=?',(first,)).fetchone()[0])
            self.assertNotEqual(generate_draft(1,now=now+timedelta(days=7)),first)
            self.assertEqual(mail.call_count,0)

    def test_unedited_draft_refreshes_but_approved_issue_stays_frozen(self):
        now=datetime(2030,10,15,12,tzinfo=timezone.utc)
        old={'predictions':'Earlier published predictions','matchups':'','trends':'','updates':''}
        new=dict(old,predictions='Latest published predictions')
        meta={'generated_at':now.isoformat(),'warnings':[],'sources':{}}
        with self.app.app_context(),patch('newsletter_draft.build_draft',return_value=(old,meta)):
            issue_id=generate_draft(1,now=now)
        with self.app.app_context(),patch('newsletter_draft.build_draft',return_value=(new,dict(meta))):
            self.assertEqual(generate_draft(1,now=now),issue_id)
            self.assertIn('Latest',db().execute('SELECT sections FROM newsletter_issues WHERE id=?',(issue_id,)).fetchone()[0])
            with db():db().execute("UPDATE newsletter_issues SET status='approved' WHERE id=?",(issue_id,))
        with self.app.app_context(),patch('newsletter_draft.build_draft',return_value=(old,dict(meta))) as builder:
            generate_draft(1,now=now)
            self.assertEqual(builder.call_count,0)

    def test_owner_review_page_and_cli_prepare_drafts_without_email(self):
        self.app.config['NEWSLETTER_AUTO_DRAFT_ENABLED']=True
        sections={'predictions':'Published predictions with saved evidence.','matchups':'Games','trends':'Trends','updates':''}
        with patch('newsletter_draft.build_draft',return_value=(sections,{'generated_at':'2030-10-15','warnings':[],'sources':{}})),patch('newsletter.urlopen') as mail:
            self.assertEqual(self.client.get('/newsletter/manage').status_code,200)
            self.assertEqual(self.client.get('/newsletter/manage').status_code,200)
            with self.app.app_context():
                self.assertEqual(db().execute('SELECT COUNT(*) FROM newsletter_generated').fetchone()[0],2)
            result=self.app.test_cli_runner().invoke(args=['newsletter-generate'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('No email sent',result.output)
            self.assertEqual(mail.call_count,0)


if __name__=='__main__':unittest.main()
