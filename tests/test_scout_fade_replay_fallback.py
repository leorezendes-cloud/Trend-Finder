import json

from scout_fade import record_context


def test_week_six_replay_counts_do_not_depend_on_forecast_archive(tmp_path):
    replay_path = tmp_path / "data/scout4/fade_replay/2026_week6.json"
    replay_path.parent.mkdir(parents=True)
    replay_path.write_text(json.dumps({
        "season": 2026,
        "week": 6,
        "formula_version": "plug-points-only-4",
        "configuration_sha256": "4b9a85b948cb0f1eeab19078df6d6f69a0244c947f460e01ab1537bbe9a12a31",
        "weights": {"scout_scoring": 0.0, "plug_points_only": 1.0},
        "games": [
            {"game_id": f"g{i}", "away_team": f"A{i}", "home_team": f"H{i}",
             "scout_pick": f"A{i}", "updated_formula_pick": f"H{i}",
             "expected_result": "Loss" if i < 8 else "Win"}
            for i in range(14)
        ],
    }))
    context = record_context(tmp_path, [], [], 2026, 6)
    assert context["week"]["Win"] == 8
    assert context["week"]["Loss"] == 6
    assert context["week"]["Push"] == 0
    assert context["week"]["selected"] == 14
    assert len(context["rows"]) == 14
    assert all(row["replayed"] for row in context["rows"])
