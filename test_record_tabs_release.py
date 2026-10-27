"""Independent weekly Scout vs issued Plug record rendering checks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jinja2 import Environment
from weekly_results import build_results


class RecordTabsReleaseTests(unittest.TestCase):
    def test_shared_tabs_present_in_all_three_pages(self):
        root=Path(__file__).resolve().parent
        for p in ('templates/sunday_results.html','templates/prediction_results.html','templates/plug_ats_record.html'):
            s=(root/p).read_text()
            self.assertIn("'_record_navigation.html'",s,p)
        nav=(root/'templates/_record_navigation.html').read_text()
        for s in ('Weekly Results','Scout Record','Plug Record'):
            self.assertIn(s,nav)

    def test_weekly_uses_only_issued_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            g1=dict(game_id='2026_05_BUF_LA',season='2026',week='5',game_type='REG',gameday='2026-10-12',gametime='20:15',away_team='BUF',home_team='LA',away_score='27',home_score='21',spread_line='2.5')
            g2=dict(game_id='2026_05_TB_DAL',season='2026',week='5',game_type='REG',gameday='2026-10-12',gametime='20:15',away_team='TB',home_team='DAL',away_score='10',home_score='28',spread_line='1.5')
            published=[dict(game_id=g1['game_id'],season=2026,week=5,selected=True,away_team='BUF',side='BUF',away_line=2.5,result='Win')]
            decisions={g1['game_id']:dict(selected=True),g2['game_id']:dict(selected=False)}
            with patch('weekly_results.load_games',return_value={g['game_id']:g for g in (g1,g2)}), patch('forecast_history.official_sources',return_value={}), patch('weekly_results.published_history',return_value=(published,{})),patch('weekly_results.for_game',side_effect=lambda k:decisions.get(k)):
                result=build_results(root,5)
            self.assertEqual(result['plug_tally']['Win'],1)
            self.assertEqual(result['plug_tally']['selected'],1)
            items={g['game_id']:g for g in result['games']}
            self.assertEqual(items[g1['game_id']]['plug_status'],'selected')
            self.assertEqual(items[g1['game_id']]['plug_pick'],'BUF +2.5')
            self.assertEqual(items[g2['game_id']]['plug_status'],'stay_away')
            self.assertEqual(result['tally']['correct'],0)  # No historical Scout records in fixture

    def test_no_issued_receipt_is_not_a_fake_pick(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            game=dict(game_id='2026_05_BUF_LA',season='2026',week='5',game_type='REG',gameday='2026-10-12',gametime='20:15',away_team='BUF',home_team='LA',away_score='27',home_score='21',spread_line='2.5')
            with patch('weekly_results.load_games',return_value={game['game_id']:game}),patch('forecast_history.official_sources',return_value={}),patch('weekly_results.published_history',return_value=([],{})),patch('weekly_results.for_game',return_value=None):
                result=build_results(root,5)
            self.assertEqual(result['plug_tally']['selected'],0)
            self.assertEqual(result['games'][0]['plug_status'],'not_issued')

    def test_template_syntax(self):
        root=Path(__file__).resolve().parent
        env=Environment()
        for p in ('templates/_record_navigation.html','templates/sunday_results.html','templates/prediction_results.html','templates/plug_ats_record.html'):
            env.parse((root/p).read_text())

if __name__=='__main__':unittest.main()
