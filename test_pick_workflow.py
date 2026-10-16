"""Shared checklist workflow, partial saves, and inline comparisons."""
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_member_picks
from membership import db
from saved_trends import manual_trend_title


class PickWorkflowTests(unittest.TestCase):
    setUp=test_member_picks.MemberPicksTests.setUp
    tearDown=test_member_picks.MemberPicksTests.tearDown
    login_owner=test_member_picks.MemberPicksTests.login_owner
    write_schedule=test_member_picks.MemberPicksTests.write_schedule
    member=test_member_picks.MemberPicksTests.member
    token=test_member_picks.MemberPicksTests.token
    sheet=test_member_picks.MemberPicksTests.sheet

    def batch(self,client,ids,**choices):
        data=MultiDict([('csrf_token',self.token('/members/preferences',client)),('return_to','/picks/')]+[('game_ids',str(ident)) for ident in ids])
        for key,value in choices.items():
            for item in value if isinstance(value,list) else [value]:data.add(key,item)
        return client.post('/picks/save',data=data,headers={'Accept':'application/json'})

    def second_game(self):
        self.rows.append(dict(self.rows[0],game_id='2030_06_C_D',away_team='C',home_team='D',gameday='2030-10-20',gametime='13:00'))
        self.write_schedule()
        with self.app.app_context():
            with db():
                week=db().execute('SELECT id FROM pick_weeks').fetchone()[0]
                return db().execute('INSERT INTO pick_games(week_id,game_id,away,home,kickoff_at,lock_at,away_spread,total,line_source) VALUES(?,?,?,?,?,?,?,?,?)',
                    (week,'2030_06_C_D','C','D','2030-10-20T17:00:00+00:00','2030-10-20T17:00:00+00:00',-2.5,43,'Wednesday snapshot')).lastrowid

    def test_single_save_persists_partial_choices_across_multiple_games(self):
        first,_=self.sheet();second=self.second_game();client=self.member()
        html=client.get('/picks/').text
        self.assertEqual(html.count('>Save picks</button>'),1)
        self.assertEqual(html.count('type="checkbox"'),12)
        self.assertNotIn('<select id="su-',html)
        self.assertIn('/matchup/2030_06_A_B',html)
        response=self.batch(client,[first,second],**{f'su_{first}':'A',f'ou_{second}':'Under'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['saved'],2)
        with self.app.app_context():
            picks=db().execute('SELECT * FROM member_picks ORDER BY game_id').fetchall()
            self.assertEqual((picks[0]['su'],picks[0]['ats'],picks[0]['ou']),('A',None,None))
            self.assertEqual((picks[1]['su'],picks[1]['ats'],picks[1]['ou']),(None,None,'Under'))
            self.assertEqual({p['member_id'] for p in picks},{2})
        html=client.get('/picks/').text
        self.assertIn(f'name="su_{first}" value="A" checked',html)
        self.assertIn(f'name="ou_{second}" value="Under" checked',html)

    def test_finish_and_clear_saved_progress(self):
        ident,_=self.sheet();client=self.member()
        self.batch(client,[ident],**{f'su_{ident}':'A'})
        self.batch(client,[ident],**{f'su_{ident}':'A',f'ats_{ident}':'B',f'ou_{ident}':'Over'})
        self.batch(client,[ident],**{f'ats_{ident}':'B',f'ou_{ident}':'Over'})
        with self.app.app_context():
            saved=db().execute('SELECT * FROM member_picks').fetchone()
            self.assertEqual((saved['su'],saved['ats'],saved['ou']),(None,'B','Over'))

    def test_duplicate_choices_rejected_atomically_and_csrf_required(self):
        first,_=self.sheet();second=self.second_game();client=self.member()
        response=self.batch(client,[first,second],**{f'su_{first}':'A',f'su_{second}':['C','D']})
        self.assertEqual(response.status_code,400)
        with self.app.app_context():self.assertEqual(db().execute('SELECT COUNT(*) FROM member_picks').fetchone()[0],0)
        self.assertEqual(client.post('/picks/save',data={'game_ids':first}).status_code,400)

    def test_games_locking_during_edit_keep_original_and_save_others(self):
        first,_=self.sheet();second=self.second_game();client=self.member()
        self.batch(client,[first],**{f'su_{first}':'A'})
        self.clock.return_value=datetime(2030,10,18,0,15,tzinfo=timezone.utc)
        response=self.batch(client,[first,second],**{f'su_{first}':'B',f'su_{second}':'C'})
        self.assertEqual((response.json['saved'],response.json['locked']),(1,1))
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT su FROM member_picks WHERE game_id=?',(first,)).fetchone()[0],'A')
            self.assertEqual(db().execute('SELECT su FROM member_picks WHERE game_id=?',(second,)).fetchone()[0],'C')

    def test_inline_controls_and_save_return_to_comparison(self):
        ident,_=self.sheet();client=self.member()
        from member_picks import comparison_picks
        from flask import render_template
        with self.app.test_request_context('/scout4/teams?team=A&opponent=B'):
            from flask import g
            g.member={'id':2};g.is_owner=False
            games=comparison_picks(team='A',opponent='B')
            html=render_template('_inline_picks.html',inline_picks=games)
            self.assertIn('type="checkbox"',html)
            self.assertIn('>Save picks</button>',html)
            self.assertNotIn('href="/picks/',html)
        response=client.post('/picks/save',data={'csrf_token':self.token('/members/preferences',client),'game_ids':str(ident),'return_to':'/scout4/teams?team=A&opponent=B',f'su_{ident}':'A'})
        self.assertEqual(response.location,'/scout4/teams?team=A&opponent=B')
        response=client.post('/picks/save',data={'csrf_token':self.token('/members/preferences',client),'game_ids':str(ident),'return_to':'https://example.com/scout4/teams',f'su_{ident}':'B'})
        self.assertEqual(response.location,'/picks/')

    def test_manual_names_show_trend_type_and_filters(self):
        title=manual_trend_title('/trend-finder?run=analyze&season=2026&location=Away&primetime=yes&away_coach=Dan+Quinn&spread_mode=min&min_spread=3')
        self.assertEqual(title,'Away dogs | Primetime | Spread +3 or more | Season 2026 | Away Coach: Dan Quinn')
        self.assertEqual(manual_trend_title('/trend-finder?run=analyze'),'All underdog games')

    def test_comparison_responses_with_member_choices_are_private(self):
        client=self.member()
        self.assertEqual(client.get('/scout4.teams_page').headers['Cache-Control'],'no-store')
