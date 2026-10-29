"""Production integration: real decisions/journals/closing and bounded workers."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

from hosted_updates import initialize_data, refresh_scheduled_market, update_once
from plug_dynamic_journal import append, read
from plug_dynamic_closing import finalize, read_closing, _canonical
from plug_dynamic_pregame import decide
from plug_dynamic_official import POLICY, PIPELINE, apply, enroll, history, record_context
from plug_dynamic_readiness import checkpoint, check
from test_plug_dynamic_receipt_bridge import ATS, OU, GID, KICK

AT='2026-10-28T13:00:00+00:00'

def decision(at=AT, spread=-7.5, total=48.5):
    return decide(away_team='BAL',home_team='PIT',model_away_spread=-8,
                  v14_total=49.5,original_total_side='Over',market_away_spread=spread,
                  market_total=total,quote_observed_utc=at,evaluation_utc=at,
                  kickoff_utc=KICK)

def activate(root):
    p=Path(root)/'plug_dynamic_official/activation.json'
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(dict(policy=POLICY,pipeline=PIPELINE,
                                activated_at_utc='2026-10-28T12:30:00+00:00')))

def item(final=None):
    result={'scout':{'game':dict(game_id=GID,away_team='BAL',home_team='PIT',kickoff_utc=KICK)},
            'saved_picks':{'spread':{'side':'PIT'}},'plug_ou_pick':'Over 50'}
    if final:result['final_score']=dict(away=final[0],home=final[1])
    return result

class ProductionIntegration(unittest.TestCase):
    def sources(self):
        stack=ExitStack()
        ats=dict(ATS,policy='fixture-legacy',games=[dict(ATS['games'][0],selected=True,side='BAL',away_line=-7.5)])
        stack.enter_context(patch('plug_ats_v5_weekly.read_week',return_value=ats))
        stack.enter_context(patch('plug_ou_receipts.read',return_value=OU))
        stack.enter_context(patch.dict('os.environ',{'TREND_FINDAH_DYNAMIC_OFFICIAL':'1'}))
        return stack

    def test_real_line_changes_idempotency_prospective_records_and_locked_grades(self):
        with tempfile.TemporaryDirectory() as root,self.sources():
            # Pre-activation research remains research until freshly observed.
            row=append(root,GID,decision('2026-10-28T12:00:00+00:00'))
            activate(root)
            self.assertFalse(apply(root,item(),as_of_utc=AT))
            enroll(root,GID,row,AT)
            unchanged=append(root,GID,decision())
            self.assertEqual(row,unchanged)
            card=item()
            self.assertTrue(apply(root,card,as_of_utc=AT))
            self.assertEqual(card['plug_ats_pick'],'BAL -7.5')
            self.assertEqual(card['plug_ou_pick'],'Under 48.5')
            self.assertEqual(card['saved_picks']['spread']['side'],'PIT')
            # Changed valid market quote turns both selections off.
            later='2026-10-28T14:00:00+00:00'
            append(root,GID,decision(later,-6.5,47.5))
            card=item();apply(root,card,as_of_utc=later)
            self.assertEqual(card['plug_ats_status'],'stay_away')
            self.assertEqual(card['plug_ou_status'],'stay_away')
            # Returning across the thresholds restores selections with new lines.
            later='2026-10-28T15:00:00+00:00'
            append(root,GID,decision(later,-8.5,49))
            append(root,GID,decision('2026-10-28T16:00:00+00:00',-8.5,49))
            self.assertEqual(len(read(root,GID)),3)
            self.assertEqual(history(root,{},as_of_utc=later)[0]['ats_result'],'Pending')
            receipt=finalize(root,GID,as_of_utc=KICK)
            card=item((28,20));self.assertTrue(apply(root,card,as_of_utc=KICK))
            self.assertEqual(card['plug_ats_result'],'Win') # PIT +8.5
            self.assertEqual(card['plug_ou_result'],'Loss') # Over 49, score 48
            with self.assertRaises(ValueError):append(root,GID,decision(later,-9,55))
            self.assertEqual(receipt,read_closing(root,GID))
            ctx=record_context(root,{GID:(28,20)},2026,8,as_of_utc=KICK)
            self.assertEqual(ctx['dynamic_record_counts']['ats']['Win'],1)
            self.assertNotIn('legacy',ctx['dynamic_record_counts'])

    def test_flag_alone_and_pre_activation_kickoff_cannot_publish_research(self):
        with tempfile.TemporaryDirectory() as root,self.sources():
            append(root,GID,decision())
            card=item();self.assertFalse(apply(root,card,as_of_utc=AT))
            self.assertTrue(card['plug_dynamic_review'])
            self.assertEqual(card['plug_ou_pick'],None)
            self.assertTrue(record_context(root,{},2026,8)['dynamic_record_review'])
            activate(root)
            path=Path(root)/'plug_dynamic_official/activation.json'
            obj=json.loads(path.read_text());obj['activated_at_utc']='2026-10-30T00:00:00+00:00'
            path.write_text(json.dumps(obj))
            self.assertFalse(apply(root,item(),as_of_utc='2026-10-30T01:00:00+00:00'))
            self.assertEqual(history(root,{},as_of_utc='2026-10-30T01:00:00+00:00'),[])

    def test_kickoff_crossed_while_waiting_for_journal_lock_rejects_write(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'Kickoff passed'):
                append(root,GID,decision(),clock=lambda:datetime.fromisoformat(KICK))
            self.assertEqual(read(root,GID),[])

    def test_recomputed_closing_checksum_cannot_change_locked_price(self):
        with tempfile.TemporaryDirectory() as root:
            append(root,GID,decision());finalize(root,GID,as_of_utc=KICK)
            p=Path(root)/'plug_dynamic_closing'/(GID+'.json')
            payload=json.loads(p.read_text());payload.pop('receipt_sha256')
            payload['ats_away_line']=-20
            payload['receipt_sha256']=hashlib.sha256(_canonical(payload)).hexdigest()
            p.write_bytes(_canonical(payload))
            with self.assertRaisesRegex(ValueError,'differs from locked'):read_closing(root,GID)

    def test_persistent_restart_preserves_journals_closing_and_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir();target=Path(tmp)/'persistent'
            append(source,GID,decision());finalize(source,GID,as_of_utc=KICK);activate(source)
            before={p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file() and p.suffix!='.lock'}
            initialize_data(source,target)
            initialize_data(source,target)
            for p,data in before.items():self.assertEqual((source/p).read_bytes(),data)
            for name in ('plug_dynamic_research','plug_dynamic_closing','plug_dynamic_official'):
                self.assertTrue((source/name).is_symlink())
            redeploy=Path(tmp)/'redeploy';redeploy.mkdir()
            initialize_data(redeploy,target)
            self.assertEqual(read_closing(redeploy,GID),read_closing(source,GID))

    def test_persistence_conflict_fails_before_discarding_either_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'source';b=Path(tmp)/'persistent'
            for folder,text in ((a,'first'),(b,'second')):
                p=folder/'plug_dynamic_closing/game.json';p.parent.mkdir(parents=True);p.write_text(text)
            with self.assertRaises(ValueError):initialize_data(a,b)
            self.assertEqual((a/'plug_dynamic_closing/game.json').read_text(),'first')
            self.assertEqual((b/'plug_dynamic_closing/game.json').read_text(),'second')

    def test_historical_checkpoint_allows_journal_append_but_no_old_byte_changes(self):
        with tempfile.TemporaryDirectory() as root,patch('plug_ats_select.storage_root',return_value=Path(root)/'ats'):
            append(root,GID,decision())
            p=Path(root)/'checkpoint.json';checkpoint(root,p)
            append(root,GID,decision('2026-10-28T14:00:00+00:00',-6.5))
            self.assertGreater(checkpoint(root,p,True),0)
            journal=Path(root)/'plug_dynamic_research'/(GID+'.jsonl')
            journal.write_text(journal.read_text().replace('BAL','PIT',1))
            with self.assertRaises(ValueError):checkpoint(root,p,True)

    def test_restart_checkpoint_requires_an_actual_new_boot(self):
        with tempfile.TemporaryDirectory() as tmp,patch('plug_ats_select.storage_root',return_value=Path(tmp)/'ats'):
            root=Path(tmp);logs=root/'logs';logs.mkdir()
            boot=logs/'dynamic_boot.json'
            boot.write_text(json.dumps(dict(boot_id='first',pipeline=PIPELINE)))
            append(root,GID,decision())
            snapshot=logs/'checkpoint.json';checkpoint(root,snapshot)
            with self.assertRaisesRegex(ValueError,'Restart the Render'):
                checkpoint(root,snapshot,True,require_restart=True)
            boot.write_text(json.dumps(dict(boot_id='second',pipeline=PIPELINE)))
            checkpoint(root,snapshot,True,require_restart=True)
            verified=json.loads((logs/'dynamic_restart_verified.json').read_text())
            self.assertEqual(verified['boot_id'],'second')

    def test_only_real_gunicorn_web_boot_records_restart_identity(self):
        import runpy
        with patch('hosted_updates.record_web_boot') as boot,patch('hosted_updates.start_scheduler'):
            runpy.run_path('gunicorn.conf.py')['post_worker_init'](None)
            boot.assert_called_once()
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'TREND_FINDAH_ENV':'production'}):
            from hosted_updates import record_web_boot
            record_web_boot(tmp)
            first=json.loads((Path(tmp)/'logs/dynamic_boot.json').read_text())['boot_id']
            record_web_boot(tmp)
            self.assertNotEqual(first,json.loads((Path(tmp)/'logs/dynamic_boot.json').read_text())['boot_id'])

    def test_pending_qb_is_visible_nonfatal_but_real_errors_fail(self):
        for error,expected in ((ValueError('6 requested/completed games still need QB verification'),'ok'),
                               (ValueError('Corrupt verification store'),'needs attention')):
            with self.subTest(error=error),tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
                root=Path(tmp);(root/'nfl_games.csv').write_text('game_id,away_team,home_team\n')
                (root/'data/scout4/blend/predictions').mkdir(parents=True)
                for name in ('hosted_updates.backup_database','update_nfl_games.main','scout4.collect.collect',
                             'prediction_staging.run_staged','plug_ou_receipts.issue_pending',
                             'plug_ou_weekly_v3.issue_weekly','plug_publication.publish'):
                    stack.enter_context(patch(name,return_value=None))
                stack.enter_context(patch('qb_verification.refresh_qbs',side_effect=error))
                stack.enter_context(patch('scheduled_ats_capture.run',return_value=0))
                stack.enter_context(patch.dict('os.environ',{'TREND_FINDAH_CONTEXT_RESEARCH':'0',
                    'TREND_FINDAH_EXPERT_AUTO_DRAFT':'0','TREND_FINDAH_DYNAMIC_RESEARCH':'0',
                    'TREND_FINDAH_DYNAMIC_OFFICIAL':'0'}))
                status=update_once(root)
                self.assertEqual(status['state'],expected)
                self.assertEqual(status['stages']['predictions'],'ok')
                if expected=='ok':self.assertIn('QB verification',status['warnings'])

    def test_regular_market_path_runs_on_non_gameday(self):
        with patch('scheduled_ats_capture.run',return_value=0) as capture:
            refresh_scheduled_market(Path('/tmp'),datetime(2026,10,27,16,tzinfo=timezone.utc))
            capture.assert_called_once()

    def test_readiness_requires_current_successful_worker_timer_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp,self.sources():
            root=Path(tmp);logs=root/'logs';logs.mkdir()
            append(root,GID,decision())
            full=dict(pipeline=PIPELINE,state='ok',finished=AT,warnings={'QB':'6 pending'})
            market=dict(pipeline=PIPELINE,state='ok',dynamic_finished_utc=AT,
                        dynamic={'state':'partial','unavailable':1,'games':{'missing':'no v5 receipt'}},
                        dynamic_closing={'errors':0})
            (logs/'auto_update_status.json').write_text(json.dumps(full))
            (logs/'ats_capture_status.json').write_text(json.dumps(market))
            timer=logs/'game-day-market_scheduler.jsonl'
            timer.write_text(json.dumps(dict(at=AT,pipeline=PIPELINE,state='success'))+'\n')
            result=check(root,now=datetime.fromisoformat(AT),require_hosted=False)
            self.assertTrue(result['ready'],result)
            self.assertEqual(len(result['warnings']),2)
            waiting={'2026_09_JAX_BAL':'Awaiting the upcoming weekly receipt'}
            market['dynamic']=dict(state='ok',unavailable=0,next_week_games=waiting)
            (logs/'ats_capture_status.json').write_text(json.dumps(market))
            result=check(root,now=datetime.fromisoformat(AT),require_hosted=False)
            self.assertTrue(result['ready'],result)
            self.assertEqual(result['awaiting_next_week'],waiting)
            self.assertEqual(len(result['warnings']),1)  # The real QB warning stays visible.
            market['dynamic_error']='corrupt stored evidence'
            (logs/'ats_capture_status.json').write_text(json.dumps(market))
            self.assertFalse(check(root,now=datetime.fromisoformat(AT),require_hosted=False)['ready'])

    def test_missing_live_scheduler_evidence_never_passes_readiness(self):
        with tempfile.TemporaryDirectory() as root:
            result=check(root,require_hosted=False)
            self.assertFalse(result['ready'])
            self.assertIn('Awaiting successful unattended market scheduler tick',result['errors'])

if __name__=='__main__':unittest.main()

class RenderedIntegration(unittest.TestCase):
    sources=ProductionIntegration.sources
    # Reuse setup helpers, not the inherited tests, for a real dashboard and
    # weekly-results join against the same official record.
    def test_dashboard_weekly_and_newsletter_share_dynamic_selection(self):
        from app import app
        from expert_beta import instant
        from plug_dashboard import weekly_dashboard
        from weekly_results import build_results
        from flask import render_template
        import csv
        with tempfile.TemporaryDirectory() as tmp,self.sources(),ExitStack() as stack:
            root=Path(tmp);activate(root)
            row=append(root,GID,decision());enroll(root,GID,row,AT)
            game=dict(game_id=GID,season=2026,week=8,game_type='REG',away_team='BAL',
                      home_team='PIT',gameday='2026-10-29',gametime='16:00',
                      away_score='',home_score='',spread_line='-7.5')
            with (root/'nfl_games.csv').open('w') as f:
                w=csv.DictWriter(f,fieldnames=list(game));w.writeheader();w.writerow(game)
            scout=item()['scout'];scout['game'].update(season=2026,week=8)
            obj=dict(item(),scout=scout,show_scores=False,expert_available=False,
                     expert_access=False,expert_picks=None,assessment=None,pending=False,
                     saved_picks={'spread':{'side':'PIT'},'total':{'side':'Over'}},
                     locked_quotes={},url='/the-plug/2026/8/BAL-PIT?version=original')
            stack.enter_context(patch('plug_dashboard.ROOT',root))
            stack.enter_context(patch('plug_dashboard.load_schedule',return_value=[game]))
            stack.enter_context(patch('plug_dashboard.combined_cards',return_value=([obj],[])))
            stack.enter_context(patch('site_week.active_slate',return_value=((2026,'REG',8),[game])))
            stack.enter_context(patch('plug_ou_weekly_v3.read_effective',return_value=None))
            with app.test_request_context('/the-plug'):
                context=weekly_dashboard([],None,instant(AT))
                html=render_template('expert_dashboard.html',**context)
                self.assertIn('BAL -7.5',html)
                self.assertIn('Under 48.5',html)
                self.assertNotIn('version=original',context['games'][0]['url'])
                detail=render_template('_plug_dynamic_official.html',item=obj)
                self.assertIn('BAL -7.5',detail)
                self.assertIn('Under 48.5',detail)
            stack.enter_context(patch('weekly_results.load_games',return_value={GID:game}))
            stack.enter_context(patch('forecast_history.official_sources',return_value={}))
            stack.enter_context(patch('plug_ats_v5_weekly.published_history',return_value=([],{})))
            with patch('plug_dynamic_official.datetime') as dt:
                dt.now.return_value=instant(AT)
                results=build_results(root,8)
            self.assertEqual(results['plug_tally']['selected'],0)
            self.assertEqual(results['dynamic_record_counts']['ats']['Pending'],1)
            with app.test_request_context('/sunday-results'):
                html=render_template('sunday_results.html',**results)
                self.assertIn('BAL -7.5',html)
                self.assertIn('Under 48.5',html)
                self.assertIn('legacy weekly',html)

            from newsletter_draft import _plug_content
            from unittest.mock import Mock
            archive=Mock()
            archive.featured.return_value=[]
            source=dict(game=scout['game'],spread={'side':'PIT'},total={'side':'Over'},quotes={})
            archive.records.return_value=[dict(scout=source,kind='production_import',
                                                version='original',generated_at=AT)]
            with app.app_context(),patch('expert_beta.store',return_value=archive):
                picks,_,_=_plug_content(instant(AT),'https://trendfindah.com',[],root=root)
            self.assertIn('ATS: BAL -7.5',picks[0])
            self.assertEqual(len(picks[0].splitlines()),3)
            self.assertIn('Total: Under 48.5',picks[0])

    def test_current_detail_uses_canonical_final_even_without_archived_expert_grade(self):
        from app import app
        from expert_beta import public_record, instant
        from test_expert_beta import fixture
        from flask import render_template
        with tempfile.TemporaryDirectory() as tmp,self.sources(),app.test_request_context('/the-plug/2026/8/BAL-PIT'):
            root=Path(tmp);activate(root)
            row=append(root,GID,decision());enroll(root,GID,row,AT)
            finalize(root,GID,as_of_utc=KICK)
            scout=fixture('BAL','PIT');scout['game'].update(game_id=GID,season=2026,week=8,kickoff_utc=KICK)
            record=dict(scout=scout,version='original',kind='production_import',generated_at=AT,expert=None)
            with patch('expert_beta.__file__',str(root/'expert_beta.py')),\
                 patch('expert_beta.accessible',return_value=True),\
                 patch('expert_beta.results_for',return_value=None),\
                 patch('expert_beta.clock',return_value=instant(KICK)),\
                 patch('plug_line_movement.compare_line',return_value=None),\
                 patch('plug_dashboard._completed_games',return_value={GID:(28,20)}):
                detail=public_record(record,True)
                self.assertEqual(detail['plug_ats_result'],'Win')
                self.assertEqual(detail['plug_ou_result'],'Win')
                html=render_template('expert_game.html',item=detail,versions=[])
                self.assertIn('BAL -7.5',html)
                self.assertIn('Under 48.5',html)
                with app.test_request_context('/the-plug/2026/8/BAL-PIT?version=original'):
                    pinned=public_record(record,True)
                    self.assertNotIn('plug_dynamic_official',pinned)
                    self.assertEqual(pinned['saved_picks'],detail['saved_picks'])
