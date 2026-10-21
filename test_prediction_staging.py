"""Offline atomic pipeline tests: synthetic games, unchanged approved model."""
import csv
import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from scout4 import blend, shadow
import prediction_staging as staging
import hosted_updates as hosted
from scheduler_runtime import atomic_json, due_job, exclusive

SOURCE = Path(__file__).resolve().parent
CONFIG = SOURCE/'automatic_model.json'
NOW = datetime(2030, 10, 16, 13, tzinfo=timezone.utc)

class FixedClock(datetime):
    @staticmethod
    def now(tz=None): return NOW

def csv_file(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader(); writer.writerows(rows)


def fixture(root):
    root.mkdir()
    shutil.copyfile(CONFIG, root/'automatic_model.json')
    for name in blend.CORE:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE/name, target)
    schedule = []
    feed = []
    for week in range(1, 4):
        game_id = f'2030_{week:02}_NE_BUF'
        schedule.append(dict(game_id=game_id, season='2030', week=str(week), game_type='REG',
            gameday=f'2030-09-{week*7:02}', gametime='13:00', away_team='NE', home_team='BUF',
            away_score=str(20+week), home_score=str(24+week), location='Home', spread_line='3', total_line='45'))
        for team, opponent in [('NE','BUF'), ('BUF','NE')]:
            feed.append(dict(game_id=game_id, season='2030', week=str(week), season_type='REG',
                team=team, opponent_team=opponent, passing_epa='3', rushing_epa='1',
                attempts='30', carries='20', sacks_suffered='2', passing_yards='250', rushing_yards='90'))
    schedule.append(dict(schedule[-1], game_id='2030_04_NE_BUF', week='4', gameday='2030-10-17',
                         gametime='20:15', away_score='', home_score=''))
    csv_file(root/'nfl_games.csv', schedule)
    csv_file(root/'data/scout4/fixture/team.csv', feed)
    team = root/'data/scout4/fixture/team.csv'
    manifest = root/'data/scout4/2030/latest.json'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'retrieved_at':NOW.isoformat(), 'files':{'team':{
        'path':'fixture/team.csv', 'sha256':hashlib.sha256(team.read_bytes()).hexdigest()}}}))
    quote = dict(game_id='2030_04_NE_BUF', away_team='NE', home_team='BUF', market='Spread',
        side_a='NE', side_b='BUF', line_a='3', line_b='-3', odds_a='-110', odds_b='-110',
        captured_at_utc=NOW.isoformat(), kickoff_utc=shadow.kickoff(schedule[-1]).isoformat(),
        sportsbook='Fixture', source_url='https://example.test/fixture')
    csv_file(root/'public_money_snapshots.csv', [quote, dict(quote, market='Total', side_a='Over',
        side_b='Under', line_a='45', line_b='45')])


def generate(root):
    # Only the wall clock is controlled; all model functions and configuration are real.
    with patch.dict(os.environ, {'TREND_FINDAH_AUTO_MODEL_CONFIG':str(root/'automatic_model.json')}), patch.object(shadow, 'datetime', FixedClock):
        result = blend.run(root, now=NOW)
    assert result['saved'] == 1, result
    return root/'data/scout4/blend/predictions/2030_04_NE_BUF.json'



class AtomicPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'root'
        fixture(self.root)
        self.clock = NOW
        for target in ('scout4.shadow.datetime',):
            controller = patch(target, FixedClock)
            controller.start(); self.addCleanup(controller.stop)
        controller = patch('plug_publication.clock', side_effect=lambda:self.clock)
        controller.start(); self.addCleanup(controller.stop)
        self.final = self.root/'data/scout4/blend/predictions'
        self.area = self.root/'data/scout4/blend/atomic_staging'

    def run_pipeline(self):
        return staging.run_staged(self.root, SOURCE, CONFIG, clock=lambda:self.clock)

    def target(self):
        return self.final/'2030_04_NE_BUF.json'

    def latest(self):
        return next(self.area.glob('run-*'))

    def test_output_identical_to_direct_unchanged_model(self):
        direct = Path(self.temp.name)/'direct'; fixture(direct)
        expected = generate(direct).read_bytes()
        result = self.run_pipeline()
        self.assertEqual(self.target().read_bytes(), expected)
        self.assertEqual(result['state'], 'ok')
        self.assertFalse(any(p.is_symlink() for p in self.latest().rglob('*')))
        self.assertEqual(self.latest().stat().st_dev, self.final.stat().st_dev)
        record = json.loads(expected)
        self.assertIsNotNone(record['totals'])
        self.assertIn('EPA Recent Form', record['research_benchmarks'])

    def test_restart_after_complete_skips_existing_forecast(self):
        self.run_pipeline(); original = self.target().read_bytes()
        self.clock += timedelta(seconds=1)
        self.run_pipeline()
        self.assertEqual(self.target().read_bytes(), original)
        self.assertEqual(len(list(self.final.glob('*.json'))), 1)

    def test_interrupted_install_recovers_without_regeneration(self):
        with patch('prediction_staging.os.link', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): self.run_pipeline()
        self.assertFalse(self.target().exists())
        candidate = self.latest()/'data/scout4/blend/predictions'/self.target().name
        expected = candidate.read_bytes()
        with patch('scout4.blend.run', side_effect=AssertionError('must recover, not generate')):
            self.run_pipeline()
        self.assertEqual(self.target().read_bytes(), expected)

    def test_crash_after_link_before_journal_recovers_exact_bytes(self):
        original = staging.atomic_json
        def interrupt(path, value):
            if value.get('records') and any(v.get('result') == 'installed' for v in value['records'].values()):
                raise KeyboardInterrupt('after link')
            return original(path, value)
        with patch('prediction_staging.atomic_json', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt): self.run_pipeline()
        expected = self.target().read_bytes()
        self.clock += timedelta(seconds=1)
        self.run_pipeline()
        self.assertEqual(self.target().read_bytes(), expected)

    def test_interruption_before_first_forecast_recovers_missed_generation(self):
        with patch('scout4.blend.run', side_effect=KeyboardInterrupt('before first write')):
            with self.assertRaises(KeyboardInterrupt): self.run_pipeline()
        self.assertFalse(self.target().exists())
        self.run_pipeline()
        self.assertTrue(self.target().exists())
        states = [json.loads((stage/'journal.json').read_text())['state'] for stage in self.area.glob('run-*')]
        self.assertCountEqual(states, ['abandoned_generation', 'complete'])

    def test_interrupted_snapshot_allows_fresh_isolated_attempt(self):
        with patch.object(staging, 'snapshot', side_effect=KeyboardInterrupt('snapshot')):
            with self.assertRaises(KeyboardInterrupt): self.run_pipeline()
        self.run_pipeline()
        self.assertTrue(self.target().exists())
        states = [json.loads((stage/'journal.json').read_text())['state'] for stage in self.area.glob('run-*')]
        self.assertCountEqual(states, ['abandoned_snapshot', 'complete'])

    def test_partial_staged_write_is_retained_and_flagged(self):
        def partial(path, record, **kwargs):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{')
            raise KeyboardInterrupt('during model write')
        with patch('scout4.blend.seal', side_effect=partial):
            with self.assertRaises(KeyboardInterrupt): self.run_pipeline()
        with self.assertRaises(json.JSONDecodeError): self.run_pipeline()
        self.assertFalse(self.target().exists())
        journal = json.loads((self.latest()/'journal.json').read_text())
        self.assertEqual(journal['state'], 'needs_review')
        self.assertEqual((self.latest()/'data/scout4/blend/predictions'/self.target().name).read_bytes(), b'{')

    def test_partial_existing_final_is_never_repaired(self):
        self.final.mkdir(parents=True); self.target().write_bytes(b'{')
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertEqual(self.target().read_bytes(), b'{')

    def test_conflicting_existing_file_is_preserved(self):
        with patch('prediction_staging.os.link', side_effect=OSError('pause')):
            with self.assertRaises(OSError): self.run_pipeline()
        self.target().write_text('{"status":"SEALED_PREKICKOFF_RESEARCH","different":true}')
        original = self.target().read_bytes()
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertEqual(self.target().read_bytes(), original)

    def test_post_kickoff_recovery_rejected(self):
        with patch('prediction_staging.os.link', side_effect=OSError('pause')):
            with self.assertRaises(OSError): self.run_pipeline()
        candidate = self.latest()/'data/scout4/blend/predictions'/self.target().name
        self.clock = datetime.fromisoformat(json.loads(candidate.read_text())['kickoff_utc'])
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertFalse(self.target().exists())

    def test_staging_symlink_rejected_without_writing_target(self):
        outside = Path(self.temp.name)/'outside'; outside.mkdir()
        self.area.parent.mkdir(parents=True)
        self.area.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertEqual(list(outside.iterdir()), [])

    def test_recovery_symlink_and_provenance_tampering_rejected(self):
        with patch('prediction_staging.os.link', side_effect=OSError('pause')):
            with self.assertRaises(OSError): self.run_pipeline()
        (self.latest()/'nfl_games.csv').write_text('changed')
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertFalse(self.target().exists())

    def test_whole_pipeline_lock_rejects_concurrent_operation(self):
        self.area.mkdir(parents=True)
        with exclusive(self.area/'pipeline.lock'):
            with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertFalse(self.target().exists())

    def test_simultaneous_install_attempts_publish_one_complete_file(self):
        direct = Path(self.temp.name)/'direct'; fixture(direct)
        candidate = generate(direct)
        self.final.mkdir(parents=True)
        record = json.loads(candidate.read_text())
        results, errors = [], []
        def attempt():
            try:
                results.append(staging.install(candidate, self.target(), record, lambda:NOW))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=attempt) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(results.count('installed'), 1)
        self.assertEqual(results.count('preserved'), 3)
        self.assertEqual(self.target().read_bytes(), candidate.read_bytes())

    def test_different_filesystem_is_rejected(self):
        direct = Path(self.temp.name)/'direct'; fixture(direct)
        candidate = generate(direct)
        self.final.mkdir(parents=True)
        original = Path.stat
        from types import SimpleNamespace
        def stat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == candidate:
                return SimpleNamespace(st_dev=result.st_dev+1)
            return result
        with patch.object(Path, 'stat', stat):
            with self.assertRaises(staging.StagingError):
                staging.install(candidate, self.target(), json.loads(candidate.read_text()), lambda:NOW)
        self.assertFalse(self.target().exists())

    def test_kickoff_boundary_is_checked_after_flush(self):
        direct = Path(self.temp.name)/'direct'; fixture(direct)
        candidate = generate(direct)
        self.final.mkdir(parents=True)
        record = json.loads(candidate.read_text())
        kickoff = datetime.fromisoformat(record['kickoff_utc'])
        with self.assertRaises(staging.StagingError):
            staging.install(candidate, self.target(), record, lambda:kickoff)
        self.assertFalse(self.target().exists())
        self.assertEqual(list(self.final.iterdir()), [])

    def test_symlink_inside_recovery_tree_cannot_write_production(self):
        with patch('prediction_staging.os.link', side_effect=OSError('pause')):
            with self.assertRaises(OSError): self.run_pipeline()
        path = self.latest()/'nfl_games.csv'
        path.unlink(); path.symlink_to(self.root/'nfl_games.csv')
        original = (self.root/'nfl_games.csv').read_bytes()
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertEqual((self.root/'nfl_games.csv').read_bytes(), original)
        self.assertFalse(self.target().exists())

    def test_missing_completed_candidate_is_not_silently_accepted(self):
        with patch('prediction_staging.os.link', side_effect=OSError('pause')):
            with self.assertRaises(OSError): self.run_pipeline()
        candidate = self.latest()/'data/scout4/blend/predictions'/self.target().name
        candidate.unlink()  # Simulate loss in the temporary fixture only.
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertFalse(self.target().exists())

    def test_final_directory_symlink_is_rejected(self):
        outside = Path(self.temp.name)/'outside'; outside.mkdir()
        self.final.parent.mkdir(parents=True)
        self.final.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertEqual(list(outside.iterdir()), [])

    def test_candidate_tampering_is_rejected(self):
        with patch('prediction_staging.os.link', side_effect=OSError('pause')):
            with self.assertRaises(OSError): self.run_pipeline()
        candidate = self.latest()/'data/scout4/blend/predictions'/self.target().name
        record = json.loads(candidate.read_text())
        record['plug_points_only']['away_points'] = 99
        candidate.write_text(json.dumps(record))
        with self.assertRaises(staging.StagingError): self.run_pipeline()
        self.assertFalse(self.target().exists())

    def test_scheduler_lock_due_state_and_pipeline_integration(self):
        def update(root):
            self.run_pipeline()
            return {'state':'ok'}
        with patch.object(hosted, 'update_once', side_effect=update):
            action = lambda:hosted.locked_update(self.root)
            self.assertEqual(due_job(self.root, 'automatic-data-updates', action, 21600, 600, lambda:100), 0)
            original = self.target().read_bytes()
            self.assertEqual(due_job(self.root, 'automatic-data-updates', action, 21600, 600, lambda:101), 'not_due')
            with exclusive(self.root/'logs/auto_update.lock'):
                self.assertEqual(hosted.locked_update(self.root), 75)
        self.assertEqual(self.target().read_bytes(), original)

    def test_update_once_routes_only_prediction_stage_through_wrapper(self):
        # Replace every external stage; exercise real update_once dispatch only.
        from types import SimpleNamespace
        inert = Mock()
        (self.root/'data/scout4/blend').mkdir(parents=True)
        with patch.dict('sys.modules', {
            'update_nfl_games':SimpleNamespace(main=inert),
            'scout4.collect':SimpleNamespace(collect=inert),
            'scheduled_ats_capture':SimpleNamespace(run=lambda root:0),
            'fan_views':SimpleNamespace(prediction_performance=lambda *a:({}, [], [])),
            'qb_verification':SimpleNamespace(refresh_qbs=inert),
            'plug_publication':SimpleNamespace(publish=inert),
            'scout4.research_benchmarks':SimpleNamespace(grade_benchmarks=lambda *a:{})}), patch.object(hosted, 'backup_database'), patch.dict(os.environ, {'TREND_FINDAH_CONTEXT_RESEARCH':'0','TREND_FINDAH_EXPERT_AUTO_DRAFT':'0'}), patch.object(staging, 'run_staged', return_value={'state':'ok'}) as wrapper:
            hosted.update_once(self.root)
        wrapper.assert_called_once_with(self.root, hosted.SOURCE, hosted.SOURCE/'automatic_model.json')

if __name__ == '__main__': unittest.main()
