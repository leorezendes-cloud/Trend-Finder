"""Guest feedback honeypot prevents spam writes without blocking normal reports."""
import unittest
from unittest.mock import patch
from flask import Flask, g
from membership import bp

class HoneypotTest(unittest.TestCase):
    def test_filled_trap_skips_rate_limiter_and_database(self):
        app = Flask(__name__)
        app.secret_key = "test-only"
        app.register_blueprint(bp)
        with app.test_request_context("/members/feedback", method="POST",
               data={"website":"https://spam.example","category":"Suggestion",
                     "message":"Buy search optimization now"}):
            g.member = None
            with patch("membership.allow_attempt", side_effect=AssertionError("rate limiter called")), patch(
                    "membership.db", side_effect=AssertionError("database called")):
                response = app.view_functions["membership.feedback_page"]()
            self.assertEqual(response.status_code, 302)
            self.assertIn("sent=1", response.location)

if __name__ == "__main__":
    unittest.main()
