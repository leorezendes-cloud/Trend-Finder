import unittest
from unittest.mock import patch
from app import app

class LaunchValidationTests(unittest.TestCase):
    def test_bad_analysis_input_never_runs_analysis(self):
        forms = [
            {'spread_mode':'min','min_spread':value}
            for value in ('invalid','nan','inf','-1','26','1.3','')
        ] + [
            {'season':'bad'}, {'season':'99999'},
            {'season_mode':'range','start_season':'bad','end_season':'2026'},
            {'season_mode':'range','start_season':'2026','end_season':'2025'},
            {'season_mode':'range','start_season':'2020'},
            {'spread_mode':'range','min_spread':'7','max_spread':'3'},
            {'spread_mode':'unknown'}, {'season_mode':'unknown'},
            {'location':'unknown'}, {'primetime':'unknown'},
        ]
        for form in forms:
            with self.subTest(form=form), patch('app.run_analysis') as analysis:
                response=app.test_client().post('/trend-finder',data=form)
                self.assertEqual(response.status_code,200)
                self.assertIn('Please choose valid',response.get_data(as_text=True))
                analysis.assert_not_called()

    def test_valid_modes_and_legacy_redirect(self):
        client=app.test_client()
        for form in ({'spread_mode':'exact','exact_spread':'0'},
                     {'spread_mode':'range','min_spread':'1.5','max_spread':'7'},
                     {'season_mode':'range','start_season':'2025','end_season':'2026'}):
            with self.subTest(form=form):
                response=client.post('/',data=form,follow_redirects=True)
                self.assertEqual(response.status_code,200)
                self.assertNotIn('Please choose valid',response.get_data(as_text=True))

if __name__=='__main__':
    unittest.main()
