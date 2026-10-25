"""Public standings regressions; no real database, writes, or provider requests."""
import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask, g, request
import huddle_leaderboard as board


class PublicLeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE members (id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE community_profiles (member_id INTEGER PRIMARY KEY, display_name TEXT);
            CREATE TABLE pick_weeks (id INTEGER PRIMARY KEY, season INTEGER, week INTEGER,
              stage TEXT, published_at TEXT);
            CREATE TABLE pick_games (id INTEGER PRIMARY KEY, week_id INTEGER,
              away_final INTEGER, home_final INTEGER, result_at TEXT, void_reason TEXT);
            CREATE TABLE member_picks (member_id INTEGER, game_id INTEGER,
              su TEXT, ats TEXT, ou TEXT, su_result TEXT, ats_result TEXT, ou_result TEXT);
            CREATE TABLE huddle_leagues (id INTEGER PRIMARY KEY, name TEXT, created_at TEXT);
            CREATE TABLE huddle_league_members (member_id INTEGER, league_id INTEGER);
            INSERT INTO members VALUES (1,'hidden@example.com'),(2,'private@example.com');
            INSERT INTO community_profiles VALUES (1,'First Down'),(2,NULL);
            INSERT INTO pick_weeks VALUES (1,2026,7,'REG','2026-10-20'),
              (2,2026,8,'REG','2026-10-23'),(3,2025,1,'REG','2025-09-08'),
              (4,2026,9,'REG',NULL);
            INSERT INTO huddle_leagues VALUES (8,'Friends Only','2026-10-20');
            INSERT INTO huddle_league_members VALUES (1,8);
        ''')
        for i in range(1, 7):
            self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',
                              (i, 1, 21, 20, '2026-10-20', None))
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',
                          (7, 2, 17, 10, '2026-10-23', None))
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',
                          (8, 3, 17, 10, '2025-09-08', None))
        for i in range(1, 7):
            self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',
                              (1, i, 'NE', 'NE', 'Over', 'Win', 'Loss' if i == 6 else 'Win', 'Push'))
        for i in range(1, 6):
            self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',
                              (2, i, 'NE', 'NE', 'Over', 'Loss', 'Loss' if i == 5 else 'Win', 'Win'))
        self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',
                          (2, 7, 'NE', 'NE', 'Over', 'Win', 'Win', 'Win'))
        self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',
                          (1, 8, 'NE', 'NE', 'Over', 'Win', 'Win', 'Win'))

    def tearDown(self):
        self.conn.close()

    def test_season_week_and_independent_categories(self):
        season = board.standings(self.conn, season=2026)
        self.assertEqual(season['ats'][0]['name'], 'First Down')
        self.assertEqual((season['ats'][0]['wins'], season['ats'][0]['losses']), (5, 1))
        self.assertEqual(season['ats'][1]['name'], 'Fan #2')
        week = board.standings(self.conn, season=2026, week_id=2, minimum=1)
        self.assertEqual([r['member_id'] for r in week['ats']], [2])
        self.assertEqual(week['su'][0]['wins'], 1)
        self.assertEqual(season['ou'][0]['pushes'], 0)
        self.assertNotIn('hidden@example.com', str(season))
        self.assertNotIn('private@example.com', str(season))

    def test_unpublished_void_and_ungraded_do_not_count(self):
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',
                          (9, 4, 10, 7, '2026-10-24', None))
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',
                          (10, 1, 10, 7, '2026-10-24', 'Void'))
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',
                          (11, 1, None, None, None, None))
        for game_id in (9, 10, 11):
            self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',
                              (2, game_id, 'NE', 'NE', 'Over', 'Win', 'Win', 'Win'))
        self.assertEqual(board.standings(self.conn, season=2026)['ats'][1]['wins'], 5)
        self.assertEqual(len(board.published_weeks(self.conn)), 3)

    def test_validation_and_read_only(self):
        changes = self.conn.total_changes
        self.assertEqual(board.standings(self.conn, minimum=1)['ats'][0]['member_id'], 1)
        self.assertEqual(changes, self.conn.total_changes)
        for kwargs in ({'season': '2026'}, {'week_id': '1'}, {'minimum': 0}, {'limit': 501}):
            with self.assertRaises(ValueError):
                board.standings(self.conn, **kwargs)

    def test_public_route_filters_and_league_visibility(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['HUDDLE_LEADERBOARD_PREVIEW_ENABLED'] = False
        board.init_huddle_leaderboard(app)
        captured = {}

        @app.before_request
        def visitor():
            g.member = {'id': 1} if request.args.get('logged_in') == '1' else None
            g.is_owner = False

        def fake_template(template, **kwargs):
            captured.update(kwargs)
            return f"{template}:{len(kwargs['rows'])}"

        with patch.object(board, 'db', return_value=self.conn), \
             patch.object(board, 'render_template', side_effect=fake_template):
            client = app.test_client()
            before = self.conn.total_changes
            r = client.get('/community/leaderboard/?view=weekly&season=2026&week_id=2&market=ats')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(captured['rows'][0]['member_id'], 2)
            self.assertEqual(captured['leagues'], [])
            self.assertEqual(r.headers['Cache-Control'], 'private, no-store')
            r = client.get('/community/leaderboard/?view=season&season=2026&market=ou&logged_in=1')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(len(captured['leagues']), 1)
            self.assertEqual(captured['leagues'][0]['name'], 'Friends Only')
            self.assertEqual(client.get('/community/leaderboard/?week_id=99').status_code, 400)
            self.assertEqual(client.get('/community/leaderboard/?market=moneyline').status_code, 400)
            self.assertEqual(client.get('/community/leaderboard/preview').status_code, 404)
            self.assertEqual(before, self.conn.total_changes)


if __name__ == '__main__':
    unittest.main()
