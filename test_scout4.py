"""Scout 4.0 regression tests: real joins, cutoffs, missingness and weighted rates."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scout4.stats import (team_records, player_records, summarize_player, summarize_team,
                          adjusted_defense, PLAYER_METRICS)


def game(id, week, away='A', home='B', a=10, h=20, location='Home'):
    return dict(game_id=id, season='2025', game_type='REG', week=str(week),
                away_team=away, home_team=home, away_score=str(a), home_score=str(h),
                gameday=f'2025-09-{week:02}', location=location)


def feed(id, week, team, pass_epa, rush_epa=0):
    return dict(game_id=id, week=str(week), team=team, season='2025', season_type='REG',
                passing_epa=pass_epa, rushing_epa=rush_epa)


class StatisticsTests(unittest.TestCase):
    def test_before_week_and_future_score_invariance(self):
        schedule=[game('one',1),game('two',2,a=90),game('future',3,a=50)]
        rows=team_records(schedule,[],2025,2)
        changed=copy.deepcopy(schedule);changed[1]['away_score']='999'
        self.assertEqual(rows,team_records(changed,[],2025,2))
        self.assertEqual({r['game_id'] for r in rows},{'one'})
        self.assertIsNone(rows[0]['passing_epa'])

    def test_neutral_and_designated_side_separate(self):
        rows=team_records([game('n',1,location='Neutral')],[],2025,19)
        self.assertEqual([r['venue'] for r in rows],['Neutral','Neutral'])
        self.assertEqual({r['designated_side'] for r in rows},{'Away','Home'})

    def test_defense_matches_opponent_by_game_not_team_or_week(self):
        schedule=[game('ab',1),game('ac',2,home='C')]
        data=[feed('ab',1,'A',8),feed('ab',1,'B',3),feed('ac',2,'A',20),feed('ac',2,'C',1)]
        rows=team_records(schedule,data,2025,3)
        b=next(r for r in rows if r['team']=='B')
        self.assertEqual(b['passing_epa_allowed'],8)
        # A's other game is 20, so B suppressed 12; the evaluated game is excluded.
        self.assertEqual(adjusted_defense(rows)['B']['pass']['value'],12)
        self.assertEqual(adjusted_defense(rows)['B']['pass']['n'],1)
        self.assertIsNone(adjusted_defense(rows)['A']['pass']['value'])

    def test_missing_metrics_do_not_turn_into_zero(self):
        rows=team_records([game('one',1),game('two',2)],[feed('one',1,'A',8)],2025,3)
        a=[r for r in rows if r['team']=='A'];s=summarize_team(a,a)
        self.assertEqual(s['games'],2)
        self.assertEqual(s['metrics']['passing_epa'],{'value':8,'n':1,'smoothed':8})

    def test_rates_weight_opportunities_and_exclude_incomplete_pairs(self):
        rows=[{m:None for m in PLAYER_METRICS} for _ in range(3)]
        for i,r in enumerate(rows):r['game_id']=str(i)
        rows[0].update(completions=1,attempts=1,passing_yards=10)
        rows[1].update(completions=10,attempts=20,passing_yards=100)
        rows[2].update(completions=None,attempts=30,passing_yards=None)
        s=summarize_player(rows,rows)
        self.assertAlmostEqual(s['completion']['value'],100*11/21)
        self.assertEqual(s['completion']['opportunities'],21)
        self.assertAlmostEqual(s['yards_per_attempt']['value'],110/21)
        self.assertIsNone(s['catch_rate']['value'])

    def test_player_venue_join_and_unattributed_exclusions(self):
        row=feed('one',1,'A',8);row.update(player_id='p',player_display_name='Player',position='QB')
        anonymous={**row,'player_id':''}
        diagnostics={}
        rows=player_records([game('one',1,location='Neutral')],[row,anonymous],2025,2,diagnostics)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['venue'],'Neutral')
        self.assertEqual(diagnostics['unidentified_players'],1)
        with self.assertRaises(ValueError):player_records([game('one',1)],[row,row],2025,2)

    def test_small_venue_sample_shrinks_toward_same_window_baseline(self):
        rows=team_records([game('one',1,a=40),game('two',2,a=0)],[],2025,3)
        a=[r for r in rows if r['team']=='A']
        self.assertEqual(summarize_team(a[:1],a)['metrics']['points_for']['smoothed'],24)


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app
        app.testing=True
        cls.client=app.test_client()

    def test_real_pages_and_matchup(self):
        for path in ['/scout4/teams','/scout4/players',
                     '/scout4/teams?season=2025&before_week=5&team=DAL&opponent=NYJ',
                     '/scout4/players?season=2025&before_week=5&team=DAL&position=QB',
                     '/scout4/teams?season=2025&venue=Neutral',
                     '/scout4/players?season=2025&display=all&page=2']:
            with self.subTest(path=path):
                response=self.client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertIn('not validated prediction confidence',response.get_data(as_text=True))
        text=self.client.get('/scout4/teams?season=2025&before_week=5&team=DAL&opponent=NYJ').get_data(as_text=True)
        self.assertIn('DAL offense vs NYJ defense',text)
        self.assertIn('NYJ offense vs DAL defense',text)

    def test_empty_window_and_missing_season_cache(self):
        for path in ['/scout4/teams?before_week=1','/scout4/players?before_week=1',
                     '/scout4/teams?season=1999','/scout4/players?season=1999']:
            self.assertEqual(self.client.get(path).status_code,200)
        self.assertIn('has not been imported',self.client.get('/scout4/players?season=1999').get_data(as_text=True))

    def test_nonseason_cache_folders_do_not_break_statistics_pages(self):
        from scout4.web import ROOT
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            for name in ('2025', '2026', 'daily', 'archive'):
                folder = cache_root / 'data' / 'scout4' / name
                folder.mkdir(parents=True)
                (folder / 'latest.json').write_text('{}')
            (cache_root / 'nfl_games.csv').write_bytes((ROOT / 'nfl_games.csv').read_bytes())
            with patch('scout4.web.ROOT', cache_root), patch('scout4.web.sources', return_value=([], [], None)):
                for path in (
                    '/scout4/teams?team=SEA&season=2026&before_week=6',
                    '/scout4/teams?team=DEN&season=2026&before_week=6',
                    '/scout4/players',
                ):
                    with self.subTest(path=path):
                        self.assertEqual(self.client.get(path).status_code, 200)

    def test_home_away_splits_keep_cutoff_and_neutral_games_separate(self):
        from flask import render_template
        schedule = [game('away', 1, a=10, h=20),
                    game('home', 2, away='B', home='A', a=14, h=30),
                    game('neutral', 3, a=7, h=7, location='Neutral'),
                    game('future', 4, a=99)]
        schedule[0].update(spread_line='3', total_line='30')
        records = team_records(schedule, [feed('away', 1, 'A', 8)], 2025, 4)
        view = dict(season=2025, before_week=4, venue='Home', years=[2025],
                    cache_years=[], records=records, teams=['A', 'B'],
                    players=[], positions=[], manifest=None, diagnostics={}, coverage_week=3)
        with patch('scout4.web.view_data', return_value=view), patch(
                'scout4.web.render_template', wraps=render_template) as render:
            response = self.client.get('/scout4/teams?team=A&venue=Home')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Home and away splits', response.get_data(as_text=True))
        self.assertIn('A home and away statistics', response.get_data(as_text=True))
        card = render.call_args.kwargs['cards'][0]
        self.assertEqual(card['summary']['games'], 1)
        splits = {split['venue']: split['summary'] for split in card['venue_splits']}
        self.assertEqual(set(splits), {'Home', 'Away', 'Neutral'})
        self.assertEqual([splits[v]['games'] for v in ('Home', 'Away', 'Neutral')], [1, 1, 1])
        self.assertEqual(splits['Home']['wins'], 1)
        self.assertEqual(splits['Away']['losses'], 1)
        self.assertEqual(splits['Neutral']['ties'], 1)
        self.assertEqual(splits['Home']['metrics']['points_for']['value'], 30)
        self.assertEqual(splits['Away']['metrics']['points_for']['value'], 10)
        self.assertIsNone(splits['Home']['metrics']['passing_epa']['value'])
        self.assertEqual(splits['Away']['metrics']['passing_epa']['value'], 8)
        self.assertEqual(splits['Away']['markets']['ats_l'], 1)
        self.assertEqual(splits['Away']['markets']['total_push'], 1)
        self.assertEqual(splits['Home']['markets']['ats_known'], 0)

    def test_home_away_splits_render_when_one_venue_has_no_games(self):
        from flask import render_template
        records = team_records([game('away', 1)], [], 2025, 2)
        view = dict(season=2025, before_week=2, venue='All', years=[2025],
                    cache_years=[], records=records, teams=['A', 'B'],
                    players=[], positions=[], manifest=None, diagnostics={}, coverage_week=1)
        with patch('scout4.web.view_data', return_value=view), patch(
                'scout4.web.render_template', wraps=render_template) as render:
            response = self.client.get('/scout4/teams?team=A')
        self.assertEqual(response.status_code, 200)
        splits = render.call_args.kwargs['cards'][0]['venue_splits']
        self.assertEqual([s['venue'] for s in splits], ['Home', 'Away'])
        self.assertEqual(splits[0]['summary']['games'], 0)
        self.assertIsNone(splits[0]['summary']['metrics']['points_for']['value'])
        self.assertIn('—', response.get_data(as_text=True))

    def test_invalid_filters(self):
        for query in ['season=oops','before_week=0','venue=Road','team=XXX','season=9999']:
            self.assertEqual(self.client.get('/scout4/teams?'+query).status_code,400)
        self.assertEqual(self.client.get('/scout4/players?page=0').status_code,400)

    def test_navigation_and_preserved_scout(self):
        self.assertIn('/scout4/teams',self.client.get('/').get_data(as_text=True))
        self.assertEqual(self.client.get('/sunday-scout').status_code,200)


if __name__=='__main__':unittest.main()
