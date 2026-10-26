"""Focused, offline tests for the independent top-quarter selector."""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from plug_ats_select import shortlist, decorate_dashboard, storage_root, for_game


class PlugSelectorReleaseTests(unittest.TestCase):
    def test_ceiling_and_deterministic_tie_without_cutoff(self):
        r = [dict(game_id=f'2026_08_A_{i:02}', season=2026, week=8, edge=e)
             for i, e in enumerate([11.0, -8.9, 7.0, 6.9, 2, 1, 0, -0.5, .25, .001])]
        self.assertEqual(shortlist(r), {'2026_08_A_00', '2026_08_A_01', '2026_08_A_02'})
        r[3]['edge'] = 7
        self.assertEqual(shortlist(r), {'2026_08_A_00', '2026_08_A_01', '2026_08_A_02'})

    def test_zero_edges_omitted(self):
        r = [dict(game_id=str(i), season=2026, week=8, edge=x) for i, x in enumerate([0, .1, .2, .3, .4])]
        self.assertEqual(shortlist(r), {'4'})

    def test_seasons_and_weeks_are_independent(self):
        r = [dict(game_id=f'{year}_{week}_{i}', season=year, week=week, edge=i+1)
             for year,week in [(2024, 8), (2025, 8), (2026, 8), (2026, 9)] for i in range(8)]
        self.assertEqual(len(shortlist(r)), 8)

    def test_duplicate_identity_fails(self):
        r = [dict(game_id='dup', season=2026, week=9, edge=1)] * 2
        with self.assertRaises(ValueError):
            shortlist(r)

    def _game(self, n, kickoff, edge):
        name = f'2026_08_A{n}_H{n}'
        return {'scout': {'game': {'game_id':name,'season':2026,'week':8,
                'away_team':f'A{n}','home_team':f'H{n}','kickoff_utc':kickoff.isoformat()}},
                'plug_ats_source': {'model_version':'plug-points-only-4',
                    'side':f'A{n}' if edge >= 0 else f'H{n}', 'edge':edge,
                    'away_line':2, 'source_sha256':'a'*64,
                    'captured_at_utc':(kickoff-timedelta(hours=4)).isoformat(),
                    'sealed_at_utc':(kickoff-timedelta(hours=3)).isoformat()}}

    def test_receipt_is_immutable_and_pregame(self):
        now = datetime(2026,10,28,12,tzinfo=timezone.utc)
        kick = now+timedelta(days=1)
        rows=[self._game(n,kick,e) for n,e in enumerate([11,8.9,7,6,3,2,1,0])]
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ', {'TREND_FINDAH_PLUG_ATS_STORE':d}):
            sections={'games':rows,'underway_games':[],'completed_games':[],'awaiting_games':[]}
            decorate_dashboard(sections,now)
            self.assertEqual([r['plug_ats_status'] for r in rows].count('selected'), 2)
            self.assertEqual(rows[0]['plug_ats_status'],'selected')
            self.assertEqual(rows[1]['plug_ats_status'],'selected')
            self.assertIsNotNone(for_game(rows[0]['scout']['game']['game_id']))
            files=list(Path(d).glob('*.json'))
            self.assertEqual(len(files),1)
            saved=files[0].read_bytes()
            # Model direction and rankings may change, but the original receipt cannot.
            rows[0]['plug_ats_source']['edge'] = .1
            decorate_dashboard(sections,now+timedelta(minutes=2))
            self.assertEqual(saved,files[0].read_bytes())
            self.assertEqual(rows[0]['plug_ats_status'],'selected')

    def test_partial_or_started_slate_is_not_published(self):
        now=datetime(2026,10,28,12,tzinfo=timezone.utc)
        kick=now+timedelta(days=1)
        rows=[self._game(n,kick,e) for n,e in enumerate([8,6,4,2])]
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ', {'TREND_FINDAH_PLUG_ATS_STORE':d}):
            sections={'games':rows, 'completed_games':[], 'underway_games':[], 'awaiting_games':[]}
            rows[2].pop('plug_ats_source')
            decorate_dashboard(sections, now)
            self.assertTrue(all(r['plug_ats_status']=='pending' for r in rows))
            self.assertFalse(list(Path(d).glob('*.json')))
            rows[2]['plug_ats_source']=self._game(2,kick,4)['plug_ats_source']
            rows[2]['scout']['game']['kickoff_utc']=(now-timedelta(hours=1)).isoformat()
            decorate_dashboard(sections,now)
            self.assertFalse(list(Path(d).glob('*.json')))

if __name__ == '__main__': unittest.main()
