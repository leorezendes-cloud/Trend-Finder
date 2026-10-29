"""Every actual capture path refreshes dynamic state once, without model rebuilds."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import scheduled_ats_capture as capture
import test_odds_backup as backup

class DynamicCaptureTests(unittest.TestCase):
    setUp=backup.BackupTests.setUp
    parse=backup.BackupTests.parse
    setup_root=backup.BackupTests.setup_root
    def test_primary_and_backup_invoke_dynamic_once_after_persisted_capture(self):
        for primary_failed in (False,True):
            with self.subTest(backup=primary_failed),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.setup_root(root)
                rows=self.parse()
                with patch.object(capture,'collect',side_effect=ValueError('feed unavailable') if primary_failed else None,return_value=rows),\
                     patch.object(capture,'missing_prices',return_value=[]),\
                     patch.object(capture,'analyze',return_value={'all':{'qualifying':0,'pending':0}}),\
                     patch('odds_backup.collect',return_value=rows),\
                     patch('plug_dynamic_batch.refresh',return_value={'state':'partial','unavailable':1}) as dynamic,\
                     patch('plug_dynamic_finalize_batch.finalize_due',return_value={'errors':0}) as close,\
                     patch.dict('os.environ',{'TREND_FINDAH_DYNAMIC_RESEARCH':'1'}):
                    self.assertEqual(capture.run(root,self.now),0)
                    dynamic.assert_called_once();close.assert_called_once()
                status=json.loads((root/'logs/ats_capture_status.json').read_text())
                self.assertEqual(status['dynamic']['state'],'partial')

    def test_failed_capture_cannot_refresh_and_dynamic_corruption_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.setup_root(root);rows=self.parse()
            with patch.object(capture,'collect',side_effect=ValueError('offline')),\
                 patch('odds_backup.collect',side_effect=ValueError('offline')),\
                 patch('plug_dynamic_batch.refresh') as dynamic,\
                 patch.dict('os.environ',{'TREND_FINDAH_DYNAMIC_RESEARCH':'1'}):
                self.assertEqual(capture.run(root,self.now),1);dynamic.assert_not_called()
            with patch.object(capture,'collect',return_value=rows),\
                 patch.object(capture,'missing_prices',return_value=[]),\
                 patch.object(capture,'analyze',return_value={'all':{'qualifying':0,'pending':0}}),\
                 patch('plug_dynamic_batch.refresh',side_effect=ValueError('journal corrupt')),\
                 patch.dict('os.environ',{'TREND_FINDAH_DYNAMIC_RESEARCH':'1'}):
                self.assertEqual(capture.run(root,self.now),1)
            status=json.loads((root/'logs/ats_capture_status.json').read_text())
            self.assertEqual(status['state'],'error')
            self.assertIn('journal corrupt',status['dynamic_error'])

if __name__=='__main__':unittest.main()
