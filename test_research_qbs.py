"""Current-season QB evidence must match the game's actual quarterback."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import app
from research_qbs import research_rows
from general_research import research_games, find_combinations
from trend_finder_2 import game_file
from pregame_lines import effective_rows
from score_finals import confirmed_score_rows

FINAL=dict(away='SEA',home='DEN',date='2026-10-16T00:15:00Z',
           state='post',completed=True,status='Final/OT',away_score='14',home_score='17')

class ResearchQBTests(unittest.TestCase):
    def rows(self):
        with open(game_file,newline='') as f:return list(effective_rows(csv.DictReader(f),game_file))

    def test_verified_assignments_do_not_modify_source_rows(self):
        original=self.rows();before=[dict(row) for row in original]
        corrected=research_rows(original,game_file)
        games={g['game_id']:g for g in corrected}
        self.assertEqual(original,before)
        self.assertEqual(games['2026_02_SEA_ARI']['away_qb_name'],'Drew Lock')
        for gid,side in [('2026_03_SEA_WAS','away'),('2026_04_LAC_SEA','home'),
                         ('2026_05_SF_SEA','home'),('2026_06_SEA_DEN','away')]:
            self.assertEqual(games[gid][side+'_qb_name'],'Sam Darnold')
            self.assertIn('https://www.seahawks.com/',games[gid][side+'_qb_source'])
        self.assertEqual(games['2026_03_SEA_WAS']['home_qb_name'],'Marcus Mariota')

    def test_current_road_games_are_present_once_denver_is_confirmed_final(self):
        rows=research_rows(confirmed_score_rows(self.rows(),[FINAL]),game_file)
        report=research_games(rows,season=2026,filters={'away_qb_name':'Sam Darnold','away_team':'SEA'})
        self.assertEqual([g['game_id'] for g in report['matches']],['2026_06_SEA_DEN','2026_03_SEA_WAS'])
        self.assertEqual(report['matches'][0]['away_score'],14)
        self.assertEqual(report['matches'][0]['home_score'],17)

    def test_combination_record_and_latest_ten_include_current_season(self):
        rows=research_rows(confirmed_score_rows(self.rows(),[FINAL]),game_file)
        report=research_games(rows,season=(2022,2026),filters={'away_qb_name':'Sam Darnold','away_team':'SEA'})
        self.assertEqual(report['matches'][0]['game_id'],'2026_06_SEA_DEN')
        self.assertEqual(report['matches'][1]['game_id'],'2026_03_SEA_WAS')
        self.assertNotIn('2025_22_SEA_NE',[g['game_id'] for g in report['matches']])
        trends=find_combinations(report['matches'],role='away',current_rows=rows)
        self.assertTrue(trends)
        for trend in trends:
            self.assertEqual(trend['sample'],report['games'])
            self.assertEqual(trend['recent_games'],report['games'])

    def test_evidence_route_shows_current_season_games_and_qb_sources(self):
        with patch('score_finals.request_finals',return_value=[FINAL]):
            response=app.test_client().get('/trend-finder?research_view=general&run=analyze&season_mode=range&start_season=2022&end_season=2026&away_qb_name=Sam+Darnold&away_team=SEA&evidence=1&evidence_metric=Away+teams+ATS')
        self.assertEqual(response.status_code,200)
        html=response.text
        self.assertIn('2026_06_SEA_DEN',html)
        self.assertIn('2026_03_SEA_WAS',html)
        self.assertIn('SEA QB source',html)
        self.assertLess(html.index('2026_06_SEA_DEN'),html.index('2026_03_SEA_WAS'))
        self.assertNotIn('2025_22_SEA_NE',html)

    def test_corrections_require_matching_identity_and_known_old_value(self):
        rows=self.rows();target=next(g for g in rows if g['game_id']=='2026_03_SEA_WAS')
        for field,value in [('away_team','BUF'),('gameday','2026-09-28'),('away_qb_name','Another QB')]:
            changed={**target,field:value}
            result=research_rows([changed],game_file)[0]
            self.assertEqual(result['away_qb_name'],changed['away_qb_name'])

if __name__=='__main__':unittest.main()
