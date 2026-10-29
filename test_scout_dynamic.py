"""Real frozen-model Scout integration; synthetic inputs, zero network/publication."""
from contextlib import ExitStack
from datetime import timedelta
import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_prediction_staging import fixture, generate, NOW, csv_file
import scout_dynamic as worker
from scout_dynamic_store import (MAX_REVISIONS, append, canonical, closing, digest,
                                  finalize, folder, grade, journal, signed, utc)
from scout_dynamic_public import attach, enroll, records, state

REAL_MARKETS=worker.markets
GID='2030_04_NE_BUF'
SOURCE=Path(__file__).resolve().parent


class ScoutDynamicTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'data';fixture(self.root)
        self.seed=generate(self.root);self.seed_bytes=self.seed.read_bytes()
        self.game=json.loads(self.seed_bytes)
        self.kick=utc(self.game['kickoff_utc'])
        self.config,self.signature=worker.configuration(SOURCE)
        self.now=NOW
        self.quotes={kind:dict(line=line,captured_at_utc=NOW.isoformat(),
                              kickoff_utc=self.kick.isoformat(),source='Fixture',url='https://example.test')
                     for kind,line in (('Spread',3.0),('Total',45.0))}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict('os.environ',{
            'TREND_FINDAH_SCOUT_DYNAMIC_RESEARCH':'1','TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC':'0'}))
        self.market=self.stack.enter_context(patch('scout_dynamic.markets',side_effect=lambda *a:self.quotes))

    def cycle(self,at=None):
        at=at or self.now
        return worker.cycle(self.root,now=at,source=SOURCE,clock=lambda:at)

    def activate(self):
        path=self.root/'scout_dynamic/activation.json';path.parent.mkdir(exist_ok=True)
        path.write_bytes(canonical(signed(dict(policy=worker.POLICY,
            activated_at=(NOW-timedelta(minutes=1)).isoformat(),configuration_sha256=self.signature))))
        self.stack.enter_context(patch.dict('os.environ',{'TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC':'1'}))

    def item(self):
        return dict(scout={'game':{k:self.game[k] for k in ('game_id','away_team','home_team','kickoff_utc')}},
                    saved_picks={'spread':{'side':'BUF'}},locked_quotes={'original':'unchanged'},
                    plug_ats_pick='BUF -8',plug_ou_pick='Under 50',plug_ats_result='Win',
                    plug_ats_source={'original':True},expert_picks={'ats_side':'BUF'})

    def test_matches_original_frozen_production_and_preserves_all_original_bytes(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.cycle();self.assertEqual(result['refreshed'],1,result)
        row=journal(self.root,GID)[-1];original=json.loads(self.seed_bytes)
        self.assertEqual(row['projection']['away_margin'],original['components']['Blend']['away_margin'])
        self.assertEqual(row['ats_side'],original['components']['Blend']['pick'])
        self.assertAlmostEqual(row['totals']['total'],original['totals']['prediction']['total'])
        self.assertEqual(row['ou_side'],original['totals']['prediction']['lean'])
        self.assertEqual(row['model_family'],'Scout 4.0')
        self.assertEqual(row['scout_scoring']['model_family'],'Scout 4.0')
        for path,raw in before.items():self.assertEqual(path.read_bytes(),raw,str(path))

    def test_unchanged_inputs_and_fresh_identical_quotes_do_not_duplicate(self):
        self.cycle();first=journal(self.root,GID)
        self.now+=timedelta(minutes=15)
        for q in self.quotes.values():q['captured_at_utc']=self.now.isoformat()
        manifest=self.root/'data/scout4/2030/latest.json'
        m=json.loads(manifest.read_text());m['retrieved_at']=self.now.isoformat();manifest.write_text(json.dumps(m))
        self.cycle()
        self.assertEqual(journal(self.root,GID),first)

    def test_spread_moves_flip_ats_without_shifting_independent_points(self):
        self.cycle();old=journal(self.root,GID)[-1]
        self.quotes['Spread']['line']=20
        self.now+=timedelta(minutes=15);self.cycle();new=journal(self.root,GID)[-1]
        self.assertNotEqual(old['ats_side'],new['ats_side'])
        self.assertEqual(old['projection'],new['projection'])
        self.assertEqual(old['scout_scoring'],new['scout_scoring'])
        self.assertEqual(new['revision'],2)

    def test_totals_follow_unchanged_market_anchored_formula(self):
        self.cycle();first=journal(self.root,GID)[-1]
        self.quotes['Total']['line']=20;self.now+=timedelta(minutes=15);self.cycle()
        last=journal(self.root,GID)[-1]
        from scout4.totals import predict
        expected=predict(self.config['totals_candidate']['model'],last['total_features'],20)
        self.assertEqual(last['totals']['total'],expected['total'])
        self.assertTrue(last['totals']['market_anchored'])
        self.assertNotEqual(last['ou_side'],first['ou_side'])
        self.assertEqual(last['projection'],first['projection'])

    def test_eligible_corrected_prior_input_refreshes_projection(self):
        self.cycle();old=journal(self.root,GID)[-1]
        path=self.root/'nfl_games.csv'
        rows=list(csv.DictReader(path.read_text().splitlines()));rows[0]['away_score']='45';csv_file(path,rows)
        self.now+=timedelta(minutes=15);self.cycle();new=journal(self.root,GID)[-1]
        self.assertNotEqual(old['inputs_sha256'],new['inputs_sha256'])
        self.assertNotEqual(old['projection'],new['projection'])
        self.assertEqual(self.seed.read_bytes(),self.seed_bytes)

    def test_target_and_future_results_never_enter_projection_inputs(self):
        self.cycle();old=journal(self.root,GID)
        # A later game's score is not a prior-week model input.
        path=self.root/'nfl_games.csv';rows=list(csv.DictReader(path.read_text().splitlines()))
        rows.append(dict(rows[-1],game_id='2030_05_NE_BUF',week='5',gameday='2030-10-24',away_score='99',home_score='0'))
        csv_file(path,rows);self.now+=timedelta(minutes=15);self.cycle()
        self.assertEqual(journal(self.root,GID),old)

    def test_market_outage_preserves_last_valid_revision(self):
        self.cycle();old=journal(self.root,GID)
        self.market.side_effect=ValueError('provider offline')
        report=self.cycle(NOW+timedelta(minutes=15))
        self.assertIn(GID,report['pending']);self.assertEqual(journal(self.root,GID),old)

    def test_kickoff_closes_despite_market_stats_and_config_failure(self):
        self.cycle();self.activate();enroll(self.root,GID,journal(self.root,GID)[-1],now=NOW)
        self.market.side_effect=ValueError('offline')
        with patch('scout_dynamic.configuration',side_effect=ValueError('config unavailable')):
            report=self.cycle(self.kick)
        self.assertEqual(report['closed'],1)
        path=folder(self.root,GID)/'closing.json';raw=path.read_bytes()
        self.cycle(self.kick+timedelta(minutes=15));self.assertEqual(path.read_bytes(),raw)
        value=state(self.root,self.item()['scout']['game'],now=self.kick)
        self.assertEqual(value['status'],'locked')
        with self.assertRaisesRegex(ValueError,'closed'):
            append(self.root,GID,journal(self.root,GID)[-1],clock=lambda:NOW)

    def test_lock_boundary_rejects_late_write_without_new_revision(self):
        self.cycle();row=dict(journal(self.root,GID)[-1]);row.pop('sha256');row.pop('revision')
        row['decision_id']='changed'
        with self.assertRaisesRegex(ValueError,'pregame'):
            append(self.root,GID,row,clock=lambda:self.kick)
        self.assertEqual(len(journal(self.root,GID)),1)

    def test_bounded_retention_preserves_final_prediction(self):
        self.cycle();row=journal(self.root,GID)[-1]
        for i in range(MAX_REVISIONS+10):
            change={k:v for k,v in row.items() if k not in ('sha256','revision')}
            change['decision_id']=str(i);change['evaluated_at']=(NOW+timedelta(seconds=i+1)).isoformat()
            append(self.root,GID,change,clock=lambda:NOW+timedelta(hours=1))
        rows=journal(self.root,GID)
        self.assertEqual(len(rows),MAX_REVISIONS);self.assertEqual(rows[-1]['revision'],MAX_REVISIONS+11)
        final=finalize(self.root,GID,now=self.kick);self.assertEqual(final,rows[-1])
        self.assertLess((folder(self.root,GID)/'revisions.json').stat().st_size,512*1024)

    def test_publication_needs_gate_fresh_issuance_and_kickoff_receipt(self):
        self.cycle();obj=self.item();original=copy.deepcopy(obj)
        attach(self.root,obj,now=NOW);self.assertEqual(obj,original)
        self.activate();obj=self.item();attach(self.root,obj,now=NOW)
        self.assertEqual(obj['scout_dynamic']['status'],'review')
        self.cycle();obj=self.item();attach(self.root,obj,now=NOW)
        self.assertEqual(obj['scout_dynamic']['status'],'pregame')
        for key,value in original.items():self.assertEqual(obj[key],value,key)
        attach(self.root,obj,now=self.kick);self.assertEqual(obj['scout_dynamic']['status'],'review')
        finalize(self.root,GID,now=self.kick)
        obj=self.item();obj['final_score']={'away':20,'home':24};attach(self.root,obj,now=self.kick)
        self.assertEqual(obj['scout_dynamic']['status'],'locked')
        self.assertEqual(obj['scout_dynamic']['grades'],grade(closing(self.root,GID),(20,24)))

    def test_grading_uses_closing_line_and_keeps_legacy_record_separate(self):
        self.activate();self.cycle();row=journal(self.root,GID)[-1]
        finalize(self.root,GID,now=self.kick)
        self.quotes['Spread']['line']=99;self.quotes['Total']['line']=100
        result=records(self.root,{GID:(20,24)},2030,4,now=self.kick)
        self.assertEqual(len(result['scout_dynamic_records']),1)
        self.assertEqual(result['scout_dynamic_records'][0]['grades'],grade(row,(20,24)))
        self.assertEqual(self.seed.read_bytes(),self.seed_bytes)
        for scores in ((-1,3),(1.5,3),(float('nan'),3),(True,3)):
            with self.assertRaises(ValueError):grade(row,scores)

    def test_restart_persistence_and_conflicting_records_fail_closed(self):
        from hosted_updates import initialize_data
        self.cycle();persistent=Path(self.temp.name)/'disk'
        initialize_data(self.root,persistent)
        redeploy=Path(self.temp.name)/'redeploy';redeploy.mkdir()
        initialize_data(redeploy,persistent)
        self.assertEqual(journal(self.root,GID),journal(redeploy,GID))
        self.assertTrue((redeploy/'scout_dynamic').is_symlink())
        conflicting=Path(self.temp.name)/'conflict';p=folder(conflicting,GID)/'revisions.json';p.parent.mkdir(parents=True);p.write_text('conflict')
        with self.assertRaisesRegex(ValueError,'Conflicting'):initialize_data(conflicting,persistent)
        self.assertEqual(p.read_text(),'conflict')

    def test_corrupted_journal_never_becomes_public(self):
        self.activate();self.cycle()
        p=folder(self.root,GID)/'revisions.json';p.write_text(p.read_text().replace('Scout 4.0','Scout 4.1'))
        obj=self.item();attach(self.root,obj,now=NOW)
        self.assertEqual(obj['scout_dynamic']['status'],'review')

    def test_independent_store_does_not_touch_plug_artifacts(self):
        protected=[]
        for name in ('plug_dynamic_research','plug_dynamic_closing','plug_dynamic_official'):
            path=self.root/name/'keep.json';path.parent.mkdir();path.write_text('unchanged');protected.append(path)
        self.cycle();finalize(self.root,GID,now=self.kick)
        for p in protected:self.assertEqual(p.read_text(),'unchanged')

    def test_bad_config_or_old_stats_never_creates_revision(self):
        with patch('scout_dynamic.configuration',side_effect=ValueError('weights changed')):
            report=self.cycle()
        self.assertIn('inputs',report['errors']);self.assertEqual(journal(self.root,GID),[])
        self.cycle(NOW+timedelta(hours=25));self.assertEqual(journal(self.root,GID),[])

    def test_existing_scheduler_finally_runs_scout_even_if_market_capture_fails(self):
        from hosted_updates import refresh_scheduled_market
        with patch('scheduled_ats_capture.run',return_value=1),patch('scout_dynamic.cycle') as cycle:
            with self.assertRaises(RuntimeError):refresh_scheduled_market(self.root)
            cycle.assert_called_once_with(self.root)
        with patch('scheduled_ats_capture.run',return_value=0),patch('scout_dynamic.cycle',side_effect=ValueError('bad Scout')):
            refresh_scheduled_market(self.root)  # Cannot change Plug success into failure.

    def test_no_worker_or_public_change_by_default(self):
        with patch.dict('os.environ',{'TREND_FINDAH_SCOUT_DYNAMIC_RESEARCH':'0','TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC':'0'}):
            self.assertEqual(self.cycle(),{'state':'disabled'})
            self.assertEqual(records(self.root,{},2030,4),{})

    def test_public_templates_display_same_saved_revision_without_model_execution(self):
        from app import app
        from flask import render_template
        self.activate();self.cycle()
        obj=self.item();attach(self.root,obj,now=NOW)
        from jinja2 import Environment,FileSystemLoader
        env=Environment(loader=FileSystemLoader(str(SOURCE/'templates')))
        env.filters['eastern_time']=str
        for template in ('_scout_dynamic.html',):
            with patch('scout_dynamic.evaluate',side_effect=AssertionError('request recalculated model')):
                html=env.get_template(template).render(item=obj)
            row=obj['scout_dynamic']['row'];line=row['spread']['line'] if row['ats_side']=='NE' else -row['spread']['line']
            self.assertIn(f"{row['ats_side']} {line:+g}",html)
            self.assertIn('Scout O/U:',html)
        # Existing route integration is independently gated from Plug state.
        with app.test_request_context('/the-plug/2030/4/NE-BUF'), \
             patch('expert_beta.__file__',str(self.root/'expert_beta.py')), \
             patch('expert_beta.clock',return_value=NOW), \
             patch('expert_beta.accessible',return_value=True), \
             patch('expert_beta.results_for',return_value=None), \
             patch('plug_line_movement.compare_line',return_value=None), \
             patch('plug_ou_weekly_v3.read_effective',return_value=None):
            from test_expert_beta import fixture as expert_fixture
            from expert_beta import public_record
            scout=expert_fixture('NE','BUF');scout['game'].update(self.item()['scout']['game'])
            record=dict(scout=scout,version='original',kind='production_import',generated_at=NOW.isoformat(),expert=None)
            detail=public_record(record,True)
            self.assertEqual(detail['scout_dynamic']['row']['sha256'],obj['scout_dynamic']['row']['sha256'])
            for name in ('expert_game.html','expert_game_mobile.html'):
                html=render_template(name,item=detail,versions=[])
                self.assertIn('Current Scout prediction',html)
            with app.test_request_context('/the-plug/2030/4/NE-BUF?version=original'):
                self.assertNotIn('scout_dynamic',public_record(record,True))

    def test_real_saved_price_adapter_rejects_outage_stale_and_wrong_identity(self):
        from public_pick_market import matchup_public_market
        game=self.item()['scout']['game']
        raw=dict(game_id=GID,away_team='NE',home_team='BUF',market='Spread',
                 side_a='NE',side_b='BUF',line_a='3',line_b='-3',odds_a='-110',odds_b='-110',
                 captured_at_utc=NOW.isoformat(),kickoff_utc=self.kick.isoformat(),sportsbook='DraftKings',
                 source_url='https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
                 handle_a='',handle_b='',bets_a='',bets_b='')
        total=dict(raw,market='Total',side_a='Over',side_b='Under',line_a='45',line_b='45')
        csv_file(self.root/'public_money_snapshots.csv',[raw,total])
        valid=REAL_MARKETS(self.root,game,NOW)
        self.assertEqual(valid['Spread']['line'],3)
        for changed in ({'home_team':'NYJ'},{'line_b':'-7'},
                        {'captured_at_utc':(NOW-timedelta(hours=7)).isoformat()},
                        {'captured_at_utc':(NOW+timedelta(seconds=1)).isoformat()},
                        {'source_url':'https://example.test/unverified'}):
            csv_file(self.root/'public_money_snapshots.csv',[dict(raw,**changed),total])
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                REAL_MARKETS(self.root,game,NOW)

    def test_dashboard_comparison_and_records_share_latest_validated_revision(self):
        from app import app
        from flask import render_template
        from plug_dashboard import weekly_dashboard
        self.activate();self.cycle()
        self.quotes['Spread']['line']=20;self.now+=timedelta(minutes=15);self.cycle()
        obj=self.item();obj['scout']['game'].update(season=2030,week=4)
        obj['scout'].update(scores={'NE':22,'BUF':26},sources=[])
        obj.update(show_scores=True,expert_available=False,expert_access=False,expert_picks=None,
                   assessment=None,pending=False,forecast_pending=False,saved_at=NOW.isoformat(),url='/the-plug/2030/4/NE-BUF')
        g=dict(game_id=GID,season='2030',week='4',game_type='REG',away_team='NE',home_team='BUF',
               gameday='2030-10-17',gametime='20:15',away_score='',home_score='')
        with app.test_request_context('/the-plug'), \
             patch('plug_dashboard.ROOT',self.root), \
             patch('plug_dashboard.load_schedule',return_value=[g]), \
             patch('plug_dashboard.combined_cards',return_value=([obj],[])), \
             patch('site_week.active_slate',return_value=((2030,'REG',4),[g])), \
             patch('plug_ats_v5_weekly.effective_week',return_value=None), \
             patch('plug_ou_weekly_v3.read_effective',return_value=None), \
             patch('scout_dynamic.evaluate',side_effect=AssertionError('public model execution')):
            ctx=weekly_dashboard([],None,self.now)
            html=render_template('expert_dashboard.html',**ctx)
            self.assertIn('NE +20',html)
            self.assertEqual(ctx['games'][0]['scout_dynamic']['row']['revision'],2)
            comparison=render_template('_comparison_prediction.html',prediction_item=obj,
                                       use_results_forecast=False,forecast=None,game=g)
            self.assertIn('NE +20',comparison)
            context=records(self.root,{},2030,4,now=self.now)
            html=render_template('_scout_dynamic_records.html',**context)
            self.assertIn('NE +20',html)
            self.assertEqual(context['scout_dynamic_records'][0]['revision'],2)
            pinned=render_template('_comparison_prediction.html',prediction_item=obj,
                                  use_results_forecast=True,forecast=json.loads(self.seed_bytes),game=g)
            self.assertNotIn('Current Scout prediction',pinned)

    def test_readiness_requires_current_validated_worker_and_closing(self):
        from scout_dynamic_cli import check
        self.cycle()
        with patch('scout_dynamic_cli.configuration',return_value=(self.config,self.signature)):
            # Status uses actual completion time; pin only that metadata to fixture time.
            p=self.root/'scout_dynamic/status.json';d=json.loads(p.read_text());d['checked_at']=NOW.isoformat();p.write_text(json.dumps(d))
            self.assertTrue(check(self.root,now=NOW,hosted=False)['ready'])
            self.assertFalse(check(self.root,now=self.kick,hosted=False)['ready'])

if __name__=='__main__':unittest.main()
