"""Offline checks for exact source references in Expert requests."""
import unittest
import json
from expert_provider import OpenAIProvider, validate_response_structure
from expert_beta import SECTIONS


class CitationSchemaTests(unittest.TestCase):
    def body(self, evidence):
        return OpenAIProvider(approved=True, model='test', api_key='test').request_body(
            {'instruction':'Use supplied evidence only.', 'evidence':evidence})

    def references(self, body):
        return body['text']['format']['schema']['properties']['sections']['items']['properties']['evidence_ids']

    def test_only_exact_source_names_and_nonempty_references(self):
        body=self.body({'sources':[{'name':'Spread market'}, {'name':'Total market'}]})
        refs=self.references(body)
        self.assertEqual(refs['minItems'],1)
        self.assertEqual(refs['items']['enum'],['Spread market','Total market','scout'])
        self.assertIn('case-sensitive',body['instructions'])

    def test_missing_personnel_evidence_can_reference_scout_limitations(self):
        body=self.body({'conditions':['No injury, confirmed QB replacement or weather adjustments.']})
        self.assertEqual(self.references(body)['items']['enum'],['scout'])
        self.assertIn('Scout conditions',body['instructions'])

    def test_empty_references_still_fail_existing_response_validator(self):
        report={k:'test' for k in ('summary','counterargument','uncertainty','betting_assessment','disagreement_reason')}
        report.update(ats_side=None,total_side=None,sections=[
            {'heading':h,'text':'test','evidence_ids':['scout']} for h in SECTIONS])
        validate_response_structure(report)
        report['sections'][2]['evidence_ids']=[]
        with self.assertRaises(ValueError):
            validate_response_structure(report)

    def test_authoritative_venue_signs_and_contradictory_total_are_explicit(self):
        scout={'game':{'away_team':'LV','home_team':'NYJ'},'scores':{'LV':23.8,'NYJ':23.9},
               'spread':{'side':'LV'},'total':{'side':'Under'},'quotes':{
                   'Spread':{'side_a':'LV','side_b':'NYJ','line_a':1.5,'line_b':-1.5},
                   'Total':{'line_a':45.5}}}
        before=json.dumps(scout,sort_keys=True)
        body=self.body(scout)
        facts=json.loads(body['input'])['authoritative_facts']
        self.assertEqual((facts['away_team'],facts['home_team']),('LV','NYJ'))
        self.assertEqual(facts['spread_by_team'],{'LV':1.5,'NYJ':-1.5})
        self.assertEqual(facts['combined_projected_points'],47.7)
        self.assertEqual(facts['combined_points_minus_market_total'],2.2)
        self.assertEqual(facts['combined_points_vs_total'],'above')
        self.assertEqual(facts['saved_total_side'],'Under')
        self.assertIn('separate totals model',facts['totals_model_note'])
        self.assertEqual(json.dumps(scout,sort_keys=True),before)


if __name__=='__main__':
    unittest.main()
