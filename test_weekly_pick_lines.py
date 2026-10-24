import csv,json,sys
from types import SimpleNamespace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import unittest
import test_member_picks
from member_picks import kickoff
from weekly_pick_lines import freeze_snapshot,publish_saved_snapshot,snapshot_path,scheduled_capture
from membership import db


class AutomaticLinesTests(unittest.TestCase):
    def setUp(self):
        test_member_picks.MemberPicksTests.setUp(self)
    tearDown=test_member_picks.MemberPicksTests.tearDown
    login_owner=test_member_picks.MemberPicksTests.login_owner
    write_schedule=test_member_picks.MemberPicksTests.write_schedule
    member=test_member_picks.MemberPicksTests.member
    pick=test_member_picks.MemberPicksTests.pick
    token=test_member_picks.MemberPicksTests.token
    def quotes(self,observed=None):
        observed=observed or self.now
        game=self.rows[0]
        quote=dict(game_id=game['game_id'],away_team='A',home_team='B',kickoff_utc=kickoff(game).isoformat(),captured_at_utc=observed.isoformat(),market='Spread',side_a='A',side_b='B',line_a='2.5',line_b='-2.5')
        rows=[quote,dict(quote,market='Total',side_a='Over',side_b='Under',line_a='44.5',line_b='44.5')]
        with (self.root/'public_money_snapshots.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=quote);writer.writeheader();writer.writerows(rows)

    def test_automatic_snapshot_and_publication_without_owner_input(self):
        self.quotes()
        report=freeze_snapshot(self.root,self.now)
        self.assertEqual(report['state'],'ready')
        response=self.member().get('/picks/')
        self.assertEqual(response.status_code,200)
        self.assertIn('A +2.5 · B -2.5',response.text)
        self.assertIn('44.5',response.text)
        self.assertIn('Wednesday 8 a.m. ET snapshot',response.text)
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM pick_weeks').fetchone()[0],1)
            game=db().execute('SELECT * FROM pick_games').fetchone()
        self.assertEqual(self.pick(self.member(),game['id']).status_code,302)
        # Subsequent quotes and another page visit cannot change published lines.
        self.quotes(self.now+timedelta(hours=1))
        again=freeze_snapshot(self.root,self.now+timedelta(hours=1))
        self.assertEqual(again,report)
        self.member().get('/picks/')
        with self.app.app_context():self.assertEqual(db().execute('SELECT away_spread FROM pick_games').fetchone()[0],2.5)


    def test_owner_can_see_pending_capture_status(self):
        logs = self.root / 'logs'
        logs.mkdir(exist_ok=True)
        (logs / 'weekly_lines_status.json').write_text(
            json.dumps({
                'state': 'pending',
                'reason': 'Fresh verified lines required',
                'missing': ['2030_06_A_B']
            })
        )
        response = self.client.get('/picks/admin')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Latest weekly capture', response.text)
        self.assertIn('Fresh verified lines required', response.text)
        self.assertIn('1 game(s) missing', response.text)
        self.assertNotIn('This week uses a one-time exception',
                         response.text)

    def test_missing_quotes_prevent_publication_and_schedule_fallback(self):
        self.assertEqual(freeze_snapshot(self.root,self.now)['state'],'pending')
        with self.app.app_context():
            self.assertFalse(publish_saved_snapshot(db(),self.root,self.now))
            self.assertEqual(db().execute('SELECT COUNT(*) FROM pick_weeks').fetchone()[0],0)

    def test_delayed_job_cannot_backdate_newer_lines(self):
        self.quotes(self.now+timedelta(hours=1))
        self.assertEqual(freeze_snapshot(self.root,self.now+timedelta(hours=2))['state'],'pending')
        self.quotes(self.now-timedelta(minutes=5))
        report=freeze_snapshot(self.root,self.now+timedelta(hours=2))
        self.assertEqual(report['state'],'ready')
        self.assertEqual(report['games'][0]['spread_time'],(self.now-timedelta(minutes=5)).isoformat())

    def test_before_cutoff_and_stale_evidence_are_rejected(self):
        self.quotes()
        self.assertEqual(freeze_snapshot(self.root,self.now-timedelta(seconds=1))['state'],'pending')
        self.quotes(self.now-timedelta(days=2))
        self.assertEqual(freeze_snapshot(self.root,self.now+timedelta(hours=2))['state'],'pending')

    def test_exception_uses_now_and_cannot_roll_into_following_week(self):
        self.quotes(self.now+timedelta(hours=1))
        report=freeze_snapshot(self.root,self.now+timedelta(hours=2),exception=True)
        self.assertTrue(report['exception'])
        self.assertEqual(report['state'],'ready')
        self.assertEqual(report['games'][0]['spread_time'],(self.now+timedelta(hours=1)).isoformat())
        self.clock.return_value=self.now+timedelta(hours=2)
        self.assertIn('This week’s exception',self.member().get('/picks/').text)
        self.rows[0].update(week='7',gameday='2030-10-24',game_id='2030_07_A_B');self.write_schedule()
        with self.app.app_context():self.assertFalse(publish_saved_snapshot(db(),self.root,self.now+timedelta(days=7)))

    def test_changed_kickoff_prevents_automatic_publication(self):
        self.quotes();freeze_snapshot(self.root,self.now)
        self.rows[0]['gametime']='19:15';self.write_schedule()
        with self.app.app_context():self.assertFalse(publish_saved_snapshot(db(),self.root,self.now))

    def test_scheduled_worker_captures_at_boundary_and_publishes(self):
        self.quotes()
        with patch('weekly_pick_lines.datetime') as clock, patch('scheduled_ats_capture.run',return_value=0) as collector, patch.dict(sys.modules,{'app':SimpleNamespace(app=self.app)}):
            clock.now.return_value=self.now
            scheduled_capture(self.root)
            collector.assert_called_once_with(self.root)
        with self.app.app_context():self.assertIsNotNone(db().execute('SELECT published_at FROM pick_weeks').fetchone()[0])
        self.assertEqual(json.loads((self.root/'logs/weekly_lines_status.json').read_text())['state'],'ready')

    def test_saved_exception_does_not_trigger_new_market_collection(self):
        self.quotes();report=freeze_snapshot(self.root,self.now,exception=True)
        with patch('weekly_pick_lines.datetime') as clock,patch('scheduled_ats_capture.run') as collector,patch.dict(sys.modules,{'app':SimpleNamespace(app=self.app)}):
            clock.now.return_value=self.now
            scheduled_capture(self.root);scheduled_capture(self.root)
            collector.assert_not_called()
        self.assertEqual(json.loads(snapshot_path(self.root,2030,6).read_text()),report)
        with self.app.app_context():self.assertEqual(db().execute('SELECT COUNT(*) FROM pick_games').fetchone()[0],1)

    def test_late_worker_never_fetches_later_lines_as_wednesday_snapshot(self):
        self.quotes(self.now+timedelta(hours=1))
        with patch('weekly_pick_lines.datetime') as clock,patch('scheduled_ats_capture.run') as collector:
            clock.now.return_value=self.now+timedelta(hours=2)
            scheduled_capture(self.root)
            collector.assert_not_called()
        self.assertEqual(json.loads((self.root/'logs/weekly_lines_status.json').read_text())['state'],'pending')
