"""Regression checks for the release's scoreboard/highlight lock cycle."""
import json
import unittest
from unittest.mock import MagicMock, patch
from flask import Flask
import fan_views


class ReleaseMemoryTests(unittest.TestCase):
    def test_badges_can_read_final_signature_without_recursing_into_scores(self):
        app = Flask(__name__)
        app.config['HOSTED_READ_ONLY_DATA'] = True
        payload = {'events':[{'date':'2030-10-18T00:15:00Z','competitions':[{
            'status':{'type':{'state':'pre','shortDetail':'Scheduled'}},
            'competitors':[{'homeAway':side,'team':{'abbreviation':team},'score':'0'}
                           for side,team in [('away','NE'),('home','BUF')]]}]}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        def highlights(**kwargs):
            from score_finals import final_signature
            self.assertEqual(final_signature(fan_views.ROOT/'nfl_games.csv'), ())
            return []
        with app.test_request_context('/scores.json'), patch.dict(fan_views._score_cache,
                {'expires':0,'games':[],'updated':None},clear=True), \
                patch('fan_views.read_csv',return_value=[]), \
                patch('fan_views.urlopen',return_value=response), \
                patch('active_trends.load_highlights',side_effect=highlights), \
                patch('fan_views.scores',side_effect=AssertionError('recursive scoreboard')):
            self.assertEqual(fan_views._scores_uncached().status_code,200)

    def test_all_literal_template_dependencies_are_packaged(self):
        from app import app
        from jinja2 import meta
        for name in app.jinja_env.list_templates():
            source = app.jinja_env.loader.get_source(app.jinja_env, name)[0]
            for dependency in meta.find_referenced_templates(app.jinja_env.parse(source)):
                if dependency is not None:
                    app.jinja_env.get_template(dependency)

    def test_busy_scoreboard_does_not_wait_for_refresh_lock(self):
        app = Flask(__name__)
        with app.test_request_context('/scores.json'), patch.dict(fan_views._score_response,
                {'key':None,'expires':0,'body':None},clear=True):
            self.assertTrue(fan_views._score_response_lock.acquire(blocking=False))
            try:
                response = fan_views.scores()
                self.assertEqual(response[1],503)
                self.assertEqual(response[2]['Retry-After'],'1')
            finally:
                fan_views._score_response_lock.release()
