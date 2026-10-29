"""Receipt bridge rejects missing, conflicting and late frozen sources."""
import tempfile
import unittest
from unittest.mock import patch
from plug_dynamic_receipt_bridge import observe_from_receipts

GID="2026_08_BAL_PIT"
KICK="2026-10-29T20:00:00+00:00"
ATS={"issued_at_utc":"2026-10-28T10:00:00+00:00",
     "games":[{"game_id":GID,"away_team":"BAL","home_team":"PIT",
               "kickoff_utc":KICK,"model_away_spread":-8.0}]}
OU={"away_team":"BAL","home_team":"PIT","kickoff_utc":KICK,
    "issued_at_utc":"2026-10-28T10:00:00+00:00",
    "v14_total":49.5,"original_scout_side":"Over"}

class ReceiptBridgeTest(unittest.TestCase):
    def run_bridge(self, ats=ATS, ou=OU, now="2026-10-28T15:00:00+00:00"):
        with tempfile.TemporaryDirectory() as root:
            with patch("plug_dynamic_receipt_bridge.read_ats_week",return_value=ats),\
                 patch("plug_dynamic_receipt_bridge.read_ou",return_value=ou),\
                 patch("plug_dynamic_receipt_bridge.observe",return_value={"revision":1}) as observe:
                result=observe_from_receipts(root,game_id=GID,evaluation_utc=now)
                observe.assert_called_once()
                self.assertEqual(observe.call_args.kwargs["model_away_spread"],-8.0)
                self.assertEqual(observe.call_args.kwargs["v14_total"],49.5)
                return result

    def test_valid_verified_sources(self):
        self.assertEqual(self.run_bridge()["revision"],1)

    def test_invalid_sources_fail_closed(self):
        for ats,ou,now in (
            (None,OU,"2026-10-28T15:00:00+00:00"),
            (ATS,None,"2026-10-28T15:00:00+00:00"),
            (ATS,{**OU,"home_team":"CLE"},"2026-10-28T15:00:00+00:00"),
            (ATS,{**OU,"kickoff_utc":"2026-10-30T20:00:00+00:00"},"2026-10-28T15:00:00+00:00"),
            (ATS,OU,KICK),
            (ATS,{**OU,"issued_at_utc":"2026-10-28T16:00:00+00:00"},"2026-10-28T15:00:00+00:00"),
        ):
            with self.subTest(ats=ats,ou=ou,now=now),self.assertRaises(ValueError):
                self.run_bridge(ats,ou,now)

if __name__=="__main__":
    unittest.main()
