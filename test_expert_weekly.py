import copy
import json
import tempfile
import unittest
from pathlib import Path
from expert_weekly import blind_packet,load_slate,run,selections,validate_result

def fixture():
    return {'game':{'game_id':'2099_01_HOU_JAX','season':2099,'week':1,'away_team':'HOU','home_team':'JAX','kickoff_utc':'2099-09-10T17:00:00+00:00'},'cutoff_utc':'2099-09-10T12:00:00+00:00','scores':{'HOU':24,'JAX':21},'spread':{'side':'HOU'},'total':{'side':'Under'},'before_scores':{'secret':777},'conditions':['Scout predicts 777'], 'sources':[{'name':'Scout 777','url':'https://example.test','observed_at':'2099-09-10T12:00:00+00:00'}], 'quotes':{m:{'game_id':'2099_01_HOU_JAX','side_a':a,'side_b':b,'line_a':v,'line_b':v if m=='Total' else -v,'captured_at_utc':'2099-09-10T12:00:00+00:00'} for m,a,b,v in [('Spread','HOU','JAX',3),('Total','Over','Under',45)]}}

def fake(packet):
    return {'scores':{'away':20,'home':28},'analysis':'SYNTHETIC TEST DOUBLE: no real forecast.','counterargument':'Synthetic opposing case.','uncertainty':'Synthetic missing facts.','evidence_ids':[],'provider':'TEST DOUBLE','model':'fixture'}

class WeeklyTests(unittest.TestCase):
    def test_blind_packet_has_no_scout_outputs(self):
        s=fixture();packet=blind_packet(s,[])
        self.assertNotIn('777',json.dumps(packet));self.assertNotIn('scores',packet)
        changed=copy.deepcopy(s);changed['scores']['HOU']=99
        self.assertEqual(packet,blind_packet(changed,[]))
    def test_default_zero_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def provider(p):calls.append(p);return fake(p)
            _,r=run([fixture()],d,model='fixture',provider=provider)
            self.assertEqual(calls,[]);self.assertIsNone(r['games'][0]['gemini'])
            _,r=run([fixture()],d,model='fixture',provider=provider,max_requests=1)
            self.assertEqual(len(calls),1);self.assertTrue(r['games'][0]['disagreements']['winner'])
            _,r=run([fixture()],d,model='fixture',provider=provider,max_requests=1)
            self.assertEqual(len(calls),1);self.assertEqual(r['games'][0]['status'],'cached')
    def test_uncertain_failure_never_retries(self):
        with tempfile.TemporaryDirectory() as d:
            def fail(p):raise TimeoutError()
            run([fixture()],d,model='fixture',provider=fail,max_requests=1)
            _,r=run([fixture()],d,model='fixture',provider=lambda p:self.fail('retried'),max_requests=1)
            self.assertEqual(r['games'][0]['status'],'attempt_requires_review')
    def test_post_cutoff_evidence_rejected(self):
        f={'game_id':fixture()['game']['game_id'],'id':'weather','team':'HOU','url':'https://example.test','observed_at':'2099-09-10T13:00:00+00:00','metrics':{'wind_mph':12}}
        with self.assertRaises(ValueError):blind_packet(fixture(),[f])
    def test_nan_and_false_citation_rejected(self):
        for field,value in [('scores',{'away':float('nan'),'home':20}),('evidence_ids',['invented'])]:
            r=fake({});r[field]=value
            with self.assertRaises(ValueError):validate_result(r,blind_packet(fixture(),[]))
    def test_identical_lines_pushes_and_published_pick_preserved(self):
        s=fixture();self.assertEqual(selections({'away':21,'home':24},s)['ats'],'Push')
        self.assertEqual(selections({'away':21,'home':24},s)['total'],'Push')
    def test_cache_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            run([fixture()],d,model='fixture',provider=fake,max_requests=1)
            p=next(Path(d).glob('cache/*/result.json'));v=json.loads(p.read_text());v['result']['scores']['away']=90;p.write_text(json.dumps(v))
            with self.assertRaises(ValueError):run([fixture()],d,model='fixture')
    def test_week_selection_and_forecast_immutability(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.json';p.write_text(json.dumps({'games':[fixture()]}));before=p.read_bytes()
            self.assertEqual(len(load_slate(p,2099,1)),1)
            with self.assertRaises(ValueError):load_slate(p,2099,2)
            run(load_slate(p,2099,1),Path(d)/'out',model='fixture')
            self.assertEqual(before,p.read_bytes())

if __name__=='__main__':unittest.main()
