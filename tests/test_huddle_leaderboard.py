"""Read-only standing calculations and hidden-preview authorization."""
import sqlite3
import unittest
from unittest.mock import patch
from flask import Flask, g

import huddle_leaderboard as board


class HiddenLeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript('''
          CREATE TABLE members (id INTEGER PRIMARY KEY, email TEXT);
          CREATE TABLE pick_weeks (id INTEGER PRIMARY KEY, season INTEGER, published_at TEXT);
          CREATE TABLE pick_games (id INTEGER PRIMARY KEY, week_id INTEGER, away_final INTEGER,
             home_final INTEGER, result_at TEXT, void_reason TEXT);
          CREATE TABLE member_picks (member_id INTEGER,game_id INTEGER,su TEXT,ats TEXT,ou TEXT,
             su_result TEXT,ats_result TEXT,ou_result TEXT);
          INSERT INTO members VALUES(1,'secret@example.com'),(2,'private@example.com');
          INSERT INTO pick_weeks VALUES(1,2026,'2026-10-20'),(2,2025,'2025-10-15'),(3,2026,NULL);
        ''')
        for n in range(1, 12):
            self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)', (n, 1, 10, 7, '2026-10-20', None))
        # Fan 1 wins 5/6 ATS, Fan 2 wins 4/5 ATS; other markets independent.
        for n in range(1, 7):
            self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',
                              (1,n,'DAL','DAL','Over','Win','Loss' if n == 6 else 'Win','Push'))
        for n in range(1, 6):
            self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',
                              (2,n,'DAL','DAL','Over','Loss','Loss' if n == 5 else 'Win','Win'))

    def tearDown(self):
        self.conn.close()

    def test_rank_and_independent_markets(self):
        tables = board.standings(self.conn)
        self.assertEqual([x['name'] for x in tables['ats']], ['Fan #1','Fan #2'])
        self.assertEqual(tables['ats'][0]['wins'], 5)
        self.assertEqual(tables['ats'][0]['losses'], 1)
        self.assertEqual(tables['su'][0]['name'], 'Fan #1')
        self.assertEqual([x['name'] for x in tables['ou']], ['Fan #2'])
        self.assertNotIn('email', str(tables))

    def test_unpublished_void_unfinalized_and_pending_excluded(self):
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',(99,3,10,7,'2026-10-20',None))
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',(98,1,10,7,'2026-10-20','Void'))
        self.conn.execute('INSERT INTO pick_games VALUES(?,?,?,?,?,?)',(97,1,None,None,None,None))
        for game in (99,98,97):
            self.conn.execute('INSERT INTO member_picks VALUES(?,?,?,?,?,?,?,?)',(2,game,'DAL','DAL','Over','Win','Win','Win'))
        tables = board.standings(self.conn)
        self.assertEqual(tables['ats'][1]['wins'],4)
        self.assertEqual(tables['ats'][1]['losses'],1)

    def test_stale_pending_results_excluded_without_writes(self):
        self.conn.execute('UPDATE member_picks SET ats_result=? WHERE member_id=1 AND game_id=1',('Pending',))
        total_before = self.conn.total_changes
        self.assertEqual(board.standings(self.conn)['ats'][0]['wins'],4)
        self.assertEqual(self.conn.total_changes,total_before)

    def test_season_and_minimum(self):
        self.assertEqual(board.standings(self.conn,season=2025)['ats'],[])
        self.assertEqual(len(board.standings(self.conn,season=2026,minimum=6)['ats']),1)
        with self.assertRaises(ValueError):board.standings(self.conn,minimum=0)

    def test_preview_disabled_and_owner_only(self):
        app = Flask(__name__)
        app.config['HUDDLE_LEADERBOARD_PREVIEW_ENABLED'] = False
        board.init_huddle_leaderboard(app)
        @app.before_request
        def set_owner():
            g.is_owner = False
        client = app.test_client()
        self.assertEqual(client.get('/community/leaderboard/preview').status_code,404)
        app.config['HUDDLE_LEADERBOARD_PREVIEW_ENABLED'] = True
        self.assertEqual(client.get('/community/leaderboard/preview').status_code,404)

    def test_installer_is_idempotent(self):
        from install_hidden_leaderboard import update_source
        source = 'from community_comments import init_community\ninit_community(app)\n'
        new, changed = update_source(source)
        self.assertTrue(changed)
        self.assertIn('init_huddle_leaderboard(app)',new)
        self.assertEqual(update_source(new),(new,False))


if __name__ == '__main__': unittest.main()
