"""Derived underdog-QB filters must follow the spread's dog side."""
import csv
import json
import unittest
from unittest.mock import patch

from app import app
import trend_finder_2 as finder


class DogQbFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(finder.game_file, newline='') as source:
            cls.rows = list(csv.DictReader(source))
        cls.sample = next(row for row in cls.rows if row['home_score'] and row['away_score'] and row['spread_line'] and row['result'])

    def test_qb_filter_follows_home_and_away_dogs(self):
        home_dog = dict(self.sample, spread_line='-3', home_qb_name='Selected QB', away_qb_name='Other QB')
        away_dog = dict(self.sample, spread_line='3', home_qb_name='Other QB', away_qb_name='Selected QB')
        favorite = dict(home_dog, spread_line='3')
        pickem = dict(home_dog, spread_line='0')
        missing = dict(home_dog, home_qb_name='')
        games = [home_dog, away_dog, favorite, pickem, missing]
        result = finder.Check_Games(games, dog_qb_name='Selected QB')
        self.assertEqual(result, finder.Check_Games([home_dog, away_dog]))
        self.assertEqual(result['all_games']['games'], 2)
        self.assertTrue(finder.matches_csv_filters(home_dog, {'dog_qb_name': 'Selected QB'}))
        self.assertFalse(finder.matches_csv_filters(favorite, {'dog_qb_name': 'Selected QB'}))

    def test_current_and_historical_dropdowns_have_separate_choices(self):
        from html.parser import HTMLParser
        class SelectOptions(HTMLParser):
            def __init__(self):
                super().__init__()
                self.current = None
                self.options = {}
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'select':
                    self.current = attrs.get('name')
                if tag == 'option' and self.current:
                    self.options.setdefault(self.current, set()).add(attrs.get('value'))
            def handle_endtag(self, tag):
                if tag == 'select':
                    self.current = None
        current = set(finder.get_current_qb_options())
        historical = set(finder.get_csv_filter_options()['dog_qb_name'])
        self.assertTrue(historical - current)
        html = app.test_client().get('/trend-finder').get_data(as_text=True)
        parser = SelectOptions()
        parser.feed(html)
        self.assertEqual(parser.options['dog_qb_name'] - {''}, current)
        self.assertEqual(parser.options['historical_dog_qb_name'] - {''}, historical)
        self.assertLess(html.index('id="spread_mode"'), html.index('id="dog_qb_name"'))
        self.assertLess(html.index('More filters'), html.index('id="historical_dog_qb_name"'))

    def test_forms_forward_current_or_historical_qb_and_reject_conflicts(self):
        client = app.test_client()
        current = finder.get_current_qb_options()[0]
        historical = next(qb for qb in finder.get_csv_filter_options()['dog_qb_name'] if qb not in finder.get_current_qb_options())
        for name, value in (('dog_qb_name', current), ('historical_dog_qb_name', historical)):
            with patch('app.run_analysis', wraps=finder.run_analysis) as analysis:
                response = client.post('/trend-finder', data={name: value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(analysis.call_args.kwargs['dog_qb_name'], value)
        with patch('app.run_analysis') as analysis:
            response = client.post('/trend-finder', data={'dog_qb_name': current, 'historical_dog_qb_name': historical})
        self.assertIn('Choose one underdog QB', response.get_data(as_text=True))
        analysis.assert_not_called()
        response = client.post('/trend-finder', data={'dog_qb_name': historical})
        self.assertIn('Choose a current-season underdog QB', response.get_data(as_text=True))

    def test_main_filters_do_not_expand_more_filters(self):
        from html.parser import HTMLParser
        class MoreFilterState(HTMLParser):
            def __init__(self):
                super().__init__()
                self.open = None
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'details' and attrs.get('id') == 'more-filters':
                    self.open = 'open' in attrs
        client = app.test_client()
        current = finder.get_current_qb_options()[0]
        cases = [({'dog_qb_name': current}, False), ({'game_type': 'REG'}, False),
                 ({'dog_qb_name': current, 'game_type': 'REG'}, False),
                 ({'historical_dog_qb_name': current}, True), ({'roof': 'dome'}, False)]
        for form, expected in cases:
            with self.subTest(form=form):
                html = client.post('/trend-finder', data=form).get_data(as_text=True)
                state = MoreFilterState()
                state.feed(html)
                self.assertEqual(state.open, expected)
                self.assertIn('More filters</summary>', html)

    def test_combination_evidence_respects_qb_scope(self):
        scope = {'dog_qb_name': 'Josh Allen'}
        groups = finder.scan_grouped_combinations(**scope)
        self.assertTrue(groups)
        source = {row['game_id']: row for row in self.rows}
        for group in groups[:5]:
            matches = finder.find_matching_trend_games(group['filters'], **scope)
            self.assertEqual(len(matches), group['sample'])
            for game in matches:
                self.assertEqual(finder.underdog_qb_name(source[game['game_id']]), 'Josh Allen')
        response = app.test_client().get('/combination-details', query_string={
            'conditions': json.dumps(groups[0]['filters']), 'selection': json.dumps(scope)})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Josh Allen quarterbacks the underdog', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
