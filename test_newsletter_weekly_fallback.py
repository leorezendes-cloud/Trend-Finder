"""Weekly newsletter should not hide saved picks when Expert is pending."""
import unittest
from newsletter_draft import _weekly_featured_pick

class WeeklyFeatureFallback(unittest.TestCase):
    def test_preserves_published_picks_when_expert_missing(self):
        picks=["Team A at Team B\nATS: Team A +3 · Total: Under 47\nhttps://trendfindah.com/the-plug/2026/8/A-B",
               "Team C at Team D\nATS: Team C -4 · Total: Over 44\nhttps://trendfindah.com/the-plug/2026/8/C-D"]
        warnings=[]
        displayed,versions=_weekly_featured_pick(picks,[],["v1","v2"],warnings)
        self.assertIn(picks[0],displayed)
        self.assertIn(picks[1],displayed)
        self.assertEqual(versions,["v1","v2"])
        self.assertTrue(any("Expert analysis remains pending" in w for w in warnings))
    def test_no_picks_remains_pending(self):
        displayed,versions=_weekly_featured_pick([],[],[],[])
        self.assertIn("being prepared",displayed)
        self.assertEqual(versions,[])

if __name__=="__main__":
    unittest.main()
