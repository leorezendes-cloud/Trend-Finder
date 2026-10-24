"""Saved-version navigation and grading guards; no production data writes."""
import copy,hashlib,json,unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from forecast_history import grade_components,total_result,pregame_record
from fan_views import prediction_performance,matchup

ROOT=Path(__file__).resolve().parent

class ForecastHistoryChecks(unittest.TestCase):
    def setUp(self):
        self.path=ROOT/'data/scout4/blend/predictions/2026_06_NYJ_NE.json'
        self.raw=self.path.read_bytes();self.record=json.loads(self.raw)
        self.game={k:self.record[k] for k in ('game_id','away_team','home_team','season','week')}
        self.game.update(away_score='19',home_score='26',gameday='2026-10-18',gametime='13:00')

    def test_selected_side_with_own_frozen_line(self):
        r=copy.deepcopy(self.record)
        for pick,expected in [('NYJ','Win'),('NE','Loss')]:
            r['components']['Blend']['pick']=pick
            self.assertEqual(grade_components(r,self.game)['Blend'],expected)
        r['quote']['line']=7
        for pick in ('NYJ','NE'):
            r['components']['Blend']['pick']=pick
            self.assertEqual(grade_components(r,self.game)['Blend'],'Push')

    def test_no_ats_pick_is_not_push(self):
        self.record['components']['Blend']['pick']=None;self.record['quote']['line']=7
        self.assertEqual(grade_components(self.record,self.game)['Blend'],'No Call')

    def test_no_total_pick_is_not_push(self):
        self.record['totals']['prediction']['lean']='No Call';self.record['totals']['quote']['line']=45
        self.assertEqual(total_result(self.record,self.game),'No Call')

    def test_full_quote_cutoff_seal_order(self):
        from expert_beta import instant
        self.record['quote']['captured_at_utc']=(instant(self.record['decision_cutoff_utc'])+timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):pregame_record(self.record)
        self.assertEqual(prediction_performance([self.record],[self.game])[2],1)

    def test_total_quote_order_also_checked(self):
        self.record['totals']['quote']['captured_at_utc']=self.record['kickoff_utc']
        with self.assertRaises(ValueError):pregame_record(self.record)

    def test_conflicting_versions_not_double_counted(self):
        other=copy.deepcopy(self.record);other['version']='different';other['components']['Blend']['pick']='NE'
        groups,_,excluded=prediction_performance([self.record,other],[self.game])
        self.assertEqual(groups,[]);self.assertEqual(excluded,2)

    def test_unknown_side_rejected(self):
        self.record['components']['Blend']['pick']='DAL'
        with self.assertRaises(ValueError):grade_components(self.record,self.game)

    def request_matchup(self,query='',final=True):
        app=Flask(__name__)
        fake={'saved_picks':{'spread':{'side':'NE'}}}
        with app.test_request_context('/matchup/2026_06_NYJ_NE'+query), \
             patch('fan_views.read_csv',return_value=[self.game]), \
             patch('fan_views.effective_rows',side_effect=lambda rows,path:rows), \
             patch('fan_views.fan_context',return_value=(2026,6,[],[],{},[],[])), \
             patch('fan_views._saved_final',return_value=final), \
             patch('fan_views._final_box_score',return_value=None), \
             patch('expert_beta.matchup_prediction',return_value=fake), \
             patch('member_picks.comparison_picks',return_value=[]), \
             patch('fan_views.render_template',side_effect=lambda template,**kw:('NYJ' if kw['use_results_forecast'] else 'NE')):
            return matchup('2026_06_NYJ_NE').get_data(as_text=True)

    def test_completed_page_defaults_to_graded_forecast(self):
        self.assertEqual(self.request_matchup(),'NYJ')

    def test_exact_pinned_version_and_stale_pin(self):
        from werkzeug.exceptions import Conflict
        digest=hashlib.sha256(self.raw).hexdigest()
        self.assertEqual(self.request_matchup('?forecast='+digest),'NYJ')
        with self.assertRaises(Conflict):self.request_matchup('?forecast='+'0'*64)

    def test_upcoming_uses_same_canonical_source(self):
        self.assertEqual(self.request_matchup(final=False),'NYJ')

    def test_explicit_archive_keeps_alternate_forecast(self):
        self.assertEqual(self.request_matchup('?archive='+'a'*64),'NE')

    def test_ambiguous_pin_rejected(self):
        from werkzeug.exceptions import BadRequest
        with self.assertRaises(BadRequest):self.request_matchup('?archive=x&forecast=y')

    def test_archive_version_must_belong_to_game(self):
        from expert_beta import Store,matchup_prediction
        from werkzeug.exceptions import NotFound
        records=Store(ROOT/'instance/expert_beta').records()
        with patch('expert_beta.enabled',return_value=True),patch('expert_beta.records_or_fail',return_value=records):
            with self.assertRaises(NotFound):matchup_prediction('2026_06_NYJ_NE',version='0'*64)

    def test_real_history_counts_unchanged(self):
        records=[json.loads(p.read_text()) for p in (ROOT/'data/scout4/blend/predictions').glob('*.json')]
        import csv
        with (ROOT/'nfl_games.csv').open() as f:games=list(csv.DictReader(f))
        groups,_,excluded=prediction_performance(records,games)
        self.assertEqual(excluded,0)
        from scout4.blend import grade_components as original
        from collections import Counter
        by_id={g['game_id']:g for g in games}
        expected=Counter(original(r,by_id[r['game_id']])['Blend'] for r in records)
        for status,count in expected.items():
            self.assertEqual(sum(g['ats'].get(status,0) for g in groups),count)

    def test_dashboard_history_uses_graded_pick_but_expert_keeps_own_line(self):
        from app import app
        from expert_beta import Store, public_record, instant
        from plug_dashboard import combined_cards
        scout={'game':{k:self.record[k] for k in ('game_id','away_team','home_team','season','week','kickoff_utc')},
               'quotes':{'Spread':{'side_a':'NYJ','side_b':'NE','line_a':8.5,'line_b':-8.5}},'sources':[]}
        records=[{'scout':scout,'version':'a'*64}]
        def render_record(record):
            return dict(scout=record['scout'],saved_picks={'spread':{'side':'NE'},'total':{'side':None}},
                        expert_picks={'ats_side':'NE'},expert_available=True,expert_access=True,
                        assessment='Fixture',url='/report')
        with app.test_request_context('/'), patch.dict(app.config,EXPERT_BETA_ENABLED=True,EXPERT_BETA_STORE=str(ROOT/'instance/expert_beta')), \
             patch('plug_dashboard.legacy_records',return_value=[self.record]), \
             patch('plug_dashboard._completed_games',return_value={self.game['game_id']:(19,26)}):
            _,earlier=combined_cards(records,render_record,instant('2026-10-24T20:00:00+00:00'))
        item=earlier[0]
        self.assertEqual(item['saved_picks']['spread']['side'],'NYJ')
        self.assertEqual(item['locked_quotes']['Spread']['line_a'],7.5)
        self.assertEqual(item['completed_grades']['scout_ats'],'Win')
        self.assertEqual(item['expert_locked_quotes'],records[-1]['scout']['quotes'])
        self.assertNotIn('version',item)

    def test_completed_template_shows_the_pinned_pick(self):
        from app import app
        from expert_beta import matchup_prediction
        from flask import g,render_template
        with app.test_request_context('/'),patch.dict(app.config,EXPERT_BETA_ENABLED=True,EXPERT_BETA_STORE=str(ROOT/'instance/expert_beta')):
            g.member=None
            item=matchup_prediction(self.game['game_id'])
            html=render_template('matchup.html',game=self.game,prediction_item=item,forecast=self.record,
                teams=[],season=2026,week=6,manifest={},inline_picks=[],is_final=True,box_score=None,
                use_results_forecast=True)
        quantitative=html.split('<div class="prediction-quantitative">',1)[1].split('<section class="prediction-expert-panel">',1)[0]
        self.assertIn('NYJ +7.5',quantitative)
        self.assertNotIn('NE -7.5',quantitative)
        self.assertIn('Based on the saved market line.',quantitative)
        self.assertNotIn('Results-table forecast',quantitative)
        self.assertNotIn('Other saved forecast',quantitative)

if __name__=='__main__':unittest.main()
