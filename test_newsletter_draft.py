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
        from flask import Flask
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime(2030, 10, 16, 13, tzinfo=timezone.utc)
        self.app = Flask(__name__)
        self.app.config["PUBLIC_ORIGIN"] = "https://trendfindah.com"
        self.context = self.app.app_context()
        self.context.push()
        row = dict(game_id="2030_07_A_B", gameday="2030-10-17",
                   gametime="20:15", away_team="A", home_team="B",
                   away_score="", home_score="", spread_line="99",
                   season="2030", week="7", game_type="REG")
        with (self.root / "nfl_games.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=row)
            writer.writeheader()
            writer.writerow(row)
        legacy = self.root / "data/scout4/blend/predictions/game.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{bad old snapshot")

    def tearDown(self):
        self.context.pop()
        self.temp.cleanup()

    def test_published_scout_snapshot_is_used_without_source_mutation(self):
        url = "https://trendfindah.com/the-plug/2030/7/A-B"
        picks = ["A @ B · Thursday\nATS: A +3 · Total: Under 40\n" + url]
        reports = ["A @ B · Thursday\nATS: A · Total: Under\n"
                   "Approved public analysis.\n" + url]
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

        with patch("newsletter_draft._plug_content",
                   return_value=(picks, reports, ["saved-v1"])), \
             patch("newsletter_draft._trends_content", return_value=([], [])):
            sections, metadata = build_draft(self.root, self.now)

        self.assertIn("Scout: ATS: A +3", sections["predictions"])
        self.assertIn("Expert's take:", sections["predictions"])
        self.assertNotIn("A +99", sections["predictions"])
        self.assertEqual(metadata["published_forecast_versions"], ["saved-v1"])
        self.assertIn("nfl_games.csv", metadata["sources"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_unmatched_public_expert_cannot_be_featured(self):
        url = "https://trendfindah.com/the-plug/2030/7/A-B"
        picks = ["A @ B · Thursday\nATS: A +3 · Total: Under 40\n" + url]
        with patch("newsletter_draft._plug_content",
                   return_value=(picks, [], ["saved-v1"])), \
             patch("newsletter_draft._trends_content", return_value=([], [])):
            sections, metadata = build_draft(self.root, self.now)

        self.assertIn("being prepared", sections["predictions"])
        self.assertNotIn("A +3", sections["predictions"])
        self.assertEqual(metadata["published_forecast_versions"], [])
        self.assertTrue(metadata["warnings"])

    def test_missing_schedule_and_legacy_files_never_invent_a_pick(self):
        (self.root / "nfl_games.csv").unlink()
        with patch("newsletter_draft._plug_content", return_value=([], [], [])), \
             patch("newsletter_draft._trends_content", return_value=([], [])):
            sections, metadata = build_draft(self.root, self.now)

        self.assertIn("being prepared", sections["predictions"])
        self.assertIn("No upcoming games", sections["matchups"])
        self.assertTrue(metadata["warnings"])

    def test_ats_trend_copy_does_not_invent_push_adjusted_rates(self):
        from newsletter_draft import _trends_content
        trend = dict(title="MIN — ATS", scope="team", kind="ats",
                     outcome="Cover", streak=2, wins=5, sample=7,
                     pushes=2, params={"research_team": "MIN"})
        with patch("active_trends.load_highlights", return_value=[trend]):
            blocks, identities = _trends_content("https://trendfindah.com", [])

        self.assertEqual(len(blocks), 1)
        self.assertEqual(len(identities), 1)
        self.assertIn("5 of Last 7 Covers", blocks[0])
        self.assertNotIn("66.7%", blocks[0])

    def test_monthly_features_close_and_high_scoring_finished_games(self):
        from newsletter_draft import _monthly_recap

        fields = [
            "game_id", "gameday", "gametime", "away_team",
            "home_team", "away_score", "home_score"
        ]
        fixtures = [
            ("close", "2030-10-08", "20:15", "NE", "CHI", "31", "30"),
            ("close", "2030-10-08", "20:15", "NE", "CHI", "80", "0"),
            ("shootout", "2030-10-10", "20:15", "KC", "BUF", "42", "39"),
            ("one_score", "2030-10-12", "20:15", "SF", "SEA", "24", "17"),
            ("blowout", "2030-10-15", "01:00", "NYJ", "MIA", "7", "48"),
            ("in_progress", "2030-10-16", "08:00", "CAR", "TB", "25", "24"),
            ("future", "2030-10-20", "20:15", "DAL", "PHI", "28", "27"),
        ]

        with (self.root / "nfl_games.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for fixture in fixtures:
                writer.writerow(dict(zip(fields, fixture)))

        sources, warnings = {}, []
        recap = _monthly_recap(
            self.root, self.now,
            "https://trendfindah.com", sources, warnings
        )

        self.assertIn("4 completed NFL games", recap)
        self.assertIn("GAME OF THE MONTH", recap)
        self.assertIn("KC 42", recap)
        self.assertIn("NE 31", recap)
        self.assertIn("SF 24", recap)
        self.assertLess(recap.index("KC 42"), recap.index("NE 31"))

        self.assertNotIn("NYJ 7", recap)
        self.assertNotIn("CAR 25", recap)
        self.assertNotIn("DAL 28", recap)
        self.assertNotIn("comeback", recap.lower())
        self.assertNotIn("overtime", recap.lower())

        self.assertEqual(recap.count("/matchup/"), 3)
        self.assertIn("/newsletter/results/2030/10?at=", recap)
        self.assertIn("nfl_games.csv", sources)

    def test_eastern_week_period_boundary(self):
        self.assertEqual(
            period_key("weekly", datetime(2030,10,16,11,59,tzinfo=timezone.utc)),
            "2030-W41"
        )
        self.assertEqual(
            period_key("weekly", datetime(2030,10,16,12,tzinfo=timezone.utc)),
            "2030-W42"
        )


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

    def test_generated_draft_and_approved_issue_remain_frozen(self):
        now=datetime(2030,10,15,12,tzinfo=timezone.utc)
        old={'predictions':'Earlier published predictions','matchups':'','trends':'','updates':''}
        new=dict(old,predictions='Latest published predictions')
        meta={'generated_at':now.isoformat(),'warnings':[],'sources':{}}
        with self.app.app_context(),patch('newsletter_draft.build_draft',return_value=(old,meta)):
            issue_id=generate_draft(1,now=now)
        with self.app.app_context(),patch('newsletter_draft.build_draft',return_value=(new,dict(meta))):
            self.assertEqual(generate_draft(1,now=now),issue_id)
            self.assertIn('Earlier published predictions',db().execute('SELECT sections FROM newsletter_issues WHERE id=?',(issue_id,)).fetchone()[0])
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
                self.assertEqual(db().execute('SELECT COUNT(*) FROM newsletter_generated').fetchone()[0],0)
            result=self.app.test_cli_runner().invoke(args=['newsletter-generate'])
            self.assertEqual(result.exit_code,0,result.output);self.assertIn('No email sent',result.output)
            self.assertEqual(mail.call_count,0)



class WednesdayDraftScheduleTests(unittest.TestCase):
    setUp = test_newsletter.NewsletterTests.setUp
    tearDown = test_newsletter.NewsletterTests.tearDown
    login_owner = test_newsletter.NewsletterTests.login_owner

    def test_wednesday_window_is_idempotent_and_never_sends(self):
        from newsletter import wednesday_draft_due, prepare_wednesday_draft
        from datetime import timedelta

        self.app.config["NEWSLETTER_AUTO_DRAFT_ENABLED"] = True
        at_nine = datetime(2030, 10, 16, 13, tzinfo=timezone.utc)
        before_nine = at_nine - timedelta(minutes=1)
        next_day = at_nine + timedelta(days=1)

        self.assertFalse(wednesday_draft_due(before_nine))
        self.assertTrue(wednesday_draft_due(at_nine))
        self.assertFalse(wednesday_draft_due(next_day))

        sections = dict(predictions="Approved public evidence",
                        trends="Trends", expert="", matchups="Games", updates="")
        metadata = dict(generated_at=at_nine.isoformat(),
                        warnings=[], sources={})
        with patch("newsletter_draft.build_draft",
                   return_value=(sections, metadata)) as builder, \
             patch("newsletter.urlopen") as provider:
            self.assertEqual(
                prepare_wednesday_draft(self.app, before_nine), "not_due"
            )
            issue = prepare_wednesday_draft(self.app, at_nine)
            self.assertIsInstance(issue, int)
            self.assertEqual(
                prepare_wednesday_draft(self.app, at_nine), "not_due"
            )
            self.assertEqual(
                prepare_wednesday_draft(self.app, next_day), "not_due"
            )
            self.assertEqual(builder.call_count, 1)
            self.assertEqual(provider.call_count, 0)

        with self.app.app_context():
            self.assertEqual(
                db().execute("SELECT COUNT(*) FROM newsletter_generated").fetchone()[0],
                1
            )




class MonthlyDraftTimingTests(unittest.TestCase):
    setUp = test_newsletter.NewsletterTests.setUp
    tearDown = test_newsletter.NewsletterTests.tearDown
    login_owner = test_newsletter.NewsletterTests.login_owner

    def test_first_day_after_nine_and_seven_day_retry_window(self):
        from zoneinfo import ZoneInfo
        from newsletter import completed_month_draft_due
        et = ZoneInfo('America/New_York')
        nov_first = datetime(2030, 11, 1, 9, tzinfo=et)
        self.assertFalse(completed_month_draft_due(nov_first - timedelta(minutes=1)))
        self.assertTrue(completed_month_draft_due(nov_first))
        self.assertTrue(completed_month_draft_due(datetime(2030, 11, 7, 9, tzinfo=et)))
        self.assertFalse(completed_month_draft_due(datetime(2030, 11, 8, 9, tzinfo=et)))

    def test_scheduler_saves_previous_month_once_without_sending(self):
        from zoneinfo import ZoneInfo
        from newsletter import prepare_completed_month_draft
        self.app.config['NEWSLETTER_AUTO_DRAFT_ENABLED'] = True
        now = datetime(2030, 11, 1, 9, tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        sections = {'predictions': 'Completed October NFL recap',
                    'trends': 'Trends', 'expert': '', 'matchups': 'Games', 'updates': ''}
        meta = {'generated_at': now.isoformat(), 'warnings': [], 'sources': {}}
        with patch('newsletter_draft.build_draft', return_value=(sections, meta)) as builder, \
             patch('newsletter.urlopen') as provider:
            issue = prepare_completed_month_draft(self.app, now)
            self.assertIsInstance(issue, int)
            self.assertEqual(prepare_completed_month_draft(self.app, now), 'not_due')
            builder.assert_called_once()
            self.assertEqual(builder.call_args.kwargs['report_month'], '2030-10')
            provider.assert_not_called()
        with self.app.app_context():
            row = db().execute('SELECT subject,frequency,status FROM newsletter_issues WHERE id=?', (issue,)).fetchone()
            self.assertEqual(row['subject'], 'The Monthly Plug · October 2030')
            self.assertEqual(row['status'], 'draft')
            self.assertEqual(row['frequency'], 'monthly')
            self.assertEqual(db().execute("SELECT period FROM newsletter_generated WHERE issue_id=?", (issue,)).fetchone()[0], '2030-10')

    def test_existing_early_monthly_issue_is_not_overwritten(self):
        from zoneinfo import ZoneInfo
        from newsletter import prepare_completed_month_draft
        now = datetime(2030, 11, 1, 9, tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        with self.app.app_context():
            with db():
                issue = db().execute("INSERT INTO newsletter_issues(subject,frequency,sections,owner_id) VALUES(?,?,?,?)", ('The Monthly Plug · October 2030','monthly','{}',1)).lastrowid
                db().execute("INSERT INTO newsletter_generated VALUES(?,?,?,?)", ('monthly','2030-10',issue,'{}'))
        with patch('newsletter_draft.build_draft') as builder:
            self.assertEqual(prepare_completed_month_draft(self.app, now), 'not_due')
            builder.assert_not_called()

    def test_weekly_subscriber_alone_qualifies_for_monthly(self):
        from zoneinfo import ZoneInfo
        from newsletter import prepare_completed_month_draft
        now = datetime(2030, 11, 1, 9, tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        self.app.config['NEWSLETTER_AUTO_DRAFT_ENABLED'] = True
        with self.app.app_context(), db():
            db().execute("UPDATE members SET newsletter_opt_in=0 WHERE newsletter_frequency='monthly'")
        with patch('newsletter_draft.build_draft', return_value=(
                {'predictions': 'Completed October recap'}, {'warnings': [], 'sources': {}})):
            self.assertIsInstance(prepare_completed_month_draft(self.app, now), int)

    def test_previous_month_scores_include_last_night_game(self):
        from newsletter_draft import _monthly_recap
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            fields = ['game_id','gameday','gametime','away_team','home_team','away_score','home_score']
            with (root/'nfl_games.csv').open('w', newline='') as fp:
                writer = csv.DictWriter(fp, fieldnames=fields)
                writer.writeheader()
                writer.writerows([
                    dict(game_id='oct31',gameday='2030-10-31',gametime='20:20',away_team='KC',home_team='BUF',away_score='40',home_score='38'),
                    dict(game_id='nov1',gameday='2030-11-01',gametime='01:00',away_team='NYJ',home_team='NE',away_score='7',home_score='35'),
                ])
            from zoneinfo import ZoneInfo
            now = datetime(2030,11,1,9,tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
            recap = _monthly_recap(root, now, 'https://trendfindah.com', {}, [], report_month='2030-10')
            self.assertIn('October 2030', recap)
            self.assertIn('KC 40', recap)
            self.assertNotIn('NYJ 7', recap)
            self.assertIn('/newsletter/results/2030/10?at=', recap)
            self.assertIn('through Oct 31', recap)


if __name__=='__main__':unittest.main()
