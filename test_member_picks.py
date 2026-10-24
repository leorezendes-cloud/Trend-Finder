import csv,re,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import test_newsletter
from membership import db
from member_picks import sync_results,grade


class MemberPicksTests(unittest.TestCase):
    login_owner=test_newsletter.NewsletterTests.login_owner
    tearDown=test_newsletter.NewsletterTests.tearDown

    def setUp(self):
        test_newsletter.NewsletterTests.setUp(self)
        self.now=datetime(2030,10,16,12,tzinfo=timezone.utc)
        clock_patch=patch('member_picks.now_utc',return_value=self.now);self.clock=clock_patch.start();self.addCleanup(clock_patch.stop)
        self.root=Path(self.temp.name);self.app.config['PICKS_SOURCE_ROOT']=str(self.root)
        self.rows=[dict(game_id='2030_06_A_B',season='2030',week='6',game_type='REG',gameday='2030-10-17',gametime='20:15',away_team='A',home_team='B',away_score='',home_score='',result='',spread_line='3',total_line='40')]
        self.write_schedule()
        # Shared navigation needs these routes in the isolated test app.
        for endpoint in ('discussion', 'save_identity', 'upload_identity_photo'):
            name = 'community.' + endpoint
            if name not in self.app.view_functions:
                self.app.add_url_rule(
                    '/fixture-community/' + endpoint,
                    name, lambda: ''
                )
        if 'community.avatar_image' not in self.app.view_functions:
            self.app.add_url_rule(
                '/fixture-avatar/<int:member_id>',
                'community.avatar_image',
                lambda member_id: ''
            )

    def write_schedule(self):
        with (self.root/'nfl_games.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=self.rows[0]);writer.writeheader();writer.writerows(self.rows)

    def token(self,path,client=None):
        response=(client or self.client).get(path)
        return re.search('name="csrf_token" value="([^"]+)"',response.text).group(1)

    def sheet(self,publish=True):
        # Frozen DB fixture for grading/locking tests; public UI is read-only.
        with self.app.app_context():
            with db():
                cursor=db().execute('INSERT INTO pick_weeks(season,week,owner_id,published_at) VALUES(?,?,?,?)',(2030,6,1,self.now.isoformat() if publish else None))
                sheet=cursor.lastrowid
                cursor=db().execute('INSERT INTO pick_games(week_id,game_id,away,home,kickoff_at,lock_at,away_spread,total,line_source) VALUES(?,?,?,?,?,?,?,?,?)',
                    (sheet,'2030_06_A_B','A','B','2030-10-18T00:15:00+00:00','2030-10-18T00:15:00+00:00',3,40,'Wednesday snapshot'))
                game=cursor.lastrowid
        return game,f'/picks/admin/weeks/{sheet}'

    def member(self,member_id=2):
        client=self.app.test_client()
        with client.session_transaction() as session:session['member_id']=member_id;session['member_version']=0
        return client

    def pick(self,client,game_id,**choices):
        data=dict(su='A',ats='A',ou='Over',csrf_token=self.token('/members/preferences',client));data.update(choices)
        return client.post(f'/picks/games/{game_id}',data=data)

    def test_access_control_csrf_and_private_drafts(self):
        guest=self.app.test_client()
        self.assertEqual(guest.get('/picks/').location,'/members/login')
        self.assertEqual(self.member().get('/picks/admin').status_code,403)
        self.assertEqual(self.client.post('/picks/admin',data={}).status_code,405)
        game_id,_=self.sheet(publish=False)
        client=self.member()
        self.assertNotIn('A at B',client.get('/picks/').text)
        self.assertEqual(client.post(f'/picks/games/{game_id}',data={'csrf_token':self.token('/picks/',client) if 'name="csrf_token"' in client.get('/picks/').text else self.token('/members/preferences',client)}).status_code,404)

    def test_shared_lines_immutable_and_member_records_are_private(self):
        game_id,path=self.sheet()
        client=self.member();self.assertEqual(self.pick(client,game_id).status_code,302)
        other=self.member(3)
        self.assertEqual(self.pick(other,game_id,su='B',ats='B',ou='Under').status_code,302)
        self.assertIn('A +3 · B -3',client.get('/picks/').text)
        data={'csrf_token':self.token('/members/preferences'),f'spread_{game_id}':10,f'total_{game_id}':50,'action':'publish'}
        self.assertEqual(self.client.post(path,data=data).status_code,405)
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT away_spread FROM pick_games').fetchone()[0],3)
            self.assertEqual(db().execute('SELECT su FROM member_picks WHERE member_id=2').fetchone()[0],'A')
            self.assertEqual(db().execute('SELECT su FROM member_picks WHERE member_id=3').fetchone()[0],'B')

    def test_edits_before_kickoff_invalid_choices_and_lock_at_exact_kickoff(self):
        game_id,_=self.sheet();client=self.member()
        self.assertEqual(self.pick(client,game_id,su='Invalid').status_code,400)
        self.assertEqual(self.pick(client,game_id).status_code,302)
        self.assertEqual(self.pick(client,game_id,su='B').status_code,302)
        self.clock.return_value=datetime(2030,10,18,0,15,tzinfo=timezone.utc)
        self.assertEqual(self.pick(client,game_id).status_code,409)
        with self.app.app_context():self.assertEqual(db().execute('SELECT su FROM member_picks').fetchone()[0],'B')

    def test_final_grading_uses_published_lines_and_is_idempotent(self):
        game_id,_=self.sheet();client=self.member();self.pick(client,game_id)
        self.rows[0].update(away_score='20',home_score='22',result='2',spread_line='99',total_line='100');self.write_schedule()
        self.clock.return_value=datetime(2030,10,18,5,tzinfo=timezone.utc)
        with self.app.app_context():
            sync_results();sync_results()
            pick=db().execute('SELECT * FROM member_picks').fetchone()
            self.assertEqual((pick['su_result'],pick['ats_result'],pick['ou_result']),('Loss','Win','Win'))
            self.assertEqual(db().execute('SELECT COUNT(*) FROM member_picks').fetchone()[0],1)
        html=client.get('/picks/').text
        self.assertIn('Final: A 20',html)
        self.assertNotIn('A +99',html)

    def test_tie_and_push_grading_and_incomplete_results(self):
        game_id,path=self.sheet(publish=False)
        with self.app.app_context():
            with db():
                db().execute('UPDATE pick_games SET away_spread=0 WHERE id=?',(game_id,))
                db().execute('UPDATE pick_weeks SET published_at=?',(self.now.isoformat(),))
        client=self.member();self.pick(client,game_id)
        self.clock.return_value=datetime(2030,10,18,5,tzinfo=timezone.utc)
        self.rows[0].update(away_score='20',home_score='20',result='');self.write_schedule()
        with self.app.app_context():
            sync_results();self.assertEqual(db().execute('SELECT su_result FROM member_picks').fetchone()[0],'Pending')
        self.rows[0]['result']='0';self.write_schedule()
        with self.app.app_context():
            sync_results();pick=db().execute('SELECT * FROM member_picks').fetchone()
            self.assertEqual((pick['su_result'],pick['ats_result'],pick['ou_result']),('Tie','Push','Push'))

    def test_postponed_and_missing_games_do_not_unlock_or_guess_results(self):
        game_id,_=self.sheet();client=self.member();self.pick(client,game_id)
        self.clock.return_value=datetime(2030,10,18,1,tzinfo=timezone.utc)
        self.assertEqual(self.pick(client,game_id).status_code,409)
        self.rows[0]['gameday']='2030-10-25';self.write_schedule()
        self.assertEqual(self.pick(client,game_id).status_code,409)
        self.rows[0]['game_id']='different';self.write_schedule()
        with self.app.app_context():sync_results();self.assertEqual(db().execute('SELECT su_result FROM member_picks').fetchone()[0],'Pending')

    def test_owner_void_cancellation_excluded_from_win_loss(self):
        game_id,path=self.sheet();client=self.member();self.pick(client,game_id)
        token=self.token(path)
        self.assertEqual(self.client.post(f'/picks/admin/games/{game_id}/void',data={'csrf_token':token,'reason':'Game canceled and will not be played.'}).status_code,302)
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT su_result FROM member_picks').fetchone()[0],'Void')
        self.assertEqual(self.pick(client,game_id).status_code,409)


    def test_void_grades_stay_unchanged_after_repeated_sync(self):
        game_id, review_path = self.sheet()
        client = self.member()
        self.assertEqual(self.pick(client, game_id).status_code, 302)

        response = self.client.post(
            f'/picks/admin/games/{game_id}/void',
            data={
                'csrf_token': self.token(review_path),
                'reason': 'Game canceled and will not be played.'
            }
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            connection = db()
            before = [
                tuple(row) for row in connection.execute(
                    'SELECT * FROM member_picks'
                )
            ]
            writes = []
            connection.set_trace_callback(
                lambda statement: writes.append(statement)
            )
            try:
                sync_results()
                sync_results()
            finally:
                connection.set_trace_callback(None)

            after = [
                tuple(row) for row in connection.execute(
                    'SELECT * FROM member_picks'
                )
            ]

            self.assertEqual(before, after)
            self.assertFalse([
                sql for sql in writes
                if sql.lstrip().upper().startswith('UPDATE MEMBER_PICKS')
            ])

    def test_manual_line_entry_is_unavailable(self):
        game_id,path=self.sheet(publish=False)
        before=(self.root/'nfl_games.csv').read_bytes()
        self.assertNotIn('type="number"',self.client.get('/picks/admin').text)
        self.assertNotIn('name="spread_',self.client.get(path).text)
        self.assertEqual(self.client.post(path,data={'action':'publish'}).status_code,405)
        self.assertEqual((self.root/'nfl_games.csv').read_bytes(),before)


if __name__=='__main__':unittest.main()
