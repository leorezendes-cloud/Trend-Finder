import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from expert_provider import GeminiProvider
from expert_beta import generate_draft
from test_expert_beta import fixture, report

class GeminiTests(unittest.TestCase):
    def opener(self,payload):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=json.dumps(payload).encode()
        opener=Mock();opener.open.return_value=response
        return opener

    def test_billing_confirmation_and_key_required_without_network(self):
        with patch('expert_provider.build_opener') as network:
            with self.assertRaises(RuntimeError):generate_draft(fixture(),GeminiProvider(api_key='secret',free_tier_confirmed=False))
            with patch.dict('os.environ',{},clear=True),patch('expert_credentials.load_local',return_value={}):
                with self.assertRaises(RuntimeError):generate_draft(fixture(),GeminiProvider(free_tier_confirmed=True))
            network.assert_not_called()

    def test_structured_draft_provenance_and_no_key_in_url(self):
        s=fixture();opener=self.opener({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'private thought','thought':True},{'text':json.dumps(report(s))}]}}],'modelVersion':'gemini-2.5-flash','usageMetadata':{'totalTokenCount':30}})
        with patch('expert_provider.build_opener',return_value=opener):
            result=generate_draft(s,GeminiProvider(api_key='secret',free_tier_confirmed=True))
        req=opener.open.call_args.args[0];body=json.loads(req.data)
        self.assertNotIn('secret',req.full_url);self.assertNotIn('tools',body)
        self.assertEqual(body['generationConfig']['candidateCount'],1)
        self.assertEqual(result['review_status'],'pending');self.assertEqual(result['provider'],'Google Gemini')
        self.assertEqual(result['usage']['totalTokenCount'],30)

    def test_quota_stops_without_retry_or_openai_fallback(self):
        opener=Mock();opener.open.side_effect=HTTPError('https://example.test',429,'secret detail',{},None)
        with patch('expert_provider.build_opener',return_value=opener),patch('expert_provider.OpenAIProvider.__call__') as paid:
            with self.assertRaisesRegex(RuntimeError,'quota exhausted'):
                generate_draft(fixture(),GeminiProvider(api_key='secret',free_tier_confirmed=True))
            paid.assert_not_called();self.assertEqual(opener.open.call_count,1)

    def test_blocked_truncated_and_unapproved_model_rejected(self):
        for payload in ({'promptFeedback':{'blockReason':'SAFETY'}},{'candidates':[{'finishReason':'MAX_TOKENS'}]}):
            with patch('expert_provider.build_opener',return_value=self.opener(payload)):
                with self.assertRaises(ValueError):generate_draft(fixture(),GeminiProvider(api_key='secret',free_tier_confirmed=True))
        with patch('expert_provider.build_opener') as network:
            with self.assertRaises(ValueError):generate_draft(fixture(),GeminiProvider(model='../other',api_key='secret',free_tier_confirmed=True))
            network.assert_not_called()

if __name__=='__main__':unittest.main()
