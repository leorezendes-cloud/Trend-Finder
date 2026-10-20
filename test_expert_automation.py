"""Offline integration tests for the lightweight Expert-only worker."""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
NOW=datetime(2026,10,20,12,tzinfo=timezone.utc)


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('tested_expert_automation',HERE/'expert_automation.py')
        cls.module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'site-data'
        self.root.mkdir()
        self.source=Path(self.tmp.name)/'source'
        self.source.mkdir()
        self.archive=Path(self.tmp.name)/'expert_beta'
        self.archive.mkdir()
        (self.source/'automatic_model.json').write_text('{}')
        self.calls=[]
        st=types.ModuleType('expert_beta')
        st.clock=lambda:NOW
        pub=types.ModuleType('plug_publication')
        pub.publish=lambda root,store,config:self.calls.append(('publish',root,store,config)) or {'state':'awaiting approved production seals'}
        draft=types.ModuleType('expert_auto_queue')
        draft.bounded_run=lambda store,model,**kwargs:self.calls.append(('draft',store,model,kwargs)) or {'state':'complete','saved_drafts':1}
        review=types.ModuleType('expert_review_publication')
        review.run=lambda store,**kwargs:self.calls.append(('review',store,kwargs)) or {'published_now':1}
        self.mods={'expert_beta':st,'plug_publication':pub,'expert_auto_queue':draft,'expert_review_publication':review}

    def test_disabled_flags_do_not_call_gemini_or_publish_reviews(self):
        with patch.dict(sys.modules,self.mods):
            with patch.dict(os.environ,{},clear=True):
                r=self.module.execute_once(self.source,self.root,self.archive)
        self.assertEqual(r['drafts'],'disabled')
        self.assertEqual(r['review_publication'],'disabled')
        self.assertEqual([x[0] for x in self.calls],['publish'])
        self.assertTrue((self.root/'logs/expert_automation_status.json').exists())

    def test_explicit_flags_enable_review_and_draft(self):
        with patch.dict(sys.modules,self.mods):
            with patch.dict(os.environ,{'TREND_FINDAH_EXPERT_AUTO_DRAFT':'1','TREND_FINDAH_EXPERT_AUTO_PUBLISH':'1',
                                        'TREND_FINDAH_EXPERT_DAILY_LIMIT':'16', 'TREND_FINDAH_EXPERT_RUN_LIMIT':'4'}):
                r=self.module.execute_once(self.source,self.root,self.archive)
        self.assertEqual([x[0] for x in self.calls],['publish','draft','review'])
        self.assertEqual(self.calls[1][3]['daily_limit'],16)
        self.assertEqual(self.calls[1][3]['run_limit'],4)
        self.assertEqual(r['state'],'ok')

    def test_provider_failure_is_not_silently_swallowed(self):
        def fail(*args,**kwargs):raise RuntimeError('Provider not available')
        self.mods['expert_auto_queue'].bounded_run=fail
        with patch.dict(sys.modules,self.mods):
            with patch.dict(os.environ,{'TREND_FINDAH_EXPERT_AUTO_DRAFT':'1'}):
                with self.assertRaisesRegex(RuntimeError,'Provider not available'):
                    self.module.execute_once(self.source,self.root,self.archive)
        saved=json.loads((self.root/'logs/expert_automation_status.json').read_text())
        self.assertEqual(saved['state'],'failed')
        self.assertEqual(saved['error_type'],'RuntimeError')


if __name__=='__main__':unittest.main()
