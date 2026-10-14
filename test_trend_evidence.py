"""Evidence must reproduce discovery records without changing the sample."""
import csv
import json
import unittest
from unittest.mock import patch

from app import app
import trend_finder_2 as finder


class TrendEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(finder.game_file, newline='') as source:
            cls.rows = list(csv.DictReader(source))
        cls.current_season = max(int(row['season']) for row in cls.rows)

    def test_each_group_record_matches_its_game_list(self):
        groups = finder.scan_grouped_combinations(limit=20, beam_width=25)
        self.assertTrue(groups)
        for group in groups:
            with self.subTest(filters=group['filters']):
                games = finder.find_matching_trend_games(group['filters'])
                record = finder.summarize_evidence_games(games)
                for field in ('sample', 'ats_wins', 'ats_losses', 'ats_pushes', 'ats_rate'):
                    self.assertEqual(group[field], record[field])
                self.assertEqual(group['evidence']['periods'][0]['sample'], len(games))
                self.assertEqual(sum(row['sample'] for row in group['evidence']['seasons']), len(games))

    def test_standard_analysis_verifies_grouped_conditions(self):
        conditions = ['Stadium: Mercedes-Benz Stadium', 'Month: 10']
        games = finder.find_matching_trend_games(conditions, season=(2020, 2026))
        self.assertTrue(games)
        record = finder.summarize_evidence_games(games)
        stats = finder.run_analysis(combination_conditions=conditions, season=(2020, 2026))
        verified = finder.evaluate_trend(stats)
        for field in ('sample', 'ats_wins', 'ats_losses', 'ats_pushes', 'ats_rate'):
            self.assertEqual(record[field], verified[field])
        from home_results import matching_game_groups
        listed = matching_game_groups(combination_conditions=conditions, season=(2020, 2026))
        self.assertEqual({game['game_id'] for group in listed for game in group['games']},
                         {game['game_id'] for game in games})
        response = app.test_client().post('/trend-finder', data={
            'combination_conditions': json.dumps(conditions), 'season_mode':'range',
            'start_season':'2020', 'end_season':'2026', 'action':'analyze'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Verifying:', response.get_data(as_text=True))
        self.assertIn('Mercedes-Benz Stadium', response.get_data(as_text=True))

    def test_stadium_subsets_are_one_family_and_keep_exact_records(self):
        anchor = ('Stadium', 'Example Stadium')
        features = [('Home team', 'A'), ('Month', '10'), ('Underdog QB', 'Example QB')]
        memberships = {anchor:frozenset(range(20))}
        def evaluate(ids):
            n = len(ids)
            return dict(ats_rate=60.0, ats_wins=3*n//5, ats_losses=n-3*n//5,
                        ats_pushes=0, sample=n, ci_low=40.0, coming_soon=False)
        trends = []
        for index, feature in enumerate(features):
            ids = frozenset(range(index, index+10))
            memberships[feature] = ids
            trends.append(dict(evaluate(ids), _features=(anchor, feature), _ids=ids,
                               filters=[f'{key}: {value}' for key,value in (anchor, feature)]))
        groups = finder.group_related_combinations(trends, memberships, evaluate)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['family_filters'], ['Stadium: Example Stadium'])
        self.assertEqual(len(groups[0]['related']), 3)
        for variant in groups[0]['related']:
            self.assertEqual(variant['sample'], len(variant['_ids']))

    def test_matching_games_obey_manual_scope_and_season(self):
        games = finder.find_matching_trend_games(['Underdog QB: Josh Allen'],
                                                 season=(2023, 2026), location='Away', min_spread=1.5)
        self.assertTrue(games)
        source = {row['game_id']: row for row in self.rows}
        for game in games:
            raw = source[game['game_id']]
            self.assertEqual(raw['away_qb_name'], 'Josh Allen')
            self.assertEqual(game['dog_team'], raw['away_team'])
            self.assertGreaterEqual(game['dog_spread'], 1.5)
            self.assertTrue(2023 <= game['season'] <= 2026)

    def test_periods_separate_current_history_and_recent_subset(self):
        games = [dict(season=2022, gameday='2022-01-01', ats_result='Loss'),
                 dict(season=2023, gameday='2023-01-01', ats_result='Win'),
                 dict(season=2025, gameday='2025-01-01', ats_result='Push'),
                 dict(season=2026, gameday='2026-01-01', ats_result='Win')]
        evidence = finder.build_trend_evidence(games, 2026)
        overall, historical, recent, current = evidence['periods']
        self.assertEqual((overall['ats_wins'], overall['ats_losses'], overall['ats_pushes']), (2, 1, 1))
        self.assertEqual(historical['sample'], 3)
        self.assertEqual(recent['sample'], 2)
        self.assertEqual(current['sample'], 1)
        self.assertEqual(recent['ats_rate'], 100)
        empty = finder.build_trend_evidence([], 2026)['periods'][0]
        self.assertEqual(empty['sample'], 0)
        self.assertIsNone(empty['ats_rate'])

    def test_game_page_paginates_and_displays_exact_record(self):
        client = app.test_client()
        conditions = ['Underdog QB: Josh Allen']
        games = finder.find_matching_trend_games(conditions)
        self.assertGreater(len(games), 25)
        query = dict(conditions=json.dumps(conditions), selection='{}')
        response = client.get('/trend-games', query_string=query)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Games behind the record', html)
        self.assertIn('Next 25 games', html)
        for game in games[:25]:
            self.assertIn(game['gameday'], html)
        response = client.get('/trend-games', query_string=dict(query, page=2))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Previous 25 games', response.get_data(as_text=True))
        response = client.get('/trend-games', query_string=dict(query, page=999999))
        self.assertEqual(response.status_code, 404)

    def test_game_page_rejects_malformed_requests(self):
        client = app.test_client()
        for query in ({}, {'conditions': 'invalid'},
                      {'conditions': '["Month: 10"]', 'selection': '{"unknown":true}'},
                      {'conditions': '["Month: 10"]', 'selection': '{"season":[2026,2025]}'},
                      {'conditions': '["Month: 10"]', 'selection': '{"min_spread":"bad"}'},
                      {'conditions': '["Month: 10"]', 'page': '0'}):
            with self.subTest(query=query):
                self.assertEqual(client.get('/trend-games', query_string=query).status_code, 400)

    def test_detail_link_keeps_manual_scope_and_season(self):
        from urllib.parse import urlencode
        conditions = ['Underdog QB: Josh Allen']
        selection = {'season': [2023, 2026], 'location': 'Away', 'min_spread': 1.5}
        client = app.test_client()
        url = '/combination-details?' + urlencode({
            'conditions': json.dumps(conditions), 'selection': json.dumps(selection)})
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Seasons 2023–2026', html)
        self.assertIn('the underdog plays away', html)
        self.assertIn('the underdog spread is at least 1.5', html)
        self.assertIn('Recent and historical performance', html)

    def test_detail_page_handles_all_pushes(self):
        game = dict(game_id='push', season=2026, gameday='2026-10-01',
                    away_team='BUF', home_team='NYJ', away_score=20, home_score=23,
                    dog_team='BUF', dog_spread=3, ats_result='Push')
        with patch('app.find_matching_trend_games', return_value=[game]), \
             patch('app.scan_grouped_combinations', return_value=[]):
            response = app.test_client().get('/combination-details', query_string={
                'conditions': '["Underdog QB: Josh Allen"]', 'selection': '{}'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('all were pushes; there is no ATS cover rate', response.get_data(as_text=True))

    def test_main_cards_show_evidence_and_working_game_link(self):
        from html.parser import HTMLParser
        class EvidenceLinks(HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = []
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == 'a' and values.get('class') == 'evidence-link':
                    self.urls.append(values['href'])
        client = app.test_client()
        response = client.post('/trend-finder', data={'action': 'combinations', 'season': '2026'})
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('Recent and historical performance', html)
        self.assertIn('Full trend details', html)
        self.assertIn('CSV file last modified', html)
        self.assertNotIn('not a test on unseen games', html)
        links = EvidenceLinks()
        links.feed(html)
        self.assertTrue(links.urls)
        for url in links.urls[:3]:
            detail = client.get(url)
            self.assertEqual(detail.status_code, 200)
            detail_html = detail.get_data(as_text=True)
            self.assertIn('Trend details', detail_html)
            self.assertIn('Recent and historical performance', detail_html)
            self.assertIn('not a test on unseen games', detail_html)
            self.assertIn('Games behind the record', detail_html)
            self.assertIn('95% ATS range:', detail_html)


if __name__ == '__main__':
    unittest.main()
