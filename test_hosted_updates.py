import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from hosted_updates import initialize_data, configure_persistent_data, update_once


class HostedUpdatesTests(unittest.TestCase):
    def test_persistence_preserves_updates_and_seeded_predictions_on_redeploy(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source';target=Path(directory)/'persistent'
            source.mkdir();(source/'nfl_games.csv').write_text('seed')
            predictions=source/'data/scout4/blend/predictions';predictions.mkdir(parents=True)
            (predictions/'game.json').write_text('sealed')
            initialize_data(source,target)
            (target/'nfl_games.csv').write_text('updated')
            self.assertEqual((source/'nfl_games.csv').read_text(),'updated')
            initialize_data(source,target)
            self.assertEqual((source/'nfl_games.csv').read_text(),'updated')
            self.assertEqual((source/'data/scout4/blend/predictions/game.json').read_text(),'sealed')

    def test_upstream_failure_skips_new_predictions_and_reports_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'logs').mkdir()
            (root/'nfl_games.csv').write_text('game_id,away_team,home_team\n')
            (root/'data/scout4/blend/predictions').mkdir(parents=True)
            with patch('update_nfl_games.main',side_effect=ValueError('unverified final')), patch('scout4.collect.collect'), patch('scheduled_ats_capture.run',return_value=0), patch('scout4.blend.run') as predictions:
                status=update_once(root)
            self.assertEqual(status['state'],'needs attention')
            self.assertIn('skipped',status['stages']['predictions'])
            predictions.assert_not_called()
            self.assertTrue((root/'logs/auto_update_status.json').exists())

    def test_automatic_updates_are_disabled_by_default_and_guarded_locally(self):
        with patch.dict('os.environ', {'TREND_FINDAH_AUTO_UPDATE':'0'}):
            configure_persistent_data()
        with patch.dict('os.environ', {'TREND_FINDAH_AUTO_UPDATE':'1','TREND_FINDAH_ENV':'development'}):
            with self.assertRaises(RuntimeError):configure_persistent_data()


if __name__=='__main__':unittest.main()
