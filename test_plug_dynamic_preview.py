"""Render-level tests for the isolated dynamic Plug preview."""
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT=Path(__file__).resolve().parent
ENV=Environment(loader=FileSystemLoader(str(ROOT/"templates")),
                autoescape=select_autoescape(["html"]))
TEMPLATE=ENV.get_template("_plug_dynamic_preview.html")

class DynamicPreviewTest(unittest.TestCase):
    def test_no_preview_when_unavailable(self):
        self.assertEqual(TEMPLATE.render(dynamic_card={"status":"unavailable"}).strip(),"")
        self.assertEqual(TEMPLATE.render().strip(),"")
    def test_selected_picks_and_note(self):
        result=TEMPLATE.render(dynamic_card={
            "status":"pregame","ats":"BAL +7.5","ou":"Under 48.5",
            "changed":True,
            "note":"Picks may change with line movement. Final selections lock at kickoff."})
        self.assertIn("BAL +7.5",result)
        self.assertIn("Under 48.5",result)
        self.assertIn("Updated with Vegas line movement",result)
        self.assertIn("Final selections lock at kickoff",result)
    def test_stay_away_and_locked(self):
        result=TEMPLATE.render(dynamic_card={
            "status":"locked","ats":"Stay Away","ou":"Stay Away",
            "changed":False,"note":"Final pregame selections"})
        self.assertEqual(result.count("Stay Away"),2)
        self.assertNotIn("Updated with Vegas line movement",result)
        self.assertIn("Final pregame selections",result)
    def test_escape_untrusted_values(self):
        result=TEMPLATE.render(dynamic_card={
            "status":"pregame","ats":"<script>oops</script>","ou":"Stay Away",
            "changed":False,"note":"Picks may change"})
        self.assertNotIn("<script>",result)
        self.assertIn("&lt;script&gt;",result)

if __name__=="__main__":
    unittest.main()
