import unittest
from unittest.mock import patch
from general_research import research_games, find_combinations
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

    def test_simple_presets_and_original_actions_and_cards(self):
        from html.parser import HTMLParser
        class Choices(HTMLParser):
            def __init__(self):super().__init__();self.field=None;self.choices={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='select':self.field=attrs.get('name');self.choices[self.field]=[]
                if tag=='option' and self.field:self.choices[self.field].append(attrs.get('value'))
            def handle_endtag(self,tag):
                if tag=='select':self.field=None
        client=app.test_client();html=client.get('/trend-finder').text
        parser=Choices();parser.feed(html)
        self.assertEqual(len(parser.choices['wind']),4)
        self.assertEqual(len(parser.choices['temp']),5)
        self.assertEqual(len(parser.choices['gametime']),3)
        self.assertNotIn('game_id',parser.choices)
        self.assertIn('name="action" value="combinations"',html)
        self.assertIn('class="clear-button"',html)
        self.assertNotIn('Kickoff windows include',html)
        html=client.get('/trend-finder?research_view=general&run=analyze&season=2025&research_team=BUF').text
        self.assertIn('class="results-grid"',html);self.assertIn('class="stat',html)
        self.assertIn('BUF — Any role',html)

    def test_general_combinations_include_favorites_and_respect_scope(self):
        rows=[game(str(i),temp='25',wind='22') for i in range(12)]
        trends=find_combinations(rows,role='favorite')
        self.assertTrue(trends)
        self.assertTrue(any(t['label']=='Favorites ATS' for t in trends))
        self.assertFalse(any('Underdog' in t['label'] for t in trends))
        for trend in trends:
            self.assertEqual(trend['wins'],12);self.assertEqual(trend['losses'],0)
            verified=research_games(rows,filters=trend['conditions'])
            self.assertEqual(verified['games'],trend['sample'])
            self.assertNotIn('game_id',trend['conditions'])
            self.assertNotIn('away_score',trend['conditions'])
            from trend_finder_2 import CSV_FILTER_FIELDS
            self.assertTrue(set(trend['conditions']).issubset(CSV_FILTER_FIELDS))
        self.assertEqual(find_combinations(rows[:9]),[])

    def test_location_and_spread_work_independently_of_team(self):
        rows=[game('home_dog',spread_line='-3',gametime='20:15'),
              game('away_dog',spread_line='3',gametime='20:15'),
              game('day',spread_line='-3',gametime='13:00'),
              game('large',spread_line='-10.5',gametime='20:15')]
        report=research_games(rows,role='underdog',location='home',primetime='yes',spread_size='short')
        self.assertEqual([g['game_id'] for g in report['matches']],['home_dog'])
        self.assertEqual(research_games(rows,role='underdog',location='away',primetime='yes')['games'],1)
        self.assertEqual(research_games(rows,team='BUF',location='home')['games'],0)
        self.assertEqual(research_games(rows,spread_size='double')['games'],1)
        from general_research import spread_matches
        for line,band in [(0,'pickem'),(-3,'short'),(3.5,'medium'),(-7,'medium'),(7.5,'large'),(10,'large'),(10.5,'double')]:
            self.assertTrue(spread_matches(line,band))
        self.assertFalse(spread_matches(None,'short'))

    def test_evidence_is_an_inline_fragment_preserving_scope(self):
        client=app.test_client()
        query='/trend-finder?research_view=general&run=analyze&season=2025&research_role=underdog&research_location=home&primetime=yes&spread_size=short'
        response=client.get(query+'&evidence=1&evidence_metric=Underdogs+ATS')
        self.assertEqual(response.status_code,200)
        self.assertIn('matching games',response.text)
        self.assertIn('Underdogs ATS',response.text)
        self.assertNotIn('home-filter-form',response.text)
        self.assertNotIn('<html',response.text)
        html=client.get(query+'&action=combinations').text
        self.assertIn('data-evidence-url=',client.get('/trend-finder?research_view=general&run=analyze&season=2025&action=combinations').text)
        self.assertIn('id="research_location"',html)
        self.assertIn('id="spread_size"',html)
        self.assertNotIn('name="spread_line"',html)
        self.assertEqual(client.get(query.replace('research_location=home','research_location=nowhere')).status_code,400)
        self.assertEqual(client.get(query.replace('spread_size=short','spread_size=bad')).status_code,400)
        cards=client.get(query).text
        for label in ('Dogs ATS','Dogs cover %','Dogs straight up','Dogs SU %'):
            self.assertIn(label,cards)

    def test_card_order_and_ten_game_preview(self):
        import re
        from urllib.parse import urlsplit,parse_qs
        from html import unescape
        client=app.test_client()
        query='/trend-finder?research_view=general&run=analyze&season=2025&research_role=underdog&primetime=yes'
        html=client.get(query).text
        labels=re.findall(r'<span class="stat-label">(.*?)</span>',html)
        expected=['Games','Pick’ems','Over','Under']
        for team in ('Home team','Away team','Favorites','Dogs'):
            expected.extend(team+' '+metric for metric in ('ATS','cover %','straight up','SU %'))
        self.assertEqual(labels,expected)
        fragment=client.get(query+'&evidence=1&evidence_metric=Underdogs+ATS').text
        self.assertEqual(fragment.count('<tr>'),11) # Header plus ten games.
        self.assertIn('All Games Involved',fragment)
        link=unescape(re.search(r'href="([^"]+)">All Games Involved',fragment).group(1))
        params=parse_qs(urlsplit(link).query)
        self.assertEqual(params['research_role'],['underdog'])
        self.assertEqual(params['primetime'],['yes'])
        self.assertNotIn('evidence',params)
        self.assertEqual(urlsplit(link).path,'/trend-finder/games')
        self.assertNotIn('target="_blank"',fragment)
        full=client.get(link).text
        self.assertGreater(full.count('<tr>'),11)
        self.assertIn('class="all-research-games"',full)
        self.assertNotIn('home-filter-form',full)
        self.assertIn('Back to Trend Finder',full)
        paged=client.get('/trend-finder/games?season=2025&page=2').text
        self.assertIn('/trend-finder/games?',paged)
        self.assertIn('Page 2 of 3',paged)

    def test_active_tags_remove_one_filter_and_keep_combination_mode(self):
        import re
        from html import unescape
        from urllib.parse import urlsplit,parse_qs
        query='/trend-finder?research_view=general&run=analyze&season=2025&research_role=underdog&research_location=home&primetime=yes&spread_size=short&wind=Windy+%2820%2B+mph%29'
        client=app.test_client()
        for suffix in ('','&action=combinations'):
            html=client.get(query+suffix).text
            for label in ('Season 2025','Role: Underdog','Location: Home','Primetime','Spread: Up to 3 points','Wind: Windy'):
                self.assertIn('Remove '+label,html)
            match=re.search(r'href="([^"]+)" aria-label="Remove Location: Home"',html)
            link=unescape(match.group(1));params=parse_qs(urlsplit(link).query)
            self.assertNotIn('research_location',params)
            self.assertEqual(params['research_role'],['underdog'])
            self.assertEqual(params['primetime'],['yes'])
            self.assertEqual(params['action'],['combinations' if suffix else 'analyze'])
            self.assertEqual(client.get(link).status_code,200)
            self.assertEqual(urlsplit(link).fragment,'research-results')

if __name__=='__main__':unittest.main()
