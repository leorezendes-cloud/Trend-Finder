"""Scout 5.0 compact artifact and backward-compatible signed journal validation."""
import json
import unittest
import tempfile
import tarfile
import os
from unittest.mock import patch
from collections import Counter
from pathlib import Path

from scout5_totals import load_bundle
from scout_dynamic_store import grade, validate

ROOT = Path(__file__).resolve().parent


class Scout5Replacement(unittest.TestCase):
    def test_bundle_replay(self):
        doc = load_bundle(ROOT / 'scout5_ou_bundle.json')
        self.assertEqual(doc['version'], 'scout5-ou-v1')
        self.assertEqual(len(doc['replay_history']), 70)
        count = Counter(x['grades']['ou'] for x in doc['replay_history'])
        self.assertEqual((count['Win'], count['Loss']), (44, 26))
        self.assertIn('10', doc['ratings'])
        self.assertTrue(all(len(teams) == 32 for teams in doc['ratings'].values()))

    def test_retirement_archive_and_blocked_game(self):
        from scout5_retire_legacy import snapshot, verify_backup
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch)
            game=root/'scout_dynamic'/'2026_11_IND_HOU'
            game.mkdir(parents=True)
            (game/'revisions.json').write_text('not a signed journal')
            report=snapshot(root)
            self.assertEqual(report['blocked_count'],1)
            self.assertEqual(report['retirable_count'],0)
            archive=root/'backup.tar'
            with tarfile.open(archive,'w') as stream:
                stream.add(root/'scout_dynamic',arcname='scout_dynamic')
            self.assertEqual(len(verify_backup(archive,report)),64)
            (game/'revisions.json').write_text('changed')
            with self.assertRaises(ValueError):
                verify_backup(archive,snapshot(root))

    def test_cutover_preserves_ats_and_restores_original_issuance(self):
        from scout_dynamic_store import signed
        from scout5_export_ats_evidence import export
        from scout5_cutover import cutover
        from scout_dynamic_public import legacy_ats_evidence
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch)
            (root/'scout5_totals.py').write_text('present')
            directory=root/'scout_dynamic'/'2026_11_IND_HOU'
            directory.mkdir(parents=True)
            kickoff='2026-11-19T20:00:00+00:00'
            q=lambda line: {'line':line,'captured_at_utc':'2026-11-17T12:00:00+00:00','kickoff_utc':kickoff}
            row=dict(policy='scout-dynamic-v1',model_family='Scout 4.0',
                     game_id='2026_11_IND_HOU',away_team='IND',home_team='HOU',
                     model_as_of='2026-11-17T11:00:00+00:00',
                     evaluated_at='2026-11-17T13:00:00+00:00',
                     kickoff_utc=kickoff,revision=1,configuration_sha256='config',
                     inputs_sha256='inputs',decision_id='decision',
                     projection={'away_points':21,'home_points':23,'away_margin':-2},
                     totals={'total':44},ats_side='IND',ou_side='Under',
                     spread=q(3),total_quote=q(45))
            (directory/'revisions.json').write_bytes(
                json.dumps(signed({'rows':[signed(row)]})).encode())
            original_issued=signed(dict(policy='scout-dynamic-v1',
                game_id='2026_11_IND_HOU',issued_at='2026-11-17T13:01:00+00:00',
                kickoff_utc=kickoff,configuration_sha256='config'))
            (directory/'issued.json').write_bytes(json.dumps(original_issued).encode())
            exported=export(root)
            with patch('scout5_cutover.load_bundle',return_value={'replay_history':[None]*70}):
                checked=cutover(root,exported,apply=False)
                self.assertEqual(checked['games'],1)
                self.assertTrue(directory.exists())
                completed=cutover(root,exported,apply=True)
            self.assertEqual(completed['directories_removed'],1)
            self.assertFalse(directory.exists())
            self.assertEqual(legacy_ats_evidence(root,'2026_11_IND_HOU')['issued_sha256'],
                             original_issued['sha256'])

    def test_existing_issued_ats_side_and_line_are_frozen(self):
        from scout_dynamic import preserve_issued_ats
        from scout_dynamic_store import signed
        from scout5_export_ats_evidence import export
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch)
            directory=root/'scout_dynamic'/'2026_11_IND_HOU'
            directory.mkdir(parents=True)
            kickoff='2026-11-19T20:00:00+00:00'
            q=lambda line: {'line':line,'captured_at_utc':'2026-11-17T12:00:00+00:00',
                            'kickoff_utc':kickoff}
            old=dict(policy='scout-dynamic-v1',model_family='Scout 4.0',
                game_id='2026_11_IND_HOU',away_team='IND',home_team='HOU',
                model_as_of='2026-11-17T11:00:00+00:00',
                evaluated_at='2026-11-17T13:00:00+00:00',
                kickoff_utc=kickoff,revision=1,configuration_sha256='config',
                inputs_sha256='inputs',decision_id='old-decision',
                projection={'away_points':21,'home_points':23,'away_margin':-2},
                totals={'total':44},ats_side='IND',ou_side='Under',
                spread=q(3),total_quote=q(45))
            (directory/'revisions.json').write_text(json.dumps(signed({'rows':[signed(old)]})))
            (directory/'issued.json').write_text(json.dumps(signed(dict(
                policy='scout-dynamic-v1',game_id=old['game_id'],
                issued_at='2026-11-17T13:01:00+00:00',
                kickoff_utc=kickoff,configuration_sha256='config'))))
            from scout5_cutover import cutover
            (root/'scout5_totals.py').write_text('present')
            exported=export(root)
            with patch('scout5_cutover.load_bundle',return_value={'replay_history':[None]*70}):
                cutover(root,exported,apply=True)
            updated=dict(old,revision=1,model_as_of='2026-11-17T15:00:00+00:00',
                evaluated_at='2026-11-17T16:00:00+00:00',
                projection={'away_points':28,'home_points':20,'away_margin':8},
                ats_side='HOU',spread=q(-2),
                totals={'total':None,'model':'scout5-ou-v1'},ou_side=None,
                total_quote=q(47))
            frozen=preserve_issued_ats(root,updated,
                now=__import__('datetime').datetime.fromisoformat(updated['evaluated_at']))
            self.assertEqual(frozen['ats_side'],'IND')
            self.assertEqual(frozen['spread'],old['spread'])
            self.assertEqual(frozen['projection'],old['projection'])
            self.assertEqual(frozen['model_as_of'],old['model_as_of'])
            self.assertEqual(frozen['total_quote']['line'],47)
            self.assertIsNone(frozen['ou_side'])
            self.assertEqual(grade(frozen,(24,20))['ats'],'Win')

    def test_public_record_uses_only_compact_replay(self):
        from scout_dynamic_public import records
        with tempfile.TemporaryDirectory() as scratch:
            with patch.dict(os.environ, {'TREND_FINDAH_SCOUT_DYNAMIC_PUBLIC': '0'}):
                result = records(Path(scratch), {}, 2026, None)
        rows = result['scout_dynamic_records']
        self.assertEqual(len(rows), 70)
        self.assertEqual(result['scout_dynamic_counts']['ou']['Win'], 44)
        self.assertEqual(result['scout_dynamic_counts']['ou']['Loss'], 26)
        self.assertTrue(all(r['source'] == 'Scout 5.0 reconstructed historical replay' for r in rows))

    def test_missing_next_week_ou_does_not_block_ats(self):
        kickoff = '2026-11-19T20:00:00+00:00'
        q = lambda line: {'line': line, 'captured_at_utc': '2026-11-17T12:00:00+00:00', 'kickoff_utc': kickoff}
        row = dict(policy='scout-dynamic-v1', model_family='Scout 4.0', model_version='x',
                   model_as_of='2026-11-17T11:00:00+00:00',
                   evaluated_at='2026-11-17T13:00:00+00:00', kickoff_utc=kickoff,
                   game_id='2026_11_IND_HOU', away_team='IND', home_team='HOU',
                   projection={'away_points': 21, 'home_points': 23, 'away_margin': -2},
                   totals={'model': 'scout5-ou-v1', 'total': None},
                   ats_side='IND', ou_side=None, spread=q(3), total_quote=q(45))
        validate(row, row['game_id'])
        result = grade(row, (24, 20))
        self.assertEqual(result['ou'], 'No Call')
        self.assertEqual(result['ats'], 'Win')
        wrong = dict(row, totals={'model': 'scout4-totals-1', 'total': None})
        with self.assertRaises(ValueError):
            validate(wrong, wrong['game_id'])
