"""Real Expert modules, temp persistent stores, mocked transport only. No API calls."""
import copy,hashlib,json,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
from contextlib import ExitStack
from app import app
from expert_beta import Store,canonical,identity
from expert_automation import execute_once
from expert_auto_queue import production_queue
from expert_beta_cli import draft
from expert_review_publication import run as publish_reviews
from test_expert_beta import fixture,report
from membership import migrate,db

class ExpertPipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir();self.data=self.root/'data';self.data.mkdir();self.store=self.root/'archive';self.store.mkdir()
  self.now=datetime(2030,9,1,12,tzinfo=timezone.utc)
  self.stack=ExitStack();self.addCleanup(self.stack.close)
  for mod in ['expert_beta','expert_beta_cli','expert_auto_queue','expert_review_publication','expert_provider','plug_publication']:
   self.stack.enter_context(patch(mod+'.clock',side_effect=lambda:self.now))
  self.stack.enter_context(patch.dict(os.environ,{'TREND_FINDAH_EXPERT_AUTO_DRAFT':'1','EXPERT_GEMINI_FREE_TIER_CONFIRMED':'1','TREND_FINDAH_EXPERT_AUTO_PUBLISH':'1','TREND_FINDAH_EXPERT_DAILY_LIMIT':'16','TREND_FINDAH_EXPERT_RUN_LIMIT':'4','TREND_FINDAH_EXPERT_GEMINI_MODEL':'gemini-2.5-flash','GEMINI_API_KEY':'OFFLINE-FAKE-KEY'},clear=True))
  self.stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('Real network prohibited')))
  self.stack.enter_context(patch('scout4.blend.run',side_effect=AssertionError('Forecast generation prohibited')))
  self.stack.enter_context(patch('expert_auto_queue.time.sleep',side_effect=lambda n:setattr(self,'now',self.now+timedelta(seconds=n))))
  self.calls=[];self.transport_fail=False
  opener=Mock();opener.open.side_effect=self.transport
  self.stack.enter_context(patch('expert_provider.build_opener',return_value=opener))
  config={'version':'plug-points-only-4','weights':{'scout_scoring':0.,'plug_points_only':1.}}
  raw=json.dumps(config).encode();(self.source/'automatic_model.json').write_bytes(raw);self.config_hash=hashlib.sha256(raw).hexdigest()
 def transport(self,request,timeout):
  self.calls.append(request)
  if self.transport_fail:raise TimeoutError('mock timeout')
  evidence=json.loads(json.loads(request.data)['contents'][0]['parts'][0]['text'])['pregame_evidence']
  value=report(evidence);value['disagreement_reason']='Offline fixture: explicit disagreement for review'
  for section in value['sections']:section['evidence_ids']=['scout']
  response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
  response.read.return_value=json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(value)}]}}],'modelVersion':'gemini-2.5-flash'}).encode()
  return response
 def seals(self,count):
  codes=['ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE','DAL','DEN','DET','GB','HOU','IND','JAX','KC','LA','LAC','LV','MIA']
  folder=self.data/'data/scout4/blend/predictions';folder.mkdir(parents=True,exist_ok=True)
  self.input_bytes={}
  for i,away in enumerate(codes[:count]):
   cutoff=(self.now-timedelta(minutes=2)).isoformat();kickoff=(self.now+timedelta(days=7,minutes=i)).isoformat();gid=f'2030_01_{away}_NE'
   q=dict(market='Spread',line=2.5,odds={'away':-110,'home':-110},sportsbook='Fixture',source_url='https://example.test/lines',captured_at_utc=cutoff,kickoff_utc=kickoff)
   rec=dict(game_id=gid,season=2030,week=1,away_team=away,home_team='NE',kickoff_utc=kickoff,decision_cutoff_utc=cutoff,sealed_at_utc=(self.now-timedelta(minutes=1)).isoformat(),status='SEALED_PREKICKOFF_RESEARCH',version='plug-points-only-4',configuration_sha256=self.config_hash,weights={'scout_scoring':0.,'plug_points_only':1.},plug_points_only={'away_points':21.,'home_points':24.},components={'Blend':{'pick':'NE'}},quote=q,totals={'prediction':{'lean':'Under'},'quote':{**q,'market':'Total','line':45.5,'odds':{'Over':-105,'Under':-115}}})
   p=folder/(gid+'.json');p.write_bytes(canonical(rec));self.input_bytes[p]=p.read_bytes()
 def worker(self):return execute_once(self.source,self.data,self.store)
 def approve(self):
  for p in (self.store/'drafts').glob('*.json'):
   if p.name.endswith(('.attempt.json','.review.json')):continue
   value=json.loads(p.read_text());value.update(review_status='approved',reviewer='offline-human-fixture',reviewed_at=self.now.isoformat())
   p.with_name(p.stem+'.review.json').write_text(json.dumps(value))
 def test_full_slate_budget_restart_review_and_access(self):
  self.seals(20)
  for _ in range(4):self.worker()
  self.assertEqual(len(self.calls),16)
  self.assertEqual(len(production_queue(self.store,self.now)[0]),4)
  self.worker();self.assertEqual(len(self.calls),16)
  self.assertFalse(any(r['expert'] for r in Store(self.store).records()))
  self.now+=timedelta(days=1,seconds=1);self.worker();self.assertEqual(len(self.calls),20)
  self.approve();status=self.worker();self.assertEqual(status['review_publication']['published_now'],20)
  records=Store(self.store).records();approved=[r for r in records if r['expert']];self.assertEqual(len(approved),20)
  featured=Store(self.store).featured(2030,1);self.assertEqual(len(featured),2)
  before={p:p.read_bytes() for p in (self.store/'forecasts').rglob('*.json')}
  self.worker();self.assertEqual(len(self.calls),20);self.assertEqual(before,{p:p.read_bytes() for p in (self.store/'forecasts').rglob('*.json')})
  for p,raw in self.input_bytes.items():self.assertEqual(p.read_bytes(),raw)
  with patch.dict(app.config,{'EXPERT_BETA_ENABLED':True,'EXPERT_BETA_STORE':str(self.store),'EXPERT_PREMIUM_MEMBER_IDS':['1'],'MEMBERSHIP_DATABASE':str(self.root/'members.db'),'TESTING':True}),patch('plug_dashboard.legacy_records',return_value=[]):
   with app.app_context():
    migrate()
    with db():db().execute("INSERT INTO members(id,email,password_hash) VALUES(1,'premium@test.invalid','unused'),(2,'free@test.invalid','unused')")
   client=app.test_client()
   for row in approved:
    key=identity(row['scout']);page=client.get('/the-plug/'+key);api=client.get('/api/the-plug/'+key+'/expert')
    self.assertEqual(api.status_code,200 if key in featured else 403)
    self.assertEqual('PREMIUM_SECRET' in page.text,key in featured)
    self.assertIn('no-store',api.headers['Cache-Control'])
   restricted=next(identity(r['scout']) for r in approved if identity(r['scout']) not in featured)
   for member,code in [(2,403),(1,200)]:
    with client.session_transaction() as session:session['member_id']=member;session['member_version']=0
    self.assertEqual(client.get('/api/the-plug/'+restricted+'/expert').status_code,code)
 def test_varying_eligible_slate_sizes_are_not_hardcoded(self):
  for count in [0,7,13,16]:
   with self.subTest(count=count):
    # Fresh persistent archive per slate; all calls still mocked.
    self.data=self.root/('data-'+str(count));self.data.mkdir()
    self.store=self.root/('store-'+str(count));self.store.mkdir()
    start=len(self.calls);self.seals(count)
    for _ in range(max(1,(count+3)//4)):self.worker()
    self.assertEqual(len(self.calls)-start,count)
    self.assertEqual(production_queue(self.store,self.now)[1]['ready'],0)
 def test_saved_draft_reused_without_request_or_credentials(self):
  self.seals(1);self.worker();row=next(r for r in Store(self.store).records() if r['kind']=='production_import')
  with patch('expert_provider.GeminiProvider',side_effect=AssertionError('No credentials needed')):
   path=draft(self.store,row['version'],provider_name='gemini')
  self.assertTrue(Path(path).exists());self.assertEqual(len(self.calls),1)
 def test_failed_attempt_persists_and_never_auto_retries(self):
  self.seals(3);self.transport_fail=True;first=self.worker();self.assertEqual(first['state'],'needs_review');self.assertEqual(len(self.calls),1)
  self.transport_fail=False;again=self.worker();self.assertEqual(again['state'],'needs_review');self.assertEqual(len(self.calls),3)
  self.assertEqual(production_queue(self.store,self.now)[1]['attempt_requires_review'],1)
 def test_manual_cli_cannot_bypass_daily_or_minute_caps(self):
  self.seals(6)
  with patch.dict(os.environ,{'TREND_FINDAH_EXPERT_AUTO_DRAFT':'0'}):self.worker()
  rows=Store(self.store).records()
  for row in rows[:4]:draft(self.store,row['version'],provider_name='gemini')
  with self.assertRaisesRegex(RuntimeError,'minute quota'):draft(self.store,rows[4]['version'],provider_name='gemini')
  self.now+=timedelta(minutes=2)
  with patch.dict(os.environ,{'TREND_FINDAH_EXPERT_DAILY_LIMIT':'4'}):
   with self.assertRaisesRegex(RuntimeError,'24-hour quota'):draft(self.store,rows[4]['version'],provider_name='gemini')
  self.assertEqual(len(self.calls),4)
 def test_hosted_worker_timeout_covers_maximum_four_request_batch(self):
  import ast
  tree=ast.parse((Path(__file__).parent/'hosted_updates.py').read_text())
  call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
            and isinstance(n.func,ast.Name) and n.func.id=='run_worker'
            and n.args and isinstance(n.args[0],ast.Constant)
            and n.args[0].value=='expert_automation.py')
  timeout=call.args[2].value
  self.assertGreater(timeout,4*120+3*75)
 def test_changed_review_prose_is_not_published(self):
  self.seals(1);self.worker();self.approve();p=next((self.store/'drafts').glob('*.review.json'));value=json.loads(p.read_text());value['summary']='Altered claim';p.write_text(json.dumps(value))
  with self.assertRaisesRegex(ValueError,'changed AI claims'):publish_reviews(self.store,execute=True)
  self.assertFalse(any(r['expert'] for r in Store(self.store).records()))

if __name__=='__main__':unittest.main()
