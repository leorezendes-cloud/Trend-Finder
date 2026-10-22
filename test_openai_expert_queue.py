"""Real queue/provider, immutable temp stores; network transport is always mocked."""
import copy
import fcntl
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from expert_auto_queue import bounded_run, production_queue, week_usage
from expert_beta import Store, canonical, identity
from test_expert_beta import fixture, report


class OpenAIQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=datetime(2030,9,1,12,tzinfo=timezone.utc)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for mod in ['expert_beta','expert_auto_queue','expert_provider']:
            self.stack.enter_context(patch(mod+'.clock',side_effect=lambda:self.now))
        self.stack.enter_context(patch.dict(os.environ,{
            'TREND_FINDAH_EXPERT_AUTO_DRAFT':'1','OPENAI_API_KEY':'OFFLINE-SECRET',
            'EXPERT_AI_MODEL':'gpt-4.1-mini'},clear=True))
        self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('Real network prohibited')))
        self.opener=Mock();self.opener.open.side_effect=self.transport
        self.stack.enter_context(patch('expert_provider.build_opener',return_value=self.opener))
        self.calls=[];self.failure_mode=None;self.bad_evidence=False;self.past=False

    def add(self, away='BUF', week=1):
        s=fixture(away,'NE');cutoff=(self.now-timedelta(minutes=2)).isoformat()
        s['game'].update(season=2030,week=week,game_id=f'2030_{week:02}_{away}_NE',
                         kickoff_utc=(self.now+timedelta(days=7)).isoformat())
        s['cutoff_utc']=cutoff
        for q in s['quotes'].values():q.update(game_id=s['game']['game_id'],captured_at_utc=cutoff)
        for source in s['sources']:source['observed_at']=cutoff
        seal=(self.now-timedelta(minutes=1)).isoformat()
        s['production_source']=dict(sealed_at_utc=seal,configuration_sha256='a'*64,source_sha256='b'*64)
        version=Store(self.root).append(s,kind='production_import',generated_at=seal)
        return next(r for r in Store(self.root).records() if r['version']==version)

    def transport(self, request, timeout):
        # The disk reservation MUST already be durable before any transmission.
        self.assertTrue(list((self.root/'drafts').glob('*.attempt.json')))
        self.calls.append(request)
        if self.failure_mode=='timeout':raise TimeoutError('OFFLINE-SECRET must never reach logs')
        if self.failure_mode=='429':raise HTTPError(request.full_url,429,'mock',{'Retry-After':'1'},None)
        body=json.loads(request.data)
        self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
        self.assertFalse(body['store']);self.assertNotIn('tools',body)
        scout=json.loads(body['input'])['pregame_evidence']
        from expert_provider import report_schema
        value={k:v for k,v in report(scout).items() if k in report_schema()['properties']}
        value.update(total_side='Under',summary='Offline summary',disagreement_reason='')
        if self.bad_evidence:value['sections'][0]['evidence_ids']=['invented']
        if self.past:self.now+=timedelta(days=8)
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps(dict(status='completed',id='offline-response',model=body['model'],
            usage={'input_tokens':100,'output_tokens':100},
            output=[{'content':[{'type':'output_text','text':json.dumps(value)}]}])).encode()
        return response

    def run_queue(self, **kwargs):return bounded_run(self.root,execute=True,**kwargs)
    def files(self):return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.glob('forecasts/**/*.json')}

    def test_openai_default_saves_pending_provenance_once_and_preserves_seal(self):
        row=self.add();before=self.files()
        self.assertEqual(self.run_queue()['saved_drafts'],1)
        draft=json.loads((self.root/'drafts'/(row['version']+'.json')).read_text())
        self.assertEqual(draft['review_status'],'pending');self.assertEqual(draft['provider'],'OpenAI')
        self.assertEqual(draft['provider_response_id'],'offline-response')
        self.assertNotIn('reviewer',draft)
        self.assertEqual(self.run_queue()['saved_drafts'],0);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.files(),before)
        self.assertFalse(any(r.get('expert') for r in Store(self.root).records()))

    def test_all_fourteen_published_week7_reports_and_provider_attribution_untouched(self):
        for team in ['ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE','DAL','DEN','DET','GB','HOU','IND']:
            row=self.add(team,week=7)
            original=report(row['scout']);original['provider']='Original Gemini'
            Store(self.root).append(row['scout'],expert=original)
        before=self.files()
        r=self.run_queue()
        self.assertEqual(r['published'],14);self.assertEqual(len(self.calls),0)
        self.assertEqual(before,self.files())

    def test_new_seal_cannot_regenerate_existing_game_report_or_draft(self):
        row=self.add();self.run_queue()
        s=copy.deepcopy(row['scout']);s['conditions'].append('New sealed evidence')
        Store(self.root).append(s,kind='production_import',generated_at=s['production_source']['sealed_at_utc'])
        self.run_queue();self.assertEqual(len(self.calls),1)

    def test_missing_credentials_and_unknown_prices_make_no_reservation(self):
        self.add()
        for env in [{'OPENAI_API_KEY':''},{'EXPERT_AI_MODEL':'unknown-unpriced'}]:
            with patch.dict(os.environ,env):self.assertEqual(self.run_queue()['state'],'operator_review_required')
        self.assertFalse(list((self.root/'drafts').glob('*.attempt.json')));self.assertFalse(self.calls)

    def test_weekly_zero_budget_and_invalid_limits_fail_without_calls(self):
        self.add()
        self.assertEqual(self.run_queue(weekly_limit='0')['state'],'budget_exhausted')
        for value in ['1.01','NaN','Infinity','-1']:
            with self.assertRaises(ValueError):self.run_queue(weekly_limit=value)
        self.assertFalse(self.calls)

    def test_timeout_keeps_full_cost_and_never_retries_even_after_restart(self):
        self.add();self.failure_mode='timeout';first=self.run_queue()
        self.assertEqual(first['state'],'operator_review_required')
        cost,_=week_usage(self.root,Store(self.root).records(),(2030,1));self.assertGreater(cost,0)
        self.failure_mode=None;self.run_queue();self.assertEqual(len(self.calls),1)
        self.assertNotIn('OFFLINE-SECRET',(self.root/'automation_status.json').read_text())

    def test_explicit_429_retries_once_after_delay_and_counts_both_costs(self):
        self.add();self.failure_mode='429';self.assertEqual(self.run_queue()['state'],'retry_wait')
        self.run_queue();self.assertEqual(len(self.calls),1)
        self.now+=timedelta(seconds=301);self.failure_mode=None
        self.assertEqual(self.run_queue()['saved_drafts'],1);self.assertEqual(len(self.calls),2)
        attempts=list((self.root/'drafts').glob('*.attempt.json'));self.assertEqual(len(attempts),2)
        cost,n=week_usage(self.root,Store(self.root).records(),(2030,1));self.assertEqual(n,2)
        self.assertEqual(cost,sum(__import__('decimal').Decimal(json.loads(p.read_text())['reserved_usd']) for p in attempts))

    def test_repeated_429_is_bounded_to_two_requests(self):
        self.add();self.failure_mode='429';self.run_queue();self.now+=timedelta(seconds=301)
        self.assertEqual(self.run_queue()['state'],'operator_review_required')
        self.now+=timedelta(days=1);self.run_queue();self.assertEqual(len(self.calls),2)

    def test_failed_request_budget_and_daily_cap_survive_new_worker(self):
        first=self.add();self.add('MIA');self.failure_mode='timeout';self.run_queue(daily_limit=1)
        self.run_queue(daily_limit=1);self.assertEqual(len(self.calls),1)
        self.now+=timedelta(days=1,seconds=1);self.failure_mode=None
        spent,_=week_usage(self.root,Store(self.root).records(),(2030,1))
        self.assertEqual(self.run_queue(weekly_limit=str(spent))['state'],'budget_exhausted')
        self.assertEqual(len(self.calls),1)

    def test_legacy_unpriced_paid_attempt_consumes_entire_week_budget(self):
        first=self.add();self.add('MIA');folder=self.root/'drafts';folder.mkdir()
        (folder/(first['version']+'.attempt.json')).write_text(json.dumps(dict(provider='openai',started_at=self.now.isoformat())))
        self.assertEqual(self.run_queue()['state'],'budget_exhausted');self.assertFalse(self.calls)

    def test_invalid_evidence_never_saved_or_published(self):
        row=self.add();self.bad_evidence=True
        self.assertEqual(self.run_queue()['state'],'operator_review_required')
        self.assertFalse((self.root/'drafts'/(row['version']+'.json')).exists())
        self.run_queue();self.assertEqual(len(self.calls),1)

    def test_kickoff_and_late_response_do_not_create_a_draft(self):
        row=self.add();self.past=True;self.run_queue()
        self.assertFalse((self.root/'drafts'/(row['version']+'.json')).exists())
        self.run_queue();self.assertEqual(len(self.calls),1)

    def test_busy_lock_and_corrupt_reservation_stop_safely(self):
        self.add()
        with (self.root/'automation.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.run_queue()['state'],'lock_busy')
        folder=self.root/'drafts';folder.mkdir();(folder/'bad.attempt.json').write_text('{broken')
        with self.assertRaises(ValueError):self.run_queue()
        self.assertFalse(self.calls)

    def test_no_gemini_fallback_after_unknown_openai_failure(self):
        self.add();self.failure_mode='timeout'
        with patch.dict(os.environ,{'TREND_FINDAH_EXPERT_FALLBACK_PROVIDER':'gemini'}),patch('expert_provider.GeminiProvider',side_effect=AssertionError('No fallback')):
            self.run_queue()
        self.assertEqual(len(self.calls),1)

    def test_real_leader_timer_automatically_drains_new_forecast_without_shell(self):
        import threading
        import hosted_updates as hosted
        from expert_automation import execute_once
        row=self.add()
        source=self.root/'source';source.mkdir()
        data=self.root/'site-data';data.mkdir()
        stop=threading.Event()
        def worker(script, args=None, timeout=600):
            if script != 'expert_automation.py':
                return 0  # No feeds, Scout runs or other real workers in this test.
            try:
                result=execute_once(source,data,self.root,publish_reports=False)
                self.assertEqual(result['drafts']['saved_drafts'],1)
                return 0
            finally:
                stop.set()
        with patch.object(hosted,'run_worker',side_effect=worker),patch('plug_publication.publish',return_value={'state':'ok'}):
            leader=threading.Thread(target=hosted.leadership_loop,args=(data,stop),daemon=True)
            leader.start();leader.join(timeout=5)
            stop.set();leader.join(timeout=2)
        self.assertFalse(leader.is_alive())
        self.assertEqual(len(self.calls),1)
        self.assertTrue((self.root/'drafts'/(row['version']+'.json')).exists())
        schedule=json.loads((data/'logs/expert-only-updates.schedule.json').read_text())
        self.assertEqual(schedule['state'],'success')
        self.assertAlmostEqual(schedule['next_due']-schedule['finished_at'],300,places=1)

    def test_retry_budget_is_reserved_before_second_transmission(self):
        self.add();self.failure_mode='429';self.run_queue()
        spent,_=week_usage(self.root,Store(self.root).records(),(2030,1))
        self.now+=timedelta(seconds=301);self.failure_mode=None
        self.assertEqual(self.run_queue(weekly_limit=str(spent))['state'],'budget_exhausted')
        self.assertEqual(len(self.calls),1)

    def test_weekly_allowance_resets_by_slate_not_by_process_or_calendar_day(self):
        self.add();self.run_queue();self.add('MIA',week=2)
        self.assertEqual(self.run_queue(weekly_requests=1)['saved_drafts'],1)
        self.assertEqual(len(self.calls),2)

    def test_invalid_schema_never_reaches_an_approval_or_saved_draft(self):
        from expert_provider import validate_response_structure, report_schema
        original={k:v for k,v in report(fixture()).items() if k in report_schema()['properties']}
        original['disagreement_reason']=''
        for field,value in [('summary',[]),('sections',[]),('total_side','Over-ish'),('review_status','approved')]:
            bad=copy.deepcopy(original);bad[field]=value
            with self.assertRaises(ValueError):validate_response_structure(bad)

    def test_provider_fallback_must_be_explicit_and_only_before_transmission(self):
        self.add()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','TREND_FINDAH_EXPERT_FALLBACK_PROVIDER':'gemini'}),patch('expert_auto_queue._gemini_run',return_value={'state':'preview'}) as fallback:
            self.run_queue()
            fallback.assert_called_once()
        self.assertFalse(self.calls)

if __name__=='__main__':unittest.main()
