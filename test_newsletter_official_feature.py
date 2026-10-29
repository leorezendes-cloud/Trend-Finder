"""Weekly featured game must be an official selected Plug pick."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
from newsletter_draft import _plug_content, _weekly_featured_pick

class Archive:
    def __init__(self,records): self._records=records
    def records(self): return self._records
    def featured(self,season,week): return ["2026/9/TEN-CIN"]

def record(away,home,day):
    now=datetime(2026,10,29,tzinfo=timezone.utc)
    return dict(kind="production_import",version=away+"-v1",
                generated_at=now.isoformat(),expert=None,
                scout=dict(game=dict(game_id=f"2026_09_{away}_{home}",
                    season=2026,week=9,away_team=away,home_team=home,
                    kickoff_utc=(now+timedelta(days=day)).isoformat())))

class OfficialWeeklyFeatureTest(unittest.TestCase):
    def test_non_selected_featured_game_cannot_displace_selected_pick(self):
        now=datetime(2026,10,29,tzinfo=timezone.utc)
        records=[record("TEN","CIN",2),record("BAL","BUF",3)]
        def ats(gid): return None
        def ou(root,gid):
            return dict(selected=gid.endswith("BAL_BUF"),side="Over",market_total=48.5)
        app=Flask(__name__)
        with app.app_context(),patch("expert_beta.store",return_value=Archive(records)),patch(
            "plug_ats_v5_weekly.for_game",side_effect=ats),patch(
            "plug_ou_weekly_v3.read_effective",side_effect=ou):
            picks,experts,versions=_plug_content(now,"https://trendfindah.com",[],None)
        self.assertEqual(len(picks),1)
        self.assertIn("BAL @ BUF",picks[0])
        self.assertIn("Total: Over 48.5",picks[0])
        self.assertNotIn("TEN @ CIN",picks[0])
        featured,_=_weekly_featured_pick(picks,experts,versions,[])
        self.assertIn("BAL @ BUF",featured)
        self.assertNotIn("TEN @ CIN",featured)

if __name__=="__main__":
    unittest.main()
