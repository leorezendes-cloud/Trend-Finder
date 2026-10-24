"""Isolated verification for member-pick final-score feed: no external network."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from flask import Flask
from fan_views import ROOT, _score_cache, _score_lock
from score_finals import request_finals, confirmed_score_rows


class FastFinalFeedTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.config['HOSTED_READ_ONLY_DATA']=True
        self.path=ROOT/'nfl_games.csv'
        self.schedule=dict(game_id='2026_07_NE_BUF',away_team='NE',home_team='BUF',
                           gameday='2026-10-18',gametime='16:25',away_score='',home_score='',result='')
        event=dict(date='2026-10-18T20:25:00Z',competitions=[dict(
            status={'type':{'state':'post','completed':True,'shortDetail':'Final'}},
            competitors=[
                {'homeAway':'away','team':{'abbreviation':'NE'},'score':'24'},
                {'homeAway':'home','team':{'abbreviation':'BUF'},'score':'17'}])])
        provider=MagicMock()
        provider.__enter__.return_value.read.return_value=json.dumps({'events':[event]}).encode()
        self.provider=provider

    def test_final_overlay_uses_lightweight_feed_and_request_cache(self):
        with patch.dict(_score_cache,{'expires':0,'games':[],'updated':None},clear=True), \
             patch('fan_views.read_csv',return_value=[self.schedule]), \
             patch('site_week.active_week',return_value=(2026,7)), \
             patch('fan_views.urlopen',return_value=self.provider) as upstream, \
             patch('fan_views.effective_rows',side_effect=AssertionError('full scoreboard work')), \
             patch('fan_views._scores_uncached',side_effect=AssertionError('full scoreboard rendering')):
            with self.app.test_request_context('/picks/'):
                finals=request_finals(self.path)
                self.assertEqual(len(finals),1)
                self.assertEqual(finals[0]['away_score'],'24')
                self.assertIs(request_finals(self.path),finals)
                overlay=confirmed_score_rows([self.schedule],finals,now=datetime(2026,10,24,tzinfo=timezone.utc))[0]
                self.assertEqual((overlay['away_score'],overlay['home_score'],overlay['result']),('24','17','-7'))
            with self.app.test_request_context('/huddle/leagues/'):
                self.assertEqual(request_finals(self.path),finals)
            upstream.assert_called_once()
            self.assertEqual(_score_cache['week'],(2026,7))

    def test_provider_failure_keeps_same_week_confirmed_final(self):
        saved={'date':'2026-10-18T20:25:00Z','state':'post','completed':True,
               'away':'NE','home':'BUF','away_score':'24','home_score':'17'}
        with patch.dict(_score_cache,{'expires':0,'games':[saved],'updated':'previous','week':(2026,7)},clear=True), \
             patch('fan_views.read_csv',return_value=[self.schedule]), \
             patch('site_week.active_week',return_value=(2026,7)), \
             patch('fan_views.urlopen',side_effect=OSError('provider offline')):
            with self.app.test_request_context('/picks/'):
                self.assertEqual(request_finals(self.path)[0]['away_score'],'24')
                self.assertTrue(_score_cache['stale'])

    def test_busy_scoreboard_does_not_block_and_never_leaks_previous_week(self):
        saved={'date':'2026-10-18T20:25:00Z','state':'post','completed':True,
               'away':'NE','home':'BUF','away_score':'24','home_score':'17'}
        with patch.dict(_score_cache,{'expires':99999999,'games':[saved],'week':(2026,7)},clear=True), \
             patch('fan_views.read_csv',return_value=[self.schedule]), \
             patch('fan_views.urlopen',side_effect=AssertionError('must not fetch')):
            with _score_lock:
                with patch('site_week.active_week',return_value=(2026,7)):
                    with self.app.test_request_context('/picks/'):
                        self.assertEqual(len(request_finals(self.path)),1)
                with patch('site_week.active_week',return_value=(2026,8)):
                    with self.app.test_request_context('/picks/'):
                        self.assertEqual(request_finals(self.path),[])

    def test_unhosted_or_unrelated_source_cannot_fetch_scores(self):
        with patch('fan_views.urlopen',side_effect=AssertionError('must not fetch')):
            self.app.config['HOSTED_READ_ONLY_DATA']=False
            with self.app.test_request_context('/picks/'):
                self.assertEqual(request_finals(self.path),[])
            self.app.config['HOSTED_READ_ONLY_DATA']=True
            with self.app.test_request_context('/picks/'):
                self.assertEqual(request_finals(self.path.parent/'another_schedule.csv'),[])


if __name__=='__main__':
    unittest.main()
