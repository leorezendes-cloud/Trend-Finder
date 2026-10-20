"""Offline review/publication tests. No Gemini key, no provider or network access."""
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

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
HERE = Path(__file__).resolve().parent


def t(days): return (NOW + timedelta(days=days)).isoformat()


def mk_scout(away, home, day=3, week=7):
    return dict(game=dict(season=2026, week=week, away_team=away, home_team=home,
                          game_id=f'2026_{week:02}_{away}_{home}', kickoff_utc=t(day)))


def record(scout, i, kind='production_import', expert=None):
    return dict(scout=scout, kind=kind, expert=expert,
                generated_at=t(-1), version=f'{i:064x}')


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = {}
        cls.rows = []
        fake = types.ModuleType('expert_beta')
        class Store:
            def __init__(self,root): self.root=Path(root)
            def records(self): return cls.rows[:]
            def append(self,scout,expert,kind):
                row = record(scout, 100+len(cls.rows), kind, expert)
                row['generated_at'] = t(0)
                cls.rows.append(row)
                return row['version']
            def featured(self,season,week):
                p=self.root/'featured'/f'{season}-{week}.json'
                ids=json.loads(p.read_text())
                allowed={fake.identity(r['scout']) for r in cls.rows}
                if len(ids)!=2 or len(set(ids))!=2 or not set(ids)<=allowed: raise ValueError('invalid features')
                return ids
        fake.Store=Store
        fake.canonical=lambda o: json.dumps(o,sort_keys=True,separators=(',',':')).encode()
        fake.clock=lambda: NOW
        fake.identity=lambda s:f"{s['game']['season']}/{s['game']['week']}/{s['game']['away_team']}-{s['game']['home_team']}"
        fake.instant=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
        def validate_expert(expert, scout):
            if expert['review_status'] != 'approved' or not expert.get('reviewer'):
                raise ValueError('Missing approval')
            if expert['scout_sha256'] != hashlib.sha256(fake.canonical(scout)).hexdigest():
                raise ValueError('Wrong scout')
            fake.instant(expert['reviewed_at'])
        fake.validate_expert=validate_expert
        cli = types.ModuleType('expert_beta_cli')
        def feature(root, season, week, matchups):
            p=Path(root)/'featured'/f'{season}-{week}.json'
            p.parent.mkdir(exist_ok=True)
            ids=[f'{season}/{week}/{x}' for x in matchups]
            if p.exists(): raise ValueError('already frozen')
            p.write_text(json.dumps(ids))
        cli.feature=feature
        for key, module in [('expert_beta',fake),('expert_beta_cli',cli)]:
            cls.old[key]=sys.modules.get(key)
            sys.modules[key]=module
        spec=importlib.util.spec_from_file_location('tested_review_worker', HERE/'expert_review_publication.py')
        cls.mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.old.items():
            if module is None: sys.modules.pop(name,None)
            else: sys.modules[name]=module

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'drafts').mkdir()
        type(self).rows=[]

    def add(self, away,home, i, day=3):
        s=mk_scout(away,home,day)
        r=record(s,i)
        type(self).rows.append(r)
        return r

    def reviewed(self,row,*,modify=False,status='approved'):
        data={'ai_assisted':True,'scout_sha256':hashlib.sha256(self.mod.canonical(row['scout'])).hexdigest(),
              'text':'Genuine saved Gemini draft', 'review_status':'pending'}
        reviewed={**data,'review_status':status, 'reviewer':'operator','reviewed_at':NOW.isoformat()}
        if modify: reviewed['text']='Unsupported alteration'
        folder=self.root/'drafts'
        (folder/(row['version']+'.json')).write_text(json.dumps(data))
        (folder/(row['version']+'.review.json')).write_text(json.dumps(reviewed))

    def test_no_review_no_publication(self):
        self.add('BUF','MIA',1)
        result=self.mod.run(self.root,execute=True)
        self.assertEqual(result['published_now'],0)
        self.assertEqual(result['awaiting_draft'],1)

    def test_approved_is_published_once_only(self):
        a=self.add('BUF','MIA',1)
        self.reviewed(a)
        x=self.mod.run(self.root,execute=True)
        y=self.mod.run(self.root,execute=True)
        self.assertEqual(x['published_now'],1)
        self.assertEqual(y['published_now'],0)
        self.assertEqual(len(type(self).rows),2)
        self.assertEqual(type(self).rows[-1]['expert']['reviewer'],'operator')

    def test_report_text_changes_are_blocked(self):
        a=self.add('BUF','MIA',1)
        self.reviewed(a,modify=True)
        with self.assertRaisesRegex(ValueError,'changed AI claims'):
            self.mod.run(self.root,execute=True)
        self.assertEqual(len(type(self).rows),1)

    def test_rejected_or_pending_not_published(self):
        a=self.add('BUF','MIA',1)
        self.reviewed(a,status='rejected')
        out=self.mod.run(self.root,execute=True)
        self.assertEqual(out['published_now'],0)
        self.assertEqual(out['rejected_or_pending_review'],1)

    def test_unreviewed_pre_game_only(self):
        a=self.add('BUF','MIA',1,day=-1)
        self.reviewed(a)
        out=self.mod.run(self.root,execute=True)
        self.assertEqual(out['published_now'],0)

    def test_feature_two_published_preserves_original(self):
        a=self.add('BUF','MIA',1)
        b=self.add('NYJ','NE',2)
        c=self.add('CHI','DET',3)
        for row in (a,b,c): self.reviewed(row)
        result=self.mod.run(self.root,execute=True)
        self.assertEqual(result['published_now'],3)
        path=self.root/'featured/2026-7.json'
        self.assertTrue(path.exists())
        self.assertEqual(len(json.loads(path.read_text())),2)
        original=path.read_bytes()
        second=self.mod.run(self.root,execute=True)
        self.assertEqual(second['published_now'],0)
        self.assertEqual(path.read_bytes(),original)

    def test_preview_does_not_write_records_or_feature(self):
        a=self.add('BUF','MIA',1)
        b=self.add('NYJ','NE',2)
        for row in (a,b):self.reviewed(row)
        out=self.mod.run(self.root)
        self.assertEqual(out['approved_ready'],2)
        self.assertEqual(out['published_now'],0)
        self.assertEqual(len(type(self).rows),2)
        self.assertFalse((self.root/'featured/2026-7.json').exists())

    def test_stale_feature_is_validated_and_not_overwritten(self):
        a=self.add('BUF','MIA',1)
        b=self.add('NYJ','NE',2)
        for row in (a,b):self.reviewed(row)
        (self.root/'featured').mkdir()
        (self.root/'featured/2026-7.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'invalid features'):
            self.mod.run(self.root,execute=True)

    def test_no_auto_feature_when_only_one_review(self):
        a=self.add('BUF','MIA',1)
        self.reviewed(a)
        self.mod.run(self.root,execute=True)
        self.assertFalse((self.root/'featured/2026-7.json').exists())


if __name__=='__main__':unittest.main()
