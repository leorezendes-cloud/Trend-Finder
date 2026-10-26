import json
import unittest
from unittest.mock import patch, MagicMock
from app import app
from fan_views import parse_scores, _score_cache, leaders, prediction_performance
from scout4.stats import recent_form, betting_result, team_records, summarize_team


class FanViewsTests(unittest.TestCase):
    def setUp(self):
        from fan_views import _score_response
        _score_response.update(key=None, expires=0, body=None)

    def test_scheduled_scores_are_not_reported_as_zero(self):
        event = {'date':'2026-10-09T00:15Z', 'competitions':[{
            'status':{'type':{'state':'pre', 'shortDetail':'Scheduled'}},
            'competitors':[{'homeAway':side, 'team':{'abbreviation':team}, 'score':'0'}
                           for side,team in [('away','TB'), ('home','DAL')]]}]}
        rows = parse_scores({'events':[event, {}]})
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['away_score'])
        event['competitions'][0]['status']['type']['state'] = 'in'
        self.assertEqual(parse_scores({'events':[event]})[0]['away_score'], '0')

    def test_score_cache_and_delayed_feed(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'events':[]}).encode()
        with patch.dict(_score_cache, {'expires':0,'games':[],'updated':None}, clear=True):
            with patch('fan_views.urlopen', return_value=response) as provider:
                client = app.test_client()
                self.assertFalse(client.get('/scores.json').json['stale'])
                client.get('/scores.json')
                self.assertEqual(provider.call_count, 1)
            _score_cache['expires'] = 0
            with patch('fan_views.urlopen', side_effect=OSError('offline')):
                self.assertTrue(client.get('/scores.json').json['stale'])
                self.assertIsNotNone(client.get('/scores.json').json['updated'])

    def test_live_games_use_fifteen_second_cache_without_browser_cache(self):
        with patch.dict(_score_cache, {'expires':9999999,'games':[{'state':'in','date':'2026-10-18T20:00Z','away':'BUF','home':'LV','away_score':'7','home_score':'3','status':'Q1'}], 'updated':'2026-10-18T20:05:00Z','week':(2026,6)}, clear=True):
            with patch('fan_views.time.monotonic',return_value=0), patch('site_week.active_week',return_value=(2026,6)):
                response=app.test_client().get('/scores.json')
                self.assertEqual(response.json['refresh_seconds'],15)
                self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_week_switch_discards_previous_scoreboard_cache(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'events':[]}).encode()
        with patch.dict(_score_cache,{'expires':9999999,'games':[{'state':'in'}],'updated':'old','week':(2026,5)},clear=True), patch('site_week.active_week',return_value=(2026,6)), patch('fan_views.urlopen',return_value=response) as provider:
            result=app.test_client().get('/scores.json')
            self.assertEqual(result.json['games'],[])
            self.assertIn('week=6',provider.call_args.args[0].full_url)

    def test_matchup_stats_stop_before_game_week_and_link_to_players(self):
        # Keep this route test independent of checked-in production datasets.
        game = dict(game_id='2026_06_BUF_LV',season='2026',week='6',
                    away_team='BUF',home_team='LV',gameday='2026-10-18',gametime='16:25',
                    game_type='REG',away_score='',home_score='',spread_line='3',total_line='45')
        from scout4.stats import team_records, player_records
        history = [dict(game,game_id=f'2026_{week:02}_BUF_LV',week=str(week),
                        away_score='24',home_score='21',result='-3',gameday=f'2026-09-{week:02}')
                   for week in range(1,7)]
        people = [dict(game_id=f'2026_{week:02}_BUF_LV',season='2026',week=str(week),season_type='REG',team='BUF',
                       player_id='fixture-qb',player_display_name='Fixture QB',position='QB',
                       passing_yards='200') for week in range(1,7)]
        records=team_records(history,[],2026,6)
        players=player_records(history,people,2026,6)
        self.assertTrue(all(row['week']<6 for row in records+players))
        with patch('fan_views.read_csv',return_value=[game]), \
                patch('fan_views.effective_rows',side_effect=lambda rows,*a,**kw:rows), \
                patch('fan_views.fan_context',return_value=(2026,6,records,players,{},[],[])):
            response = app.test_client().get('/matchup/2026_06_BUF_LV')
            self.assertEqual(response.status_code, 200)
            self.assertIn('before_week=6', response.text)
            self.assertIn('Top passer', response.text)
            self.assertIn('player=', response.text)
            self.assertIn('Prediction', response.text)
            self.assertEqual(app.test_client().get('/matchup/not-a-game').status_code, 404)

    def test_form_is_latest_five_and_streak_uses_chronology(self):
        rows = [{'date':f'2026-09-{i:02d}', 'week':i, 'game_id':str(i),
                 'net_points':1 if i>2 else -1,'points_for':20} for i in range(1,8)]
        form = recent_form(rows[::-1])
        self.assertEqual(form['streak'], '5 straight wins')
        self.assertEqual([r['week'] for r in form['games']], [7,6,5,4,3])

    def test_market_grades_pushes_missing_lines_and_team_perspective(self):
        game = {'home_score':'24','away_score':'21','spread_line':'3','total_line':'45'}
        self.assertEqual(betting_result(game)['home_ats'], 'P')
        self.assertEqual(betting_result(game)['ou'], 'P')
        game.update(spread_line='2.5', total_line='44.5')
        self.assertEqual(betting_result(game)['home_ats'], 'W')
        self.assertEqual(betting_result(game)['ou'], 'O')
        game.update(game_id='2026_01_BUF_LV',home_team='LV',away_team='BUF',season='2026',week='1',game_type='REG',gameday='2026-09-13')
        rows = team_records([game], [], 2026, 2)
        home = next(row for row in rows if row['team']=='LV')
        away = next(row for row in rows if row['team']=='BUF')
        self.assertEqual(home['ats'], 'W')
        self.assertEqual(away['ats'], 'L')
        self.assertEqual(summarize_team([home], [home])['markets']['over'], 1)
        game.update(spread_line='', total_line='')
        self.assertIsNone(betting_result(game)['home_ats'])
        self.assertIsNone(betting_result(game)['ou'])

    def test_prediction_results_exclude_late_records_and_separate_versions(self):
        from copy import deepcopy
        record = {'game_id':'game','away_team':'BUF','home_team':'LV',
                  'kickoff_utc':'2026-10-18T20:00:00+00:00',
                  'sealed_at_utc':'2026-10-17T20:00:00+00:00',
                  'decision_cutoff_utc':'2026-10-17T19:00:00+00:00',
                  'quote':{'line':3, 'captured_at_utc':'2026-10-17T18:00:00+00:00'},
                  'version':'v1','configuration_sha256':'config1',
                  'components':{'Blend':{'pick':'BUF'}}}
        game = {'game_id':'game','away_team':'BUF','home_team':'LV','away_score':'20','home_score':'21'}
        late = deepcopy(record);late['game_id'] = 'game-late'
        late['sealed_at_utc'] = '2026-10-19T00:00:00+00:00'
        other = deepcopy(record);other['game_id'] = 'game-other'
        other['configuration_sha256'] = 'config2'
        other['components']['Blend']['pick'] = 'LV'
        schedule = [
            game,
            dict(game, game_id='game-late'),
            dict(game, game_id='game-other'),
        ]
        groups, recent, excluded = prediction_performance(
            [record, late, other], schedule)
        self.assertEqual(excluded, 1)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['ats']['rate'], 100)
        self.assertEqual(groups[1]['ats']['rate'], 0)
        duplicate_groups, _, duplicate_excluded = prediction_performance(
            [record, deepcopy(record)], [game])
        self.assertEqual(duplicate_excluded, 2)
        self.assertEqual(duplicate_groups, [])
        game['away_score'] = ''
        groups, recent, excluded = prediction_performance([record], [game])
        self.assertIsNone(groups[0]['ats']['rate'])
        self.assertEqual(groups[0]['ats']['Pending'], 1)
        self.assertEqual(recent, [])

    def test_fantasy_week_selection_filters_results_and_rejects_invalid_week(self):
        from copy import deepcopy
        row = {'player_id':'test','team':'BUF','name':'Week four player','position':'RB','week':4,
               'passing_yards':0,'passing_tds':0,'passing_interceptions':0,'rushing_yards':80,
               'rushing_tds':1,'receiving_yards':30,'receiving_tds':0,'receptions':4}
        other = deepcopy(row);other.update(player_id='other',name='Week five player',week=5)
        view = {'players':[row,other], 'cache_years':[2026], 'season':2026,'coverage_week':5,
                'before_week':19,'venue':'All','manifest':None,'diagnostics':{'unidentified_players':0,'unmatched_games':0}}
        with patch('fan_views.view_data',return_value=view):
            response=app.test_client().get('/fantasy?week=4')
            self.assertEqual(response.status_code,200)
            self.assertIn('Week four player',response.text)
            self.assertNotIn('Week five player',response.text)
            self.assertEqual(app.test_client().get('/fantasy?week=bad').status_code,400)
            self.assertEqual(app.test_client().get('/fantasy?week=19').status_code,400)

    def test_ppr_formula_and_missing_stat_exclusion(self):
        row = {'player_id':'test', 'team':'BUF', 'name':'Test player','position':'RB',
               'passing_yards':0,'passing_tds':0,'passing_interceptions':0,
               'rushing_yards':80,'rushing_tds':1,'receiving_yards':30,'receiving_tds':0,'receptions':4}
        view = {'players':[row], 'cache_years':[2026], 'season':2026,'coverage_week':5,
                'before_week':19,'venue':'All','manifest':None,'diagnostics':{'unidentified_players':0,'unmatched_games':0}}
        with patch('fan_views.view_data', return_value=view):
            response = app.test_client().get('/fantasy')
            self.assertIn('21.0', response.text)
            self.assertIn('before fumble deductions', response.text)
            row['rushing_yards'] = None
            self.assertIn('No recorded fantasy production available', app.test_client().get('/fantasy').text)


if __name__ == '__main__':
    unittest.main()
