"""Focused beta tests; no network access or production writes."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from comeback_leads import ROOT, SNAPSHOT, records, validated_snapshot


class ComebackLeadTests(unittest.TestCase):
    def test_snapshot_consistent_and_comebacks(self):
        doc = validated_snapshot()
        self.assertIsNotNone(doc, 'Snapshot must match local saved 2026 final scores')
        self.assertEqual(len(doc['games']), doc['games_checked'])
        self.assertEqual(sum(v['comeback_wins_10_plus']
                             for v in doc['teams'].values()),
                         sum(int(g['home_comeback']) + int(g['away_comeback'])
                             for g in doc['games'].values()))
        self.assertEqual(len(records(doc)), 32)

    def test_flag_off_hides_route(self):
        with patch.dict(app.config, {'COMEBACK_LEADS_ENABLED': False}):
            res = app.test_client().get('/trend-finder/comebacks')
            self.assertEqual(res.status_code, 404)

    def test_flag_on_renders_season_snapshot(self):
        with patch.dict(app.config, {'COMEBACK_LEADS_ENABLED': True}):
            res = app.test_client().get('/trend-finder/comebacks')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Comebacks <span>&amp;</span> Blown Leads', res.data)
            self.assertIn(b'Games audited', res.data)

    def test_changed_saved_final_fails_closed(self):
        doc = validated_snapshot()
        self.assertIsNotNone(doc)
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp)
            snapshot = fake / SNAPSHOT
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text(json.dumps(doc))
            with (fake/'nfl_games.csv').open('w', newline='') as f:
                out = csv.DictWriter(f, fieldnames=[
                    'game_id', 'home_team', 'away_team', 'home_score', 'away_score'])
                out.writeheader()
                for gid, g in doc['games'].items():
                    out.writerow(dict(game_id=gid, home_team=g['home'],
                        away_team=g['away'], home_score=g['home_pts']+1,
                        away_score=g['away_pts']))
            self.assertIsNone(validated_snapshot(fake))



if __name__ == '__main__':
    unittest.main()
