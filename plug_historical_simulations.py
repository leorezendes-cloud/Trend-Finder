"""Clearly labeled retrospective Plug v5/v14 simulations for 2026 Weeks 6-7.

These are research replays against the closing lines in nfl_games.csv, not
pregame-issued picks or official receipts. They remain separate from the
immutable prospective receipt stores and official season record.
"""
import csv
import math
from pathlib import Path


def _finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def historical_simulations(root, season, week):
    if int(season) != 2026 or int(week) not in (6, 7):
        return []
    root = Path(root)
    schedule_path = root / "nfl_games.csv"
    with schedule_path.open(newline="", encoding="utf-8-sig") as stream:
        games = [r for r in csv.DictReader(stream)
                 if r.get("game_type") == "REG"
                 and int(r.get("season") or 0) == int(season)
                 and int(r.get("week") or 0) == int(week)]
    if not games:
        return []

    from plug_ats_v5_model import projections as ats_projections
    from plug_ats_v5_weekly import classify
    from plug_v14_model import projections as total_projections
    from plug_totals_policy import select as select_total
    from forecast_history import official_sources

    ids = {g["game_id"] for g in games}
    ats = ats_projections(schedule_path, int(season), int(week))
    totals = total_projections(schedule_path, season=int(season), eligible_ids=ids)
    forecasts = official_sources(root)
    output = []
    for game in games:
        gid = game["game_id"]
        away_score = _finite(game.get("away_score"))
        home_score = _finite(game.get("home_score"))
        if (away_score is None or home_score is None
                or not away_score.is_integer() or not home_score.is_integer()):
            continue

        source = forecasts.get(gid) or {}
        # nflverse spread_line is the away team's handicap: positive means
        # the home team is favored, negative means the away team is favored.
        # v5 projections/classify() use this same away-team perspective.
        away_line = _finite(game.get("spread_line"))
        projection = _finite(ats.get(gid))
        ats_side = ats_result = ats_pick = None
        if away_line is not None and projection is not None:
            ats_side = classify(projection, away_line,
                                game["away_team"], game["home_team"])
            if ats_side:
                edge = away_score - home_score + away_line
                ats_result = "Push" if abs(edge) < 1e-9 else (
                    "Win" if (edge > 0) == (ats_side == game["away_team"]) else "Loss")
                signed_line = away_line if ats_side == game["away_team"] else -away_line
                ats_pick = f"{ats_side} {signed_line:+g}"

        # The independent v14 projection is compared with the closing total.
        # The original saved Scout lean remains the policy's starting side.
        close_total = _finite(game.get("total_line"))
        v14 = _finite(totals.get(gid))
        original = ((source.get("totals") or {}).get("prediction") or {}).get("lean")
        ou_side = ou_result = ou_pick = None
        if (close_total is not None and v14 is not None
                and 10 < close_total < 90
                and close_total >= 48
                and original in ("Over", "Under")
                and abs(v14 - close_total) > 1e-9):
            decision = select_total(original, close_total, v14)
            ou_side = decision["side"]
            actual_total = away_score + home_score
            delta = actual_total - close_total
            ou_result = "Push" if abs(delta) < 1e-9 else (
                "Win" if (delta > 0) == (ou_side == "Over") else "Loss")
            ou_pick = f"{ou_side} {close_total:g}"

        if not ats_side and not ou_side:
            continue
        output.append({
            "game_id": gid, "season": int(season), "week": int(week),
            "away_team": game["away_team"], "home_team": game["home_team"],
            "ats_side": ats_side, "ats_pick": ats_pick, "ats_result": ats_result,
            "ou_side": ou_side, "ou_pick": ou_pick, "ou_result": ou_result,
            "ats_projection": projection, "v14_projection": v14,
            "spread_line": away_line, "total_line": close_total,
            "source": "Closing-line historical simulation · not issued pregame",
        })
    return output
