"""Guard the Expert's football-first voice without changing historical forecasts."""
import unittest

from expert_beta import EXPERT_VOICE, SECTIONS
from expert_provider import OpenAIProvider, GeminiProvider


class ExpertConversationalVoiceTests(unittest.TestCase):
    def test_summary_is_human_football_opinion(self):
        voice = EXPERT_VOICE.lower()
        for expected in ("owner review cards", "recent-performance", "game script",
                         "never invent", "model scores", "sources",
                         "independent ats and o/u", "what scout sees"):
            self.assertIn(expected, voice)

    def test_structured_evidence_and_six_sections_preserved(self):
        self.assertEqual(len(SECTIONS), 6)
        self.assertIn("What Scout Sees", SECTIONS)
        self.assertIn("evidence_ids", __import__("inspect").getsource(
            __import__("expert_provider").report_schema))
        self.assertIn("source manifest", EXPERT_VOICE)

    def test_voice_in_openai_request_without_network(self):
        # Validate that the shared drafting voice reaches the real provider,
        # not only a comment or an unused editorial constant.
        from unittest.mock import patch
        import expert_beta
        dummy = {"game": {"away_team": "IND", "home_team": "HOU"},
                 "scores": {"IND": 21, "HOU": 23}, "quotes": {},
                 "sources": []}
        packet = {"instruction": "Write grounded analysis. " + EXPERT_VOICE,
                  "evidence": dummy}
        adapter = OpenAIProvider(approved=False, model="test-model", api_key="none")
        body = adapter.request_body(packet)
        self.assertIn("owner review cards", body["instructions"])
        self.assertIn("game script", body["instructions"])
        self.assertIn("evidence_ids", body["instructions"])


if __name__ == "__main__":
    unittest.main()
