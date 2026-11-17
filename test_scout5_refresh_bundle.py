"""Safety tests for the automatic official-source Scout 5 EPA refresh."""
import copy
import unittest
from scout5_refresh_bundle import collect, extend_bundle
from scout5_totals import load_bundle
from pathlib import Path


class Scout5RefreshTests(unittest.TestCase):
    def setUp(self):
        self.original = load_bundle(Path(__file__).with_name("scout5_ou_bundle.json"))
        self.old = self.original["ratings"]
        self.latest = max(map(int, self.old))

    def test_existing_provider_weeks_are_noop(self):
        self.assertIsNone(extend_bundle(self.original, copy.deepcopy(self.old)))

    def test_week_extension_preserves_original_model_and_replay(self):
        updated_source = copy.deepcopy(self.old)
        updated_source[str(self.latest + 1)] = copy.deepcopy(self.old[str(self.latest)])
        extended = extend_bundle(self.original, updated_source)
        self.assertEqual(extended["ratings_latest_week"], self.latest + 1)
        self.assertEqual(extended["coef"], self.original["coef"])
        self.assertEqual(extended["replay_history"], self.original["replay_history"])
        self.assertEqual(self.original["ratings"], self.old)

    def test_refuses_historical_mutation(self):
        new_data = copy.deepcopy(self.old)
        new_data[str(self.latest)]["ARI"][0] += 0.01
        self.assertIsNone(extend_bundle(self.original, new_data))
        new_data[str(self.latest + 1)] = copy.deepcopy(self.old[str(self.latest)])
        updated = extend_bundle(self.original, new_data)
        self.assertEqual(updated["ratings"][str(self.latest)]["ARI"],
                         self.old[str(self.latest)]["ARI"])
        self.assertEqual(updated["ratings_latest_week"], self.latest + 1)

    def test_refuses_incomplete_new_week(self):
        rows = []
        for week, teams in self.old.items():
            for team, values in teams.items():
                rows.append(dict(season=2026, team_id=team, as_of_week=int(week),
                                 games=int(week)-1, adj_off_epa=values[0],
                                 adj_def_epa=values[1], adj_net=values[0]-values[1]))
        rows.append(dict(season=2026, team_id="ARI", as_of_week=self.latest+1,
                         games=self.latest, adj_off_epa=0, adj_def_epa=0, adj_net=0))
        with self.assertRaisesRegex(ValueError, "Incomplete week"):
            collect(rows, 2026)


if __name__ == "__main__":
    unittest.main()
