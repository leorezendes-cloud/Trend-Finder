import copy
import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from app import app
from expert_beta import Store, SECTIONS, canonical, clock, generate_draft, grade, identity, validate_scout
from expert_beta_cli import feature, save_final
from membership import migrate, db


def fixture(away='HOU', home='JAX', historical=False):
    cutoff = '2025-09-05T12:00:00+00:00' if historical else clock().isoformat()
    kickoff = '2025-09-07T17:00:00+00:00' if historical else (clock()+timedelta(days=2)).isoformat()
    game_id=f'{2025 if historical else 2026}_01_{away}_{home}'
    return {'game':{'game_id':game_id,'season':2025 if historical else 2026,'week':1,'away_team':away,'home_team':home,'kickoff_utc':kickoff},
            'cutoff_utc':cutoff,'model_version':'software-fixture-not-real-forecast','scores':{away:24.,home:21.},'before_scores':{away:23.,home:21.},
            'spread':{'label':'Lean','side':away},'total':{'label':'Lean','side':'Under'},'conditions':['Unknown replacement impact; no penalty invented.'], 'evidence_issues':[],
            'sources':[{'name':'fixture','url':'https://example.test/pregame','observed_at':cutoff}],
            'quotes':{market:{'game_id':game_id,'side_a':a,'side_b':b,'line_a':line,'line_b':line if market=='Total' else -line,'odds_a':-110,'odds_b':100,'captured_at_utc':cutoff,'sportsbook':'Fixture'} for market,a,b,line in [('Spread',away,home,3),('Total','Over','Under',45)]}}


def report(s):
    return {'ai_assisted':True,'provider':'TEST DOUBLE','model':'fixture','review_status':'approved','reviewer':'fixture-only','reviewed_at':s['cutoff_utc'],
            'scout_sha256':hashlib.sha256(canonical(s)).hexdigest(),'sections':[{'heading':h,'text':'PREMIUM_SECRET — test narrative only','evidence_ids':['fixture','scout']} for h in SECTIONS],
            'summary':'PRIVATE_SUMMARY','counterargument':'Fixture opposition','uncertainty':'Fixture missing personnel','betting_assessment':'Not recommended','ats_side':s['game']['away_team'],'total_side':None}


class ExpertBetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old={key:app.config.get(key) for key in ('EXPERT_BETA_ENABLED','EXPERT_BETA_STORE','EXPERT_PREMIUM_MEMBER_IDS','MEMBERSHIP_DATABASE','TESTING')}
        app.config.update(EXPERT_BETA_ENABLED=True,EXPERT_BETA_STORE=str(self.root),EXPERT_PREMIUM_MEMBER_IDS=['1'],MEMBERSHIP_DATABASE=str(self.root/'members.db'),TESTING=True)
        with app.app_context():
            migrate()
            with db():
                db().execute("INSERT INTO members(id,email,password_hash) VALUES(1,'premium@example.test','unused'),(2,'free@example.test','unused')")
        self.store=Store(self.root)
        self.games=[fixture(),fixture('CHI','ATL'),fixture('BUF','NYJ')]
        for s in self.games:self.store.append(s,expert=report(s))
        feature(self.root,2026,1,['HOU-JAX','CHI-ATL'])
        self.client=app.test_client()

    def tearDown(self):
        app.config.update(self.old);self.tmp.cleanup()

    def login(self, member):
        with self.client.session_transaction() as session:
            session['member_id']=member;session['member_version']=0

    def test_actual_app_dashboard_dynamic_and_no_private_leak(self):
        response=self.client.get('/the-plug');self.assertEqual(response.status_code,200)
        self.assertEqual(response.text.count('class="expert-card"'),3)
        self.assertNotIn('PREMIUM_SECRET',response.text)
        payload=self.client.get('/api/the-plug').json
        restricted=next(x for x in payload['games'] if x['scout']['game']['away_team']=='BUF')
        self.assertIsNone(restricted['expert']);self.assertIsNone(restricted['assessment'])
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')

    def test_two_featured_and_restricted_html_api(self):
        for slug in ('HOU-JAX','CHI-ATL'):
            self.assertIn('PREMIUM_SECRET',self.client.get('/the-plug/2026/1/'+slug).text)
        self.assertNotIn('PREMIUM_SECRET',self.client.get('/the-plug/2026/1/BUF-NYJ').text)
        self.assertEqual(self.client.get('/api/the-plug/2026/1/BUF-NYJ/expert').status_code,403)
        self.login(2);self.assertEqual(self.client.get('/api/the-plug/2026/1/BUF-NYJ/expert').status_code,403)
        self.login(1);self.assertEqual(self.client.get('/api/the-plug/2026/1/BUF-NYJ/expert').status_code,200)
        self.assertIn('PREMIUM_SECRET',self.client.get('/the-plug/2026/1/BUF-NYJ').text)

    def test_revoked_session_denied(self):
        self.login(1)
        with app.app_context(), db():db().execute('UPDATE members SET session_version=1 WHERE id=1')
        self.assertEqual(self.client.get('/api/the-plug/2026/1/BUF-NYJ/expert').status_code,403)

    def test_expired_quotes_not_current_no_projection_mutation(self):
        with patch('expert_beta.clock',return_value=clock()+timedelta(minutes=16)):
            row=self.client.get('/api/the-plug').json['games'][0]
            self.assertFalse(row['market_current']);self.assertEqual(row['scout']['quotes'],{})
            self.assertIsNone(row['scout']['spread']['side'])
        self.assertEqual(self.store.records()[0]['scout']['spread']['label'],'Lean')

    def test_future_quotes_and_hindsight_rejected(self):
        s=fixture();s['quotes']['Spread']['captured_at_utc']=(clock()+timedelta(hours=1)).isoformat()
        with self.assertRaises(ValueError):validate_scout(s)
        s=fixture();s['sources'][0]['observed_at']=(clock()+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):validate_scout(s)

    def test_immutable_versions_and_tamper_fail_closed(self):
        before={p:p.read_bytes() for p in self.root.glob('forecasts/**/*.json')}
        s=copy.deepcopy(self.games[0]);s['scores']['HOU']=25
        self.store.append(s)
        for p,raw in before.items():self.assertEqual(p.read_bytes(),raw)
        self.assertEqual(len(self.store.records()),4)
        p=next(iter(before));p.write_text('{}')
        self.assertEqual(self.client.get('/api/the-plug').status_code,503)

    def test_provider_unavailable_and_draft_not_publishable(self):
        with self.assertRaises(RuntimeError):generate_draft(self.games[0])
        draft=generate_draft(self.games[0],lambda payload:report(payload['evidence']))
        self.assertEqual(draft['review_status'],'pending')
        with self.assertRaises(ValueError):self.store.append(self.games[0],expert=draft)

    def test_grounding_rejects_unsupported_reference_and_projection_change(self):
        r=report(self.games[0]);r['sections'][0]['evidence_ids']=['invented']
        with self.assertRaises(ValueError):self.store.append(self.games[0],expert=r)
        r=report(self.games[0]);r['scout_sha256']='wrong'
        with self.assertRaises(ValueError):self.store.append(self.games[0],expert=r)

    def test_historical_fixture_grading_and_no_backfill(self):
        s=fixture(historical=True)
        with self.assertRaises(ValueError):self.store.append(s,kind='prospective',generated_at=s['cutoff_utc'])
        self.store.append(s,kind='historical_reconstruction')
        final={'game_id':s['game']['game_id'],'status':'final','away_score':24,'home_score':21,'source_url':'https://example.test/final','observed_at':'2025-09-08T00:00:00+00:00'}
        save_final(self.root,final)
        r=next(r for r in self.store.records() if r['kind']=='historical_reconstruction')
        result=grade(r,final)
        self.assertEqual(result['scout']['Spread']['result'],'Win')
        self.assertAlmostEqual(result['scout']['Spread']['return_units'],100/110)
        self.assertEqual(result['scout']['Total']['result'],'Push')
        self.assertEqual(result['team_score_mae'],0)
        page=self.client.get('/the-plug/2025/1/HOU-JAX')
        self.assertEqual(page.status_code,200);self.assertIn('historical_reconstruction',page.text)
        self.assertIn('24–21',page.text)

    def test_ties_missing_odds_invalid_finals(self):
        s=fixture(historical=True);s['scores']['HOU']=21.;s['quotes']['Spread'].pop('odds_a')
        r={'scout':s,'kind':'historical_reconstruction','expert':None}
        final={'game_id':s['game']['game_id'],'status':'final','away_score':21,'home_score':21,'source_url':'https://example.test/final','observed_at':'2025-09-08T00:00:00+00:00'}
        result=grade(r,final);self.assertEqual(result['straight_up'],'Tie');self.assertIsNone(result['scout']['Spread']['return_units'])
        final['away_score']=True
        with self.assertRaises(ValueError):grade(r,final)

    def test_disabled_endpoints_and_legacy_route(self):
        app.config['EXPERT_BETA_ENABLED']=False
        self.assertEqual(self.client.get('/api/the-plug').status_code,404)
        with patch.dict(app.view_functions,{'sunday_scout.sunday_scout_page':lambda:'legacy'}):
            self.assertEqual(self.client.get('/the-plug').text,'legacy')

    def test_feature_choices_frozen_and_version_route_protected(self):
        with self.assertRaises(ValueError):feature(self.root,2026,1,['BUF-NYJ','CHI-ATL'])
        r=next(r for r in self.store.records() if r['scout']['game']['away_team']=='BUF')
        self.assertNotIn('PREMIUM_SECRET',self.client.get('/the-plug/2026/1/BUF-NYJ?version='+r['version']).text)
        self.assertEqual(self.client.get('/the-plug/2026/1/BUF-NYJ?version=bad').status_code,404)

if __name__=='__main__':unittest.main()
