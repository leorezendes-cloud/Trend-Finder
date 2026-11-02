import copy
import json
import tempfile
import unittest
from pathlib import Path

from scout_fade import (
    CONFIGURATION_SHA256, FORMULA_VERSION, WEIGHTS,
    grade_pick, pick_for_record, record_context, safe_record_context,
)

ROOT = Path(__file__).resolve().parent


class ScoutFadeChecks(unittest.TestCase):
    def test_week6_replay_is_explicit_and_immutable(self):
        path = ROOT / "data/scout4/fade_replay/2026_week6.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["replay_record"], "8-6-0")
        record = {
            "season": 2026, "week": 6, "game_id": "2026_06_NO_NYG",
            "away_team": "NO", "home_team": "NYG",
            "version": "legacy-scout", "weights": {"scout_scoring": .5, "plug_points_only": .5},
            "components": {"Blend": {"pick": "NYG"}},
        }
        original = copy.deepcopy(record)
        self.assertEqual(pick_for_record(record, ROOT), "NO")
        self.assertEqual(record, original)

    def test_week7_8_points_only_selection_is_faded(self):
        record = {
            "season": 2026, "week": 7, "game_id": "2026_07_A_B",
            "away_team": "A", "home_team": "B",
            "version": FORMULA_VERSION, "configuration_sha256": CONFIGURATION_SHA256,
            "weights": dict(WEIGHTS), "components": {"Blend": {"pick": "A"}},
        }
        self.assertEqual(pick_for_record(record, ROOT), "B")

    def test_unapproved_formula_is_not_publicly_selected(self):
        record = {
            "season": 2026, "week": 9, "game_id": "2026_09_A_B",
            "away_team": "A", "home_team": "B",
            "version": FORMULA_VERSION, "configuration_sha256": "0" * 64,
            "weights": dict(WEIGHTS), "components": {"Blend": {"pick": "A"}},
        }
        self.assertIsNone(pick_for_record(record, ROOT))

    def test_frozen_line_grading(self):
        record = {"game_id": "g", "away_team": "A", "home_team": "B",
                  "quote": {"line": 3.5}}
        game = {"game_id": "g", "away_team": "A", "home_team": "B",
                "away_score": "20", "home_score": "24"}
        self.assertEqual(grade_pick(record, game, "B"), "Win")
        self.assertEqual(grade_pick(record, game, "A"), "Loss")
        game["away_score"] = ""
        self.assertEqual(grade_pick(record, game, "B"), "Pending")


    def test_missing_replay_data_does_not_break_public_results_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = {
                "season": 2026, "week": 6, "game_id": "2026_06_A_B",
                "away_team": "A", "home_team": "B",
            }
            context = safe_record_context(Path(tmp), [record], [], 2026, 6)
            self.assertIsNotNone(context)
            self.assertEqual(context["week"]["selected"], 0)

    def test_week_and_all_weeks_records_are_distinct_scopes(self):
        records=[];schedule=[]
        for week, gid, away_score, home_score in ((7,"g7","24","20"),(8,"g8","17","21")):
            records.append({"season":2026,"week":week,"game_id":gid,"away_team":"A","home_team":"B",
                "version":FORMULA_VERSION,"configuration_sha256":CONFIGURATION_SHA256,"weights":dict(WEIGHTS),
                "components":{"Blend":{"pick":"A"}},"quote":{"line":3.5},
                "kickoff_utc":f"2026-11-{week:02d}T18:00:00+00:00"})
            schedule.append({"game_id":gid,"away_team":"A","home_team":"B","away_score":away_score,"home_score":home_score})
        week7=record_context(ROOT,records,schedule,2026,7)
        all_weeks=record_context(ROOT,records,schedule,2026,None)
        self.assertEqual(week7["week"]["selected"],1)
        self.assertEqual(all_weeks["week"]["selected"],2)
        self.assertEqual(all_weeks["overall"]["selected"],2)

    def test_week6_replay_context_uses_verified_saved_grades(self):
        data = json.loads((ROOT / "data/scout4/fade_replay/2026_week6.json").read_text())
        records = []
        for row in data["games"]:
            records.append({
                "season": 2026, "week": 6, "game_id": row["game_id"],
                "away_team": row["away_team"], "home_team": row["home_team"],
                "version": "legacy-scout", "weights": {"scout_scoring": .5, "plug_points_only": .5},
                "components": {"Blend": {"pick": row["updated_formula_pick"]}},
                "quote": {"line": 3.5},
                "kickoff_utc": "2026-10-18T17:00:00+00:00",
            })
        context = record_context(ROOT, records, [], 2026, 6)
        self.assertEqual(context["week"]["Win"], 8)
        self.assertEqual(context["week"]["Loss"], 6)
        self.assertEqual(context["week"]["selected"], 14)
        self.assertTrue(all(row["replayed"] for row in context["rows"]))

    def test_replay_cohort_counts_all_14(self):
        data = json.loads((ROOT / "data/scout4/fade_replay/2026_week6.json").read_text())
        self.assertEqual(len(data["games"]), 14)
        self.assertEqual(sum(row["expected_result"] == "Win" for row in data["games"]), 8)
        self.assertEqual(sum(row["expected_result"] == "Loss" for row in data["games"]), 6)


if __name__ == "__main__":
    unittest.main()
