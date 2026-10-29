"""Dynamic preview is opt-in, read-only and never substitutes official picks."""
import unittest
from pathlib import Path
from unittest.mock import patch
import plug_dashboard

class PreviewWiringTest(unittest.TestCase):
    def test_guarded_optional_preview(self):
        source=Path(plug_dashboard.__file__).read_text()
        self.assertIn("TREND_FINDAH_DYNAMIC_PREVIEW",source)
        self.assertIn("if card['status'] != 'unavailable':",source)
        self.assertIn("item['plug_dynamic_card'] = card",source)
        self.assertIn("from plug_dynamic_cards import card_state",source)
        self.assertNotIn("item['saved_picks'] = card",source)
        self.assertNotIn("item['plug_ou_pick'] = card",source)
if __name__=="__main__":
    unittest.main()
