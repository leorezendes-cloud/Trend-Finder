import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError
from expert_provider import OpenAIProvider
from expert_beta import generate_draft, Store
from expert_beta_cli import draft, import_package
from test_expert_beta import fixture, report


class ProviderTests(unittest.TestCase):
    def response(self, payload):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(payload).encode()
        opener = Mock();opener.open.return_value=response
        return opener

    def test_no_network_without_explicit_approval_or_key(self):
        with patch('expert_provider.build_opener') as network:
            with self.assertRaises(RuntimeError):generate_draft(fixture(),OpenAIProvider(api_key='secret',model='test'))
            with patch.dict('os.environ',{},clear=True):
                with self.assertRaises(RuntimeError):generate_draft(fixture(),OpenAIProvider(approved=True,model='test'))
            network.assert_not_called()

    def test_bounded_request_and_pending_draft_provenance(self):
        s=fixture();opener=self.response({'status':'completed','model':'returned-model','id':'resp-test','usage':{'total_tokens':50},'output':[{'content':[{'type':'output_text','text':json.dumps(report(s))}]}]})
        with patch('expert_provider.build_opener',return_value=opener):
            result=generate_draft(s,OpenAIProvider(approved=True,api_key='secret',model='configured-model'))
        req=opener.open.call_args.args[0];body=json.loads(req.data)
        self.assertFalse(body['store']);self.assertEqual(body['max_output_tokens'],6000)
        self.assertTrue(body['text']['format']['strict']);self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(result['review_status'],'pending');self.assertEqual(result['model'],'returned-model')
        self.assertEqual(s['scores'],{'HOU':24.,'JAX':21.})

    def test_failure_no_retry_no_secret_leak(self):
        opener=Mock();opener.open.side_effect=URLError('secret-provider-body')
        with patch('expert_provider.build_opener',return_value=opener):
            with self.assertRaisesRegex(RuntimeError,'no automatic retry') as error:
                generate_draft(fixture(),OpenAIProvider(approved=True,api_key='secret',model='test'))
        self.assertNotIn('secret',str(error.exception));self.assertEqual(opener.open.call_count,1)

    def test_incomplete_and_refusal_rejected(self):
        for response in ({'status':'incomplete'},{'status':'completed','output':[{'content':[{'type':'refusal'}]}]}):
            with patch('expert_provider.build_opener',return_value=self.response(response)):
                with self.assertRaises(ValueError):generate_draft(fixture(),OpenAIProvider(approved=True,api_key='secret',model='test'))

    def test_reservation_prevents_duplicate_billing_after_failure(self):
        with tempfile.TemporaryDirectory() as root:
            version=Store(root).append(fixture())
            with patch.dict('os.environ',{'OPENAI_API_KEY':'secret','EXPERT_AI_MODEL':'test'}),patch('expert_provider.OpenAIProvider.__call__',side_effect=RuntimeError('timeout')) as call:
                with self.assertRaises(RuntimeError):draft(root,version,True)
                with self.assertRaises(FileExistsError):draft(root,version,True)
                self.assertEqual(call.call_count,1)
            self.assertFalse((Path(root)/'drafts'/(version+'.json')).exists())

    def test_manifest_must_bind_hash_to_correct_filename(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            package=Path(folder)/'package';package.mkdir()
            raw=b'{"games": []}';(package/'scout_public.json').write_bytes(raw)
            (package/'manifest.json').write_text(json.dumps({'files':{'unrelated':hashlib.sha256(raw).hexdigest()}}))
            with self.assertRaises(ValueError):import_package(Path(folder)/'store',package)

class RefreshTests(unittest.TestCase):
    def test_refresh_import_and_failure_preserve_previous(self):
        from expert_refresh import refresh
        from expert_beta import canonical, clock
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);lab=root/'lab';lab.mkdir();store=root/'store'
            (lab/'scout_release.py').write_text('# existing entrypoint fixture')
            package=lab/'outputs/launch_candidates/test';package.mkdir(parents=True)
            raw=canonical({'generated_at_utc':clock().isoformat(),'games':[fixture()]})
            (package/'scout_public.json').write_bytes(raw)
            (package/'manifest.json').write_text(json.dumps({'files':{'scout_public.json':hashlib.sha256(raw).hexdigest()}}))
            state=lab/'outputs/release_state';state.mkdir()
            def runner(*args,**kwargs):
                (state/'latest_release.json').write_text(json.dumps({'package':str(package),'completed_at_utc':clock().isoformat()}))
            result=refresh(lab,store,runner)
            self.assertEqual(len(result['versions']),1)
            previous=(store/'last_refresh.json').read_bytes()
            def fail(*args,**kwargs):raise RuntimeError('collection failed')
            with self.assertRaises(RuntimeError):refresh(lab,store,fail)
            self.assertEqual((store/'last_refresh.json').read_bytes(),previous)
            self.assertEqual(len(Store(store).records()),1)

    def test_stale_release_rejected(self):
        from expert_refresh import refresh
        with tempfile.TemporaryDirectory() as folder:
            lab=Path(folder)/'lab';lab.mkdir();(lab/'scout_release.py').write_text('# fixture')
            state=lab/'outputs/release_state';state.mkdir(parents=True)
            (state/'latest_release.json').write_text(json.dumps({'completed_at_utc':'2020-01-01T00:00:00+00:00'}))
            with self.assertRaisesRegex(ValueError,'new successful release'):
                refresh(lab,Path(folder)/'store',lambda *a,**k:None)

if __name__=='__main__':unittest.main()
