"""Schedule-led weekly rollover with no production jobs, records, or network."""
import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from site_week import active_slate, EASTERN
from plug_dashboard import weekly_dashboard

NOW = datetime(2026,10,21,12,tzinfo=EASTERN)

def game(week=7,day='2026-10-25',away='NE',home='CHI',season=2026,kind='REG',**kw):
    return dict(game_id=f'{season}_{week:02}_{away}_{home}',season=str(season),week=str(week),
                game_type=kind,gameday=day,gametime='13:00',away_team=away,home_team=home,
                away_score='',home_score='',**kw)

class WeeklyRolloverTests(unittest.TestCase):
    def context(self,rows,now=NOW,legacy=(),live=()):
        app=Flask(__name__)
        app.add_url_rule('/matchup/<game_id>',endpoint='fans.matchup',view_func=lambda game_id:'')
        with app.test_request_context(),patch('plug_dashboard.load_schedule',return_value=rows), \
                patch('plug_dashboard.legacy_records',return_value=legacy), \
                patch.dict('fan_views._score_cache',{'games':list(live),'expires':float('inf'),'stale':False}):
            return weekly_dashboard([],lambda r:r,now)

    def test_all_current_games_appear_without_forecasts_and_old_week_does_not(self):
        rows=[game(),game(away='BUF',home='NYJ'),game(6,'2026-10-18',away='ATL',home='NO')]
        result=self.context(rows)
        self.assertEqual(result['active_slate'],(2026,'REG',7))
        self.assertEqual(len(result['games']),2)
        self.assertTrue(all(item['pending'] for item in result['games']))
        self.assertFalse(result['completed_games'] or result['underway_games'])

    def test_thursday_sunday_monday_are_one_slate_until_wednesday_eastern(self):
        rows=[game(day='2026-10-22'),game(away='BUF',home='NYJ'),game(day='2026-10-26',away='ATL',home='NO'),
              game(8,'2026-10-29',away='LAC',home='KC')]
        for stamp in (NOW,datetime(2026,10,26,23,tzinfo=EASTERN),datetime(2026,10,28,7,59,tzinfo=EASTERN)):
            self.assertEqual(active_slate(rows,stamp)[0],(2026,'REG',7))
        self.assertEqual(active_slate(rows,datetime(2026,10,28,8,tzinfo=EASTERN))[0],(2026,'REG',8))

    def test_actual_live_and_completed_states_not_just_elapsed_kickoff(self):
        now=datetime(2026,10,25,14,tzinfo=EASTERN)
        finished=game(away='BUF',home='NYJ');finished.update(away_score='21',home_score='24')
        rows=[game(),finished,game(away='ATL',home='NO')]
        live=[dict(away='NE',home='CHI',date='2026-10-25T17:00:00Z',state='in',completed=False)]
        result=self.context(rows,now,live=live)
        self.assertEqual(len(result['underway_games']),1)
        self.assertEqual(len(result['completed_games']),1)
        self.assertEqual(len(result['awaiting_games']),1)
        self.assertFalse(result['games'])

    def test_byes_offseason_and_postseason_use_schedule_season(self):
        rows=[game(18,'2027-01-03'),game(19,'2027-01-09',kind='WC')]
        self.assertEqual(active_slate(rows,datetime(2027,1,1,tzinfo=EASTERN))[0],(2026,'REG',18))
        self.assertEqual(active_slate(rows,datetime(2027,1,7,tzinfo=EASTERN))[0],(2026,'WC',19))
        self.assertEqual(active_slate(rows,datetime(2027,7,1,tzinfo=EASTERN)),(None,[]))
        # A sparse/bye slate is not padded from the last saved prediction week.
        self.assertEqual(len(active_slate([game()],NOW)[1]),1)

    def test_new_record_attaches_without_cached_slate_or_model_generation(self):
        row=game();ko='2026-10-25T17:00:00+00:00'
        legacy=dict(game_id=row['game_id'],away_team='NE',home_team='CHI',season=2026,week=7,
            kickoff_utc=ko,components={'Blend':{'pick':'NE','away_margin':3}},quote={'line':3},totals=None)
        import hashlib
        from plug_dashboard import ROOT
        legacy.update(version='plug-points-only-4',
            configuration_sha256=hashlib.sha256((ROOT/'automatic_model.json').read_bytes()).hexdigest(),
            weights={'scout_scoring':0.0,'plug_points_only':1.0},
            decision_cutoff_utc=(NOW-timedelta(minutes=1)).isoformat(),sealed_at_utc=NOW.isoformat(),
            status='SEALED_PREKICKOFF_RESEARCH',plug_points_only={'away_points':24.,'home_points':21.})
        legacy['quote'].update(market='Spread',kickoff_utc=ko,odds={'away':-110,'home':-110},
            sportsbook='Fixture',captured_at_utc=legacy['decision_cutoff_utc'],source_url='https://example.test/fixture')
        before=copy.deepcopy(legacy)
        self.assertTrue(self.context([row])['games'][0]['pending'])
        self.assertFalse(self.context([row],legacy=[legacy])['games'][0]['pending'])
        self.assertEqual(legacy,before)

    def test_post_kickoff_record_never_becomes_a_new_upcoming_pick(self):
        result=self.context([game()],datetime(2026,10,25,14,tzinfo=EASTERN))
        self.assertFalse(result['games'])
        self.assertTrue(result['awaiting_games'][0]['pending'])

    def test_optional_context_timeout_keeps_forecasting_and_publication_available(self):
        import os, subprocess
        import hosted_updates as hosted
        from types import SimpleNamespace
        from test_prediction_staging import fixture
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'root';fixture(root)
            (root/'data/scout4/blend/predictions').mkdir(parents=True)
            def execute(command, **kwargs):
                if command[2]=='context':
                    self.assertEqual(kwargs['timeout'],180)
                    self.assertTrue(kwargs['pass_fds'])
                    raise subprocess.TimeoutExpired(command,180)
                return subprocess.CompletedProcess(command,0)
            with patch.object(hosted.subprocess,'run',side_effect=execute), \
                    patch.object(hosted,'backup_database'),patch('qb_verification.refresh_qbs'), \
                    patch('scheduled_ats_capture.run',return_value=0), \
                    patch('prediction_staging.run_staged') as forecasts,patch('plug_publication.publish') as publish, \
                    patch.dict('sys.modules',{'fan_views':SimpleNamespace(prediction_performance=lambda *a:({},[],[]))}), \
                    patch.dict(os.environ,{'TREND_FINDAH_CONTEXT_RESEARCH':'1','TREND_FINDAH_EXPERT_AUTO_DRAFT':'0'}):
                self.assertEqual(hosted.locked_update(root),1)
                forecasts.assert_called_once();publish.assert_called_once()

    def test_personnel_streaming_preserves_json_bytes(self):
        import json,hashlib
        import polars as pl
        from scout4 import personnel
        from datetime import timedelta
        depth=pl.DataFrame({'dt':[(NOW-timedelta(days=1)).isoformat(),(NOW+timedelta(days=1)).isoformat()],
                            'team':['NE','BUF'],'pos_abb':['QB','QB'],'label':['é',None]})
        injuries=pl.DataFrame({'team':['NE'],'season':[2026],'week':[7],'note':[None]})
        class FixedDate(datetime):
            @classmethod
            def now(cls,tz=None): return NOW
        with tempfile.TemporaryDirectory() as directory,patch('nflreadpy.load_depth_charts',return_value=depth), \
                patch('nflreadpy.load_injuries',return_value=injuries),patch.object(personnel,'datetime',FixedDate):
            root=Path(directory);manifest=personnel.collect(2026,root)
            for kind,rows in [('depth_charts',depth.to_dicts()[:1]),('injuries',injuries.to_dicts())]:
                info=manifest['files'][kind];compressed=(root/info['path']).read_bytes()
                raw=__import__('gzip').decompress(compressed)
                self.assertEqual(raw,json.dumps(rows,default=str).encode())
                self.assertEqual(info['sha256'],hashlib.sha256(compressed).hexdigest())
                self.assertEqual(info['content_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(list(personnel._json_rows(root/info['path'])),rows)
