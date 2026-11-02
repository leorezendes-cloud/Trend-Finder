import csv
from pathlib import Path

import plug_ats_v5_model
import plug_v14_model
import forecast_history
from plug_historical_simulations import historical_simulations


def test_week_six_replay_is_separate_and_uses_v5_v14_rules(tmp_path, monkeypatch):
    schedule = tmp_path / "nfl_games.csv"
    fields = ["game_id", "season", "week", "game_type", "away_team",
              "home_team", "away_score", "home_score", "spread_line",
              "total_line"]
    with schedule.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "game_id": "2026_06_AAA_BBB", "season": 2026, "week": 6,
            "game_type": "REG", "away_team": "AAA", "home_team": "BBB",
            "away_score": 20, "home_score": 17, "spread_line": 8,
            "total_line": 48,
        })
    monkeypatch.setattr(plug_ats_v5_model, "projections",
                        lambda path, season, week: {"2026_06_AAA_BBB": -7.5})
    monkeypatch.setattr(plug_v14_model, "projections",
                        lambda path, season, eligible_ids: {"2026_06_AAA_BBB": 49.5})
    monkeypatch.setattr(forecast_history, "official_sources", lambda root: {
        "2026_06_AAA_BBB": {
            "totals": {"prediction": {"lean": "Over"}}
        }
    })

    rows = historical_simulations(tmp_path, 2026, 6)
    assert len(rows) == 1
    row = rows[0]
    assert row["ats_side"] == "AAA"
    assert row["ats_result"] == "Win"
    assert row["ou_side"] == "Over"
    assert row["ou_result"] == "Loss"
    assert row["source"] == "Historical simulation · not issued pregame"


def test_only_weeks_six_and_seven_are_replayed(tmp_path):
    assert historical_simulations(tmp_path, 2026, 5) == []
    assert historical_simulations(tmp_path, 2026, 8) == []
    assert historical_simulations(tmp_path, 2025, 6) == []
