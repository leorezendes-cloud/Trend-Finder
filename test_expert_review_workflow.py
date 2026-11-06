"""Offline safeguards for owner Expert review and newsletter auto-refresh."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from expert_review_web import pending_reports
from membership import db
from newsletter import refresh_unapproved_featured


NOW = datetime(2026, 11, 5, 20, tzinfo=timezone.utc)
VERSION = "a" * 64
URL = "https://trendfindah.com/the-plug/2026/10/ARI-SEA"


class ExpertQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "drafts").mkdir()
        self.scout = {"game": {"game_id": "2026_10_ARI_SEA",
                               "season": 2026, "week": 10,
                               "away_team": "ARI", "home_team": "SEA",
                               "kickoff_utc": "2026-11-15T21:25:00+00:00"}}
        self.source = {"version": VERSION, "kind": "production_import",
                       "generated_at": "2026-11-05T18:00:00+00:00",
                       "scout": self.scout, "expert": None}
        (self.root / "drafts" / (VERSION + ".json")).write_text(
            json.dumps({"review_status": "pending", "summary": "Original"}))
        (self.root / "drafts" / (VERSION + ".replacement-1.json")).write_text(
            json.dumps({"review_status": "pending", "summary": "New"}))

    def test_prefers_newest_replacement_without_double_review(self):
        store = SimpleNamespace(root=self.root, records=lambda: [self.source])
        pending = pending_reports(store, now=NOW)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["report"]["summary"], "New")

    def test_published_game_is_no_longer_pending(self):
        published = {**self.source, "kind": "development", "expert": {"review_status": "approved"}}
        store = SimpleNamespace(root=self.root, records=lambda: [self.source, published])
        self.assertEqual(pending_reports(store, now=NOW), [])


class NewsletterRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__)
        self.app.config.update(MEMBERSHIP_DATABASE=str(Path(self.temp.name) / "members.db"),
                               PUBLIC_ORIGIN="https://trendfindah.com")
        self.context = self.app.app_context()
        self.context.push()
        with db():
            db().execute("CREATE TABLE newsletter_issues "
                         "(id INTEGER PRIMARY KEY, status TEXT, sections TEXT, audience_frozen INTEGER)")
            db().execute("CREATE TABLE newsletter_generated "
                         "(frequency TEXT, period TEXT, issue_id INTEGER, metadata TEXT)")
            sections = {"predictions": "The featured Expert pick is being prepared.",
                        "trends": "Owner trend edits remain", "matchups": "Owner notes"}
            metadata = {"original_sections": dict(sections)}
            db().execute("INSERT INTO newsletter_issues VALUES (1, 'draft', ?, 0)",
                         (json.dumps(sections),))
            db().execute("INSERT INTO newsletter_generated VALUES ('weekly', '2026-W45', 1, ?)",
                         (json.dumps(metadata),))

    def tearDown(self):
        self.context.pop()

    def test_refresh_changes_only_untouched_draft_featured_block(self):
        picks = [f"ARI @ SEA · Sunday\\nATS: ARI +8.5 · Total: Stay Away\\n{URL}"]
        experts = [f"ARI @ SEA · Sunday\\nATS: ARI · Total: Over\\nFootball matchup story.\\n{URL}"]
        with patch("newsletter_draft._plug_content", return_value=(picks, experts, [VERSION])):
            status = refresh_unapproved_featured(NOW)
        self.assertEqual(status, "featured-section-refreshed")
        sections = json.loads(db().execute("SELECT sections FROM newsletter_issues WHERE id=1").fetchone()[0])
        self.assertIn("Expert's take:", sections["predictions"])
        self.assertEqual(sections["trends"], "Owner trend edits remain")
        self.assertEqual(sections["matchups"], "Owner notes")

    def test_manual_edits_and_approved_issues_remain_untouched(self):
        with db():
            original = json.loads(db().execute(
                "SELECT sections FROM newsletter_issues WHERE id=1").fetchone()[0])
            original["predictions"] = "Custom owner story"
            db().execute("UPDATE newsletter_issues SET sections=? WHERE id=1",
                         (json.dumps(original),))
        self.assertEqual(refresh_unapproved_featured(NOW), "owner-edits-preserved")
        with db():
            db().execute("UPDATE newsletter_issues SET status='approved' WHERE id=1")
        self.assertEqual(refresh_unapproved_featured(NOW), "approved-or-sent-issue-untouched")


if __name__ == "__main__":
    unittest.main()
