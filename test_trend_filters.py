"""Verify CSV filters against independently selected historical games."""
import csv
import unittest
from unittest.mock import patch

import trend_finder_2 as finder
from app import app, display_trend_filters, display_trend_baseline


class CsvFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(finder.game_file, newline='') as source:
            cls.games = list(csv.DictReader(source))
        cls.row = next(game for game in cls.games if all(
            game.get(field, '') for field in finder.CSV_FILTER_FIELDS if field not in ('qb_name','home_coast','away_coast','dog_coast')
        ))

    def test_every_csv_parameter_filters_games(self):
        for field in finder.CSV_FILTER_FIELDS:
            if field in ('home_coast','away_coast','dog_coast'):
                continue  # Derived geography is covered in test_coast_filters.
            with self.subTest(field=field):
                value = self.row['home_qb_name'] if field=='qb_name' else self.row[field]
                if field=='qb_name':
                    subset=[game for game in self.games if value in (game.get('home_qb_name'),game.get('away_qb_name'))]
                elif field in finder.NUMERIC_FILTER_FIELDS:
                    subset = [game for game in self.games if game.get(field, '')
                              and float(game[field]) == float(value)]
                else:
                    subset = [game for game in self.games if game.get(field) == value]
                self.assertEqual(finder.Check_Games(self.games, **{field: value}),
                                 finder.Check_Games(subset))

    def test_near_identical_samples_are_grouped_without_changing_records(self):
        def group(ids,label,rate):
            return {'_ids':frozenset(ids),'filters':[label],'ats_rate':rate,
                    'ats_wins':7,'ats_losses':3,'ats_pushes':0,'sample':10}
        first=group(range(10),'Underdog QB: Example',70)
        similar=group(list(range(9))+[10],'Away team: BUF',65)
        separate=group(range(20,30),'Away team: SEA',60)
        collapsed=finder.collapse_overlapping_combinations([first,similar,separate])
        self.assertEqual(len(collapsed),2)
        self.assertEqual(collapsed[0]['ats_rate'],70)
        self.assertEqual(collapsed[0]['overlapping_patterns'][0]['ats_rate'],65)

    def test_combination_scan_keeps_scope(self):
        scope = {'home_team': self.row['home_team'], 'roof': self.row['roof']}
        trends = finder.scan_basic_trends(season=self.row['season'], **scope)
        self.assertTrue(trends)
        for trend in trends:
            expected = finder.Check_Games(
                self.games, season=self.row['season'], game_type='REG',
                location=trend['location'], is_primetime=trend['primetime'],
                min_spread=trend['min_spread'], max_spread=trend['max_spread'], **scope)
            self.assertEqual(trend['sample'], finder.evaluate_trend(expected)['sample'])

    def test_ats_threshold_and_collapsed_cards(self):
        template = finder.scan_basic_trends(season=self.row['season'])[0]
        template['filters'] = ['Away team: ATL', 'Home team rest: 7 days', 'Stadium roof: dome']
        template.update(ats_wins=5, ats_losses=3, ats_pushes=1)
        candidates = [
            dict(template, ats_rate=54.99, sample=3),
            dict(template, ats_rate=55.0, sample=3),
            dict(template, ats_rate=62.5, sample=4),
            dict(template, ats_rate=100.0, sample=2),
        ]
        with patch('app.scan_grouped_combinations', return_value=candidates):
            response = app.test_client().post('/trend-finder', data={'action': 'combinations', 'season': '2026'})
        html = response.get_data(as_text=True)
        self.assertNotIn('54.99% ATS', html)
        self.assertNotIn('100.00% ATS', html)
        self.assertIn('55.00% ATS', html)
        self.assertIn('62.50% ATS', html)
        self.assertEqual(html.count('<details class="combination-card">'), 2)
        self.assertIn('class="combination-win-rate"', html)
        self.assertNotIn('95% ATS range:', html)
        self.assertIn('Full trend details', html)
        self.assertIn('Underdog ATS: 5–3–1', html)
        self.assertNotIn('(W–L–P)', html)
        self.assertIn('Away team: ATL | Home team rest: 7 days | Stadium roof: dome', html)
        self.assertIn('ATL is the away team', html)
        self.assertIn('the home team has 7 days of rest', html)
        self.assertNotIn('Search checks up to three grouped features together', html)

    def test_group_boundaries_and_sample_rule(self):
        self.assertEqual(finder.combination_min_games(None), 10)
        self.assertEqual(finder.combination_min_games('2025'), 10)
        self.assertEqual(finder.combination_min_games((2025, 2026)), 10)
        self.assertEqual(finder.combination_min_games('2026'), 3)
        self.assertEqual(finder.combination_min_games((2026, 2026)), 3)
        game = dict(self.row, gametime='12:00', home_rest='7', away_rest='8', total_line='45')
        features = finder.grouped_game_features(game, finder.analyze_game(game))
        self.assertIn(('Game time', 'Day (12:00–18:59)'), features)
        self.assertIn(('Home team rest', '7 days'), features)
        self.assertIn(('Away team rest', '>7 days'), features)
        self.assertFalse(any(field == 'Pregame total line' for field, _ in features))
        self.assertFalse(any(field in {'Home Score', 'Away Score', 'Result', 'Overtime', 'Game Id'} for field, _ in features))

    def test_grouped_scan_limits_and_historical_minimum(self):
        trends = finder.scan_grouped_combinations(season=self.row['season'], limit=12, beam_width=10)
        self.assertTrue(trends)
        self.assertLessEqual(len(trends), 12)
        for trend in trends:
            self.assertGreaterEqual(trend['sample'], 10)
            self.assertGreaterEqual(trend['ats_rate'], 55)
            self.assertLessEqual(len(trend['filters']), 3)

    def test_discovery_uses_current_contexts_but_manual_filters_keep_history(self):
        contexts = finder.current_feature_contexts(finder.effective_rows(self.games, finder.game_file), {})
        self.assertTrue(contexts)
        trends = finder.scan_grouped_combinations(limit=30, beam_width=20)
        self.assertTrue(trends)
        labels = [{f'{field}: {value}' for field, value in context} for context in contexts]
        for trend in trends:
            self.assertTrue(any(set(trend['filters']) <= context for context in labels))
        current_season = max(int(game['season']) for game in self.games)
        current_qbs = {game[field] for game in self.games
                       if int(game['season']) == current_season
                       for field in ('home_qb_name', 'away_qb_name') if game.get(field)}
        historical_qb = next(game['home_qb_name'] for game in self.games
                            if game.get('home_qb_name') and game['home_qb_name'] not in current_qbs)
        self.assertGreater(finder.Check_Games(self.games, home_qb_name=historical_qb)['all_games']['games'], 0)
        self.assertIn(historical_qb, finder.get_csv_filter_options()['home_qb_name'])
        self.assertEqual(finder.scan_grouped_combinations(home_qb_name=historical_qb), [])
        upcoming = dict(self.row, season='2027', home_score='', away_score='', result='')
        self.assertTrue(finder.current_feature_contexts([upcoming], {}))

    def test_automatic_qb_feature_uses_only_underdog_side(self):
        for spread, expected in ((-3, 'Home QB'), (3, 'Away QB')):
            with self.subTest(spread=spread):
                game = dict(self.row, spread_line=str(spread),
                            home_qb_name='Home QB', away_qb_name='Away QB')
                features = finder.grouped_game_features(game, finder.analyze_game(game))
                qb_features = {feature for feature in features if 'QB' in feature[0] or 'Qb' in feature[0]}
                self.assertEqual(qb_features, {('Underdog QB', expected)})
        game['away_qb_name'] = ''
        features = finder.grouped_game_features(game, finder.analyze_game(game))
        self.assertFalse(any(field == 'Underdog QB' for field, _ in features))
        game['spread_line'] = '0'
        features = finder.grouped_game_features(game, finder.analyze_game(game))
        self.assertFalse(any(field == 'Underdog QB' for field, _ in features))

    def test_spreads_are_manual_scope_only(self):
        features = finder.grouped_game_features(self.row, finder.analyze_game(self.row))
        self.assertFalse(any('spread' in field.lower() for field, _ in features))
        above_all_spreads = max(abs(float(game['spread_line'])) for game in self.games
                                if game.get('spread_line')) + 1
        trends = finder.scan_grouped_combinations(min_spread=above_all_spreads)
        self.assertEqual(trends, [])
        with patch('app.scan_grouped_combinations', return_value=[]) as scan:
            response = app.test_client().post('/trend-finder', data={
                'action': 'combinations', 'spread_mode': 'range',
                'min_spread': '3', 'max_spread': '7',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(scan.call_args.kwargs['min_spread'], 3.0)
        self.assertEqual(scan.call_args.kwargs['max_spread'], 7.0)

    def test_ats_record_counts_covers_losses_and_pushes(self):
        games = [dict(self.row, spread_line='3', result=str(result),
                      home_score=str(20 + result), away_score='20')
                 for result in (0, 7, 3)]
        trend = finder.evaluate_trend(finder.Check_Games(games))
        self.assertEqual((trend['ats_wins'], trend['ats_losses'], trend['ats_pushes']), (1, 1, 1))
        self.assertEqual(trend['ats_rate'], 50.0)

    def test_upcoming_matches_are_known_unstarted_and_rank_first(self):
        now = finder.datetime(2026, 10, 11, 12, tzinfo=finder.ZoneInfo('America/New_York'))
        upcoming = dict(self.row, gameday='2026-10-12', gametime='13:00',
                        home_score='', away_score='', result='', spread_line='3',
                        home_rest='7', roof='dome', away_team='ATL')
        started = dict(upcoming, gameday='2026-10-11', gametime='11:00')
        distant = dict(upcoming, gameday='2026-10-20')
        unknown = dict(upcoming, roof='')
        contexts = finder.upcoming_combination_contexts([upcoming, started, distant, unknown], {}, now=now)
        self.assertEqual(len(contexts), 2)
        trends = [
            dict(filters=['Stadium roof: outdoors'], ci_low=90, sample=100),
            dict(filters=['Away team: ATL', 'Home team rest: 7 days', 'Stadium roof: dome'], ci_low=20, sample=10),
        ]
        finder.prioritize_upcoming_combinations(trends, contexts)
        self.assertTrue(trends[0]['coming_soon'])
        self.assertEqual(len(trends[0]['upcoming_games']), 1)
        self.assertFalse(trends[1]['coming_soon'])
        self.assertEqual(finder.upcoming_combination_contexts([upcoming], {'min_spread': 7}, now=now), [])
        self.assertEqual(finder.upcoming_combination_contexts([upcoming], {'home_team': 'NONEXISTENT'}, now=now), [])

    def test_only_top_30_of_100_cards_display(self):
        template = finder.evaluate_trend(finder.Check_Games(self.games))
        candidates = [dict(template, filters=[f'Example: {index}'], ats_rate=60,
                           coming_soon=index == 0, upcoming_games=[])
                      for index in range(100)]
        with patch('app.scan_grouped_combinations', return_value=candidates):
            response = app.test_client().post('/trend-finder', data={'action': 'combinations'})
        html = response.get_data(as_text=True)
        self.assertEqual(html.count('<details class="combination-card">'), 30)
        self.assertIn('top 30 grouped trends from 100 combinations', html)
        self.assertIn('Coming up within 7 days', html)
        self.assertNotIn('Example: 30', html)

    def test_trend_description_names_underdog_and_all_conditions(self):
        trend = dict(filters=['Game Type: REG', 'Underdog QB: Josh Allen'], ats_rate=61.25)
        description = finder.describe_combination(trend, season='2026', min_spread=3, roof='dome')
        self.assertIn('In 2026, when it is a regular-season game and Josh Allen quarterbacks the underdog', description)
        self.assertIn('the underdog spread is at least 3', description)
        self.assertIn('the game is played in a dome', description)
        self.assertIn('covered the spread 61.25% of the time, excluding pushes', description)

    def test_related_filters_share_baseline_and_show_record_differences(self):
        qb = ('Underdog QB', 'Josh Allen')
        roof = ('Stadium roof', 'dome')
        rest = ('Home team rest', '7 days')
        baseline_ids = frozenset(range(10))
        strong_ids = frozenset(range(6))
        weak_ids = frozenset(range(4, 10))
        def stats(ids):
            wins = 6 if ids == baseline_ids else 5 if ids == strong_ids else 3
            return dict(sample=len(ids), ats_wins=wins, ats_losses=len(ids)-wins,
                        ats_pushes=0, ats_rate=wins/len(ids)*100, ci_low=20)
        def variant(ids, extra):
            return dict(stats(ids), _ids=ids, _features=(extra, qb),
                        filters=[f'{field}: {value}' for field, value in (extra, qb)],
                        coming_soon=False, upcoming_games=[])
        strong = variant(strong_ids, roof)
        weak = variant(weak_ids, rest)
        groups = finder.group_related_combinations(
            [strong], {qb: baseline_ids, roof: strong_ids, rest: weak_ids}, stats, [strong, weak])
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group['filters'], ['Underdog QB: Josh Allen'])
        self.assertEqual(group['ats_wins'], 6)
        self.assertEqual(group['ats_rate'], 60)
        self.assertEqual(len(group['related']), 2)
        changes = {item['ats_wins']: item['ats_difference'] for item in group['related']}
        self.assertAlmostEqual(changes[5], 5/6*100-60)
        self.assertAlmostEqual(changes[3], -10)

    def test_totals_are_manual_filters_only(self):
        features = finder.grouped_game_features(self.row, finder.analyze_game(self.row))
        self.assertFalse(any('total' in field.lower() for field, _ in features))
        with patch('app.scan_grouped_combinations', return_value=[]) as scan:
            response = app.test_client().post('/trend-finder', data={
                'action': 'combinations', 'total_line': self.row['total_line'],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(scan.call_args.kwargs['total_line'], self.row['total_line'])

    def test_month_names_are_display_only(self):
        labels = ['Month: 10', 'Away team: ATL']
        self.assertEqual(display_trend_filters(labels), 'Month: October | Away team: ATL')
        self.assertEqual(labels, ['Month: 10', 'Away team: ATL'])
        self.assertEqual(display_trend_filters(['Month: 01']), 'Month: January')
        self.assertEqual(display_trend_filters(['Month: 13']), 'Month: 13')
        trend = dict(finder.evaluate_trend(finder.Check_Games(self.games)),
                     filters=labels, ats_rate=60)
        with patch('app.scan_grouped_combinations', return_value=[trend]):
            response = app.test_client().post('/trend-finder', data={'action': 'combinations'})
        html = response.get_data(as_text=True)
        self.assertIn('Month: October | Away team: ATL', html)
        self.assertNotIn('Month: 10', html)

    def test_related_filters_keep_broader_baseline_comparisons(self):
        anchor = ('Div Game', '0')
        surface = ('Surface', 'matrixturf')
        rest = ('Home team rest', '7 days')
        main_ids = frozenset(range(6))
        further_ids = frozenset(range(4))
        sibling_ids = frozenset(range(4, 10))
        all_ids = frozenset(range(10))
        def stats(ids):
            rate = 50 if ids == all_ids else 60 if ids == main_ids else 70 if ids == further_ids else 40
            return dict(sample=len(ids), ats_rate=rate, ci_low=rate-20)
        def variant(ids, features):
            return dict(stats(ids), _ids=ids, _features=features,
                        filters=[f'{field}: {value}' for field, value in features], coming_soon=False)
        main = variant(main_ids, (anchor, surface))
        further = variant(further_ids, (anchor, surface, rest))
        further['ci_low'] = 0  # Keep the two-condition main card as the leader.
        sibling = variant(sibling_ids, (anchor, rest))
        # Anchor must be the widest facet, so all variants join its family.
        memberships = {anchor: all_ids, surface: main_ids, rest: sibling_ids}
        groups = finder.group_related_combinations([main], memberships, stats, [main, further, sibling])
        card = groups[0]
        rows = {tuple(row['filters']): row for row in card['related']}
        self.assertIn(tuple(card['filters']), rows)
        self.assertEqual(rows[tuple(main['filters'])]['added_filters'], ['Surface: matrixturf'])
        self.assertEqual(rows[tuple(main['filters'])]['ats_difference'], 10)
        self.assertEqual(rows[tuple(further['filters'])]['ats_difference'], 20)

    def test_baseline_division_labels_are_separate_from_ats_rate(self):
        labels = ['Div Game: 0']
        self.assertEqual(display_trend_baseline(labels), 'Non-division games')
        self.assertEqual(display_trend_baseline(['Div Game: 1']), 'Division games')
        self.assertEqual(labels, ['Div Game: 0'])
        with app.test_request_context('/'):
            from flask import render_template
            record = dict(ats_rate=57.86, ats_wins=81, ats_losses=59, ats_pushes=0,
                          sample=140, filters=['Div Game: 0', 'Surface: matrixturf'])
            baseline = dict(record, filters=labels, ats_rate=50.75)
            card = dict(record, baseline=baseline, related=[dict(record, added_filters=['Surface: matrixturf'], ats_difference=7.11)],
                        description='', dog_no_push=140, games_url='/combination-details',
                        coming_soon=True, upcoming_games=[dict(matchup='BUF at LA', kickoff='Oct 12', dog_team='BUF')])
            html = render_template('index.html', combinations=[card], combination_count=1,
                                   combination_minimum=10, summary=None, csv_filters={}, filter_options={}, active_filters=[])
        self.assertIn('Baseline: Non-division games | Underdog ATS: 50.75%', html)
        self.assertLess(html.index('Baseline: Non-division games'), html.index('<strong>Upcoming matches</strong>'))

    def test_form_combinations_and_invalid_csv_choice(self):
        client = app.test_client()
        self.assertEqual(client.get('/trend-finder').status_code, 200)
        response = client.post('/trend-finder', data={
            'home_team': self.row['home_team'], 'action': 'combinations',
            'season': self.row['season'],
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Combinations within your filters', response.data)
        self.assertTrue(f'value="{self.row["home_team"]}"' in response.get_data(as_text=True))
        response = client.post('/trend-finder', data={'home_team': 'invalid'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Choose a CSV value', response.data)


if __name__ == '__main__':
    unittest.main()
