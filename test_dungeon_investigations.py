"""Editorial contracts and request-only integration; no external collectors."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse
os.environ.setdefault('TREND_FINDAH_DATABASE', '/tmp/dungeon-test-members.sqlite3')
from app import app
import dungeon_investigations as investigations


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.index = investigations.read_index()

    def library(self, **args):
        return self.client.get('/conspiracy-dungeon', query_string=dict(panel='anomalies', mobile_results='1', **args))

    def test_default_is_current_season_and_lazy(self):
        with patch('dungeon_results.load_games', side_effect=AssertionError('No historical scan')):
            response = self.library()
        self.assertEqual(response.status_code, 200)
        self.assertIn('13 cases', response.text)
        self.assertNotIn('The rule hiding in plain sight', response.text)
        self.assertNotIn('What specific instruction reached', response.text)
        self.assertIn('Featured investigation', response.text)

    def test_all_category_filters_have_only_matching_cases(self):
        for key in investigations.CATEGORIES:
            response = self.library(case_category=key)
            self.assertEqual(response.status_code, 200)
            for case in self.index:
                present = ('<h3><a href="/conspiracy-dungeon/investigations/' + case['slug'] + '">') in response.text
                self.assertEqual(present, key in case['categories'] and case['season']==2026)

    def test_archive_and_all_seasons(self):
        archive = self.library(case_season='archive').text
        self.assertIn('The rule hiding in plain sight', archive)
        self.assertNotIn('A field goal that never happened</a>', archive)
        self.assertIn('14 cases', self.library(case_season='all').text)

    def test_search_escaping_empty_and_sorting(self):
        self.assertIn('1 case matching', self.library(q='Washington').text)
        empty = self.library(q='<script>alert(1)</script>').text
        self.assertIn('No cases match', empty)
        self.assertNotIn('<script>alert(1)</script>', empty)
        self.assertIn('&lt;script&gt;', empty)
        html = self.library(sort='oldest').text
        self.assertLess(html.index('Too early for victory formation?</a>'), html.index('A trophy night, then a drone</a>'))

    def test_bad_filter_rejected(self):
        for args in [dict(case_category='fake'),dict(case_season='2027'),dict(sort='random')]:
            self.assertEqual(self.library(**args).status_code, 400)

    def test_every_case_renders_sections_and_sources(self):
        for entry in self.index:
            response = self.client.get('/conspiracy-dungeon/investigations/'+entry['slug'])
            self.assertEqual(response.status_code, 200)
            for heading in ['What happened', 'Timeline', 'Why it’s unusual', 'Betting impact', 'Sources & video', 'Possible explanations', 'Unresolved questions']:
                self.assertIn(heading, response.text)
            self.assertNotIn('<iframe', response.text)
            self.assertIn('rel="noopener noreferrer"', response.text)

    def test_unknown_case_and_path_rejected(self):
        for path in ['not-a-case','index.json','../app.py','%2e%2e%2fapp.py']:
            self.assertEqual(self.client.get('/conspiracy-dungeon/investigations/'+path).status_code,404)

    def test_catalogue_consistency_and_evidence_contract(self):
        self.assertEqual(len({c['slug'] for c in self.index}),len(self.index))
        for entry in self.index:
            detail=json.loads((investigations.ROOT/(entry['slug']+'.json')).read_text())
            for field in ('slug','title','date','teams','season','categories','summary'):
                self.assertEqual(detail[field],entry[field])
            self.assertTrue(detail['timeline']);self.assertTrue(detail['questions']);self.assertTrue(detail['sources'])
            self.assertTrue(set(detail['categories']) <= set(investigations.CATEGORIES))
            for source in detail['sources']:
                self.assertEqual(urlparse(source['url']).scheme,'https')
                self.assertTrue(urlparse(source['url']).hostname)
                self.assertNotIn('example.com',source['url'])
            if detail['betting']:
                for field in ('line','provenance','outcome','caution'):self.assertTrue(detail['betting'][field])

    def test_original_research_deep_links_preserved(self):
        for category in ('world','player','team','game'):
            response=self.library(category=category, anomaly_year='2026')
            self.assertEqual(response.status_code,200)
            self.assertIn('Original research archive',response.text)
            self.assertIn('Add a sourced event',response.text)
        self.assertIn('International Games',self.library(research='1').text)

    def test_other_dungeon_panels_render(self):
        for panel in ('money','movement','primetime'):
            response=self.client.get('/conspiracy-dungeon',query_string=dict(panel=panel,mobile_results='1'))
            self.assertEqual(response.status_code,200)
        html=self.client.get('/conspiracy-dungeon?panel=money').text
        self.assertIn('.money-matchups .dungeon-market-grid { grid-template-columns:repeat(3',html)
        self.assertIn('Only documented qualifying signals',html)
        self.assertIn('build_primetime_tracker',Path('dungeon_results.py').read_text())

    def test_preview_does_not_write_existing_records(self):
        root=Path(__file__).resolve().parent
        names=['nfl_games.csv','anomaly_events.csv','ats_handle_snapshots.csv','public_money_snapshots.csv']
        before={name:(root/name).read_bytes() for name in names}
        self.library();self.client.get('/conspiracy-dungeon/investigations/miami-extra-point')
        for tool in ('international', 'statistics', 'notes'):
            self.assertEqual(self.library(tool=tool).status_code, 200)
        self.assertEqual(self.client.get('/conspiracy-dungeon/investigations/ditka-memorial-game').status_code, 200)
        self.assertEqual(before,{name:(root/name).read_bytes() for name in names})

    def test_mobile_links_preserve_results_mode(self):
        html=self.library().text
        self.assertIn('mobile_results=1',html)
        detail=self.client.get('/conspiracy-dungeon/investigations/lambeau-drone').text
        self.assertIn('mobile_results=1',detail)


    def test_ditka_case_and_original_note_preserved(self):
        import csv
        detail=json.loads((investigations.ROOT/'ditka-memorial-game.json').read_text())
        with open('anomaly_events.csv',newline='') as handle:
            original=next(r for r in csv.DictReader(handle) if r['event_id']==detail['legacy_event_id'])
        self.assertEqual(original['title'],'The Mike Ditka Memorial Game')
        self.assertIn('30–24',detail['summary'])
        self.assertIn('Super Bowl XX',detail['summary'])
        self.assertIsNone(detail['betting'])
        self.assertTrue(any(s['kind']=='Video' for s in detail['sources']))
        self.assertIn('The Coach',self.library(q='Ditka').text)

    def test_integrated_research_tools_render_and_retain_context(self):
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.destinations = []
            def handle_starttag(self, tag, attrs):
                href = dict(attrs).get('href', '')
                if tag == 'a' and 'tool=' in href and href.endswith('#research-heading'):
                    self.destinations.append(href)
        links = Links()
        links.feed(self.library().text)
        self.assertEqual(len(links.destinations), 3)
        for destination in links.destinations:
            response = self.client.get(destination)
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="research-heading"', response.text)
            self.assertNotIn('Featured investigation', response.text)
        for tool,expected in [('international','International ATS history'),('statistics','High scoring'),('notes','The Mike Ditka Memorial Game')]:
            response=self.library(tool=tool)
            self.assertEqual(response.status_code,200)
            self.assertIn(expected,response.text)
            self.assertNotIn('Original research &amp; records',response.text)
        international=self.library(tool='international').text
        for label in ('Before this game','Kickoff, rest and next-game details','View Schedule Source'):
            self.assertIn(label,international)
        notes=self.library(tool='notes').text
        self.assertIn('Explore the Ditka case',notes)
        self.assertIn('Add a sourced event',notes)

    def test_statistical_filter_and_old_seasons(self):
        response=self.library(tool='statistics',anomaly_type='High scoring')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('Large winning margin</span>',response.text)
        response=self.library(tool='international',research_year='2025')
        self.assertEqual(response.status_code,200)
        self.assertIn('2025',response.text)
        for args in [dict(tool='fake'),dict(tool='statistics',anomaly_type='fake'),dict(tool='notes',event_category='fake'),dict(tool='international',research_year='oops'),dict(tool='international',research_page='0')]:
            self.assertEqual(self.library(**args).status_code,400)

    def test_default_does_not_calculate_research(self):
        with patch.object(investigations,'_research_data',side_effect=AssertionError('Not lazy')):
            self.assertEqual(self.library().status_code,200)
        self.assertEqual(investigations._research_data.cache_info().maxsize,2)

    def test_research_never_requests_live_finals(self):
        investigations._research_data.cache_clear()
        with patch('score_finals.request_finals',side_effect=AssertionError('No live feed')):
            self.assertEqual(self.library(tool='international').status_code,200)
            self.assertEqual(self.library(tool='statistics').status_code,200)

    def test_research_pagination_uses_filtered_records(self):
        from anomaly_analysis import CATEGORIES
        events=[dict(event_id=str(i),title='High scoring',status='Calculated',event_date='2026-10-01',description='test',matchup='A @ B') for i in range(25)]
        data=dict(events=events,international=[],years=['2026'],categories=CATEGORIES,category='game')
        with patch.object(investigations,'_research_data',return_value=data):
            with app.test_request_context('/conspiracy-dungeon'):
                report=investigations.research_view('statistics',{'research_page':'2'},2026)
                self.assertEqual(len(report['rows']),12)
                self.assertEqual(report['rows'][0]['event_id'],'12')
                self.assertEqual(report['pages'],3)


if __name__=='__main__':unittest.main()
