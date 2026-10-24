"""Isolated Phase 1 league integration checks; no site data or network used."""
import itertools
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from jinja2 import ChoiceLoader, DictLoader
from werkzeug.security import generate_password_hash
from membership import init_membership
from huddle_leagues import standings


class LeagueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'members.sqlite3')
        self.app = self.make_app()
        self.client = self.app.test_client()
        with self.connection() as c:
            password = generate_password_hash('long secure password')
            c.executemany('INSERT INTO members(id,email,password_hash) VALUES(?,?,?)',
                          [(i, f'private{i}@example.com', password) for i in range(1, 4)])
        self.login(1)
        self.clock = patch('huddle_leagues.now_utc', return_value=datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def make_app(self):
        app = Flask(__name__, instance_path=self.temp.name)
        app.add_url_rule('/', 'home', lambda: 'home')
        app.add_url_rule('/community', 'community.discussion', lambda: 'The Huddle')
        app.add_url_rule('/matchup/<game_id>', 'fans.matchup', lambda game_id: game_id)
        with patch.dict('os.environ', {'TREND_FINDAH_DATABASE': self.path,
                                     'TREND_FINDAH_SECRET_KEY': 'isolated-test-secret'}):
            init_membership(app)
        app.config.update(TESTING=True, PICKS_SOURCE_ROOT=self.temp.name, RESEND_API_KEY='')
        app.jinja_loader = ChoiceLoader([DictLoader({'_site_navigation.html': '', '_branding_head.html': ''}), app.jinja_loader])
        return app

    def connection(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        return c

    def login(self, member):
        with self.client.session_transaction() as s:
            s.clear()
            if member:
                s['member_id'] = member
                s['member_version'] = 0
            s['_csrf'] = 'test-token'

    def post(self, path, **data):
        return self.client.post(path, data={'csrf_token': 'test-token', **data})

    def create(self, categories=('su', 'ats', 'ou')):
        response = self.post('/huddle/leagues/create', name='Friends League', categories=list(categories))
        self.assertEqual(response.status_code, 303)
        with self.connection() as c:
            return c.execute('SELECT * FROM huddle_leagues ORDER BY id DESC').fetchone()

    def join(self, league, member=2):
        self.login(member)
        return self.post('/huddle/leagues/join/' + league['invite_token'])

    def seed(self, league, results=('Win', 'Win', 'Win'), lock='2026-10-02T12:00:00+00:00',
             week=5, season=2026, finals=True, void=None, published=True):
        with self.connection() as c:
            c.execute('INSERT OR IGNORE INTO pick_weeks(season,week,owner_id,published_at) VALUES(?,?,1,?)',
                      (season, week, '2026-10-01' if published else None))
            wid = c.execute('SELECT id FROM pick_weeks WHERE season=? AND week=?', (season, week)).fetchone()[0]
            gid = c.execute('''INSERT INTO pick_games(week_id,game_id,away,home,kickoff_at,lock_at,
                away_spread,total,line_source,away_final,home_final,result_at,void_reason)
                VALUES(?,lower(hex(randomblob(8))),'NE','BUF',?,?,3,44,'fixed snapshot',?,?,?,?)''',
                (wid, lock, lock, 24 if finals else None, 17 if finals else None,
                 '2026-10-03T00:00:00+00:00' if finals else None, void)).lastrowid
            c.executemany('''INSERT INTO member_picks(member_id,game_id,su,ats,ou,
                su_result,ats_result,ou_result,updated_at) VALUES(?,?,'NE','NE','Over',?,?,?,?)''',
                [(m, gid, *results, '2026-10-01T01:00:00+00:00') for m in (1, 2, 3)])
        return wid, gid

    def scores(self, league, week=None, season=2026):
        with self.connection() as c:
            return standings(c, league, season, week, datetime(2026, 11, 1, tzinfo=timezone.utc))

    def test_all_category_combinations(self):
        with patch('huddle_leagues.allow_attempt', return_value=True):
            for count in range(1, 4):
                for categories in itertools.combinations(('su', 'ats', 'ou'), count):
                    league = self.create(categories)
                    self.assertEqual(sum(league[c + '_enabled'] for c in ('su', 'ats', 'ou')), count)
                    self.assertEqual(len(league['invite_token']), 43)
                    self.seed(league)
                    self.assertEqual(self.scores(league)[0]['points'], count)
                    # Keep each category combination independent.
                    with self.connection() as c:
                        c.execute('DELETE FROM member_picks')
                        c.execute('DELETE FROM pick_games')

    def test_invalid_forms_and_csrf(self):
        for categories in ([], ['bad'], ['su', 'su']):
            self.assertEqual(self.post('/huddle/leagues/create', name='Valid', categories=categories).status_code, 400)
        self.assertEqual(self.post('/huddle/leagues/create', name='x', categories=['ats']).status_code, 400)
        self.assertEqual(self.client.post('/huddle/leagues/create').status_code, 400)
        self.assertEqual(self.post('/huddle/leagues/join', invite='http://[').status_code, 400)
        with patch('huddle_leagues.allow_attempt', return_value=False):
            self.assertEqual(self.post('/huddle/leagues/create', name='Valid', categories=['su']).status_code, 429)

    def test_private_routes_and_commissioner_permissions(self):
        league = self.create()
        self.login(3)
        self.assertEqual(self.client.get(f'/huddle/leagues/{league["id"]}').status_code, 404)
        self.join(league)
        self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/invitation').status_code, 403)
        self.login(1)
        self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/invitation').status_code, 303)
        self.assertEqual(self.client.get('/huddle/leagues/join/' + league['invite_token']).status_code, 404)
        self.login(2)
        response = self.client.get(f'/huddle/leagues/{league["id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('private1@example.com', response.text)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.login(None)
        self.assertEqual(self.client.get('/huddle/leagues/').status_code, 302)

    def test_join_is_explicit_idempotent_and_multiple(self):
        first, second = self.create(), self.create()
        self.login(2)
        self.client.get('/huddle/leagues/join/' + first['invite_token'])
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM huddle_league_members WHERE member_id=2').fetchone()[0], 0)
        for league in (first, first, second):
            self.assertEqual(self.join(league).status_code, 303)
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM huddle_league_members WHERE member_id=2').fetchone()[0], 2)
            self.assertEqual(c.execute('SELECT joined_at FROM huddle_league_members WHERE member_id=2 LIMIT 1').fetchone()[0], first['created_at'])

    def test_invitation_survives_login_and_registration(self):
        league = self.create()
        target = '/huddle/leagues/join/' + league['invite_token']
        for register in (False, True):
            self.login(None)
            self.assertEqual(self.client.get(target).status_code, 200)
            data = dict(email='new@example.com' if register else 'private2@example.com', password='long secure password')
            if register:
                data['password_confirm'] = data['password']
            response = self.post('/members/register' if register else '/members/login', **data)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, target)
            with self.client.session_transaction() as s:
                self.assertNotIn('_csrf', s)
        self.login(None)
        self.assertEqual(self.post('/members/login', email='private2@example.com', password='long secure password').location, '/')

    def test_no_retroactive_or_unverified_points(self):
        league = self.create()
        self.join(league)
        with self.connection() as c:
            c.execute("UPDATE huddle_league_members SET joined_at='2026-10-03T00:00:00+00:00' WHERE member_id=2")
        self.seed(league, lock='2026-09-30T00:00:00+00:00')
        self.seed(league, lock=league['created_at'])
        self.seed(league)
        self.seed(league, finals=False)
        self.seed(league, published=False, week=6)
        rows = {r['member_id']: r for r in self.scores(league)}
        self.assertEqual(rows[1]['points'], 3)
        self.assertEqual(rows[2]['points'], 0)
        self.assertEqual(rows[1]['Pending'], 3)

    def test_push_void_tie_pending_and_stored_grades(self):
        league = self.create()
        for results in [('Push', 'Tie', 'Pending'), ('Loss', 'Win', 'Win')]:
            self.seed(league, results=results)
        self.seed(league, void='cancelled')
        row = self.scores(league)[0]
        self.assertEqual((row['points'], row['Push'], row['Tie'], row['Pending'], row['Void']), (2, 1, 1, 1, 3))

    def test_week_season_ties_shared_updates_and_restart(self):
        league = self.create()
        self.join(league)
        self.join(league, 3)
        wid, gid = self.seed(league)
        self.seed(league, week=6)
        self.seed(league, week=1, season=2027)
        self.assertEqual([r['rank'] for r in self.scores(league)], [1, 1, 1])
        with self.connection() as c:
            c.execute("UPDATE member_picks SET ats_result='Loss' WHERE member_id=3 AND game_id=?", (gid,))
            before = list(c.iterdump())
        self.assertEqual([r['points'] for r in self.scores(league, wid)], [3, 3, 2])
        self.assertEqual([r['rank'] for r in self.scores(league)], [1, 1, 3])
        app = self.make_app()
        with self.connection() as c:
            self.assertEqual(before, list(c.iterdump()))
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 4)
        client = app.test_client()
        with client.session_transaction() as s:
            s['member_id'] = 1
        for path in ('/', '/create', '/join', f'/{league["id"]}', f'/{league["id"]}?season=2026&week_id={wid}'):
            self.assertEqual(client.get('/huddle/leagues' + path).status_code, 200)
        self.assertEqual(client.get(f'/huddle/leagues/{league["id"]}?season=bad').status_code, 400)
        self.assertEqual(client.get(f'/huddle/leagues/{league["id"]}?week_id=999').status_code, 400)

    def test_join_timestamp_cannot_be_reset_and_boundary_is_excluded(self):
        league = self.create()
        self.join(league)
        with self.connection() as c:
            c.execute("UPDATE huddle_league_members SET joined_at='2026-10-02T12:00:00+00:00' WHERE member_id=2")
        self.join(league)
        self.seed(league)
        rows = {r['member_id']: r for r in self.scores(league)}
        self.assertEqual(rows[1]['points'], 3)
        self.assertEqual(rows[2]['points'], 0)

    def test_shared_source_reflects_grading_in_multiple_leagues(self):
        first, second = self.create(), self.create()
        _, gid = self.seed(first, results=('Pending', 'Pending', 'Pending'))
        self.assertEqual(self.scores(first)[0]['points'], 0)
        from member_picks import grade
        with self.connection() as c:
            game = c.execute('SELECT * FROM pick_games WHERE id=?', (gid,)).fetchone()
            results = grade(game, 'NE', 'NE', 'Over')
            c.execute('UPDATE member_picks SET su_result=?,ats_result=?,ou_result=? WHERE member_id=1 AND game_id=?', (*results, gid))
            before = list(c.iterdump())
        self.assertEqual(self.scores(first)[0]['points'], 2)
        self.assertEqual(self.scores(second)[0]['points'], 2)
        with self.connection() as c:
            self.assertEqual(before, list(c.iterdump()))

    def test_profiles_are_escaped_and_never_expose_email(self):
        league = self.create()
        with self.connection() as c:
            c.execute('CREATE TABLE community_profiles(member_id INTEGER PRIMARY KEY,display_name TEXT)')
            c.execute("INSERT INTO community_profiles VALUES(1,'<script>bad</script>')")
        response = self.client.get(f'/huddle/leagues/{league["id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', response.text)
        self.assertNotIn('<script>bad</script>', response.text)
        self.assertNotIn('private1@example.com', response.text)

    def test_atomic_creation_rollback(self):
        with self.connection() as c:
            c.execute("CREATE TRIGGER reject_entry BEFORE INSERT ON huddle_league_members BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.post('/huddle/leagues/create', name='Rollback league', categories=['su'])
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM huddle_leagues').fetchone()[0], 0)

    def test_hosted_create_redirect_join_and_access_controls(self):
        # Load the real hosting configuration without running module-level site setup.
        import ast
        import os
        from flask import abort, jsonify, request
        from werkzeug.middleware.proxy_fix import ProxyFix
        from werkzeug.middleware.shared_data import SharedDataMiddleware
        tree = ast.parse(Path('wsgi.py').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'configure_hosted_app')
        namespace = dict(os=os, abort=abort, jsonify=jsonify, request=request,
                         ProxyFix=ProxyFix, SharedDataMiddleware=SharedDataMiddleware)
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'wsgi.py', 'exec'), namespace)
        self.app.add_url_rule('/research-write', 'research_write', lambda: 'blocked', methods=['POST'])
        namespace['configure_hosted_app'](self.app)
        response = self.client.post('/huddle/leagues/create', data={
            'csrf_token': 'test-token', 'name': 'Hosted League', 'categories': ['ats']}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Hosted League', response.text)
        self.assertIn('href="/community">The Huddle</a>', response.text)
        self.assertEqual(self.client.post('/huddle/leagues/create').status_code, 400)
        self.assertEqual(self.post('/research-write').status_code, 403)
        with self.connection() as c:
            league = c.execute('SELECT * FROM huddle_leagues').fetchone()
        self.assertEqual(self.join(league).status_code, 303)
        self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/invitation').status_code, 403)

    def test_create_form_clarity_and_huddle_navigation(self):
        response = self.client.get('/huddle/leagues/create')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Scoring starts when you join the league.', response.text)
        self.assertNotIn('Games locked before league creation', response.text)
        self.assertIn('href="/community">The Huddle</a>', response.text)
        self.assertEqual(response.text.count('class="league-category"'), 3)
        self.assertIn("url_for('huddle_leagues.mine')", Path('templates/community.html').read_text())

    def test_mine_shows_own_verified_record_without_changing_picks(self):
        league = self.create()
        self.join(league)
        self.seed(league, results=('Win', 'Loss', 'Push'))
        with self.connection() as c:
            c.execute("UPDATE member_picks SET su_result='Loss' WHERE member_id=2")
            before = [tuple(row) for row in c.execute(
                'SELECT * FROM member_picks ORDER BY member_id,game_id'
            )]
        with patch('huddle_leagues.now_utc', return_value=datetime(2026,11,1,tzinfo=timezone.utc)):
            response = self.client.get('/huddle/leagues/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<dt>Points</dt><dd>0</dd>', response.text)
        self.assertIn('<dt>Wins</dt><dd>0</dd>', response.text)
        self.assertIn('<dt>Losses</dt><dd>2</dd>', response.text)
        with self.connection() as c:
            self.assertEqual(before, [
                tuple(row) for row in c.execute(
                    'SELECT * FROM member_picks ORDER BY member_id,game_id'
                )
            ])
        self.assertEqual(self.client.get(f'/huddle/leagues/{league["id"]}').status_code, 200)
        self.assertNotIn('View season', self.client.get(f'/huddle/leagues/{league["id"]}').text)
        self.assertNotIn('id="league-season"', self.client.get(f'/huddle/leagues/{league["id"]}').text)

    def test_mobile_standings_expandable_desktop_table_preserved(self):
        league = self.create()
        self.join(league)
        self.seed(league, results=('Win', 'Loss', 'Push'))
        response = self.client.get(f'/huddle/leagues/{league["id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="league-mobile-standings"', response.text)
        self.assertIn('class="league-table-scroll"', response.text)
        self.assertIn('<details class="league-standing', response.text)
        self.assertIn('<small>W–L</small>', response.text)
        for label in ('Push', 'Tie', 'Void', 'Pending'):
            self.assertIn(f'<dt>{label}</dt>', response.text)
        self.assertIn('>The Huddle</a>', response.text)
        self.assertIn('>My Picks</a>', response.text)
        self.assertIn('>My Leagues</a>', response.text)

    def test_mine_hides_redundant_navigation_button(self):
        response = self.client.get('/huddle/leagues/')
        self.assertEqual(response.status_code, 200)
        from html.parser import HTMLParser
        class NavLinks(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_league_nav = False
                self.labels = []
            def handle_starttag(self, tag, attrs):
                if tag == 'nav' and ('class', 'league-actions') in attrs:
                    self.in_league_nav = True
            def handle_endtag(self, tag):
                if tag == 'nav':
                    self.in_league_nav = False
            def handle_data(self, data):
                if self.in_league_nav and data.strip():
                    self.labels.append(data.strip())
        nav = NavLinks()
        nav.feed(response.text)
        self.assertEqual(nav.labels, ['The Huddle', 'Create League', 'Join League', 'My Picks'])

    def test_empty_league_card_starts_with_zero_points(self):
        self.create()
        response = self.client.get('/huddle/leagues/')
        self.assertEqual(response.status_code, 200)
        for label in ('Points', 'Wins', 'Losses'):
            self.assertIn(f'<dt>{label}</dt><dd>0</dd>', response.text)


    def test_commissioner_remove_requires_authorization_csrf_and_confirmation(self):
        league = self.create()
        self.join(league, 2)
        target = f'/huddle/leagues/{league["id"]}/members/2/remove'
        self.assertEqual(self.post(target, confirm_remove='yes').status_code, 403)
        self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/leave', confirm_leave='yes').status_code, 303)
        # Rejoin after voluntary departure. An invitation does not become a ban.
        self.join(league, 2)
        self.login(1)
        self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/members/1/remove', confirm_remove='yes').status_code, 403)
        self.assertEqual(self.post(target).status_code, 400)
        self.assertEqual(self.client.post(target, data={'confirm_remove':'yes'}).status_code, 400)
        self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/members/99/remove',confirm_remove='yes').status_code,404)
        self.assertEqual(self.post(target,confirm_remove='yes').status_code,303)
        self.assertEqual(self.post(target,confirm_remove='yes').status_code,404)
        with self.connection() as c:
            row = c.execute('''SELECT exit_reason,left_at FROM huddle_league_member_periods
                WHERE league_id=? AND member_id=2 ORDER BY id DESC LIMIT 1''',(league['id'],)).fetchone()
            self.assertEqual(row['exit_reason'],'removed')
            self.assertIsNotNone(row['left_at'])

    def test_departure_preserves_old_week_without_future_points_or_picks_changes(self):
        league = self.create()
        self.join(league,2)
        self.login(1)
        wid, gid = self.seed(league)
        with self.connection() as c:
            before = [tuple(row) for row in c.execute('SELECT * FROM member_picks ORDER BY member_id,game_id')]
        with patch('huddle_leagues.now_utc',return_value=datetime(2026,10,4,tzinfo=timezone.utc)):
            self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/members/2/remove',confirm_remove='yes').status_code,303)
        self.assertEqual([row['member_id'] for row in self.scores(league)], [1])
        older = {row['member_id']:row for row in self.scores(league,wid)}
        self.assertEqual(older[2]['points'],3)
        with self.connection() as c:
            self.assertEqual(before,[tuple(row) for row in c.execute('SELECT * FROM member_picks ORDER BY member_id,game_id')])
        self.login(2)
        self.assertEqual(self.client.get(f'/huddle/leagues/{league["id"]}').status_code,404)
        self.assertNotIn('Friends League',self.client.get('/huddle/leagues/').text)

    def test_leave_and_rejoin_creates_new_period_without_gap_backfill(self):
        league = self.create()
        self.join(league,2)
        self.login(1)
        first_week, _ = self.seed(league)
        self.login(2)
        with patch('huddle_leagues.now_utc',return_value=datetime(2026,10,4,tzinfo=timezone.utc)):
            self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/leave').status_code,400)
            self.assertEqual(self.post(f'/huddle/leagues/{league["id"]}/leave',confirm_leave='yes').status_code,303)
        self.assertEqual(self.client.get(f'/huddle/leagues/{league["id"]}').status_code,404)
        # Pick a game during the gap, then again after rejoining.
        self.login(1)
        _, gap_id = self.seed(league,week=6,lock='2026-10-04T12:00:00+00:00')
        _, later_id = self.seed(league,week=7,lock='2026-10-06T12:00:00+00:00')
        with self.connection() as c:
            c.execute('UPDATE pick_games SET result_at=? WHERE id=?',('2026-10-05T00:00:00+00:00',gap_id))
            c.execute('UPDATE pick_games SET result_at=? WHERE id=?',('2026-10-07T00:00:00+00:00',later_id))
        with patch('huddle_leagues.now_utc',return_value=datetime(2026,10,5,tzinfo=timezone.utc)):
            self.join(league,2)
        with self.connection() as c:
            periods = c.execute('''SELECT joined_at,left_at FROM huddle_league_member_periods
                WHERE league_id=? AND member_id=2 ORDER BY id''',(league['id'],)).fetchall()
            self.assertEqual(len(periods),2)
            self.assertIsNotNone(periods[0]['left_at'])
            self.assertIsNone(periods[1]['left_at'])
        self.assertEqual({r['member_id']:r['points'] for r in self.scores(league)}[2],6)
        self.assertEqual({r['member_id']:r['points'] for r in self.scores(league,first_week)}[2],3)
        self.assertEqual({r['member_id']:r['points'] for r in self.scores(league)}[1],9)

    def test_member_controls_are_escaped_and_present_only_for_correct_role(self):
        league = self.create()
        self.join(league,2)
        self.login(1)
        with self.connection() as c:
            c.execute('CREATE TABLE community_profiles(member_id INTEGER PRIMARY KEY,display_name TEXT)')
            c.execute("INSERT INTO community_profiles VALUES(2,'<script>alert(1)</script>')")
        response = self.client.get(f'/huddle/leagues/{league["id"]}')
        self.assertEqual(response.status_code,200)
        self.assertIn('Manage league members',response.text)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',response.text)
        self.assertNotIn('<script>alert(1)</script>',response.text)
        self.assertIn('confirm_remove',response.text)
        self.login(2)
        response = self.client.get(f'/huddle/leagues/{league["id"]}')
        self.assertEqual(response.status_code,200)
        self.assertIn('Leave this league',response.text)
        self.assertNotIn('confirm_remove',response.text)
        self.assertNotIn('private1@example.com',response.text)

    def test_member_removal_does_not_affect_other_leagues_or_account(self):
        first, second = self.create(), self.create()
        self.join(first,2)
        self.join(second,2)
        self.login(1)
        self.assertEqual(self.post(f'/huddle/leagues/{first["id"]}/members/2/remove',
                                   confirm_remove='yes').status_code,303)
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM members WHERE id=2').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM huddle_league_members WHERE member_id=2').fetchone()[0],1)
        self.login(2)
        self.assertEqual(self.client.get(f'/huddle/leagues/{first["id"]}').status_code,404)
        self.assertEqual(self.client.get(f'/huddle/leagues/{second["id"]}').status_code,200)

    def test_period_migration_idempotent(self):
        league = self.create()
        self.join(league,2)
        with self.connection() as c:
            old = [(row['member_id'],row['joined_at'],row['left_at']) for row in c.execute('''SELECT member_id,joined_at,left_at FROM huddle_league_member_periods
                WHERE league_id=? ORDER BY id''',(league['id'],))]
        self.make_app()
        with self.connection() as c:
            new = [(row['member_id'],row['joined_at'],row['left_at']) for row in c.execute('''SELECT member_id,joined_at,left_at FROM huddle_league_member_periods
                WHERE league_id=? ORDER BY id''',(league['id'],))]
            self.assertEqual(old,new)
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],4)

    def league_picks_test_context(self):
        from unittest.mock import patch
        from contextlib import ExitStack
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch('weekly_pick_lines.publish_saved_snapshot',return_value=True))
        stack.enter_context(patch('member_picks.sync_results'))
        stack.enter_context(patch('member_picks.schedule',return_value={
            'sample':{'season':'2026','week':'5','gameday':'2026-10-02',
                      'gametime':'13:00','game_type':'REG'}}))

    def test_league_override_changes_only_its_standings_and_not_default_picks(self):
        first,second = self.create(),self.create()
        wid,gid = self.seed(first)
        self.league_picks_test_context()
        self.assertEqual(self.post(f'/huddle/leagues/{first["id"]}/picks',
            game_id=str(gid),su='BUF',ats='',ou='').status_code,303)
        with self.connection() as c:
            override = c.execute('SELECT * FROM huddle_league_pick_overrides WHERE league_id=?',
                                 (first['id'],)).fetchone()
            self.assertEqual((override['su'],override['ats'],override['ou']),('BUF',None,None))
            self.assertEqual(c.execute('SELECT su FROM member_picks WHERE member_id=1 AND game_id=?',
                                       (gid,)).fetchone()[0],'NE')
        self.assertEqual(self.scores(first)[0]['points'],2)
        self.assertEqual(self.scores(second)[0]['points'],3)
        # Selecting Use My Picks again deletes the override rather than writing to My Picks.
        self.assertEqual(self.post(f'/huddle/leagues/{first["id"]}/picks',
            game_id=str(gid),su='',ats='',ou='').status_code,303)
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM huddle_league_pick_overrides').fetchone()[0],0)
        self.assertEqual(self.scores(first)[0]['points'],3)

    def test_league_override_scores_without_any_shared_pick_row(self):
        league=self.create()
        _,gid=self.seed(league)
        with self.connection() as c:
            c.execute('DELETE FROM member_picks WHERE member_id=1 AND game_id=?',(gid,))
        self.league_picks_test_context()
        response=self.post(f'/huddle/leagues/{league["id"]}/picks',
                           game_id=str(gid),su='NE',ats='',ou='')
        self.assertEqual(response.status_code,303)
        rows=self.scores(league)
        self.assertEqual(rows[0]['points'],1)
        self.assertEqual(rows[0]['Win'],1)
        with self.connection() as c:
            self.assertIsNone(c.execute('SELECT * FROM member_picks WHERE member_id=1 AND game_id=?',
                (gid,)).fetchone())

    def test_league_override_guards_lock_membership_csrf_and_input(self):
        league=self.create()
        _,gid=self.seed(league)
        self.league_picks_test_context()
        route=f'/huddle/leagues/{league["id"]}/picks'
        self.assertEqual(self.client.post(route,data={'game_id':str(gid),'su':'BUF','ats':'','ou':''}).status_code,400)
        self.assertEqual(self.post(route,game_id=str(gid),su='INVALID',ats='',ou='').status_code,400)
        self.assertEqual(self.post(route,game_id=str(gid),su=['BUF','NE'],ats='',ou='').status_code,400)
        self.assertEqual(self.post(route,game_id=str(gid),su='BUF',ats='',ou='Over').status_code,303)
        self.login(2)
        self.assertEqual(self.client.get(route).status_code,404)
        self.assertEqual(self.post(route,game_id=str(gid),su='BUF',ats='',ou='').status_code,404)
        self.login(1)
        with patch('huddle_leagues.now_utc',return_value=datetime(2026,10,3,tzinfo=timezone.utc)):
            self.assertEqual(self.post(route,game_id=str(gid),su='NE',ats='',ou='').status_code,409)
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT su FROM huddle_league_pick_overrides WHERE league_id=?',
                (league['id'],)).fetchone()[0],'BUF')

    def test_league_picks_page_renders_without_leaking_other_leagues(self):
        first,second=self.create(),self.create()
        _,gid=self.seed(first)
        self.league_picks_test_context()
        page=self.client.get(f'/huddle/leagues/{first["id"]}/picks')
        self.assertEqual(page.status_code,200)
        self.assertIn('Use My Picks',page.text)
        self.assertIn('Save league picks',page.text)
        self.assertIn('default My Picks',page.text)
        self.assertIn('name="csrf_token"',page.text)
        self.assertNotIn('private1@example.com',page.text)
        self.assertEqual(self.post(f'/huddle/leagues/{first["id"]}/picks',
            game_id=str(gid),su='BUF',ats='',ou='').status_code,303)
        other=self.client.get(f'/huddle/leagues/{second["id"]}/picks')
        self.assertEqual(other.status_code,200)
        self.assertNotIn('selected>BUF</option>',other.text)

    def test_league_overrides_preserve_closed_periods_and_other_memberships(self):
        first,second=self.create(),self.create()
        self.join(first,2)
        self.login(1)
        _,gid=self.seed(first)
        self.league_picks_test_context()
        self.assertEqual(self.post(f'/huddle/leagues/{first["id"]}/picks',
            game_id=str(gid),su='BUF',ats='',ou='').status_code,303)
        before=next(r['points'] for r in self.scores(first) if r['member_id']==1)
        with patch('huddle_leagues.now_utc',return_value=datetime(2026,10,4,tzinfo=timezone.utc)):
            self.assertEqual(self.post(f'/huddle/leagues/{first["id"]}/members/2/remove',
                confirm_remove='yes').status_code,303)
        self.assertEqual(next(r['points'] for r in self.scores(first) if r['member_id']==1),before)
        self.assertEqual(self.scores(second)[0]['points'],3)
        with self.connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM huddle_league_pick_overrides').fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
