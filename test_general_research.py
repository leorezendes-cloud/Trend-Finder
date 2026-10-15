import unittest
from unittest.mock import patch
from general_research import research_games
from trend_filter_groups import matches_group
from saved_trends import manual_trend_title
from app import app


def game(identifier,**changes):
    return dict({'game_id':identifier,'season':'2025','week':'10','game_type':'REG','gameday':'2025-11-09','gametime':'13:00',
     'away_team':'BUF','home_team':'NYJ','away_score':'24','home_score':'20','spread_line':'-3','total_line':'44','result':'4'},**changes)

class GeneralResearchTests(unittest.TestCase):
    def test_context_records_do_not_double_count_matchups(self):
        rows=[game('a'),game('b',away_score='17',home_score='20',spread_line='3',total_line='40'),
              game('c',away_score='14',home_score='14',spread_line='0',total_line='28'),
              game('d',away_score='10',home_score='7',spread_line='',total_line=''),
              game('future',away_score='',home_score='')]
        r=research_games(rows)
        self.assertEqual(r['games'],4);self.assertEqual(r['pickems'],1);self.assertEqual(r['missing_lines'],1)
        records={v['label']:v for v in r['records']}
        self.assertEqual(records['Away teams']['covers'],1);self.assertEqual(records['Away teams']['pushes'],2)
        self.assertEqual(records['Away teams']['ats_missing'],1)
        self.assertEqual(records['Favorites']['games'],2);self.assertEqual(records['Favorites']['covers'],1)
        self.assertEqual(records['Underdogs']['pushes'],1)
        self.assertEqual(r['totals'],{'over':0,'under':1,'push':2,'missing':1})

    def test_selected_team_can_be_favorite_underdog_or_home(self):
        rows=[game('a'),game('b',spread_line='3'),game('c',away_team='MIA',home_team='BUF',spread_line='3')]
        r=research_games(rows,team='BUF',role='favorite')
        self.assertEqual({g['game_id'] for g in r['matches']},{'a','c'})
        r=research_games(rows,team='BUF',role='underdog')
        self.assertEqual([g['game_id'] for g in r['matches']],['b'])
        self.assertEqual(research_games(rows,team='BUF',role='home')['games'],1)

    def test_grouped_kickoff_weather_and_playoff_boundaries(self):
        for clock,expected in [('16:00',True),('16:05',True),('16:25',True),('16:59',True),('17:00',False),('13:00',False),('',False)]:
            self.assertEqual(matches_group({'gametime':clock},'gametime','4 p.m. ET window'),expected)
        self.assertTrue(matches_group({'gametime':'13:00'},'gametime','1 p.m. ET window'))
        for stage in ('WC','DIV','CON','SB','POST'):self.assertTrue(matches_group({'game_type':stage},'game_type','Playoffs (all rounds)'))
        self.assertFalse(matches_group({'game_type':'REG'},'game_type','Playoffs (all rounds)'))
        self.assertTrue(matches_group({'temp':'31.9'},'temp','Freezing (below 32°F)'))
        self.assertFalse(matches_group({'temp':'32'},'temp','Freezing (below 32°F)'))
        for value in ('','nan','inf',None):self.assertFalse(matches_group({'wind':value},'wind','Light wind (under 10 mph)'))
        self.assertFalse(matches_group({'wind':'-1'},'wind','Light wind (under 10 mph)'))

    def test_grouped_filters_select_same_explicit_games_in_old_and_new_engines(self):
        from trend_finder_2 import Check_Games
        rows=[game('a',game_type='WC',gametime='16:05',temp='25',wind='22'),
              game('b',game_type='DIV',gametime='16:25',temp='30',wind='25'),
              game('c',game_type='REG',gametime='16:25',temp='30',wind='25'),
              game('d',game_type='WC',gametime='13:00',temp='30',wind='25')]
        filters={'game_type':'Playoffs (all rounds)','gametime':'4 p.m. ET window','temp':'Freezing (below 32°F)','wind':'Windy (20+ mph)'}
        r=research_games(rows,filters=filters)
        self.assertEqual({g['game_id'] for g in r['matches']},{'a','b'})
        self.assertEqual(Check_Games(rows,**filters),Check_Games(rows[:2]))

    def test_default_and_legacy_saved_searches_are_routed_separately(self):
        client=app.test_client()
        with patch('general_research.render_general',return_value='general research'):
            self.assertEqual(client.get('/trend-finder').text,'general research')
            self.assertEqual(client.get('/trend-finder?research_view=general&run=analyze').text,'general research')
            self.assertNotEqual(client.get('/trend-finder?research_view=dogs').text,'general research')
            self.assertNotEqual(client.get('/trend-finder?run=analyze&season=2025').text,'general research')
        self.assertEqual(client.get('/trend-finder?research_view=unknown').status_code,400)
        self.assertEqual(client.get('/trend-finder?research_view=general&research_team=NOTATEAM').status_code,400)

    def test_general_saved_title_and_default_primary_filters(self):
        self.assertEqual(manual_trend_title('/trend-finder?research_view=general&run=analyze&research_role=all'),'All NFL games')
        title=manual_trend_title('/trend-finder?research_view=general&research_team=BUF&research_role=favorite&gametime=4+p.m.+ET+window')
        self.assertIn('Team: BUF',title);self.assertNotIn('Research View',title)
        html=app.test_client().get('/trend-finder').text
        for text in ('General NFL research','Primetime Dogs preset','1 p.m. ET window','4 p.m. ET window','Playoffs (all rounds)','Recorded temperature','Recorded wind'):
            self.assertIn(text,html)

if __name__=='__main__':unittest.main()
