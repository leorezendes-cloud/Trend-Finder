import copy
from datetime import timedelta
from unittest.mock import patch
from test_expert_beta import ExpertBetaTests,fixture
from expert_beta import clock

class DashboardTests(ExpertBetaTests):
    def test_combined_forecasts_show_earlier_games_after_upcoming(self):
        legacy=dict(game_id='2026_01_SEA_DEN',away_team='SEA',home_team='DEN',season=2026,week=1,
            kickoff_utc=(clock()-timedelta(days=1)).isoformat(),components={'Blend':{'pick':'DEN','away_margin':3}},
            quote={'line':3},totals={'prediction':{'lean':'Under'},'quote':{'line':42.5}},results={'Blend':'Win'})
        with patch('plug_dashboard.legacy_records',return_value=[legacy]):
            html=self.client.get('/the-plug').text
        self.assertLess(html.index('Upcoming games'),html.index('Games played &amp; underway'))
        self.assertLess(html.index('HOU @ JAX'),html.index('SEA @ DEN'))
        for text in ('Live market lines are unavailable','Saved picks and scores shown','premium access','Prediction archive','Existing forecasts','No calibrated confidence'):
            self.assertNotIn(text,html)
        self.assertIn('The Plug’s Record',html)
        self.assertEqual(self.client.get('/sunday-scout').status_code,302)
        self.assertIn('/the-plug',self.client.get('/sunday-scout').location)

    def test_overlapping_matchup_keeps_distinct_older_locked_pick(self):
        game=self.games[0]['game']
        legacy={**game,'components':{'Blend':{'pick':'JAX','away_margin':-4}},
            'quote':{'line':7},'totals':{'prediction':{'lean':'Over'},'quote':{'line':49.5}}}
        before={p:p.read_bytes() for p in self.root.glob('forecasts/**/*.json')}
        with patch('plug_dashboard.legacy_records',return_value=[legacy]):
            html=self.client.get('/the-plug').text
        self.assertEqual(html.count('<h2>HOU @ JAX</h2>'),1)
        self.assertIn('Earlier locked forecast',html)
        self.assertIn('JAX -7',html)
        for p,b in before.items():self.assertEqual(p.read_bytes(),b)

    def test_saved_numeric_string_lines_render(self):
        scout=copy.deepcopy(self.games[0])
        scout['quotes']['Spread']['line_a']='3'
        scout['quotes']['Spread']['line_b']='-3'
        self.store.append(scout)
        response=self.client.get('/the-plug')
        self.assertEqual(response.status_code,200)
        self.assertIn('HOU +3',response.text)

    def test_latest_market_is_separate_from_locked_line(self):
        market={'markets':[{'key':'Spread','label':'ATS winner','source':'Fixture market',
            'captured':clock().isoformat(),'sides':[{'name':'HOU','line':7.5},{'name':'JAX','line':-7.5}]}]}
        with patch('plug_dashboard.matchup_public_market',return_value=market):
            html=self.client.get('/the-plug').text
        self.assertIn('HOU +3',html)
        self.assertIn('HOU +7.5',html)
        self.assertIn('Fixture market',html)
        self.assertEqual(self.store.records()[0]['scout']['quotes']['Spread']['line_a'],3)

    def test_archive_has_no_disclaimers_and_remains_accessible(self):
        html=self.client.get('/the-plug/archive').text
        self.assertIn('Prediction archive',html)
        for phrase in ('not prospective validation','No independent validation','proven betting edge'):
            self.assertNotIn(phrase,html)

    def test_public_money_mobile_branding_and_no_export_button(self):
        market={'markets':[{'key':'Moneyline','label':'SU winner','source':'Fixture',
            'captured':clock().isoformat(),'sides':[{'name':'HOU','line':None,'money':62,'bets':55}]}]}
        with patch('plug_dashboard.matchup_public_market',return_value=market):
            html=self.client.get('/the-plug').text
        self.assertIn('62% money',html)
        self.assertIn('55% picks',html)
        self.assertIn('plug-upcoming-picks',html)
        self.assertIn('the-plug-nav.png',html)
        self.assertNotIn('Save The Plug',html)
