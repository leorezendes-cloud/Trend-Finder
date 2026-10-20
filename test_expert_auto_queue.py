"""Pure offline safety tests. No real provider, credentials, HTTP, or Flask required."""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def timestamp(offset_days):
    return (NOW + timedelta(days=offset_days)).isoformat()


def scout(team, offset_days=2):
    return {'game': {'season': 2026, 'week': 7, 'away_team': team, 'home_team': 'NE',
                     'game_id': '2026_07_' + team + '_NE', 'kickoff_utc': timestamp(offset_days)}}


def rec(team, *, kind='production_import', expert=None, offset_days=2):
    s = scout(team, offset_days)
    return {'version': hashlib.sha256(team.encode()).hexdigest(), 'kind': kind,
            'scout': s, 'generated_at': timestamp(-1), 'expert': expert}


class AutomationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = []
        fake = types.ModuleType('expert_beta')
        fake.Store = lambda path: types.SimpleNamespace(records=lambda: cls.rows)
        fake.canonical = lambda obj: json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()
        fake.clock = lambda: NOW
        fake.identity = lambda s: f"{s['game']['season']}/{s['game']['week']}/{s['game']['away_team']}-{s['game']['home_team']}"
        fake.instant = lambda t: datetime.fromisoformat(t.replace('Z', '+00:00'))
        cls.prior = sys.modules.get('expert_beta')
        sys.modules['expert_beta'] = fake
        spec = importlib.util.spec_from_file_location('tested_expert_auto_queue', HERE/'expert_auto_queue.py')
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.prior is None: sys.modules.pop('expert_beta', None)
        else: sys.modules['expert_beta'] = cls.prior

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'drafts').mkdir()
        type(self).rows = []

    def test_only_future_production_imports_are_queued(self):
        type(self).rows = [rec('BUF'), rec('MIA', kind='development'), rec('NYJ', offset_days=-1)]
        q, summary = self.module.production_queue(self.root)
        self.assertEqual([r['scout']['game']['away_team'] for r in q], ['BUF'])
        self.assertEqual(summary['imported_upcoming'], 1)

    def test_existing_saved_draft_and_uncertain_attempt_block_duplicates(self):
        a, b, c = rec('BUF'), rec('MIA'), rec('NYJ')
        type(self).rows = [a, b, c]
        (self.root/'drafts'/(a['version']+'.json')).write_text('{}')
        (self.root/'drafts'/(b['version']+'.attempt.json')).write_text('{}')
        q, counts = self.module.production_queue(self.root)
        self.assertEqual([r['version'] for r in q], [c['version']])
        self.assertEqual(counts['draft_saved'], 1)
        self.assertEqual(counts['attempt_requires_review'], 1)

    def test_published_expert_does_not_get_redrafted(self):
        a = rec('BUF')
        approved = {**a, 'kind': 'development', 'expert': {'review_status': 'approved'}}
        type(self).rows = [a, approved]
        q, summary = self.module.production_queue(self.root)
        self.assertEqual(len(q), 0)
        self.assertEqual(summary['published'], 1)

    def test_dry_run_makes_no_calls_and_respects_rolling_cap(self):
        type(self).rows = [rec('BUF'), rec('MIA')]
        (self.root/'drafts'/'test.attempt.json').write_text(json.dumps({'started_at':NOW.isoformat()}))
        output = self.module.bounded_run(self.root, 'gemini-test', daily_limit=1, execute=False)
        self.assertEqual(output['planned_requests'], 0)
        self.assertEqual(output['state'], 'preview')
        self.assertFalse((self.root/'automation_status.json').exists())

    def test_real_call_requires_two_explicit_opt_ins(self):
        type(self).rows = [rec('BUF')]
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'disabled'):
                self.module.bounded_run(self.root, 'gemini-test', execute=True)

    def test_mock_call_creates_draft_only_once(self):
        a, b = rec('BUF'), rec('MIA')
        type(self).rows = [a, b]
        requests = []
        fakecli = types.ModuleType('expert_beta_cli')
        def fake_draft(root, version, approved, model, provider_name):
            requests.append(version)
            (Path(root)/'drafts'/(version+'.attempt.json')).write_text(json.dumps({'started_at':NOW.isoformat()}))
            (Path(root)/'drafts'/(version+'.json')).write_text('{}')
        fakecli.draft = fake_draft
        with patch.dict(sys.modules, {'expert_beta_cli': fakecli}):
            with patch.dict(os.environ, {'TREND_FINDAH_EXPERT_AUTO_DRAFT':'1',
                                         'EXPERT_GEMINI_FREE_TIER_CONFIRMED':'1'}):
                first = self.module.bounded_run(self.root, 'gemini-test', daily_limit=1, execute=True)
                second = self.module.bounded_run(self.root, 'gemini-test', daily_limit=1, execute=True)
        self.assertEqual(first['saved_drafts'], 1)
        self.assertEqual(second['saved_drafts'], 0)
        self.assertEqual(len(requests), 1)

    def test_corrupt_attempt_fails_closed(self):
        type(self).rows = [rec('BUF')]
        (self.root/'drafts'/'oops.attempt.json').write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'operator review'):
            self.module.bounded_run(self.root, 'gemini-test')


if __name__ == '__main__':
    unittest.main()
