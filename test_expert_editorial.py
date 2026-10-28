"""Offline editorial checks; no provider requests or stored report rewrites."""
import copy
from html import unescape
import unittest
from unittest.mock import patch
from pathlib import Path
from expert_beta import expert_prose, generate_draft
from test_expert_beta import ExpertBetaTests, fixture, report

class ExpertEditorialTests(unittest.TestCase):
    setUp=ExpertBetaTests.setUp
    tearDown=ExpertBetaTests.tearDown
    login=ExpertBetaTests.login

    def test_citations_move_to_bottom_without_modifying_saved_reports(self):
        before={p:p.read_bytes() for p in self.root.glob('forecasts/**/*.json')}
        with patch('expert_provider.build_opener') as network:
            html=self.client.get('/the-plug/2026/1/HOU-JAX').text
        network.assert_not_called()
        self.assertIn('<summary>Experimental</summary>',html)
        self.assertNotIn('Show the Research',html)
        self.assertNotIn('Works Cited',html)
        self.assertNotIn('original calculation and saved market',html)
        self.assertNotIn('<pre>',html)
        self.assertNotIn('https://example.test/pregame',html)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertNotIn('PREMIUM_SECRET',self.client.get('/the-plug/2026/1/BUF-NYJ').text)

    def test_cleanup_only_known_citation_markers_and_escapes_html(self):
        sources=[{'name':'fixture'}]
        self.assertEqual(expert_prose('Take the Under [fixture, scout].',sources),'Take the Under.')
        self.assertEqual(expert_prose('Under [evidence_ids: fixture].',sources),'Under.')
        self.assertEqual(expert_prose('Keep [unknown] and 5–0.',sources),'Keep [unknown] and 5–0.')
        with self.client.application.app_context():
            from flask import render_template_string
            html=render_template_string('{{ text|expert_prose(sources) }}',text='<script>bad</script> [scout]',sources=sources)
        self.assertNotIn('<script>',html)

    def test_saved_technical_prose_is_simplified_without_changing_numbers(self):
        text="Scout's conditional model baseline issues an ATS lean on Atlanta (+1.5) and a total lean on Under (52.5)."
        self.assertEqual(expert_prose(text,[]),'Scout likes Atlanta (+1.5) and favors Under (52.5).')
        text='Sourced facts confirm the Atlanta Falcons host the Chicago Bears in Week 6 of the 2026 season. Atlanta can run the ball.'
        self.assertEqual(expert_prose(text,[]),'Atlanta can run the ball.')
        self.assertEqual(expert_prose('Penix has five starts; no closing totals are verified.',[]),'Penix has five starts; no closing totals are verified.')
        html=self.client.get('/the-plug/2026/1/HOU-JAX').text
        self.assertIn('Offensive and Defensive Analysis',html)
        self.assertNotIn("The Expert's Take",html)
        self.assertNotIn('Evidence: fixture',html)
        self.assertIn("The Plug's Picks",unescape(html))

    def test_expired_market_keeps_saved_picks_on_dashboard(self):
        from datetime import timedelta
        from expert_beta import clock
        with patch('expert_beta.clock',return_value=clock()+timedelta(minutes=16)):
            html=self.client.get('/the-plug').text
            record=self.client.get('/api/the-plug').json['games'][0]
        self.assertFalse(record['market_current'])
        self.assertEqual(record['scout']['quotes'],{})
        self.assertEqual(record['saved_picks']['spread']['side'],'HOU')
        self.assertIn('Scout ATS: HOU',html)
        self.assertIn('Scout O/U: Under',html)
        self.assertIn('The Plug O/U: —',html)
        self.assertIn('Scout ATS: HOU',html.split('<body>',1)[-1])

    def test_card_picks_only_for_entitled_users(self):
        html=self.client.get('/the-plug').text
        self.assertEqual(html.count('class="expert-card-picks"'),2)
        records=self.client.get('/api/the-plug').json['games']
        restricted=next(r for r in records if r['scout']['game']['away_team']=='BUF')
        self.assertIsNone(restricted['expert_picks'])
        self.login(1)
        self.assertEqual(self.client.get('/the-plug').text.count('class="expert-card-picks"'),3)

    def test_future_prompt_allows_disagreement_but_requires_verified_closing_totals(self):
        scout=fixture();original=copy.deepcopy(scout);packets=[]
        def provider(packet):
            packets.append(packet)
            return report(packet['evidence'])
        with patch('expert_provider.build_opener') as network:
            draft=generate_draft(scout,provider)
        network.assert_not_called();self.assertEqual(scout,original)
        text=packets[0]['instruction']
        for expected in ['sports fans','actual closing totals','Never invent or force a trend','may disagree with Scout','Works Cited','85 words']:
            self.assertIn(expected,text)
        self.assertEqual(draft['review_status'],'pending')


    def test_desktop_mobile_reports_have_equivalent_core_functionality(self):
        from html.parser import HTMLParser
        from flask import render_template
        from app import app
        from expert_beta import public_record, SECTIONS, identity
        class Links(HTMLParser):
            def __init__(self):super().__init__();self.links=[];self.current=None
            def handle_starttag(self,tag,attrs):
                if tag=='a':self.current=[dict(attrs).get('href'),[]]
            def handle_data(self,data):
                if self.current is not None:self.current[1].append(data)
            def handle_endtag(self,tag):
                if tag=='a' and self.current is not None:
                    self.links.append((self.current[0],''.join(self.current[1]).strip()));self.current=None
        featured=next(r for r in self.store.records() if r['scout']['game']['away_team']=='HOU')
        private=next(r for r in self.store.records() if r['scout']['game']['away_team']=='BUF')
        for record in [featured,private]:
            with self.subTest(game=identity(record['scout'])),app.test_request_context('/the-plug/'+identity(record['scout'])):
                app.preprocess_request()
                item=public_record(record,True);views=[]
                for template in ['expert_game.html','expert_game_mobile.html']:
                    html=render_template(template,item=item,versions=[record]);parsed=Links();parsed.feed(html)
                    comparison=[href for href,text in parsed.links if text=='View Team Comparison']
                    self.assertEqual(comparison,['/matchup/'+record['scout']['game']['game_id']])
                    self.assertIn('HOU' if record is featured else 'BUF',html)
                    self.assertIn('The Plug',html);self.assertIn('Spread:',html);self.assertIn('Scout O/U:',html)
                    self.assertIn('Preserved Versions',html);self.assertIn('/the-plug',dict((text,href) for href,text in parsed.links).get('← Back to The Plug'))
                    if record is featured:
                        self.assertIn('PREMIUM_SECRET',html)
                        for heading in SECTIONS:self.assertIn(expert_prose(heading,record['scout']['sources']),unescape(html))
                    else:self.assertNotIn('PREMIUM_SECRET',html)
                    views.append(comparison)
                self.assertEqual(views[0],views[1])

if __name__=='__main__':unittest.main()
