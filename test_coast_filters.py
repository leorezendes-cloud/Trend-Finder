import unittest
from trend_finder_2 import team_coast, matches_csv_filters, get_csv_filter_options, grouped_game_features


class CoastFiltersTests(unittest.TestCase):
    def test_coastal_states_and_historical_moves(self):
        self.assertEqual(team_coast('BUF', 2026), 'East Coast')
        self.assertEqual(team_coast('PHI', 2026), 'Other states')
        self.assertEqual(team_coast('LV', 2019), 'West Coast')
        self.assertEqual(team_coast('LV', 2026), 'Other states')
        self.assertEqual(team_coast('LA', 2015), 'Other states')
        self.assertEqual(team_coast('LA', 2016), 'West Coast')
        self.assertIsNone(team_coast('UNKNOWN', 2026))

    def test_filters_follow_underdog_side_and_are_search_features(self):
        game = {'home_team':'SEA','away_team':'BUF','season':'2026','spread_line':'3'}
        self.assertTrue(matches_csv_filters(game, {'home_coast':'West Coast','dog_coast':'East Coast'}))
        self.assertFalse(matches_csv_filters(game, {'away_coast':'West Coast'}))
        game['spread_line'] = '-3'
        self.assertTrue(matches_csv_filters(game, {'dog_coast':'West Coast'}))
        features = grouped_game_features(game, {'dog_location':'Home','is_primetime':False})
        self.assertIn(('Underdog coast','West Coast'), features)
        game['spread_line'] = '0'
        self.assertFalse(matches_csv_filters(game, {'dog_coast':'West Coast'}))
        self.assertEqual(get_csv_filter_options()['home_coast'], ['East Coast','West Coast','Other states'])


if __name__ == '__main__':
    unittest.main()
