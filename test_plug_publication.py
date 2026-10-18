import copy
import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from expert_beta import Store,canonical,clock
from plug_publication import publish,immutable,convert

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.dest=self.root/'persistent/expert';self.config=self.root/'approved.json'
        self.config.write_text(json.dumps({'version':'plug-points-only-4','weights':{'scout_scoring':0.,'plug_points_only':1.}}))
        self.hash=hashlib.sha256(self.config.read_bytes()).hexdigest()
        now=clock();self.cut=now-timedelta(days=3);ko=now-timedelta(days=1)
        q={'market':'Spread','line':2.5,'odds':{'away':-110,'home':-110},'sportsbook':'Fixture','source_url':'https://example.test/lines','captured_at_utc':self.cut.isoformat(),'kickoff_utc':ko.isoformat()}
        self.record=dict(game_id='2026_06_HOU_JAX',season=2026,week=6,away_team='HOU',home_team='JAX',kickoff_utc=ko.isoformat(),decision_cutoff_utc=self.cut.isoformat(),sealed_at_utc=(self.cut+timedelta(seconds=1)).isoformat(),status='SEALED_PREKICKOFF_RESEARCH',version='plug-points-only-4',configuration_sha256=self.hash,weights={'scout_scoring':0.,'plug_points_only':1.},plug_points_only={'away_points':21.,'home_points':24.},components={'Blend':{'pick':'JAX'}},quote=q,totals={'prediction':{'lean':'Under'},'quote':{**q,'market':'Total','line':45.5,'odds':{'Over':-105,'Under':-115}}})
        self.folder=self.root/'data/scout4/blend/predictions';self.folder.mkdir(parents=True)
        self.path=self.folder/(self.record['game_id']+'.json');self.save()
    def save(self):self.path.write_bytes(canonical(self.record))
    def run_publish(self):return publish(self.root,self.dest,self.config)
    def test_completed_game_import_keeps_original_timestamps_and_is_idempotent(self):
        with patch('expert_provider.GeminiProvider.__call__',side_effect=AssertionError('No AI')),patch('scout4.blend.run',side_effect=AssertionError('No prediction generation')):
            self.assertEqual(self.run_publish()['published'],1)
            before={p:p.read_bytes() for p in self.dest.rglob('*.json') if p.name!='last_publication.json'}
            self.assertEqual(self.run_publish()['preserved'],1)
        for p,b in before.items():self.assertEqual(p.read_bytes(),b)
        r=Store(self.dest).records()[0]
        self.assertEqual(r['generated_at'],self.record['sealed_at_utc']);self.assertEqual(r['scout']['cutoff_utc'],self.record['decision_cutoff_utc'])
        self.assertEqual(r['kind'],'production_import');self.assertIsNone(r['expert'])
        self.assertEqual(r['scout']['scores'],{'HOU':21.,'JAX':24.})
        self.assertEqual(r['scout']['quotes']['Spread']['line_a'],2.5)
        self.assertEqual(r['scout']['quotes']['Total']['odds_b'],-115)
        self.assertEqual(next((self.dest/'production_sources').glob('*.json')).read_bytes(),self.path.read_bytes())
    def test_old_blend_research_and_bad_configuration_are_excluded(self):
        for key,value in [('version','scout4-plug-margin-blend-1'),('configuration_sha256','wrong'),('weights',{'scout_scoring':.5,'plug_points_only':.5})]:
            changed=copy.deepcopy(self.record);changed[key]=value
            with self.assertRaises(ValueError):convert(changed,self.hash)
        self.record['version']='experimental';self.save();self.assertEqual(self.run_publish()['published'],0)
        self.assertEqual(Store(self.dest).records(),[])
    def test_missing_total_is_not_invented_and_bad_chronology_rejected(self):
        self.record['totals']=None;scout=convert(self.record,self.hash)
        self.assertIsNone(scout['total']['side']);self.assertNotIn('Total',scout['quotes'])
        self.record['sealed_at_utc']=self.record['kickoff_utc']
        with self.assertRaises(ValueError):convert(self.record,self.hash)
    def test_source_mutation_and_archive_corruption_fail_closed(self):
        self.run_publish();self.record['plug_points_only']['away_points']=22.;self.save()
        with self.assertRaises(ValueError):self.run_publish()
        self.assertEqual(len(Store(self.dest).records()),1)
        archive=next((self.dest/'forecasts').rglob('*.json'));archive.write_text('{}')
        with self.assertRaises(ValueError):self.run_publish()
    def test_crash_retry_repairs_receipt_without_duplicate_forecast(self):
        self.run_publish();next((self.dest/'publication_receipts').glob('*')).unlink()
        self.run_publish();self.assertEqual(len(Store(self.dest).records()),1)
    def test_existing_approved_report_and_pending_draft_are_not_replaced(self):
        from test_expert_beta import report
        self.run_publish();r=Store(self.dest).records()[0]
        approved=report(r['scout'])
        approved['ats_side']=r['scout']['spread']['side']
        for section in approved['sections']:section['evidence_ids']=['scout']
        Store(self.dest).append(r['scout'],expert=approved)
        drafts=self.dest/'review';drafts.mkdir();(drafts/'pending.json').write_text('{"review_status":"pending"}')
        before={p:p.read_bytes() for p in self.dest.rglob('*.json') if p.name!='last_publication.json'}
        self.run_publish()
        for p,b in before.items():self.assertEqual(p.read_bytes(),b)
        self.assertEqual(sum(r['expert'] is not None for r in Store(self.dest).records()),1)

    def test_future_seal_and_unknown_source_kind_are_rejected(self):
        scout=convert(self.record,self.hash)
        with self.assertRaises(ValueError):Store(self.dest).append(scout,kind='production_import')
        self.record['status']='DRAFT';self.save()
        self.assertEqual(self.run_publish()['published'],0)

    def test_production_archive_serves_website_without_an_expert_report(self):
        from app import app
        from membership import migrate
        future=(clock()+timedelta(days=2)).isoformat()
        self.record['kickoff_utc']=future
        self.record['quote']['kickoff_utc']=future
        self.record['totals']['quote']['kickoff_utc']=future
        self.save();self.run_publish()
        with patch.dict(app.config,{'EXPERT_BETA_ENABLED':True,'EXPERT_BETA_STORE':str(self.dest),'MEMBERSHIP_DATABASE':str(self.root/'members.db'),'TESTING':True}):
            with app.app_context():migrate()
            response=app.test_client().get('/the-plug')
            self.assertEqual(response.status_code,200)
            self.assertIn('HOU @ JAX',response.text)
            self.assertIn('The Plug ATS: Pick JAX',response.text)
            self.assertIn('The Plug total: Pick Under',response.text)
            self.assertNotIn('expert-card-picks',response.text)
            self.assertEqual(app.test_client().get('/the-plug/2026/6/HOU-JAX').status_code,200)

    def test_atomic_writer_never_replaces_content(self):
        p=self.root/'atomic.json';immutable(p,b'first');immutable(p,b'first')
        with self.assertRaises(ValueError):immutable(p,b'other')
        self.assertEqual(p.read_bytes(),b'first');self.assertEqual(list(self.root.glob('.pending-*')),[])

if __name__=='__main__':unittest.main()
