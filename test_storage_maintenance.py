"""Real disk-file integration: preserve exact evidence bytes, paths and recovery."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_storage import save_capture, share_file
from storage_maintenance import compact, maintain

RAW=b'<html>verified market evidence</html>\n'*4096
STAMP='20261028T120000000000Z'


def put(root, relative, raw=RAW):
    path=root/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    return path


class ArchiveStorageTests(unittest.TestCase):
    def test_new_captures_keep_original_names_bytes_and_independent_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'logs/ats_handle'
            a,b=folder/'first-page1.html',folder/'second-page1.html'
            expected=hashlib.sha256(RAW).hexdigest()
            self.assertEqual(save_capture(a,RAW),expected)
            self.assertEqual(save_capture(b,RAW),expected)
            self.assertEqual(a.read_bytes(),RAW)
            self.assertEqual(b.read_bytes(),RAW)
            self.assertEqual(a.stat().st_ino,b.stat().st_ino)
            save_capture(a,RAW)
            with self.assertRaises(ValueError):save_capture(a,b'changed')
            self.assertEqual(a.read_bytes(),RAW)
            self.assertEqual(len(list((folder/'_objects').glob('*.html'))),1)

    def test_corrupt_existing_object_and_symlink_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'logs/ats_handle'
            save_capture(folder/'first.html',RAW)
            object_path=next((folder/'_objects').glob('*.html'))
            # Only disposable synthetic evidence is corrupted in this fixture.
            object_path.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):save_capture(folder/'second.html',RAW)
            self.assertFalse((folder/'second.html').exists())
            original=Path(tmp)/'outside';original.write_bytes(RAW)
            path=folder/'link.html';path.symlink_to(original)
            with self.assertRaises(ValueError):save_capture(path,RAW)
            self.assertEqual(original.read_bytes(),RAW)

    def test_historical_compaction_preserves_every_path_hash_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            put(root,'logs/ats_handle/one.html')
            put(root,'logs/ats_handle/two.html')
            put(root,'logs/ats_handle/one-manifest.json',b'{"file":"one.html"}')
            for n in ('a','b'):
                stage=f'data/scout4/blend/atomic_staging/run-{n}'
                put(root,stage+'/journal.json',b'{"state":"complete"}')
                put(root,stage+'/nfl_games.csv')
                put(root,stage+f'/data/scout4/blend/inputs/{STAMP}/nfl_games.csv')
            before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            estimate=compact(root,min_age=0)
            self.assertGreater(estimate['shared_files'],0)
            self.assertNotEqual((root/'logs/ats_handle/one.html').stat().st_ino,
                                (root/'logs/ats_handle/two.html').stat().st_ino)
            applied=compact(root,apply=True,min_age=0)
            self.assertGreater(applied['shared_files'],0)
            for path,raw in before.items():self.assertEqual((root/path).read_bytes(),raw)
            self.assertEqual((root/'logs/ats_handle/one.html').stat().st_ino,
                             (root/'logs/ats_handle/two.html').stat().st_ino)
            repeat=compact(root,apply=True,min_age=0)
            self.assertEqual(repeat['shared_files'],0)
            self.assertEqual(repeat['reclaimed_bytes'],0)
            self.assertFalse(any(p.name.startswith('.share-') for p in root.rglob('*')))

    def test_live_data_receipts_journals_and_incomplete_staging_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            names=['nfl_games.csv','public_money_snapshots.csv','ats_handle_snapshots.csv',
                   'plug_dynamic_research/game.jsonl','plug_dynamic_closing/game.json',
                   'data/scout4/blend/predictions/game.json',
                   'data/scout4/blend/plug_ou/game.json',
                   'data/scout4/blend/atomic_staging/run-pending/nfl_games.csv']
            for name in names:put(root,name)
            put(root,'data/scout4/blend/atomic_staging/run-pending/journal.json',b'{"state":"generated"}')
            before={name:(root/name).stat().st_ino for name in names}
            compact(root,apply=True,min_age=0)
            for name,inode in before.items():self.assertEqual((root/name).stat().st_ino,inode)

    def test_recent_files_and_external_symlinks_are_not_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a=put(root,'logs/ats_handle/one.html')
            b=put(root,'logs/ats_handle/two.html')
            self.assertEqual(compact(root,apply=True)['shared_files'],0)
            target=put(root,'outside/original')
            a.unlink();a.symlink_to(target)
            compact(root,apply=True,min_age=0)
            self.assertTrue(a.is_symlink())
            self.assertEqual(target.read_bytes(),RAW)
            self.assertEqual(b.read_bytes(),RAW)

    def test_link_failure_and_byte_conflict_leave_original_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=put(root,'a');b=put(root,'b')
            with patch('archive_storage.os.link',side_effect=OSError('no space')):
                with self.assertRaises(OSError):share_file(a,b)
            self.assertEqual(b.read_bytes(),RAW)
            b.write_bytes(RAW.replace(b'market',b'prices'))
            expected=b.read_bytes()
            with self.assertRaises(ValueError):share_file(a,b)
            self.assertEqual(b.read_bytes(),expected)

    def test_pool_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'logs/ats_handle';folder.mkdir(parents=True)
            external=root/'outside';external.mkdir()
            (folder/'_objects').symlink_to(external,target_is_directory=True)
            path=put(root,'logs/ats_handle/one.html')
            with self.assertRaises(ValueError):save_capture(folder/'new.html',RAW)
            with self.assertRaises(ValueError):compact(root,apply=True,min_age=0)
            self.assertEqual(path.read_bytes(),RAW)
            self.assertEqual(list(external.iterdir()),[])

    def test_low_disk_maintenance_runs_before_the_guard_without_lowering_it(self):
        import hosted_updates
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').mkdir()
            low=SimpleNamespace(free=113*1024*1024)
            with patch('storage_maintenance.maintain',return_value={'state':'ok','reclaimed_bytes':0}) as reclaim,\
                 patch('hosted_updates.shutil.disk_usage',return_value=low):
                result=hosted_updates.update_once(root)
            reclaim.assert_called_once_with(root)
            self.assertEqual(result['state'],'needs attention')
            self.assertIn('128 MB',result['stages']['storage'])

    def test_daily_maintenance_does_not_repeat_when_space_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'logs').mkdir()
            compact(root,apply=True,min_age=0)
            with patch('storage_maintenance.compact') as run:
                result=maintain(root)
            self.assertEqual(result['state'],'not_due')
            run.assert_not_called()

    def test_primary_collector_still_saves_readable_raw_files_and_original_hashes(self):
        import csv
        import io
        import collect_ats_handle
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            put(root,'nfl_games.csv',b'game_id,away_team,home_team\n')
            with (root/'ats_handle_snapshots.csv').open('w',newline='') as f:
                csv.DictWriter(f,fieldnames=sorted(collect_ats_handle.REQUIRED)).writeheader()
            before=(root/'ats_handle_snapshots.csv').read_bytes()
            with patch('collect_ats_handle.urlopen',side_effect=lambda *a,**k:io.BytesIO(RAW)),\
                 patch('collect_ats_handle.parse_page',return_value=[]):
                self.assertEqual(collect_ats_handle.collect(root),[])
                self.assertEqual(collect_ats_handle.collect(root),[])
            files=list((root/'logs/ats_handle').glob('*.html'))
            manifests=list((root/'logs/ats_handle').glob('*-manifest.json'))
            self.assertEqual(len(files),2)
            self.assertEqual(files[0].stat().st_ino,files[1].stat().st_ino)
            for path in manifests:
                capture=json.loads(path.read_text())['captures'][0]
                raw=(path.parent/capture['file']).read_bytes()
                self.assertEqual(raw,RAW)
                self.assertEqual(hashlib.sha256(raw).hexdigest(),capture['sha256'])
            self.assertEqual((root/'ats_handle_snapshots.csv').read_bytes(),before)

    def test_backup_keeps_distinct_capture_timestamps_with_shared_raw_bytes(self):
        import csv
        from datetime import timedelta
        import odds_backup
        import test_odds_backup as fixture_module
        fixture=fixture_module.BackupTests();fixture.setUp()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture.setup_root(root)
            raw=json.dumps(fixture.payload).encode()
            for minute in (0,1):
                odds_backup.collect(root,clock=lambda:fixture.now+timedelta(minutes=minute),fetch=lambda url:raw)
            paths=[p for p in (root/'logs/odds_backup').glob('*.json') if not p.name.endswith('-manifest.json')]
            self.assertEqual(len(paths),2)
            self.assertEqual(paths[0].stat().st_ino,paths[1].stat().st_ino)
            for path in paths:self.assertEqual(path.read_bytes(),raw)
            with (root/'public_money_snapshots.csv').open() as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),4)
            self.assertEqual(len({r['captured_at_utc'] for r in rows}),2)
