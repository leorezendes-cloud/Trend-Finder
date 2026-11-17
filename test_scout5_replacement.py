"""Scout 5.0 compact artifact and backward-compatible signed journal validation."""
import json
import unittest
import tempfile
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
        self.assertNotIn('11', doc['ratings'])

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
