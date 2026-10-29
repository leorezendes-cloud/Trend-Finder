"""Outages cannot prevent immutable closing or leak legacy official grades."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
from threading import Thread, Event

from test_plug_dynamic_production import decision, activate, item, AT
from test_plug_dynamic_receipt_bridge import GID, KICK
from plug_dynamic_journal import append, read
from plug_dynamic_closing import read_closing
from plug_dynamic_official import apply, enroll
import scheduled_ats_capture as capture


class PipelineRegression(unittest.TestCase):
    def test_both_providers_down_still_locks_exact_saved_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').mkdir()
            append(root,GID,decision())
            with patch.object(capture,'upcoming_games',return_value=['future']), \
                 patch.object(capture,'collect',side_effect=RuntimeError('offline')), \
                 patch('odds_backup.collect',side_effect=RuntimeError('offline')), \
                 patch('plug_dynamic_batch.refresh',return_value={'state':'unavailable'}), \
                 patch.object(capture,'datetime') as clock, \
                 patch.dict('os.environ',{'TREND_FINDAH_DYNAMIC_OFFICIAL':'1'}):
                clock.now.return_value=datetime.fromisoformat(KICK)
                self.assertEqual(capture.run(root,datetime.fromisoformat(KICK)),1)
            receipt=read_closing(root,GID)
            self.assertEqual(receipt['ats_away_line'],-7.5)
            self.assertEqual(receipt['ou_market_total'],48.5)
            self.assertEqual(len(read(root,GID)),1)
            status=json.loads((root/'logs/ats_capture_status.json').read_text())
            self.assertEqual(status['state'],'error')
            self.assertEqual(status['dynamic_closing']['locked'],1)

    def test_refresh_fault_cannot_skip_closing_or_mask_failure(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('plug_dynamic_batch.refresh',side_effect=ValueError('invalid source')), \
             patch.object(capture,'datetime') as clock, \
             patch.dict('os.environ',{'TREND_FINDAH_DYNAMIC_OFFICIAL':'1'}):
            root=Path(tmp);append(root,GID,decision())
            clock.now.return_value=datetime.fromisoformat(KICK)
            status={}
            with self.assertRaisesRegex(RuntimeError,'invalid source'):
                capture.refresh_dynamic(root,status)
            self.assertEqual(status['dynamic_closing']['locked'],1)
            self.assertIsNotNone(read_closing(root,GID))

    def test_review_clears_all_effective_grades_and_preserves_archive(self):
        with tempfile.TemporaryDirectory() as root, \
             patch.dict('os.environ',{'TREND_FINDAH_DYNAMIC_OFFICIAL':'1'}):
            obj=item()
            obj.update(plug_dynamic_grades={'ats':'Win'},plug_ats_decision={'side':'PIT'},
                       plug_ou_receipt={'side':'Over'},plug_ats_policy='legacy',
                       completed_grades={'plug_ats':'Win','plug_total':'Win','scout':'Loss'})
            self.assertFalse(apply(root,obj,as_of_utc=AT))
            for key in ('plug_dynamic_grades','plug_ats_decision','plug_ou_receipt','plug_ats_policy'):
                self.assertNotIn(key,obj)
            self.assertIsNone(obj['completed_grades']['plug_ats'])
            self.assertIsNone(obj['completed_grades']['plug_total'])
            self.assertEqual(obj['completed_grades']['scout'],'Loss')
            self.assertEqual(obj['saved_picks']['spread']['side'],'PIT')

    def test_validation_and_display_hold_same_journal_lock(self):
        from test_plug_dynamic_production import ProductionIntegration
        with tempfile.TemporaryDirectory() as root, ProductionIntegration().sources():
            activate(root);row=append(root,GID,decision());enroll(root,GID,row,AT)
            started,done=Event(),Event()
            def writer():
                started.set()
                append(root,GID,decision('2026-10-28T14:00:00+00:00',-8.5,49))
                done.set()
            from plug_dynamic_authoritative import attach
            threads=[]
            def checked_attach(*args,**kwargs):
                thread=Thread(target=writer);threads.append(thread);thread.start()
                self.assertTrue(started.wait(1))
                self.assertFalse(done.wait(.05))
                return attach(*args,**kwargs)
            obj=item()
            with patch('plug_dynamic_authoritative.attach',side_effect=checked_attach):
                self.assertTrue(apply(root,obj,as_of_utc=AT))
            for thread in threads:thread.join(2)
            self.assertTrue(done.is_set())
            self.assertEqual(obj['plug_ats_pick'],'BAL -7.5')
            self.assertEqual(len(read(root,GID)),2)

if __name__=='__main__':unittest.main()
