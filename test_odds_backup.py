import copy
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import odds_backup
import scheduled_ats_capture
from public_money import FIELDS, validate_market
from scout4.shadow import quote


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 28, 16, tzinfo=timezone.utc)
        self.game = dict(game_id='2026_08_CAR_GB', season='2026', week='8', game_type='REG',
                         away_team='CAR', home_team='GB', gameday='2026-10-29', gametime='20:15',
                         away_score='', home_score='')
        self.url = odds_backup.BASE+'?dates=2026&seasontype=2&week=8&limit=100'
        self.offer = dict(provider={'name': 'DraftKings'}, pointSpread={
            'away': {'close': {'line': '+3.5', 'odds': '-108'}},
            'home': {'close': {'line': '-3.5', 'odds': '-112'}}}, total={
            'over': {'close': {'line': 'o47.5', 'odds': '-112'}},
            'under': {'close': {'line': 'u47.5', 'odds': '-108'}}})
        self.competition = dict(date='2026-10-30T00:15Z', status={'type': {'state': 'pre'}},
                                competitors=[{'homeAway':'home','team':{'abbreviation':'GB'}},
                                             {'homeAway':'away','team':{'abbreviation':'CAR'}}], odds=[self.offer])
        self.payload = {'events': [{'date': self.competition['date'], 'competitions': [self.competition]}]}

    def parse(self):
        return odds_backup.parse(self.payload, [self.game], self.now, self.url)

    def test_exact_current_prices_feed_unchanged_model_without_fake_splits(self):
        rows = self.parse()
        self.assertEqual(len(rows), 2)
        self.assertEqual(quote(rows, self.game, 'Spread', self.now)['line'], 3.5)
        self.assertEqual(quote(rows, self.game, 'Total', self.now)['line'], 47.5)
        for row in rows:
            self.assertEqual(row['captured_at_utc'], self.now.isoformat())
            self.assertEqual(row['source_url'], self.url)
            self.assertTrue(all(row[k] == '' for k in ('handle_a','handle_b','bets_a','bets_b')))
            with self.assertRaises(ValueError): validate_market(row)

    def test_live_wrong_team_wrong_kickoff_and_duplicate_events_rejected(self):
        original = copy.deepcopy(self.payload)
        self.competition['status']['type']['state'] = 'in'
        self.assertEqual(self.parse(), [])
        self.payload = copy.deepcopy(original)
        self.payload['events'][0]['competitions'][0]['competitors'][0]['team']['abbreviation'] = 'NE'
        self.assertEqual(self.parse(), [])
        self.payload = copy.deepcopy(original)
        self.payload['events'][0]['competitions'][0]['date'] = '2026-10-30T01:15Z'
        self.assertEqual(self.parse(), [])
        self.payload = copy.deepcopy(original)
        self.payload['events'] *= 2
        with self.assertRaises(RuntimeError): self.parse()

    def test_invalid_prices_do_not_get_default_prices_or_opening_lines(self):
        self.offer['pointSpread']['away']['close']['odds'] = 'NaN'
        self.offer['pointSpread']['away']['open'] = {'line': '+7', 'odds': '-110'}
        self.assertEqual([r['market'] for r in self.parse()], ['Total'])
        self.offer['total']['under']['close']['line'] = 'u46.5'
        self.assertEqual(self.parse(), [])

    def setup_root(self, root):
        with (root/'nfl_games.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.game))
            writer.writeheader(); writer.writerow(self.game)
        with (root/'public_money_snapshots.csv').open('w', newline='') as stream:
            csv.DictWriter(stream, fieldnames=FIELDS).writeheader()

    def test_collect_archives_raw_evidence_and_keeps_prior_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.setup_root(root)
            before = (root/'public_money_snapshots.csv').read_text()
            raw = json.dumps(self.payload).encode()
            rows = odds_backup.collect(root, clock=lambda:self.now, fetch=lambda url:raw)
            self.assertEqual(len(rows), 2)
            self.assertTrue((root/'public_money_snapshots.csv').read_text().startswith(before))
            files = list((root/'logs/odds_backup').glob('*-manifest.json'))
            manifest = json.loads(files[0].read_text())
            self.assertFalse(manifest['splits_available'])
            self.assertEqual((files[0].parent/manifest['captures'][0]['file']).read_bytes(), raw)
            with patch('public_pick_market.datetime') as dt:
                dt.fromisoformat = datetime.fromisoformat
                from public_pick_market import matchup_public_market
                pick = dict(game_id=self.game['game_id'],away='CAR',home='GB',kickoff_at=self.competition['date'])
                self.assertTrue(all(not m['sides'] for m in matchup_public_market(root,pick,self.now)['markets']))

    def test_passing_kickoff_during_request_never_writes_a_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.setup_root(root)
            before = (root/'public_money_snapshots.csv').read_bytes()
            times = iter([self.now, self.now, datetime(2026,10,30,0,16,tzinfo=timezone.utc)])
            with self.assertRaises(ValueError):
                odds_backup.collect(root, clock=lambda:next(times), fetch=lambda url:json.dumps(self.payload).encode())
            self.assertEqual((root/'public_money_snapshots.csv').read_bytes(), before)

    def test_partial_primary_only_fills_missing_market(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.setup_root(root)
            required = {(self.game['game_id'], 'Total')}
            rows = odds_backup.collect(root, clock=lambda:self.now,
                fetch=lambda url:json.dumps(self.payload).encode(), required=required)
            self.assertEqual([r['market'] for r in rows], ['Total'])

    def test_primary_outage_uses_prices_and_primary_success_skips_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.setup_root(root)
            rows = self.parse()
            with patch.object(scheduled_ats_capture, 'collect', side_effect=ValueError('maintenance')), \
                 patch('odds_backup.collect', return_value=rows), \
                 patch.object(scheduled_ats_capture, 'missing_prices', return_value=[]):
                self.assertEqual(scheduled_ats_capture.run(root,self.now), 0)
            status = json.loads((root/'logs/ats_capture_status.json').read_text())
            self.assertFalse(status['splits_available'])
            self.assertEqual(status['source'], 'ESPN / DraftKings')
            with patch.object(scheduled_ats_capture, 'collect', return_value=rows), \
                 patch.object(scheduled_ats_capture, 'missing_prices', return_value=[]), \
                 patch.object(scheduled_ats_capture, 'analyze', return_value={'all':{'qualifying':0,'pending':0}}), \
                 patch('odds_backup.collect') as backup:
                self.assertEqual(scheduled_ats_capture.run(root,self.now), 0)
                backup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
